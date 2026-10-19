"""Summarize benchmark runs made by `rct2loop design` (runs/*/design.json).

    uv run python scripts/summarize_bench.py <split> runs/2026*/
"""

import json
import sys
from pathlib import Path


def meets(v: dict) -> bool:
    return v["stage"] == "rated" and v["E"] >= 7.68 and v["I"] < 7.68 and v["N"] < 5.12


split = sys.argv[1]
rows = []
for d in map(Path, sys.argv[2:]):
    meta_path = d / "design.json"
    if not meta_path.exists():
        continue
    meta = json.loads(meta_path.read_text())
    if f"/{split}/" not in meta["condition"]:
        continue
    cond = json.loads(Path(meta["condition"]).read_text())
    evals = [json.loads(line) for line in open(d / "evals.jsonl")]
    t0 = evals[0]["t"]
    first = next((r for r in evals if meets(r["verdict"])), None)
    goal = [r for r in evals if meets(r["verdict"])]
    best_goal = max(goal, key=lambda r: r["verdict"]["E"], default=None)
    feasible = [r for r in evals if r["verdict"]["stage"] == "rated" and r["verdict"]["I"] < 7.68 and r["verdict"]["N"] < 5.12]
    best_feasible = max(feasible, key=lambda r: r["verdict"]["E"], default=None)
    rows.append({
        "condition": meta["condition_name"], "kind": cond.get("kind"), "params": cond.get("params") or cond.get("scenario"),
        "tiles": len(cond["area_tiles"]), "seed": meta["seed"], "evals": len(evals),
        "goal": first is not None,
        "first_goal_min": round((first["t"] - t0) / 60, 2) if first else None,
        "best_goal": [best_goal["verdict"][k] for k in ("E", "I", "N")] if best_goal else None,
        "best_feasible": [best_feasible["verdict"][k] for k in ("E", "I", "N")] if best_feasible else None,
        "best_goal_eval": best_goal["eval"] if best_goal else None,
        "run": d.name,
    })
rows.sort(key=lambda r: r["condition"])
print(f"{'condition':36s} {'tiles':>5s} {'goal':>5s} {'first':>6s} {'best goal E/I/N':>18s} {'best feasible':>18s}")
for r in rows:
    fmt = lambda x: "/".join(f"{v:.2f}" for v in x) if x else "-"
    first = f"{r['first_goal_min']:.1f}" if r["goal"] else "-"
    print(f"{r['condition']:36s} {r['tiles']:>5d} {str(r['goal']):>5s} {first:>6s} {fmt(r['best_goal']):>18s} {fmt(r['best_feasible']):>18s}")
n = len(rows)
ok = sum(r["goal"] for r in rows)
print(f"success {ok}/{n}" + (f" = {ok / n:.0%}" if n else ""))
out = Path("results") / f"benchmark_{split}.json"
out.write_text(json.dumps({"split": split, "success": ok, "n": n, "rows": rows}, indent=1))
print("->", out)
