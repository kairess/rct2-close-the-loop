"""The general pipeline: a park file and an area in, the best coaster the game will rate out.

    condition JSON -> scan the land in the game -> place a station and close a first
    loop -> annealing search with circuit-preserving edits, judged by the game.

One fixed configuration (FIXED) is used for every condition; nothing here looks
at which condition it is running.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    "batch": 28,
    "workers": 14,
}


def load_condition(path: Path) -> dict:
    cond = json.loads(Path(path).read_text())
    cond["area"] = frozenset(tuple(t) for t in cond["area_tiles"])
    park = Path(cond["park"])
    cond["park_path"] = park if park.is_absolute() else ROOT / park
    return cond


def prepare(cond: dict, ride: str, log=print, judge_factory=None):
    """Scan the land and find a starting loop. Returns (layout, track, verdict)."""
    area = cond["area"]
    x0, y0, x1, y1 = bbox(area)
    # Scan a margin of 6 tiles: scenery near the station counts for the ratings even outside the area.
    env = scan_env(cond["park_path"], (x0 - 6, y0 - 6, x1 + 6, y1 + 6), sandbox=cond.get("sandbox", False),
                   terraform=cond.get("terraform", True), tunnels=cond.get("tunnels", False))
    log(f"land: {env.summary(area)}")
    base = BASES[ride]
    if judge_factory is None:
        from .judge import Judge

        judge_factory = lambda lay: Judge(lay)  # noqa: E731
    return find_start(base, env, area, str(cond["park_path"]), judge_factory=judge_factory, log=log)


def design(condition_path: Path, seed: int = 1, overrides: dict | None = None, log=print) -> Path:
    cfg_values = {**FIXED, **(overrides or {})}
    cond = load_condition(condition_path)
    layout, track, v0 = prepare(cond, cfg_values["ride"], log=log)
    log(f"start: station {layout.station_tile} dir {layout.station_dir} z {layout.ground_z}, "
        f"{len(track)} pieces, E{v0.excitement}/I{v0.intensity}/N{v0.nausea}")
    cfg = SearchConfig(
        layout_name=f"{cfg_values['ride']}@{cond['name']}",
        workers=cfg_values["workers"], batch=cfg_values["batch"], max_evals=10**9,
        max_minutes=cfg_values["minutes"], t0=cfg_values["t0"], t1=cfg_values["t1"], seed=seed,
        slack=cfg_values["slack"], chains=cfg_values["chains"],
        i_cap_start=cfg_values["i_cap_start"], i_cap_end=cfg_values["i_cap_end"],
    )
    run_dir = run(cfg, layout, initial=track, log_print=log)
    meta = {"condition": str(condition_path), "condition_name": cond["name"], "kind": cond.get("kind"),
            "config": cfg_values, "seed": seed, "station": [*layout.station_tile, layout.station_dir, layout.ground_z]}
    (run_dir / "design.json").write_text(json.dumps(meta, indent=1))
    return run_dir

