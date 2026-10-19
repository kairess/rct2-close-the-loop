"""Experiment terrains: generate hills and trees, bake them into a park file, build a Layout.

A terrain spec (data/terrains/<name>.json) records every tile height and tree, so
the search's pre-filter knows the ground exactly. The matching park file
(data/parks/<name>.park) is what every game instance loads.
"""

from __future__ import annotations

import dataclasses
import json
import random
import shutil
from pathlib import Path

from .game import RUNTIME, Game, wait_ready
from .track import TILE, Layout

ROOT = Path(__file__).resolve().parents[2]
TERRAINS = ROOT / "data" / "terrains"
PARKS = ROOT / "data" / "parks"
BASE_UNITS = 14  # fixture land height (z 112)
TREE = "rct2.scenery_small.tco"  # Common Oak, full tile, 112 z tall
TREE_CLEARANCE = 112 + 16


def generate(name: str, seed: int, area: tuple[int, int, int, int], station_tile: tuple[int, int],
             station_dir: int = 2, relief_steps: int = 0, tree_frac: float = 0.0, ring: int = 4,
             cell: int = 5) -> dict:
    """Hills (smooth value noise in land steps of 16 z) and trees inside the area,
    keeping a flat ring of `ring` tiles along the edge where the starting oval runs."""
    rng = random.Random(seed)
    x0, y0, x1, y1 = area
    gx = range(x0, x1 + cell, cell)
    gy = range(y0, y1 + cell, cell)
    ctrl = {(cx, cy): rng.uniform(0, relief_steps) for cx in gx for cy in gy}

    def noise(tx: int, ty: int) -> float:
        cx = x0 + (tx - x0) // cell * cell
        cy = y0 + (ty - y0) // cell * cell
        fx, fy = (tx - cx) / cell, (ty - cy) / cell
        a, b = ctrl[(cx, cy)], ctrl[(cx + cell, cy)]
        c, d = ctrl[(cx, cy + cell)], ctrl[(cx + cell, cy + cell)]
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy

    def interior(tx: int, ty: int) -> bool:
        return x0 + ring <= tx < x1 - ring and y0 + ring <= ty < y1 - ring

    heights, trees = {}, []
    for tx in range(x0, x1):
        for ty in range(y0, y1):
            if not interior(tx, ty):
                continue
            steps = round(noise(tx, ty))
            if steps:
                heights[f"{tx},{ty}"] = BASE_UNITS + 2 * steps
            if rng.random() < tree_frac:
                trees.append([tx, ty])
    return {
        "name": name, "seed": seed, "area": list(area), "station_tile": list(station_tile),
        "station_dir": station_dir, "relief_steps": relief_steps, "tree_frac": tree_frac, "ring": ring,
        "base_units": BASE_UNITS, "heights": heights, "trees": trees, "tree_identifier": TREE,
    }


def bake(spec: dict) -> Path:
    """Apply the spec to the fixture park in one game instance and save it under data/parks/."""
    TERRAINS.mkdir(parents=True, exist_ok=True)
    PARKS.mkdir(parents=True, exist_ok=True)
    (TERRAINS / f"{spec['name']}.json").write_text(json.dumps(spec))
    tiles = [[*map(int, k.split(",")), h] for k, h in spec["heights"].items()]
    with Game() as g:
        wait_ready(g)
        g.call("setup")
        r = g.call("terraform", {"tiles": tiles, "trees": {"identifier": spec["tree_identifier"], "at": spec["trees"]}}, timeout=300)
        if r["errors"]:
            raise RuntimeError(f"terraform errors: {r['errors'][:5]}")
        g.call("save", {"filename": spec["name"]})
    dest = PARKS / f"{spec['name']}.park"
    shutil.copyfile(RUNTIME / "save" / f"{spec['name']}.park", dest)
    return dest


def layout_for(base: Layout, name: str) -> Layout:
    """A copy of `base` (ride type, object, limits) placed on terrain `name`."""
    spec = json.loads((TERRAINS / f"{name}.json").read_text())
    ground = {tuple(map(int, k.split(","))): h * 8 for k, h in spec["heights"].items()}
    obstacles = {}
    for tx, ty in spec["trees"]:
        obstacles[(tx, ty)] = ground.get((tx, ty), spec["base_units"] * 8) + TREE_CLEARANCE
    return dataclasses.replace(
        base,
        station_tile=tuple(spec["station_tile"]),
        station_dir=spec["station_dir"],
        ground_z=spec["base_units"] * 8,
        area=tuple(spec["area"]),
        park=str((PARKS / f"{name}.park").relative_to(ROOT)),
        ground_map=ground or None,
        obstacles=obstacles or None,
    )


def describe(layout: Layout) -> dict:
    x0, y0, x1, y1 = layout.area
    n = (x1 - x0) * (y1 - y0)
    raised = len(layout.ground_map or {})
    return {"tiles": n, "raised_tiles": raised, "trees": len(layout.obstacles or {}),
            "max_ground_steps": max(((z - layout.ground_z) // 16 for z in (layout.ground_map or {}).values()), default=0),
            "area": layout.area, "station": layout.station_tile, "tile_size": TILE}
