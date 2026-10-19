"""What the game says about the land: per-tile ground, water, ownership and obstacles.

Built from the plugin's `scan` command on the exact park the judges load, so the
search's pre-filter works from the same facts as the game: surface heights and
slopes, water level, park ownership / construction rights, and every path,
scenery item, wall, entrance or other ride on the tile.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRACK_CLEARANCE = 32  # rough vertical room a track element needs (ride clearance 24 + block clearance)
OBSTACLE_MARGIN = 8
MIN_TRACK_Z = 16  # TrackPlaceAction refuses anything lower
LAND_STEP = 16  # land heights move in steps of 2 height units
SLOPE_CORNERS = 0x0F  # a raised corner lifts it one land step
SLOPE_STEEP = 0x10  # steep slope: the raised corner is two steps up


def surface_top(base: int, slope: int) -> int:
    """Highest corner of a surface tile. Parks loaded from RCT2 files report a sloped
    surface's clearance equal to its base, but track cannot sit below its top corner
    (ConstructionClearance.cpp compares the track's base with every corner)."""
    if slope & SLOPE_STEEP:
        return base + 2 * LAND_STEP
    if slope & SLOPE_CORNERS:
        return base + LAND_STEP
    return base


@dataclass
class TileInfo:
    base: int  # surface base z
    ground: int  # top of the surface (highest corner of a slope)
    water: int  # water surface z, 0 = dry
    owned: bool
    rights: bool
    edge: bool
    blocked: list[tuple[int, int]] = field(default_factory=list)  # (z0, z1) taken by other elements
    scenery: int = 0  # small/large scenery items (trees count): the ratings' station scenery bonus

    @property
    def floor(self) -> int:
        """Lowest base z for track resting on this tile without touching land or water."""
        return max(self.ground, self.water)


@dataclass
class Env:
    tiles: dict[tuple[int, int], TileInfo]
    sandbox: bool = False  # True: ownership is ignored (the game's sandbox cheat is on)
    terraform: bool = False  # allow cutting land under track (restored after every evaluation)
    tunnels: bool = False  # allow track fully below the surface

    @classmethod
    def from_scan(cls, scan: dict, sandbox: bool = False, terraform: bool = False, tunnels: bool = False) -> Env:
        tiles = {}
        for tx, ty, base, clear, slope, water, owned, rights, edge, others in scan["tiles"]:
            blocked = [(b, c + OBSTACLE_MARGIN) for _type, b, c, _ride in others]
            scenery = sum(t in ("small_scenery", "large_scenery") for t, *_ in others)
            top = max(clear, surface_top(base, slope))
            tiles[(tx, ty)] = TileInfo(base, top, water, bool(owned), bool(rights), bool(edge), blocked, scenery)
        return cls(tiles, sandbox=sandbox, terraform=terraform, tunnels=tunnels)

    def buildable(self, tile: tuple[int, int]) -> bool:
        info = self.tiles.get(tile)
        if info is None or info.edge:
            return False
        return self.sandbox or info.owned or info.rights

    def landscapable(self, tile: tuple[int, int]) -> bool:
        info = self.tiles.get(tile)
        return (info is not None and not info.edge and not info.water and not info.blocked
                and (self.sandbox or info.owned))

    def free_at(self, tile: tuple[int, int], z: int, clear: int = TRACK_CLEARANCE) -> bool:
        """No other element occupies [z, z + clear) on the tile."""
        info = self.tiles[tile]
        return all(not (z < b1 and b0 < z + clear) for b0, b1 in info.blocked)

    def classify(self, tile: tuple[int, int], z: int, clear: int = TRACK_CLEARANCE) -> str:
        """'above' (rests on or over the land), 'under' (fully below the surface),
        'cut' (intersects the land; possible only by lowering this tile), or 'no'."""
        if not self.buildable(tile) or not self.free_at(tile, z, clear) or z < MIN_TRACK_Z:
            return "no"
        info = self.tiles[tile]
        if z >= info.floor:
            return "above"
        if info.water and z < info.water:
            return "no"  # the game refuses track under water
        # Underground: the surface's base is at or above the element's clearance (ConstructionClearance.cpp).
        if z + clear <= info.base:
            return "under" if self.tunnels else ("cut" if self.terraform and self.landscapable(tile) else "no")
        return "cut" if self.terraform and self.landscapable(tile) else "no"

    def scenery_near(self, tile: tuple[int, int], radius: int = 5) -> int:
        """Scenery items in the (2r+1)^2 square the ratings scan around the station start (cap 47)."""
        n = 0
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                info = self.tiles.get((tile[0] + dx, tile[1] + dy))
                if info:
                    n += info.scenery
        return min(n, 47)

    def summary(self, area: set[tuple[int, int]] | None = None) -> dict:
        tiles = [t for t in self.tiles if area is None or t in area]
        infos = [self.tiles[t] for t in tiles]
        return {
            "tiles": len(tiles),
            "buildable": sum(self.buildable(t) for t in tiles),
            "owned": sum(i.owned for i in infos),
            "rights_only": sum(i.rights and not i.owned for i in infos),
            "water": sum(bool(i.water) for i in infos),
            "obstacle_tiles": sum(bool(i.blocked) for i in infos),
            "relief": (max(i.base for i in infos) - min(i.base for i in infos)) if infos else 0,
        }


def cut_units(z: int) -> int:
    """Land height (in height units) that brings the surface down to or below base z."""
    return (z // LAND_STEP) * 2
