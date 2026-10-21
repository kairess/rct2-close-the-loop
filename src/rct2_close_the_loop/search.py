"""Loop-first, segment-edit search with the game as judge.

Simulated annealing over closed circuits: every round proposes a batch of
circuit-preserving edits to the current track of each chain, the judge pool
rates them in parallel, and each chain accepts its best candidate by the
Metropolis rule. A chain that stops improving restarts from the starting
oval, so one unlucky trajectory does not decide the run.
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


# Goals: the grade boundaries a design must meet. "extreme" asks only for excitement 10.24
# and keeps intensity under 10.00, where the game starts cutting excitement by a quarter.
GOALS = {
    "very_high": {"E": 7.68, "I": 7.68, "N": 5.12},
    "extreme": {"E": 10.24, "I": 10.00, "N": float("inf")},
}


def score(v: Verdict, slack: float = 0.0, i_cap: float = I_CAP, n_cap: float = N_CAP,
          height_price: float = 0.0) -> float | None:
    """Excitement minus penalties past the I/N caps.

    `slack` > 0 adds a small preference for lower intensity and nausea, so that
    between near-equal excitements the search keeps the design with headroom
    (e.g. lateral G just under the 2.80 penalty cliff) instead of a coin flip.
    A lower `i_cap` early in a run keeps designs from spending the whole
    intensity budget before their excitement structure is in place.
    `height_price` is the excitement given up per metre of mean height above
    ground (fewer, shorter supports).
    """
    if not v.rated:
        return None
    s = v.excitement - PENALTY * max(0.0, v.intensity - i_cap) - PENALTY * max(0.0, v.nausea - n_cap)
    return s - slack * (v.intensity + v.nausea) / 2 - height_price * v.height


def meets_goal(v: Verdict, goal: str = "very_high") -> bool:
    g = GOALS[goal]
    return v.rated and v.excitement >= g["E"] and v.intensity < g["I"] and v.nausea < g["N"]


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
    reheat_after: int = 60  # rounds without a new chain best before the chain restarts
    slack: float = 0.0  # weight of the low-I/N tie-breaker in score()
    chains: int = 1  # independent annealing chains sharing the judge pool
    i_cap_start: float = I_CAP  # intensity cap in score(), moving linearly to i_cap_end over the run
    i_cap_end: float = I_CAP
    stop_on_goal: bool = False
    n_cap: float = N_CAP  # nausea cap in score()
    goal: str = "very_high"  # key of GOALS: what best_goal.json and "GOAL MET" track
    height_price: float = 0.0  # score cost per metre of mean track height above ground


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


@dataclass
class Chain:
    track: list
    verdict: Verdict
    eval_id: int
    best: float
    since_best: int = 0


def run(cfg: SearchConfig, layout: Layout, initial: list[tuple[int, bool]] | None = None, log_print=print) -> Path:
    rng = random.Random(cfg.seed)
    pieces = piece_set(layout.ride_type_name)
    gen = EditGenerator(layout, pieces, seed=cfg.seed)
    track = initial or oval(layout, hill=cfg.hill)

    log = RunLog(cfg.layout_name, {"search": cfg.__dict__, "layout": layout.to_record(), "git": git_rev(), "pieces": sorted(pieces)})
    pool = JudgePool(layout, cfg.workers)
    log_print(f"run dir: {log.dir}  workers={pool.size}  chains={cfg.chains}")
    started = time.monotonic()

    def progress_frac() -> float:
        # Time-limited runs anneal by the clock; evaluation-limited runs by the count.
        return min(1.0, max(log.n / cfg.max_evals, (time.monotonic() - started) / 60 / cfg.max_minutes))

    def scorer(v: Verdict, frac: float) -> float | None:
        cap = cfg.i_cap_start + (cfg.i_cap_end - cfg.i_cap_start) * frac
        return score(v, cfg.slack, cap, cfg.n_cap, cfg.height_price)

    try:
        v0 = pool.map([track])[0]
        start_id = log.eval({"before": None, "edit": None, "track": track, "verdict": v0.to_dict(),
                             "score": scorer(v0, 0.0), "round": 0})
        if not v0.rated:
            raise RuntimeError(f"initial track not rated: {v0.to_dict()}")
        chains = [Chain(track, v0, start_id, scorer(v0, 0.0)) for _ in range(cfg.chains)]
        best, best_v, best_id = track, v0, start_id
        log.best({"eval": best_id, "score": scorer(v0, 0.0), "verdict": v0.to_dict(), "track": best})
        log_print(f"initial: {summarize(v0)} pieces={len(track)}")

        rnd = 0
        goal_hits = 0
        best_goal: float | None = None
        per_chain = max(1, cfg.batch // cfg.chains)
        while log.n < cfg.max_evals and (time.monotonic() - started) / 60 < cfg.max_minutes:
            rnd += 1
            frac = progress_frac()
            temp = cfg.t0 * (cfg.t1 / cfg.t0) ** frac
            proposals = []  # (chain index, candidate, edit)
            for ci, ch in enumerate(chains):
                for _ in range(per_chain):
                    p = gen.propose(ch.track)
                    if p:
                        proposals.append((ci, *p))
            verdicts = pool.map([c for _, c, _ in proposals])
            stages: dict[str, int] = {}
            round_best: dict[int, tuple] = {}
            for (ci, cand, edit), v in zip(proposals, verdicts):
                s = scorer(v, frac)
                stages[v.stage] = stages.get(v.stage, 0) + 1
                eid = log.eval({
                    "before": chains[ci].eval_id, "edit": edit.to_dict(), "track": cand,
                    "verdict": v.to_dict(), "score": s, "round": rnd, "chain": ci,
                })
                if meets_goal(v, cfg.goal):
                    goal_hits += 1
                    if best_goal is None or v.excitement > best_goal:
                        best_goal = v.excitement
                        log.best({"eval": eid, "score": s, "verdict": v.to_dict(), "track": cand, "round": rnd},
                                 "best_goal.json")
                        log_print(f"[r{rnd} e{log.n}] GOAL MET {summarize(v)} chain={ci} pieces={len(cand)}")
                if s is not None and (ci not in round_best or s > round_best[ci][0]):
                    round_best[ci] = (s, cand, v, eid)
            accepted = []
            for ci, ch in enumerate(chains):
                cur_s = scorer(ch.verdict, frac)
                if ci in round_best:
                    s, cand, v, eid = round_best[ci]
                    if s >= cur_s or rng.random() < math.exp((s - cur_s) / max(temp, 1e-9)):
                        ch.track, ch.verdict, ch.eval_id = cand, v, eid
                        accepted.append(eid)
                    if s > ch.best:
                        ch.best, ch.since_best = s, 0
                ch.since_best += 1
                if ch.since_best >= cfg.reheat_after:
                    # Restart from the oval rather than the chain's own best: a stuck design
                    # usually sits at the intensity boundary, and its best is the same trap.
                    ch.track, ch.verdict, ch.eval_id = track, v0, start_id
                    ch.best, ch.since_best = scorer(v0, frac), 0
                    log_print(f"[r{rnd} e{log.n}] chain {ci} stagnated: restart from the oval")
            # Global best by the final-cap score (what the goal needs), tracked across chains.
            for ci, ch in enumerate(chains):
                if scorer(ch.verdict, 1.0) > scorer(best_v, 1.0):
                    best, best_v, best_id = ch.track, ch.verdict, ch.eval_id
                    log.best({"eval": best_id, "score": scorer(best_v, 1.0), "verdict": best_v.to_dict(), "track": best,
                              "round": rnd})
                    log_print(f"[r{rnd} e{log.n}] new best {summarize(best_v)} chain={ci} pieces={len(best)} "
                              f"goal={'YES' if meets_goal(best_v, cfg.goal) else 'no'}")
            log.progress({
                "round": rnd, "evals": log.n, "minutes": round((time.monotonic() - started) / 60, 2),
                "temp": round(temp, 4), "i_cap": round(cfg.i_cap_start + (cfg.i_cap_end - cfg.i_cap_start) * frac, 3),
                "chains": [summarize(ch.verdict) for ch in chains], "best": summarize(best_v),
                "accepted_evals": accepted, "stages": stages, "proposals": len(proposals), "goal_hits": goal_hits,
            })
            if rnd % 20 == 0:
                log_print(f"[r{rnd} e{log.n} {((time.monotonic()-started)/60):.1f}m] T={temp:.3f} "
                          f"chains={[summarize(ch.verdict) for ch in chains]} best={summarize(best_v)} stages={stages}")
            if cfg.stop_on_goal and best_goal is not None:
                log_print("goal met; stopping")
                break
    finally:
        pool.close()
        log.close()
    return log.dir
