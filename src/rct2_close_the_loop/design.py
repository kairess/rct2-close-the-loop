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
    "lake": 0.0,  # share of the area dug into a lake before designing (landscape_lake)
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


def landscape_lake(cond: dict, fraction: float, log=print) -> Path:
    """Dig a lake into the middle of the area: the owned, dry, unobstructed tiles nearest the area's
    centroid, `fraction` of the area, lowered two land steps with water at the old ground level.

    Track can then skim the water and the land at the same height: pieces over water score
    WATER_OVER/TOUCH/LOW/HIGH proximity (up to 135 points, about +0.41 excitement) on top of the
    ground-touch points (120) the land still gives. Returns the new park file."""
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    env = scan_env(cond["park_path"], (x0, y0, x1, y1), sandbox=cond.get("sandbox", False), terraform=True, tunnels=False)
    cx = sum(t[0] for t in area) / len(area)
    cy = sum(t[1] for t in area) / len(area)
    ok = [t for t in area if env.landscapable(t) and env.tiles[t].ground == env.tiles[t].base]
    ok.sort(key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
    lake = ok[: int(len(area) * fraction)]
    heights = [[x, y, env.tiles[(x, y)].base // 8 - 4] for x, y in lake]
    water = [[x, y, env.tiles[(x, y)].base // 8] for x, y in lake]
    name = f"{cond['name']}_lake{int(fraction * 100)}"
    with Game(park=cond["park_path"]) as g:
        wait_ready(g)
        g.call("setup", {"sandbox": cond.get("sandbox", False)})
        r = g.call("terraform", {"tiles": heights, "water": water}, timeout=600)
        if r["errors"]:
            log(f"lake: {len(r['errors'])} tiles refused, e.g. {r['errors'][:3]}")
        g.call("save", {"filename": name})
    dest = ROOT / "data" / "extreme" / "parks" / f"{name}.park"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUNTIME / "save" / f"{name}.park", dest)
    log(f"lake: {len(lake)} of {len(area)} tiles -> {dest.relative_to(ROOT)}")
    return dest


def prepare(cond: dict, ride: str, log=print, judge_factory=None, decor: str | None = None,
            cars: int | None = None, station_len: int | None = None):
    """Scan the land and find a starting loop. Returns (layout, track, verdict)."""
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    # Scan a margin of 6 tiles: scenery near the station counts for the ratings even outside the area.
    env = scan_env(cond["park_path"], (x0 - 6, y0 - 6, x1 + 6, y1 + 6), sandbox=cond.get("sandbox", False),
                   terraform=cond.get("terraform", True), tunnels=cond.get("tunnels", False))
    log(f"land: {env.summary(area)}")
    base = dataclasses.replace(BASES[ride], decor=decor, cars=cars)
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
    if cfg_values.get("lake"):
        cond["park_path"] = landscape_lake(cond, cfg_values["lake"], log=log)
    layout, track, v0 = prepare(cond, cfg_values["ride"], log=log, decor=cfg_values.get("decor"),
                                cars=cfg_values.get("cars"), station_len=cfg_values.get("station_len"))
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
    )
    run_dir = run(cfg, layout, initial=track, log_print=log)
    meta = {"condition": str(condition_path), "condition_name": cond["name"], "kind": cond.get("kind"),
            "config": cfg_values, "seed": seed, "station": [*layout.station_tile, layout.station_dir, layout.ground_z]}
    (run_dir / "design.json").write_text(json.dumps(meta, indent=1))
    return run_dir



def layout_from_run(run_dir: Path):
    """Rebuild the layout a design run used (land re-scanned from its park). Returns (layout, meta)."""
    meta = json.loads((Path(run_dir) / "design.json").read_text())
    cond = load_condition(ROOT / meta["condition"] if not Path(meta["condition"]).is_absolute() else meta["condition"])
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    env = scan_env(cond["park_path"], (x0 - 6, y0 - 6, x1 + 6, y1 + 6), sandbox=cond.get("sandbox", False),
                   terraform=cond.get("terraform", True), tunnels=cond.get("tunnels", False))
    sx, sy, sd, sz = meta["station"]
    layout = dataclasses.replace(BASES[meta["config"]["ride"]], station_tile=(sx, sy), station_dir=sd, ground_z=sz,
                                 env=env, area_tiles=area, area=bbox(area), park=str(cond["park_path"]),
                                 decor=meta["config"].get("decor"))
    return layout, meta
