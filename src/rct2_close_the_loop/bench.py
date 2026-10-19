"""Benchmark conditions for the general algorithm: synthetic terrains and real RCT2 maps.

A condition is a JSON file: a park file, the area (any set of tiles), and the
land rules (ownership respected, terraforming allowed). Synthetic conditions mix
hills, lakes, trees, unowned or rights-only patches, sizes 12-32 and non-square
shapes; they are baked into park files from a seed. Real conditions take a window
of a scenario shipped with RCT2, chosen by a fixed procedure: the window with the
most free buildable tiles.

Development and held-out conditions come from disjoint seeds and scenarios, and
both lists are generated before any held-out run.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from .env import Env
from .game import RUNTIME, Game, rct2_path, wait_ready
from .terrain import TREE

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "data" / "bench"
ORIGIN = (100, 100)  # top-left of synthetic areas on the 266x266 fixture
SIZES = (12, 16, 20, 24, 28, 32)
SHAPES = ("rect", "L", "cross")


def shape_mask(size: int, shape: str) -> set[tuple[int, int]]:
    x0, y0 = ORIGIN
    tiles = {(x0 + i, y0 + j) for i in range(size) for j in range(size)}
    h = size // 2
    t = size // 3
    if shape == "L":  # drop the far quadrant
        tiles -= {(x0 + i, y0 + j) for i in range(h, size) for j in range(h, size)}
    elif shape == "cross":  # drop the four corners
        corners = [(0, 0), (size - t, 0), (0, size - t), (size - t, size - t)]
        for cx, cy in corners:
            tiles -= {(x0 + cx + i, y0 + cy + j) for i in range(t) for j in range(t)}
    return tiles


def _noise(rng: random.Random, tiles: set, cell: int):
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    x0, y0 = min(xs), min(ys)
    ctrl = {}

    def at(cx, cy):
        if (cx, cy) not in ctrl:
            ctrl[(cx, cy)] = rng.random()
        return ctrl[(cx, cy)]

    def f(tx, ty):
        cx = x0 + (tx - x0) // cell * cell
        cy = y0 + (ty - y0) // cell * cell
        fx, fy = (tx - cx) / cell, (ty - cy) / cell
        a, b, c, d = at(cx, cy), at(cx + cell, cy), at(cx, cy + cell), at(cx + cell, cy + cell)
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy

    return f


def synthetic_params(seed: int) -> dict:
    rng = random.Random(seed)
    return {
        "size": rng.choice(SIZES),
        "shape": rng.choice(SHAPES),
        "relief": rng.choice((0, 2, 4, 6, 8)),
        "water": rng.choice((0.0, 0.0, 0.1, 0.2, 0.3)),
        "trees": rng.choice((0.0, 0.05, 0.1, 0.2)),
        "unowned": rng.choice((0.0, 0.0, 0.1, 0.2)),
    }


def make_synthetic(name: str, seed: int, params: dict | None = None) -> dict:
    """Generate, bake and describe one synthetic condition."""
    p = params or synthetic_params(seed)
    rng = random.Random(seed * 7919 + 1)
    area = shape_mask(p["size"], p["shape"])
    hill = _noise(rng, area, 5)
    lake = _noise(rng, area, 6)
    base = 14
    lake_cut = sorted(lake(*t) for t in area)[int(len(area) * p["water"])] if p["water"] else -1
    heights, water, trees, ownership = [], [], [], []
    for t in sorted(area):
        if lake(*t) < lake_cut:
            heights.append([t[0], t[1], base - 4])
            water.append([t[0], t[1], base])
            continue
        units = base + 2 * round(hill(*t) * p["relief"])
        if units != base:
            heights.append([t[0], t[1], units])
        if rng.random() < p["trees"]:
            trees.append([t[0], t[1]])
    # Unowned (0) or rights-only (1) patches: a few rectangles covering about the given share.
    target = int(len(area) * p["unowned"])
    xs = [t[0] for t in area]
    ys = [t[1] for t in area]
    marked: set = set()
    while len(marked) < target:
        w, h = rng.randint(2, 5), rng.randint(2, 5)
        x, y = rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))
        flag = rng.choice((0, 1))
        for i in range(w):
            for j in range(h):
                if (x + i, y + j) in area and (x + i, y + j) not in marked:
                    marked.add((x + i, y + j))
                    ownership.append([x + i, y + j, flag])
    spec = {"name": name, "kind": "synthetic", "seed": seed, "params": p, "heights": heights,
            "water": water, "trees": trees, "ownership": ownership}
    park = _bake(spec)
    return {"name": name, "kind": "synthetic", "seed": seed, "params": p,
            "park": str(park.relative_to(ROOT)), "area_tiles": sorted(map(list, area)),
            "sandbox": False, "terraform": True}


def _bake(spec: dict) -> Path:
    with Game() as g:
        wait_ready(g)
        g.call("setup", {"sandbox": True})
        r = g.call("terraform", {"tiles": spec["heights"], "water": spec["water"], "ownership": spec["ownership"],
                                 "trees": {"identifier": TREE, "at": spec["trees"]}}, timeout=600)
        if r["errors"]:
            raise RuntimeError(f"{spec['name']}: terraform errors {r['errors'][:5]}")
        g.call("save", {"filename": spec["name"]})
    dest = BENCH / "parks" / f"{spec['name']}.park"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUNTIME / "save" / f"{spec['name']}.park", dest)
    return dest


def scenario_files() -> list[Path]:
    return sorted((rct2_path() / "Scenarios").glob("*.SC6"))


def best_window(env: Env, size: int) -> tuple[int, int, set]:
    """Window of size x size with the most free buildable tiles (no obstacle, dry or not)."""
    free = {t for t, i in env.tiles.items() if env.buildable(t) and not i.blocked}
    xs = [t[0] for t in env.tiles]
    ys = [t[1] for t in env.tiles]
    best = (-1, 0, 0)
    for x in range(min(xs), max(xs) - size + 1, 2):
        for y in range(min(ys), max(ys) - size + 1, 2):
            n = sum((x + i, y + j) in free for i in range(size) for j in range(size))
            if n > best[0]:
                best = (n, x, y)
    n, x, y = best
    area = {(x + i, y + j) for i in range(size) for j in range(size) if env.buildable((x + i, y + j))}
    return n, (x, y), area


def make_real(name: str, scenario: Path, size: int, min_free: float = 0.6) -> dict | None:
    with Game(park=scenario) as g:
        wait_ready(g)
        g.call("setup", {"sandbox": False})
        scan = g.call("scan", {"rect": [0, 0, 512, 512]}, timeout=120)
    env = Env.from_scan(scan, sandbox=False)
    n, origin, area = best_window(env, size)
    if n < min_free * size * size:
        return None
    return {"name": name, "kind": "real", "scenario": scenario.name, "park": str(scenario),
            "window": [*origin, size], "free_tiles": n, "area_tiles": sorted(map(list, area)),
            "sandbox": False, "terraform": True}


def generate_all(log=print) -> None:
    """Freeze the development and held-out condition lists (run once, before any held-out run)."""
    for split, seeds in (("dev", range(100, 106)), ("heldout", range(200, 210))):
        out = BENCH / split
        out.mkdir(parents=True, exist_ok=True)
        for s in seeds:
            cond = make_synthetic(f"syn{s}", s)
            (out / f"syn{s}.json").write_text(json.dumps(cond))
            log(f"{split} syn{s}: {cond['params']}")
    rng = random.Random(2026)
    files = scenario_files()
    rng.shuffle(files)
    want = {"dev": 4, "heldout": 10}
    made = {"dev": 0, "heldout": 0}
    for f in files:
        split = "dev" if made["dev"] < want["dev"] else "heldout"
        if made[split] >= want[split]:
            break
        size = rng.choice((16, 20, 24))
        name = "real_" + "".join(c for c in f.stem.lower() if c.isalnum())[:28]
        cond = make_real(name, f, size)
        if cond is None:
            log(f"skip {f.name}: not enough free buildable land for {size}x{size}")
            continue
        (BENCH / split / f"{name}.json").write_text(json.dumps(cond))
        made[split] += 1
        log(f"{split} {name}: {f.name} window {cond['window']} free {cond['free_tiles']}")
