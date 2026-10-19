"""Summaries of search runs (runs/<run>/evals.jsonl)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

CIRCUIT_WORDS = ("circuit", "complete")


def load_evals(run_dir: Path) -> list[dict]:
    with open(run_dir / "evals.jsonl") as f:
        return [json.loads(line) for line in f]


def summarize_run(run_dir: Path) -> dict:
    recs = load_evals(run_dir)
    stages = Counter(r["verdict"]["stage"] for r in recs)
    errors = Counter(
        (r["verdict"]["stage"], (r["verdict"]["error"] or "")[:100])
        for r in recs
        if r["verdict"]["stage"] not in ("rated", "timeout")
    )
    # G2: candidates the geometry model called closed that the game refused as an incomplete circuit.
    sent = [r for r in recs if r["verdict"]["stage"] != "prefilter"]
    circuit_rejects = [
        r for r in sent
        if r["verdict"]["stage"] == "test_start" and any(w in (r["verdict"]["error"] or "").lower() for w in CIRCUIT_WORDS)
    ]
    best = None
    trajectory = []
    for r in recs:
        s = r.get("score")
        if s is not None and (best is None or s > best["score"]):
            best = r
            trajectory.append({"eval": r["eval"], "score": round(s, 3), "E": r["verdict"]["E"], "I": r["verdict"]["I"], "N": r["verdict"]["N"]})
    goal = [
        r for r in recs
        if r["verdict"]["stage"] == "rated" and r["verdict"]["E"] >= 7.68 and r["verdict"]["I"] < 7.68 and r["verdict"]["N"] < 5.12
    ]
    return {
        "run": run_dir.name,
        "evals": len(recs),
        "stages": dict(stages),
        "errors": [{"count": c, "stage": k[0], "error": k[1]} for k, c in errors.most_common(10)],
        "g2_sent_to_game": len(sent),
        "g2_circuit_rejects": len(circuit_rejects),
        "goal_hits": len(goal),
        "best": {"eval": best["eval"], "score": best["score"], "verdict": best["verdict"], "pieces": len(best["track"])} if best else None,
        "trajectory": trajectory,
    }
