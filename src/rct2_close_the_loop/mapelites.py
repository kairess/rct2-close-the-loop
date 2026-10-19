"""MAP-Elites over (intensity, nausea) with excitement as fitness.

The archive keeps, for every intensity x nausea cell, the most exciting track
found so far. Each round picks parents from the archive (biased toward cells
inside the goal's intensity/nausea limits), applies one circuit-preserving
edit to each, and lets the game rate the children in parallel. Low-intensity
designs stay in the archive as stepping stones instead of being annealed away.
Logging matches search.py: one row per evaluation in evals.jsonl.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass

from .edits import EditGenerator
from .judge import JudgePool, Verdict
from .layouts import oval
from .search import RunLog, git_rev, meets_goal, summarize
from .track import Layout, piece_set

I_STEP = 0.25
N_STEP = 0.25
GOAL_I = 7.68
GOAL_N = 5.12


@dataclass
class MapElitesConfig:
    layout_name: str
    workers: int = 14
    batch: int = 28
    max_evals: int = 30000
    max_minutes: float = 60.0
    hill: int = 6
    seed: int = 1
    goal_bias: float = 0.5  # share of parents drawn from cells that satisfy the I/N limits
    stop_on_goal: bool = False


def cell_of(v: Verdict) -> tuple[int, int]:
    return (int(v.intensity / I_STEP), int(v.nausea / N_STEP))


def in_goal_box(cell: tuple[int, int]) -> bool:
    return (cell[0] + 1) * I_STEP <= GOAL_I and (cell[1] + 1) * N_STEP <= GOAL_N


def run(cfg: MapElitesConfig, layout: Layout, initial: list[list[tuple[int, bool]]] | None = None, log_print=print):
    rng = random.Random(cfg.seed)
    pieces = piece_set(layout.ride_type_name)
    gen = EditGenerator(layout, pieces, seed=cfg.seed)
    seeds = initial or [oval(layout, hill=cfg.hill)]

    log = RunLog(f"{cfg.layout_name}-me", {"mapelites": cfg.__dict__, "layout": layout.__dict__, "git": git_rev(), "pieces": sorted(pieces)})
    pool = JudgePool(layout, cfg.workers)
    log_print(f"run dir: {log.dir}  workers={pool.size}")
    started = time.monotonic()
    archive: dict[tuple[int, int], dict] = {}
    best: dict | None = None

    def consider(track, v: Verdict, eid: int) -> bool:
        nonlocal best
        if not v.rated:
            return False
        c = cell_of(v)
        old = archive.get(c)
        improved = old is None or v.excitement > old["v"].excitement
        if improved:
            archive[c] = {"track": track, "v": v, "eval": eid}
        if in_goal_box(c) and (best is None or v.excitement > best["v"].excitement):
            best = {"track": track, "v": v, "eval": eid}
            log.best({"eval": eid, "score": v.excitement, "verdict": v.to_dict(), "track": track})
            log_print(f"[e{log.n}] new best in goal box {summarize(v)} pieces={len(track)} goal={'YES' if meets_goal(v) else 'no'}")
        return improved

    try:
        for track, v in zip(seeds, pool.map(seeds)):
            eid = log.eval({"before": None, "edit": None, "track": track, "verdict": v.to_dict(), "score": v.excitement, "round": 0})
            consider(track, v, eid)
        if not archive:
            raise RuntimeError("no seed track was rated")

        rnd = 0
        while log.n < cfg.max_evals and (time.monotonic() - started) / 60 < cfg.max_minutes:
            rnd += 1
            cells = list(archive)
            goal_cells = [c for c in cells if in_goal_box(c)]
            parents = []
            for _ in range(cfg.batch):
                pool_cells = goal_cells if goal_cells and rng.random() < cfg.goal_bias else cells
                parents.append(archive[rng.choice(pool_cells)])
            children = []
            for p in parents:
                prop = gen.propose(p["track"])
                if prop:
                    children.append((p, *prop))
            verdicts = pool.map([c for _, c, _ in children])
            added = 0
            stages: dict[str, int] = {}
            for (parent, child, edit), v in zip(children, verdicts):
                stages[v.stage] = stages.get(v.stage, 0) + 1
                eid = log.eval({
                    "before": parent["eval"], "edit": edit.to_dict(), "track": child,
                    "verdict": v.to_dict(), "score": v.excitement if v.rated else None, "round": rnd,
                })
                added += consider(child, v, eid)
            log.progress({
                "round": rnd, "evals": log.n, "minutes": round((time.monotonic() - started) / 60, 2),
                "cells": len(archive), "goal_cells": len(goal_cells), "improved": added, "stages": stages,
                "best": summarize(best["v"]) if best else None,
                "max_E_any": round(max(a["v"].excitement for a in archive.values()), 2),
            })
            if rnd % 25 == 0:
                top = sorted(archive.items(), key=lambda kv: -kv[1]["v"].excitement)[:3]
                log_print(f"[r{rnd} e{log.n} {(time.monotonic()-started)/60:.1f}m] cells={len(archive)} goal_cells={len(goal_cells)} "
                          f"best={summarize(best['v']) if best else None} top_any={[summarize(a['v']) for _, a in top]}")
            if cfg.stop_on_goal and best and meets_goal(best["v"]):
                log_print("goal met; stopping")
                break
    finally:
        pool.close()
        snapshot = [
            {"cell": list(c), "eval": a["eval"], "verdict": a["v"].to_dict(), "track": a["track"]}
            for c, a in sorted(archive.items())
        ]
        (log.dir / "archive.json").write_text(json.dumps(snapshot))
        log.close()
    return log.dir
