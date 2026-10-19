"""Track geometry: where each piece goes, whether a circuit closes, what it occupies.

Mirrors OpenRCT2's track design placement (TrackDesign.cpp): a piece placed
at connection height z starts at base z - beginZ; the next piece starts at the
rotated (endX, endY) offset plus one tile forward in the new direction.
All segment data comes from the game itself (data/track_segments.json, dumped
by the plugin's `segments` command), so nothing here is hand-measured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
TILE = 32
DIR_DELTA = ((-TILE, 0), (0, TILE), (TILE, 0), (0, -TILE))
STATION = 1  # END_STATION; the game reclassifies begin/middle/end itself
UNDERGROUND_CLEARANCE = 32  # rough track clearance used to call an element fully underground
LIFT = 1  # trackPlaceFlags bit for chain lift


def rot(x: int, y: int, d: int) -> tuple[int, int]:
    """CoordsXY::Rotate."""
    d &= 3
    if d == 0:
        return x, y
    if d == 1:
        return y, -x
    if d == 2:
        return -x, -y
    return -y, x


@dataclass(frozen=True)
class Segment:
    type: int
    begin_z: int
    end_z: int
    end_x: int
    end_y: int
    begin_dir: int
    end_dir: int
    begin_slope: int
    end_slope: int
    begin_bank: int
    end_bank: int
    elements: tuple[tuple[int, int, int], ...]
    group: int
    allows_lift: bool
    is_inversion: bool
    only_above_ground: bool


@cache
def segments() -> dict[int, Segment]:
    raw = json.loads((DATA / "track_segments.json").read_text())
    return {
        s["type"]: Segment(
            type=s["type"],
            begin_z=s["beginZ"],
            end_z=s["endZ"],
            end_x=s["endX"],
            end_y=s["endY"],
            begin_dir=s["beginDirection"],
            end_dir=s["endDirection"],
            begin_slope=s["beginSlope"],
            end_slope=s["endSlope"],
            begin_bank=s["beginBank"],
            end_bank=s["endBank"],
            elements=tuple(tuple(e) for e in s["elements"]),
            group=s["trackGroup"],
            allows_lift=s["allowsChainLift"],
            is_inversion=s["isInversion"],
            only_above_ground=s["onlyAllowedAboveGround"],
        )
        for s in raw
    }


# Pieces that need extra parameters or are cosmetic duplicates of plain track.
EXCLUDED_TYPES = {
    99,  # BRAKES (needs brake speed)
    101,  # MAZE
    114,  # ON_RIDE_PHOTO
    117,  # WATER_SPLASH
    123,  # CABLE_LIFT_HILL (needs the cable lift operating mode)
    216,  # BLOCK_BRAKES
}


@cache
def piece_set(ride_type_name: str) -> frozenset[int]:
    """Buildable, orthogonal, parameter-free pieces for a ride type.

    Track groups per ride type come from the openrct2-bridge tables (generated
    from OpenRCT2's C++ ride type descriptors); TrackPlaceAction itself does not
    reject pieces from groups the ride type lacks. Group 0 is the default for
    pieces with no group of their own (covered/maze/vertical variants) and is
    never offered by the in-game builder, so it is excluded.
    """
    rtd = json.loads((DATA / "track_groups_rtd.json").read_text())
    if ride_type_name in rtd:
        # Extracted from the C++ ride type descriptors by scripts/extract_track_groups.py.
        groups = set(rtd[ride_type_name]) - {0}
    else:
        tables = json.loads((DATA / "track_groups_from_bridge.json").read_text())
        groups = set(tables["groupsByRideType"][ride_type_name]) - {0}
    out = set()
    for t, s in segments().items():
        if s.group not in groups or t in EXCLUDED_TYPES or t == STATION:
            continue
        if t in (2, 3):  # begin/middle station
            continue
        if s.begin_dir >= 4 or s.end_dir >= 4:  # diagonal
            continue
        out.add(t)
    return frozenset(out)


@dataclass(frozen=True)
class State:
    """Where the next piece connects: tile-aligned world x/y, connection z, direction, slope, bank."""

    x: int
    y: int
    z: int
    d: int
    slope: int = 0
    bank: int = 0

    def key(self) -> tuple[int, int, int, int, int, int]:
        return (self.x, self.y, self.z, self.d, self.slope, self.bank)


@dataclass(frozen=True)
class Placed:
    type: int
    x: int
    y: int
    z: int  # base z passed to trackplace
    d: int
    lift: bool


def fits(state: State, t: int) -> bool:
    s = segments()[t]
    return s.begin_slope == state.slope and s.begin_bank == state.bank


def step(state: State, t: int) -> tuple[int, State]:
    """Return (base z for placement, state after the piece)."""
    s = segments()[t]
    zb = state.z - s.begin_z
    ex, ey = rot(s.end_x, s.end_y, state.d)
    nd = (state.d + s.end_dir - s.begin_dir) & 3
    dx, dy = DIR_DELTA[nd]
    return zb, State(state.x + ex + dx, state.y + ey + dy, zb + s.end_z, nd, s.end_slope, s.end_bank)


def piece_tiles(x: int, y: int, zb: int, d: int, t: int):
    """Yield (tile_x, tile_y, base_z) for each element of a placed piece."""
    for ex, ey, ez in segments()[t].elements:
        rx, ry = rot(ex, ey, d)
        yield (x + rx) // TILE, (y + ry) // TILE, zb + ez


@dataclass
class Layout:
    """Fixed context for a track: station position and the area it must stay in."""

    ride_type_name: str
    ride_type: int
    ride_object: str
    station_tile: tuple[int, int]
    station_dir: int
    station_len: int
    ground_z: int
    area: tuple[int, int, int, int]  # x0, y0, x1, y1 tiles, inclusive-exclusive
    max_height: int  # max base z above ground, world units
    min_separation: int = 48  # vertical gap demanded between track on one tile
    min_z: int | None = None  # lowest base z allowed; None keeps track above ground (no tunnels)
    cars: int | None = None  # cars per train; None keeps the game's default
    park: str | None = None  # park file (relative to the repo) with this layout's terrain; None = flat fixture
    ground_map: dict | None = None  # {(tile_x, tile_y): surface z} where it differs from ground_z
    obstacles: dict | None = None  # {(tile_x, tile_y): top z} of trees; track must pass above
    env: object | None = None  # env.Env read from the game; when set it replaces ground_map/obstacles
    area_tiles: frozenset | None = None  # arbitrary-shape area; None = the `area` rectangle
    decor: str | None = None  # small scenery object planted around the track before rating (decor.py)

    def to_record(self) -> dict:
        """JSON-safe description for run configs (terrain maps keyed "x,y")."""
        rec = dict(self.__dict__)
        for key in ("ground_map", "obstacles"):
            if rec[key] is not None:
                rec[key] = {f"{x},{y}": z for (x, y), z in rec[key].items()}
        if self.env is not None:
            rec["env"] = {"sandbox": self.env.sandbox, "terraform": self.env.terraform,
                          "tunnels": self.env.tunnels, **self.env.summary(self.area_tiles)}
        if self.area_tiles is not None:
            rec["area_tiles"] = sorted(f"{x},{y}" for x, y in self.area_tiles)
        return rec

    def in_area(self, tx: int, ty: int) -> bool:
        if self.area_tiles is not None:
            return (tx, ty) in self.area_tiles
        x0, y0, x1, y1 = self.area
        return x0 <= tx < x1 and y0 <= ty < y1

    def ground_at(self, tx: int, ty: int) -> int:
        if self.env is not None:
            info = self.env.tiles.get((tx, ty))
            return info.floor if info else self.ground_z
        if self.ground_map is None:
            return self.ground_z
        return self.ground_map.get((tx, ty), self.ground_z)

    def start(self) -> State:
        x, y = self.station_tile
        return State(x * TILE, y * TILE, self.ground_z, self.station_dir)

    def access_tiles(self) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        """Entrance and exit beside the middle station tile: (tile_x, tile_y, direction)."""
        sx, sy = self.station_tile
        fx, fy = DIR_DELTA[self.station_dir]
        mid = (self.station_len - 1) // 2
        mx, my = sx + fx // TILE * mid, sy + fy // TILE * mid
        out = []
        for k in ((self.station_dir + 1) & 3, (self.station_dir + 3) & 3):
            ox, oy = DIR_DELTA[k]
            toward = (k + 2) & 3
            # Same empirical rule pyrct2 uses for ride_entrance_exit_place.
            direction = (toward + 2) & 3 if toward % 2 == 1 else toward
            out.append((mx + ox // TILE, my + oy // TILE, direction))
        return out[0], out[1]


@dataclass
class Trace:
    placed: list[Placed]
    end: State
    closed: bool
    problems: list[str] = field(default_factory=list)
    cuts: dict = field(default_factory=dict)  # {(tile_x, tile_y): land height units} to lower before building


def trace(layout: Layout, pieces: list[tuple[int, bool]], check: bool = True) -> Trace:
    """Lay out station + pieces from the station start and check closure and constraints."""
    state = layout.start()
    placed: list[Placed] = []
    problems: list[str] = []
    for _ in range(layout.station_len):
        zb, nxt = step(state, STATION)
        placed.append(Placed(STATION, state.x, state.y, zb, state.d, False))
        state = nxt
    for i, (t, lift) in enumerate(pieces):
        if not fits(state, t):
            problems.append(f"piece {i} type {t} does not fit slope/bank {state.slope}/{state.bank}")
            return Trace(placed, state, False, problems)
        zb, nxt = step(state, t)
        placed.append(Placed(t, state.x, state.y, zb, state.d, lift))
        state = nxt
    closed = state.key() == layout.start().key()
    cuts: dict = {}
    if check:
        if layout.env is not None:
            env_problems, cuts = check_space_env(layout, placed)
            problems.extend(env_problems)
        else:
            problems.extend(check_space(layout, placed))
    return Trace(placed, state, closed, problems, cuts)


def check_space_env(layout: Layout, placed: list[Placed]) -> tuple[list[str], dict]:
    """Pre-filter against the scanned land: area mask, ownership, water, obstacles,
    height limit, self-overlap, and which tiles must be cut to let the track through."""
    from .env import cut_units

    env = layout.env
    occupied: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (ax, ay, _) in layout.access_tiles():
        occupied[(ax, ay)] = [(layout.ground_z, -1)]
    cuts: dict[tuple[int, int], int] = {}
    for i, p in enumerate(placed):
        s = segments()[p.type]
        span = max(abs(s.end_z - s.begin_z), 0) if len(s.elements) == 1 else 0
        tiles = list(piece_tiles(p.x, p.y, p.z, p.d, p.type))
        kinds = []
        for tx, ty, z in tiles:
            t = (tx, ty)
            if not layout.in_area(tx, ty):
                return [f"piece {i} leaves area at tile {t}"], {}
            kind = env.classify(t, z)
            if kind == "no":
                return [f"piece {i} cannot sit on tile {t} at z={z}"], {}
            if z + span - env.tiles[t].base > layout.max_height:
                return [f"piece {i} too high (z={z})"], {}
            for oz, oi in occupied.get(t, ()):
                if oi != i and abs(oz - z) < layout.min_separation:
                    return [f"piece {i} overlaps piece {oi} at tile {t}"], {}
            occupied.setdefault(t, []).append((z, i))
            kinds.append(kind)
            if kind == "cut":
                cuts[t] = min(cuts.get(t, 1 << 30), cut_units(z))
        if "under" in kinds:
            if s.only_above_ground:
                return [f"piece {i} type {p.type} must stay above ground"], {}
            if len(set(kinds)) > 1:
                return [f"piece {i} straddles the surface"], {}
    return [], cuts


def check_space(layout: Layout, placed: list[Placed]) -> list[str]:
    """Cheap pre-filter for area, ground, height and self-overlap. The game has the final say."""
    x0, y0, x1, y1 = layout.area
    occupied: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for (ax, ay, _) in layout.access_tiles():
        occupied[(ax, ay)] = [(layout.ground_z, -1)]
    problems = []
    obstacles = layout.obstacles or {}
    for i, p in enumerate(placed):
        s = segments()[p.type]
        span = max(abs(s.end_z - s.begin_z), 0) if len(s.elements) == 1 else 0
        tiles = list(piece_tiles(p.x, p.y, p.z, p.d, p.type))
        below = [(z, layout.ground_at(tx, ty)) for tx, ty, z in tiles if z < layout.ground_at(tx, ty)]
        if below:
            lowest = min(z for z, _ in below)
            if layout.min_z is None:
                return [f"piece {i} below ground (z={lowest})"]
            if lowest < layout.min_z:
                return [f"piece {i} too low (z={lowest})"]
            if s.only_above_ground:
                return [f"piece {i} type {p.type} must stay above ground"]
            # A multi-tile piece cannot be partly above and partly below the surface.
            if len(tiles) > 1 and any(z + UNDERGROUND_CLEARANCE > layout.ground_at(tx, ty) for tx, ty, z in tiles):
                return [f"piece {i} straddles the surface"]
        for tx, ty, z in tiles:
            if not (x0 <= tx < x1 and y0 <= ty < y1):
                return [f"piece {i} leaves area at tile ({tx},{ty})"]
            if z + span - layout.ground_at(tx, ty) > layout.max_height:
                return [f"piece {i} too high (z={z})"]
            top = obstacles.get((tx, ty))
            if top is not None and z < top:
                return [f"piece {i} hits a tree at tile ({tx},{ty})"]
            for oz, oi in occupied.get((tx, ty), ()):
                if oi != i and abs(oz - z) < layout.min_separation:
                    return [f"piece {i} overlaps piece {oi} at tile ({tx},{ty})"]
            occupied.setdefault((tx, ty), []).append((z, i))
    return problems


def pieces_payload(placed: list[Placed]) -> list[list[int]]:
    """[trackType, x, y, z, direction, flags, brakeSpeed] per piece, as rct2loop expects."""
    return [[p.type, p.x, p.y, p.z, p.d, LIFT if p.lift else 0, 0] for p in placed]
