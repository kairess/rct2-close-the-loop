"""Collect the evidence for the goal criteria into results/report.json."""

from __future__ import annotations

import json
from pathlib import Path

from .analysis import summarize_run

ROOT = Path(__file__).resolve().parents[2]


def best_trajectory(run_dir: Path, points: int = 120) -> list[dict]:
    """Best-so-far score against evaluation count, thinned to about `points` entries."""
    traj = summarize_run(run_dir)["trajectory"]
    if len(traj) <= points:
        return traj
    step = len(traj) / points
    return [traj[int(i * step)] for i in range(points)] + [traj[-1]]


def collect(run_dirs: list[Path], out: Path) -> dict:
    runs = []
    for d in run_dirs:
        s = summarize_run(d)
        cfg = json.loads((d / "config.json").read_text())
        method = "mapelites" if "mapelites" in cfg else "anneal"
        layout = cfg["layout"]["ride_type_name"]
        runs.append({
            "run": d.name, "method": method, "ride": layout, "evals": s["evals"], "stages": s["stages"],
            "g2_sent": s["g2_sent_to_game"], "g2_rejects": s["g2_circuit_rejects"], "goal_hits": s["goal_hits"],
            "best": s["best"], "trajectory": best_trajectory(d),
        })
    report = {
        "runs": runs,
        "totals": {
            "evals": sum(r["evals"] for r in runs),
            "g2_sent": sum(r["g2_sent"] for r in runs),
            "g2_rejects": sum(r["g2_rejects"] for r in runs),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    return report
