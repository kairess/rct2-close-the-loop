"""The general pipeline: a park file and an area in, the best coaster the game will rate out.

    condition JSON -> scan the land in the game -> place a station and close a first
    loop -> annealing search with circuit-preserving edits, judged by the game.

One fixed configuration (FIXED) is used for every condition; nothing here looks
at which condition it is running.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

from .game import RUNTIME, Game, wait_ready
from .layouts import BASES
from .search import SearchConfig, run
from .site import bbox, find_start, scan_env

ROOT = Path(__file__).resolve().parents[2]

# P3: the single configuration used on every condition (chosen on development conditions only).
FIXED = {
    "ride": "twister",
    "minutes": 15.0,
    "chains": 4,
    "t0": 0.3,
    "t1": 0.02,
    "slack": 0.05,
    "i_cap_start": 6.5,
    "i_cap_end": 7.5,
    "priors": False,
    "i_price_start": 0.0,
    "i_price_end": 0.0,
    "circuits": "1",
    "decor": "rct2.scenery_small.tco",  # trees around the station and beside the track (decor.py)
    "batch": 28,
    "workers": 14,
    "goal": "very_high",
    "n_cap": 5.0,
    "cars": None,  # None: the game's default train length
    "station_len": None,  # None: the ride's base layout
    "lake": 0.0,  # share of the area dug into a lake before designing (landscape)
    "mounds": 0,  # 3x3 hills raised before designing, for tunnels (landscape)
    "tunnels": False,  # allow track fully below the surface
    "paths": False,  # route the exit path and queue line past the track in every evaluation (paths.py)
    "reversed": False,  # run the trains backwards
    "theme": False,  # match tree species, paths, colours and station style to the park around the area (theme.py)
    "height_price": 0.0,  # excitement given up per metre of mean track height above ground (supports)
}

# Phase 3: one coaster as exciting as possible (Extreme = 10.24). Intensity stays under the
# game's 10.00 excitement penalty; nausea is free.
EXTREME = {
    **FIXED,
    "goal": "extreme",
    "i_cap_start": 9.9,
    "i_cap_end": 9.9,
    "n_cap": 1000.0,
    "slack": 0.0,
}
CONFIGS = {"fixed": FIXED, "extreme": EXTREME}


def load_condition(path: Path) -> dict:
    cond = json.loads(Path(path).read_text())
    cond["area"] = frozenset(tuple(t) for t in cond["area_tiles"])
    park = Path(cond["park"])
    cond["park_path"] = park if park.is_absolute() else ROOT / park
    return cond


def landscape(cond: dict, lake: float = 0.0, mounds: int = 0, log=print) -> Path:
    """Shape the land before designing, on owned, dry, unobstructed, flat tiles of the area.

    - lake: dig the `lake` share of the area nearest its centroid two land steps down, with water
      at the old ground level. Track can skim water and land at the same height: water proximity
      (up to 135 points, about +0.41 excitement) on top of the ground-touch points the land keeps.
    - mounds: raise `mounds` flat-topped 3x3 hills by 4 land steps, spread over the rest. Track
      tunnelling through one is a sheltered section; up to 11 sections add about +0.33 excitement
      plus +0.05 each for entering cover pitched or banked, for little intensity (RideRatings.cpp).
    Returns the new park file."""
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    env = scan_env(cond["park_path"], (x0, y0, x1, y1), sandbox=cond.get("sandbox", False), terraform=True, tunnels=False)
    cx = sum(t[0] for t in area) / len(area)
    cy = sum(t[1] for t in area) / len(area)
    ok = [t for t in area if env.landscapable(t) and env.tiles[t].ground == env.tiles[t].base]
    ok.sort(key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
    lake_tiles = ok[: int(len(area) * lake)]
    heights = [[x, y, env.tiles[(x, y)].base // 8 - 4] for x, y in lake_tiles]
    water = [[x, y, env.tiles[(x, y)].base // 8] for x, y in lake_tiles]
    # Mounds: 3x3 blocks of free tiles at least 2 tiles inside the area, far from the lake and
    # from each other (greedy farthest-point choice, deterministic).
    free = set(ok) - set(lake_tiles)
    sites = [(x, y) for x, y in free
             if all((x + dx, y + dy) in free for dx in range(-3, 4) for dy in range(-3, 4))]
    chosen: list[tuple[int, int]] = []
    while sites and len(chosen) < mounds:
        best = max(sites, key=lambda t: (min(((t[0] - u[0]) ** 2 + (t[1] - u[1]) ** 2 for u in chosen), default=1e9),
                                         -((t[0] - cx) ** 2 + (t[1] - cy) ** 2)))
        chosen.append(best)
        sites = [t for t in sites if max(abs(t[0] - best[0]), abs(t[1] - best[1])) > 4]
    for mx, my in chosen:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                t = (mx + dx, my + dy)
                heights.append([t[0], t[1], env.tiles[t].base // 8 + 4])
    name = f"{cond['name']}_lake{int(lake * 100)}_m{len(chosen)}"
    with Game(park=cond["park_path"]) as g:
        wait_ready(g)
        g.call("setup", {"sandbox": cond.get("sandbox", False)})
        r = g.call("terraform", {"tiles": heights, "water": water}, timeout=600)
        if r["errors"]:
            log(f"landscape: {len(r['errors'])} changes refused, e.g. {r['errors'][:3]}")
        g.call("save", {"filename": name})
    dest = ROOT / "data" / "extreme" / "parks" / f"{name}.park"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUNTIME / "save" / f"{name}.park", dest)
    log(f"landscape: lake {len(lake_tiles)} of {len(area)} tiles, {len(chosen)} mounds -> {dest.relative_to(ROOT)}")
    return dest


def prepare(cond: dict, ride: str, log=print, judge_factory=None, decor: str | None = None,
            cars: int | None = None, station_len: int | None = None, paths: bool = False,
            reversed_trains: bool = False, use_theme: bool = False):
    """Scan the land and find a starting loop. Returns (layout, track, verdict)."""
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    # Scan a margin of 6 tiles: scenery near the station counts for the ratings even outside the area.
    env = scan_env(cond["park_path"], (x0 - 6, y0 - 6, x1 + 6, y1 + 6), sandbox=cond.get("sandbox", False),
                   terraform=cond.get("terraform", True), tunnels=cond.get("tunnels", False))
    log(f"land: {env.summary(area)}")
    look = None
    if use_theme:
        from . import theme as theme_mod

        look = theme_mod.build(theme_mod.census(cond["park_path"], (x0 - 20, y0 - 20, x1 + 20, y1 + 20),
                                                cond.get("sandbox", False)), decor)
        log(f"theme: {look['palette']} on {look['terrain']}, trees {sorted(set(look['trees']))}, paths {look['paths']}")
    base = dataclasses.replace(BASES[ride], decor=decor, cars=cars, paths=paths, reversed=reversed_trains, theme=look)
    if station_len:
        base = dataclasses.replace(base, station_len=station_len)
    if judge_factory is None:
        from .judge import Judge

        judge_factory = lambda lay: Judge(lay)  # noqa: E731
    return find_start(base, env, area, str(cond["park_path"]), judge_factory=judge_factory, log=log)


def design(condition_path: Path, seed: int = 1, overrides: dict | None = None, log=print,
           config: str = "fixed") -> Path:
    cfg_values = {**CONFIGS[config], **(overrides or {})}
    cond = load_condition(condition_path)
    if cfg_values.get("lake") or cfg_values.get("mounds"):
        cond["park_path"] = landscape(cond, cfg_values.get("lake", 0.0), cfg_values.get("mounds", 0), log=log)
    if cfg_values.get("tunnels"):
        cond["tunnels"] = True
    layout, track, v0 = prepare(cond, cfg_values["ride"], log=log, decor=cfg_values.get("decor"),
                                cars=cfg_values.get("cars"), station_len=cfg_values.get("station_len"),
                                paths=cfg_values.get("paths", False), reversed_trains=cfg_values.get("reversed", False),
                                use_theme=cfg_values.get("theme", False))
    log(f"start: station {layout.station_tile} dir {layout.station_dir} z {layout.ground_z}, "
        f"{len(track)} pieces, E{v0.excitement}/I{v0.intensity}/N{v0.nausea}")
    cfg = SearchConfig(
        layout_name=f"{cfg_values['ride']}@{cond['name']}",
        workers=cfg_values["workers"], batch=cfg_values["batch"], max_evals=10**9,
        max_minutes=cfg_values["minutes"], t0=cfg_values["t0"], t1=cfg_values["t1"], seed=seed,
        slack=cfg_values["slack"], chains=cfg_values["chains"],
        i_cap_start=cfg_values["i_cap_start"], i_cap_end=cfg_values["i_cap_end"],
        priors=cfg_values["priors"], i_price_start=cfg_values["i_price_start"], i_price_end=cfg_values["i_price_end"],
        circuits=cfg_values["circuits"], goal=cfg_values["goal"], n_cap=cfg_values["n_cap"],
        height_price=cfg_values.get("height_price", 0.0),
    )
    run_dir = run(cfg, layout, initial=track, log_print=log)
    meta = {"condition": str(condition_path), "condition_name": cond["name"], "kind": cond.get("kind"),
            "config": cfg_values, "seed": seed, "station": [*layout.station_tile, layout.station_dir, layout.ground_z],
            "park": str(cond["park_path"]), "tunnels": bool(cond.get("tunnels")), "theme": layout.theme}
    (run_dir / "design.json").write_text(json.dumps(meta, indent=1))
    return run_dir



def layout_from_run(run_dir: Path):
    """Rebuild the layout a design run used (land re-scanned from its park). Returns (layout, meta)."""
    meta = json.loads((Path(run_dir) / "design.json").read_text())
    cond = load_condition(ROOT / meta["condition"] if not Path(meta["condition"]).is_absolute() else meta["condition"])
    if meta.get("park"):  # the landscaped park the run designed on
        cond["park_path"] = Path(meta["park"])
    cond["tunnels"] = meta.get("tunnels", cond.get("tunnels", False))
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    env = scan_env(cond["park_path"], (x0 - 6, y0 - 6, x1 + 6, y1 + 6), sandbox=cond.get("sandbox", False),
                   terraform=cond.get("terraform", True), tunnels=cond.get("tunnels", False))
    sx, sy, sd, sz = meta["station"]
    cfg = meta["config"]
    layout = dataclasses.replace(BASES[cfg["ride"]], station_tile=(sx, sy), station_dir=sd, ground_z=sz,
                                 env=env, area_tiles=area, area=bbox(area), park=str(cond["park_path"]),
                                 decor=cfg.get("decor"), cars=cfg.get("cars"), paths=cfg.get("paths", False),
                                 reversed=cfg.get("reversed", False), theme=meta.get("theme"))
    if cfg.get("station_len"):
        layout = dataclasses.replace(layout, station_len=cfg["station_len"])
    return layout, meta


def continue_run(run_dir: Path, minutes: float, seed: int = 2, t0: float = 0.1, log=print) -> Path:
    """Search on from a design run's best track: same land, station and configuration, a cooler start."""
    layout, meta = layout_from_run(run_dir)
    cfg_values = {**meta["config"], "minutes": minutes, "t0": t0}
    icap = cfg_values["i_cap_end"] + 0.05
    best = None
    with open(Path(run_dir) / "evals.jsonl") as f:
        for line in f:
            r = json.loads(line)
            v = r["verdict"]
            if v["stage"] == "rated" and v["I"] < icap and (best is None or v["E"] > best["verdict"]["E"]):
                best = r
    track = [tuple(p) for p in best["track"]]
    log(f"continue from {Path(run_dir).name} eval {best['eval']} E{best['verdict']['E']}")
    cfg = SearchConfig(
        layout_name=f"{cfg_values['ride']}@{meta['condition_name']}+",
        workers=cfg_values["workers"], batch=cfg_values["batch"], max_evals=10**9,
        max_minutes=minutes, t0=t0, t1=cfg_values["t1"], seed=seed,
        slack=cfg_values["slack"], chains=cfg_values["chains"],
        i_cap_start=cfg_values["i_cap_end"], i_cap_end=cfg_values["i_cap_end"],
        priors=cfg_values["priors"], i_price_start=cfg_values["i_price_start"], i_price_end=cfg_values["i_price_end"],
        circuits=cfg_values["circuits"], goal=cfg_values["goal"], n_cap=cfg_values["n_cap"],
        height_price=cfg_values.get("height_price", 0.0),
    )
    out = run(cfg, layout, initial=track, log_print=log)
    meta = {**meta, "config": cfg_values, "seed": seed, "continued_from": str(run_dir), "from_eval": best["eval"]}
    (out / "design.json").write_text(json.dumps(meta, indent=1))
    return out
