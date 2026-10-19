"""Automatic set-up for any park and area: read the land, place a station, close a first loop.

Input is only a park file and a set of tiles. The land is scanned from the game
(env.py), every station position and direction that fits is ranked by how much
free run it has ahead, and for the best candidates a rectangular loop with a
chain-lift hill is fitted (side lengths [a, b, a + L, b] close the circuit for a
station of length L). The first loop the game actually rates is the start.
"""

from __future__ import annotations

import dataclasses
import random
from pathlib import Path

from .env import Env
from .game import Game, wait_ready
from .layouts import FLAT, LEFT3, RIGHT3, _hill
from .track import DIR_DELTA, TILE, Layout, trace

HILLS = (6, 4, 2, 0)


def scan_env(park: Path, rect: tuple[int, int, int, int], sandbox: bool, terraform: bool, tunnels: bool,
             slot: int | None = None) -> Env:
    with Game(park=park, slot=slot) as g:
        wait_ready(g)
        g.call("setup", {"sandbox": sandbox})
        scan = g.call("scan", {"rect": list(rect)}, timeout=120)
    return Env.from_scan(scan, sandbox=sandbox, terraform=terraform, tunnels=tunnels)


def bbox(tiles: frozenset) -> tuple[int, int, int, int]:
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _unit(d: int) -> tuple[int, int]:
    dx, dy = DIR_DELTA[d & 3]
    return dx // TILE, dy // TILE


def station_candidates(base: Layout, env: Env, area: frozenset) -> list[tuple[float, tuple[int, int], int, int]]:
    """(rank, station tile, direction, station z) for every placement whose station and
    entrance/exit tiles are inside the area, buildable and free at one height."""
    out = []
    L = base.station_len
    for tile in area:
        for d in range(4):
            fx, fy = _unit(d)
            st = [(tile[0] + fx * k, tile[1] + fy * k) for k in range(L)]
            mid = st[(L - 1) // 2]
            sides = []
            for k in ((d + 1) & 3, (d + 3) & 3):
                ox, oy = _unit(k)
                sides.append((mid[0] + ox, mid[1] + oy))
            need = st + sides
            if any(t not in area or not env.buildable(t) for t in need):
                continue
            floors = [env.tiles[t].floor for t in need]
            z = max(floors)
            if not all(env.free_at(t, z) for t in need):
                continue
            # Room to run ahead after the station, and room on both turning sides.
            run = 0
            x, y = st[-1]
            while (x + fx, y + fy) in area and env.buildable((x + fx, y + fy)) and run < 40:
                x, y = x + fx, y + fy
                run += 1
            side_room = 0
            for k in ((d + 1) & 3, (d + 3) & 3):
                ox, oy = _unit(k)
                r, (x, y) = 0, mid
                while (x + ox, y + oy) in area and env.buildable((x + ox, y + oy)) and r < 40:
                    x, y = x + ox, y + oy
                    r += 1
                side_room = max(side_room, r)
            stilts = z - min(floors)
            out.append((run + side_room - stilts / 16.0, tile, d, z))
    out.sort(key=lambda c: -c[0])
    return out


def rectangle_loops(layout: Layout, hill: int, turn: int, max_side: int = 40):
    """Closed rectangles from the station, largest first; yields piece lists passing the pre-filter."""
    L = layout.station_len
    n_hill = hill + 2 if hill else 0
    pairs = sorted(((a, b) for a in range(max(n_hill, 1), max_side) for b in range(1, max_side)),
                   key=lambda ab: -(ab[0] + ab[1]))
    for a, b in pairs:
        c = a + L
        side_a = (_hill(True, hill) if hill else []) + [(FLAT, False)] * (a - n_hill)
        side_c = [(FLAT, False)] * (c - n_hill) + (_hill(False, hill) if hill else [])
        pieces = (side_a + [(turn, False)] + [(FLAT, False)] * b + [(turn, False)]
                  + side_c + [(turn, False)] + [(FLAT, False)] * b + [(turn, False)])
        tr = trace(layout, pieces)
        if tr.closed and not tr.problems:
            yield pieces


def find_start(base: Layout, env: Env, area: frozenset, park: str | None, judge_factory=None,
               max_candidates: int = 60, seed: int = 0, log=print):
    """Return (layout, starting track, verdict) for the first placement the game rates."""
    rng = random.Random(seed)
    cands = station_candidates(base, env, area)
    if not cands:
        raise ValueError("no station placement fits the area")
    # Best-ranked first, with a little shuffling among near-equal ranks.
    cands = sorted(cands[: max_candidates * 3], key=lambda c: -(c[0] + rng.random()))[:max_candidates]
    judge = None
    try:
        for rank, tile, d, z in cands:
            layout = dataclasses.replace(base, station_tile=tile, station_dir=d, ground_z=z, env=env,
                                         area_tiles=area, area=bbox(area), park=park)
            for hill in HILLS:
                found = None
                for turn in (LEFT3, RIGHT3):
                    best = next(rectangle_loops(layout, hill, turn), None)
                    if best and (found is None or len(best) > len(found)):
                        found = best
                if not found:
                    continue
                if judge_factory is None:
                    return layout, found, None
                if judge is None:
                    judge = judge_factory(layout)
                else:
                    judge.layout = layout
                v = judge.evaluate(found)
                log(f"start candidate tile={tile} dir={d} z={z} hill={hill} pieces={len(found)} -> {v.stage} "
                    f"{v.excitement if v.rated else v.error or ''}")
                if v.rated:
                    return layout, found, v
                break  # this placement's biggest loop failed in game; try the next placement
        raise ValueError("no starting loop was rated by the game")
    finally:
        if judge is not None:
            judge.close()
