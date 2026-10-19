"""Where to plant trees around a track, the way players theme a coaster.

Scenery earns excitement and costs no intensity or nausea (RideRatings.cpp):

- Station scenery: small or large scenery items in the 11x11 square around the
  station start, up to 47 of them, add up to +0.24 excitement (Twister/Giga).
- Proximity: for each piece, a scenery item on the tile to its left or right
  scores SCENERY_SIDE_BELOW (it reaches up to the track) or SCENERY_SIDE_ABOVE
  (the track passes over it), each counted up to 35 times: 80 proximity points,
  about +0.25 excitement.

The plan lists tiles in order of value; the plugin plants a tree on each until
the game refuses or the budget runs out, rates the ride, and removes them again
(they stay only when the track is kept for a saved park).
"""

from __future__ import annotations

from .track import DIR_DELTA, TILE, Layout, Placed, piece_tiles

STATION_RADIUS = 5
STATION_ITEMS = 47
SIDE_COUNT = 35  # per proximity type; trees beside ground-level and raised pieces fill both
MAX_TREES = 110


def _unit(d: int) -> tuple[int, int]:
    dx, dy = DIR_DELTA[d & 3]
    return dx // TILE, dy // TILE


def plan(layout: Layout, placed: list[Placed], cuts: dict | None = None) -> list[list[int]]:
    """Tiles [x, y] to plant on, most useful first."""
    env = layout.env
    if env is None:
        return []
    track = set()
    for p in placed:
        for tx, ty, _z in piece_tiles(p.x, p.y, p.z, p.d, p.type):
            track.add((tx, ty))
    # Keep the entrance and exit, and the tile in front of each, free for guests.
    fx, fy = _unit(layout.station_dir)
    mid = (layout.station_len - 1) // 2
    mx, my = layout.station_tile[0] + fx * mid, layout.station_tile[1] + fy * mid
    keep_free = set()
    for k in ((layout.station_dir + 1) & 3, (layout.station_dir + 3) & 3):
        ux, uy = _unit(k)
        keep_free.update({(mx + ux, my + uy), (mx + 2 * ux, my + 2 * uy)})
    cuts = cuts or {}

    def plantable(t: tuple[int, int]) -> bool:
        info = env.tiles.get(t)
        return (info is not None and layout.in_area(*t) and t not in track and t not in keep_free
                and t not in cuts and not info.edge and not info.water and (env.sandbox or info.owned))

    # Proximity: how many piece sides each tile would serve.
    serves: dict[tuple[int, int], int] = {}
    for p in placed:
        x, y = p.x // TILE, p.y // TILE
        for k in ((p.d + 1) & 3, (p.d + 3) & 3):
            ux, uy = _unit(k)
            t = (x + ux, y + uy)
            if plantable(t):
                serves[t] = serves.get(t, 0) + 1
    side = sorted(serves, key=lambda t: -serves[t])
    out, covered = [], 0
    for t in side:
        if covered >= 2 * SIDE_COUNT or len(out) >= MAX_TREES:
            break
        out.append(t)
        covered += serves[t]

    # Station scenery: fill the 11x11 square up to 47 items, nearest tiles first.
    sx, sy = layout.station_tile
    chosen = set(out)
    have = env.scenery_near(layout.station_tile, STATION_RADIUS)
    have += sum(1 for t in out if abs(t[0] - sx) <= STATION_RADIUS and abs(t[1] - sy) <= STATION_RADIUS)
    square = sorted(((sx + dx, sy + dy) for dx in range(-STATION_RADIUS, STATION_RADIUS + 1)
                     for dy in range(-STATION_RADIUS, STATION_RADIUS + 1)),
                    key=lambda t: max(abs(t[0] - sx), abs(t[1] - sy)))
    for t in square:
        if have >= STATION_ITEMS or len(out) >= MAX_TREES:
            break
        if t not in chosen and plantable(t):
            out.append(t)
            chosen.add(t)
            have += 1
    return [list(t) for t in out]
