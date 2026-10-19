"""Summarize benchmark runs made by `rct2loop design` (runs/*/design.json).

    uv run python scripts/summarize_bench.py <split> runs/2026*/ [--out results/x.json] [--only-runs]

Every condition of the split appears in the table. A condition without a run
directory (the pipeline stopped before searching, e.g. no starting loop) is a
failure, with the last line of its runs/bench/<split>-<name>-seed1.out as the
error. --only-runs lists just the given runs (for a separate post-hoc re-run).
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def meets(v: dict) -> bool:
    return v["stage"] == "rated" and v["E"] >= 7.68 and v["I"] < 7.68 and v["N"] < 5.12


def summarize_run(d: Path) -> dict:
    meta = json.loads((d / "design.json").read_text())
    cond = json.loads((ROOT / meta["condition"]).read_text())
    evals = [json.loads(line) for line in open(d / "evals.jsonl")]
    t0 = evals[0]["t"]
    first = next((r for r in evals if meets(r["verdict"])), None)
    goal = [r for r in evals if meets(r["verdict"])]
    best_goal = max(goal, key=lambda r: r["verdict"]["E"], default=None)
    feasible = [r for r in evals if r["verdict"]["stage"] == "rated" and r["verdict"]["I"] < 7.68 and r["verdict"]["N"] < 5.12]
    best_feasible = max(feasible, key=lambda r: r["verdict"]["E"], default=None)
    return {
        "condition": meta["condition_name"], "kind": cond.get("kind"), "params": cond.get("params") or cond.get("scenario"),
        "tiles": len(cond["area_tiles"]), "seed": meta["seed"], "evals": len(evals),
        "goal": first is not None,
        "first_goal_min": round((first["t"] - t0) / 60, 2) if first else None,
        "best_goal": [best_goal["verdict"][k] for k in ("E", "I", "N")] if best_goal else None,
        "best_feasible": [best_feasible["verdict"][k] for k in ("E", "I", "N")] if best_feasible else None,
        "best_goal_eval": best_goal["eval"] if best_goal else None,
        "run": d.name, "error": None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("runs", nargs="*", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only-runs", action="store_true")
    args = ap.parse_args()
    split = args.split

    rows = []
    for d in args.runs:
        meta_path = d / "design.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        if f"/{split}/" not in meta["condition"]:
            continue
        rows.append(summarize_run(d))
    if not args.only_runs:
        have = {r["condition"] for r in rows}
        for path in sorted((ROOT / "data" / "bench" / split).glob("*.json")):
            cond = json.loads(path.read_text())
            if cond["name"] in have:
                continue
            out_file = ROOT / "runs" / "bench" / f"{split}-{cond['name']}-seed1.out"
            lines = [ln for ln in out_file.read_text(errors="replace").splitlines() if ln.strip()] if out_file.exists() else []
            rows.append({
                "condition": cond["name"], "kind": cond.get("kind"), "params": cond.get("params") or cond.get("scenario"),
                "tiles": len(cond["area_tiles"]), "seed": 1, "evals": 0, "goal": False, "first_goal_min": None,
                "best_goal": None, "best_feasible": None, "best_goal_eval": None, "run": None,
                "error": lines[-1] if lines else "not run",
            })
    rows.sort(key=lambda r: r["condition"])
    print(f"{'condition':36s} {'tiles':>5s} {'goal':>5s} {'first':>6s} {'best goal E/I/N':>18s} {'best feasible':>18s}")
    for r in rows:
        fmt = lambda x: "/".join(f"{v:.2f}" for v in x) if x else "-"  # noqa: E731
        first = f"{r['first_goal_min']:.1f}" if r["goal"] else "-"
        tail = f"  ERROR {r['error'][:60]}" if r["error"] else ""
        print(f"{r['condition']:36s} {r['tiles']:>5d} {str(r['goal']):>5s} {first:>6s} {fmt(r['best_goal']):>18s} "
              f"{fmt(r['best_feasible']):>18s}{tail}")
    n = len(rows)
    ok = sum(r["goal"] for r in rows)
    print(f"success {ok}/{n}" + (f" = {ok / n:.0%}" if n else ""))
    out = args.out or ROOT / "results" / f"benchmark_{split}.json"
    out.write_text(json.dumps({"split": split, "success": ok, "n": n, "rows": rows}, indent=1))
    print("->", out)


if __name__ == "__main__":
    main()
