"""MAP-Elites over (intensity, nausea) with excitement as fitness.

The archive keeps, for every intensity x nausea cell, the most exciting track
found so far. Parents come from the archive (biased toward cells inside the
goal's intensity/nausea limits), each gets one circuit-preserving edit, and
the game rates the children. Evaluation is steady-state: whenever one result
comes back it is filed and a new child is submitted, so no worker waits for
the slowest member of a batch. Low-intensity designs stay in the archive as
stepping stones instead of being annealed away.
Logging matches search.py: one row per evaluation in evals.jsonl.
"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import FIRST_COMPLETED, wait
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
    inflight: int = 28
    max_evals: int = 30000
    max_minutes: float = 60.0
    hill: int = 6
    seed: int = 1
    goal_bias: float = 0.5  # share of parents drawn from cells that satisfy the I/N limits
    tournament: int = 2  # goal-cell parents are the best of this many random goal cells
    max_window: int = 12
    max_walk: int = 8
    progress_every: int = 200
    stop_on_goal: bool = False


def cell_of(v: Verdict) -> tuple[int, int]:
    return (int(v.intensity / I_STEP), int(v.nausea / N_STEP))


def in_goal_box(cell: tuple[int, int]) -> bool:
    return (cell[0] + 1) * I_STEP <= GOAL_I and (cell[1] + 1) * N_STEP <= GOAL_N


def elites_from_run(run_dir, limit: int = 80) -> list[list[tuple[int, bool]]]:
    """Best rated track per (I, N) cell in an earlier run's evals.jsonl, most exciting first."""
    best: dict[tuple[int, int], dict] = {}
    with open(run_dir / "evals.jsonl") as f:
        for line in f:
            r = json.loads(line)
            v = r["verdict"]
            if v["stage"] != "rated":
                continue
            c = (int(v["I"] / I_STEP), int(v["N"] / N_STEP))
            if c not in best or v["E"] > best[c]["verdict"]["E"]:
                best[c] = r
    ranked = sorted(best.values(), key=lambda r: -r["verdict"]["E"])[:limit]
    return [[tuple(p) for p in r["track"]] for r in ranked]


def run(cfg: MapElitesConfig, layout: Layout, initial: list[list[tuple[int, bool]]] | None = None, log_print=print):
    rng = random.Random(cfg.seed)
    pieces = piece_set(layout.ride_type_name)
    gen = EditGenerator(layout, pieces, seed=cfg.seed, max_window=cfg.max_window, max_walk=cfg.max_walk)
    seeds = initial or [oval(layout, hill=cfg.hill)]

    log = RunLog(f"{cfg.layout_name}-me", {"mapelites": cfg.__dict__, "layout": layout.to_record(), "git": git_rev(), "pieces": sorted(pieces)})
    pool = JudgePool(layout, cfg.workers)
    log_print(f"run dir: {log.dir}  workers={pool.size}")
    started = time.monotonic()
    archive: dict[tuple[int, int], dict] = {}
    best: dict | None = None
    stages: dict[str, int] = {}
    improved = 0

    def minutes() -> float:
        return (time.monotonic() - started) / 60

    def consider(track, v: Verdict, eid: int) -> bool:
        nonlocal best
        if not v.rated:
            return False
        c = cell_of(v)
        old = archive.get(c)
        better = old is None or v.excitement > old["v"].excitement
        if better:
            archive[c] = {"track": track, "v": v, "eval": eid}
        if in_goal_box(c) and (best is None or v.excitement > best["v"].excitement):
            best = {"track": track, "v": v, "eval": eid}
            log.best({"eval": eid, "score": v.excitement, "verdict": v.to_dict(), "track": track})
            log_print(f"[e{log.n} {minutes():.1f}m] new best in goal box {summarize(v)} pieces={len(track)} "
                      f"goal={'YES' if meets_goal(v) else 'no'}")
        return better

    def pick_parent() -> dict:
        cells = list(archive)
        goal_cells = [c for c in cells if in_goal_box(c)]
        if goal_cells and rng.random() < cfg.goal_bias:
            # Tournament among goal cells: some pressure toward the most exciting elites.
            picks = [archive[rng.choice(goal_cells)] for _ in range(cfg.tournament)]
            return max(picks, key=lambda a: a["v"].excitement)
        return archive[rng.choice(cells)]

    inflight: dict = {}

    def submit_one() -> None:
        for _ in range(20):
            parent = pick_parent()
            prop = gen.propose(parent["track"])
            if prop:
                child, edit = prop
                inflight[pool.submit(child)] = (parent, child, edit)
                return

    try:
        for track, v in zip(seeds, pool.map(seeds)):
            eid = log.eval({"before": None, "edit": None, "track": track, "verdict": v.to_dict(), "score": v.excitement, "round": 0})
            consider(track, v, eid)
        if not archive:
            raise RuntimeError("no seed track was rated")

        for _ in range(cfg.inflight):
            submit_one()
        next_progress = log.n + cfg.progress_every
        while inflight:
            done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for fut in done:
                parent, child, edit = inflight.pop(fut)
                v = fut.result()
                stages[v.stage] = stages.get(v.stage, 0) + 1
                eid = log.eval({
                    "before": parent["eval"], "edit": edit.to_dict(), "track": child,
                    "verdict": v.to_dict(), "score": v.excitement if v.rated else None, "round": None,
                })
                improved += consider(child, v, eid)
                stop = (log.n >= cfg.max_evals or minutes() >= cfg.max_minutes
                        or (cfg.stop_on_goal and best is not None and meets_goal(best["v"])))
                if not stop:
                    submit_one()
            if log.n >= next_progress:
                next_progress += cfg.progress_every
                goal_cells = sum(1 for c in archive if in_goal_box(c))
                top = sorted(archive.values(), key=lambda a: -a["v"].excitement)[:3]
                rec = {
                    "evals": log.n, "minutes": round(minutes(), 2), "cells": len(archive), "goal_cells": goal_cells,
                    "improved": improved, "stages": dict(stages), "best": summarize(best["v"]) if best else None,
                    "top_any": [summarize(a["v"]) for a in top],
                }
                log.progress(rec)
                if log.n % (cfg.progress_every * 10) < cfg.progress_every:
                    log_print(f"[e{log.n} {minutes():.1f}m] cells={len(archive)} goal_cells={goal_cells} "
                              f"best={rec['best']} top_any={rec['top_any']} stages={dict(stages)}")
                stages.clear()
                improved = 0
    finally:
        pool.close()
        snapshot = [
            {"cell": list(c), "eval": a["eval"], "verdict": a["v"].to_dict(), "track": a["track"]}
            for c, a in sorted(archive.items())
        ]
        (log.dir / "archive.json").write_text(json.dumps(snapshot))
        log.close()
    return log.dir
