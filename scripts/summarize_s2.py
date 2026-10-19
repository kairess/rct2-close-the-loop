"""Summarize S2 runs: did each terrain condition reach the goal, how fast, how high.

    uv run python scripts/summarize_s2.py runs/2026*-twister*/
"""

import json
import sys
from collections import Counter
from pathlib import Path


def meets(v: dict) -> bool:
    return v["stage"] == "rated" and v["E"] >= 7.68 and v["I"] < 7.68 and v["N"] < 5.12


rows = []
for d in map(Path, sys.argv[1:]):
    cfg = json.loads((d / "config.json").read_text())
    evals = [json.loads(line) for line in open(d / "evals.jsonl")]
    t0 = evals[0]["t"]
    first = next((r for r in evals if meets(r["verdict"])), None)
    goal = [r for r in evals if meets(r["verdict"])]
    best_goal = max(goal, key=lambda r: r["verdict"]["E"], default=None)
    rated = [r for r in evals if r["verdict"]["stage"] == "rated"]
    best_any = max(rated, key=lambda r: r["verdict"]["E"], default=None)
    stages = Counter(r["verdict"]["stage"] for r in evals)
    rows.append({
        "layout": cfg["search"]["layout_name"],
        "seed": cfg["search"]["seed"],
        "evals": len(evals),
        "minutes": round((evals[-1]["t"] - t0) / 60, 1),
        "goal": first is not None,
        "first_goal_min": round((first["t"] - t0) / 60, 2) if first else None,
        "first_goal_eval": first["eval"] if first else None,
        "best_goal": [best_goal["verdict"][k] for k in ("E", "I", "N")] if best_goal else None,
        "best_any": [best_any["verdict"][k] for k in ("E", "I", "N")] if best_any else None,
        "rated_share": round(stages["rated"] / len(evals), 3),
        "stages": dict(stages),
        "run": d.name,
    })

print(f"{'layout':24s} {'seed':>4s} {'evals':>6s} {'goal':>5s} {'first(min)':>10s} {'best goal E/I/N':>20s} {'rated':>6s}")
for r in rows:
    bg = "/".join(f"{x:.2f}" for x in r["best_goal"]) if r["best_goal"] else "-"
    fm = f"{r['first_goal_min']:.2f}" if r["goal"] else "-"
    print(f"{r['layout']:24s} {r['seed']:>4d} {r['evals']:>6d} {str(r['goal']):>5s} {fm:>10s} {bg:>20s} {r['rated_share']:>6.1%}")
out = Path("results/s2_summary.json")
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(rows, indent=1))
print("->", out)
