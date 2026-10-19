"""Loop-first, segment-edit search with the game as judge.

Simulated annealing over closed circuits: every round proposes a batch of
circuit-preserving edits to the current track, the judge pool rates them in
parallel, and the best of the batch is accepted by the Metropolis rule.
Every evaluation is appended to runs/<run>/evals.jsonl as
(before track id, edit, after track, verdict, score).
"""

from __future__ import annotations

import json
import math
import random
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .edits import EditGenerator
from .judge import JudgePool, Verdict
from .layouts import oval
from .track import Layout, piece_set

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"

# Constraint caps sit just inside the goal's grade boundaries (I < 7.68, N < 5.12).
I_CAP = 7.50
N_CAP = 5.00
PENALTY = 2.0


def score(v: Verdict, slack: float = 0.0) -> float | None:
    """Excitement minus penalties past the I/N caps.

    `slack` > 0 adds a small preference for lower intensity and nausea, so that
    between near-equal excitements the search keeps the design with headroom
    (e.g. lateral G just under the 2.80 penalty cliff) instead of a coin flip.
    """
    if not v.rated:
        return None
    s = v.excitement - PENALTY * max(0.0, v.intensity - I_CAP) - PENALTY * max(0.0, v.nausea - N_CAP)
    return s - slack * (v.intensity + v.nausea) / 2


def meets_goal(v: Verdict) -> bool:
    return v.rated and v.excitement >= 7.68 and v.intensity < 7.68 and v.nausea < 5.12


@dataclass
class SearchConfig:
    layout_name: str
    workers: int = 14
    batch: int = 28
    max_evals: int = 20000
    max_minutes: float = 120.0
    t0: float = 0.6
    t1: float = 0.02
    hill: int = 6
    seed: int = 1
    reheat_after: int = 60  # rounds without a new best
    slack: float = 0.0  # weight of the low-I/N tie-breaker in score()
    stop_on_goal: bool = False


class RunLog:
    def __init__(self, name: str, config: dict):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = RUNS / f"{stamp}-{name}"
        self.dir.mkdir(parents=True, exist_ok=False)
        (self.dir / "config.json").write_text(json.dumps(config, indent=2))
        self._evals = open(self.dir / "evals.jsonl", "a", buffering=1)
        self._progress = open(self.dir / "progress.jsonl", "a", buffering=1)
        self.n = 0

    def eval(self, record: dict) -> int:
        record = {"eval": self.n, "t": round(time.time(), 3), **record}
        self._evals.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.n += 1
        return record["eval"]

    def progress(self, record: dict) -> None:
        self._progress.write(json.dumps(record, separators=(",", ":")) + "\n")

    def best(self, record: dict, name: str = "best.json") -> None:
        (self.dir / name).write_text(json.dumps(record, indent=1))

    def close(self) -> None:
        self._evals.close()
        self._progress.close()


def git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def summarize(v: Verdict) -> str:
    if not v.rated:
        return v.stage
    return f"E{v.excitement:.2f}/I{v.intensity:.2f}/N{v.nausea:.2f}"


def run(cfg: SearchConfig, layout: Layout, initial: list[tuple[int, bool]] | None = None, log_print=print) -> Path:
    rng = random.Random(cfg.seed)
    pieces = piece_set(layout.ride_type_name)
    gen = EditGenerator(layout, pieces, seed=cfg.seed)
    track = initial or oval(layout, hill=cfg.hill)

    log = RunLog(cfg.layout_name, {"search": cfg.__dict__, "layout": layout.to_record(), "git": git_rev(), "pieces": sorted(pieces)})
    pool = JudgePool(layout, cfg.workers)
    log_print(f"run dir: {log.dir}  workers={pool.size}")
    started = time.monotonic()
    try:
        v0 = pool.map([track])[0]
        cur_id = log.eval({"before": None, "edit": None, "track": track, "verdict": v0.to_dict(), "score": score(v0, cfg.slack), "round": 0})
        cur, cur_v, cur_s = track, v0, score(v0, cfg.slack)
        if cur_s is None:
            raise RuntimeError(f"initial track not rated: {v0.to_dict()}")
        best, best_v, best_s, best_id = cur, cur_v, cur_s, cur_id
        log.best({"eval": best_id, "score": best_s, "verdict": best_v.to_dict(), "track": best})
        log_print(f"initial: {summarize(v0)} score={cur_s:.3f} pieces={len(track)}")

        rnd = 0
        since_best = 0
        goal_hits = 0
        best_goal: float | None = None
        while log.n < cfg.max_evals and (time.monotonic() - started) / 60 < cfg.max_minutes:
            rnd += 1
            frac = min(1.0, log.n / cfg.max_evals)
            temp = cfg.t0 * (cfg.t1 / cfg.t0) ** frac
            proposals = []
            for _ in range(cfg.batch):
                p = gen.propose(cur)
                if p:
                    proposals.append(p)
            verdicts = pool.map([c for c, _ in proposals])
            stages: dict[str, int] = {}
            round_best = None
            for (cand, edit), v in zip(proposals, verdicts):
                s = score(v, cfg.slack)
                stages[v.stage] = stages.get(v.stage, 0) + 1
                eid = log.eval({
                    "before": cur_id, "edit": edit.to_dict(), "track": cand,
                    "verdict": v.to_dict(), "score": s, "round": rnd,
                })
                if meets_goal(v):
                    goal_hits += 1
                    if best_goal is None or v.excitement > best_goal:
                        best_goal = v.excitement
                        log.best({"eval": eid, "score": s, "verdict": v.to_dict(), "track": cand, "round": rnd}, "best_goal.json")
                        log_print(f"[r{rnd} e{log.n}] GOAL MET {summarize(v)} pieces={len(cand)}")
                if s is not None and (round_best is None or s > round_best[0]):
                    round_best = (s, cand, v, eid)
            accepted = None
            if round_best is not None:
                s, cand, v, eid = round_best
                if s >= cur_s or rng.random() < math.exp((s - cur_s) / max(temp, 1e-9)):
                    cur, cur_v, cur_s, cur_id = cand, v, s, eid
                    accepted = eid
                if s > best_s:
                    best, best_v, best_s, best_id = cand, v, s, eid
                    since_best = 0
                    log.best({"eval": best_id, "score": best_s, "verdict": best_v.to_dict(), "track": best, "round": rnd})
                    log_print(f"[r{rnd} e{log.n}] new best {summarize(best_v)} score={best_s:.3f} pieces={len(best)} "
                              f"goal={'YES' if meets_goal(best_v) else 'no'}")
            since_best += 1
            if since_best >= cfg.reheat_after:
                cur, cur_v, cur_s, cur_id = best, best_v, best_s, best_id
                since_best = 0
                log_print(f"[r{rnd} e{log.n}] stagnation: restart from best")
            log.progress({
                "round": rnd, "evals": log.n, "minutes": round((time.monotonic() - started) / 60, 2),
                "temp": round(temp, 4), "cur_score": round(cur_s, 3), "cur": summarize(cur_v),
                "best_score": round(best_s, 3), "best": summarize(best_v), "accepted_eval": accepted,
                "stages": stages, "proposals": len(proposals), "goal_hits": goal_hits, "cur_len": len(cur),
            })
            if rnd % 20 == 0:
                log_print(f"[r{rnd} e{log.n} {((time.monotonic()-started)/60):.1f}m] T={temp:.3f} cur={summarize(cur_v)} "
                          f"best={summarize(best_v)} stages={stages}")
            if cfg.stop_on_goal and meets_goal(best_v):
                log_print("goal met; stopping")
                break
    finally:
        pool.close()
        log.close()
    return log.dir
