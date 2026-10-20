"""The game as judge: build a track in OpenRCT2, test it, return its ratings."""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path

from . import decor, paths
from .game import Game, GameError, wait_ready
from .track import Layout, pieces_payload, trace

ROOT = Path(__file__).resolve().parents[2]
TICKS_PER_PIECE = 120
MIN_TICKS = 6000
EVALUATE_TIMEOUT = 60.0  # seconds; a healthy evaluation takes 0.5-3 s
RESTART_EVERY = 2000  # evaluations per game instance before a fresh launch


@dataclass
class Verdict:
    stage: str  # rated | prefilter | build | entrance | exit | test_start | timeout | crashed | error
    excitement: float | None = None
    intensity: float | None = None
    nausea: float | None = None
    stats: dict = field(default_factory=dict)
    error: str | None = None
    ticks: int = 0
    wall: float = 0.0
    build_index: int | None = None
    speed_before: int | None = None
    decor: int = 0  # trees planted for the rating (removed again unless kept)
    paths: int = 0  # footpath tiles built for the rating (removed again unless kept)

    @property
    def rated(self) -> bool:
        return self.stage == "rated"

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "E": self.excitement,
            "I": self.intensity,
            "N": self.nausea,
            "stats": self.stats,
            "error": self.error,
            "ticks": self.ticks,
            "wall": round(self.wall, 3),
            "build_index": self.build_index,
            "speed_before": self.speed_before,
            "decor": self.decor,
            "paths": self.paths,
        }


class Judge:
    """One game instance prepared for a layout's ride object."""

    def __init__(self, layout: Layout, slot: int | None = None, planner=None):
        self.layout = layout
        self.planner = planner  # optional process pool for paths.plan (see JudgePool)
        self.slot = slot
        self.restarts = 0
        self._launch()

    def _launch(self) -> None:
        park = ROOT / self.layout.park if self.layout.park else None
        self.game = Game(park=park, slot=self.slot)
        self.slot = self.game.slot
        self.evals_since_launch = 0
        wait_ready(self.game)
        env = self.layout.env
        self.game.call("setup", {"sandbox": env.sandbox} if env is not None else {})
        obj = self.game.call("load_object", {"identifier": self.layout.ride_object})
        if self.layout.ride_type not in obj["rideType"]:
            raise GameError(f"{self.layout.ride_object} is not ride type {self.layout.ride_type}: {obj['rideType']}")
        self.ride_object_index = obj["index"]

    def restart(self) -> None:
        self.game.close()
        self.restarts += 1
        self._launch()

    def evaluate(self, pieces: list[tuple[int, bool]], keep: bool = False, prefilter: bool = True,
                 circuits: int = 1) -> Verdict:
        if self.evals_since_launch >= RESTART_EVERY and not keep:
            self.restart()
        v = self._evaluate(pieces, keep, prefilter, circuits)
        if v.stage in ("error", "scenery"):
            # Lost sync with the instance (timeout, crash, closed socket), or the build
            # removed trees so the terrain no longer matches the layout: start over.
            self.restart()
        else:
            self.evals_since_launch += 1
        return v

    def _evaluate(self, pieces: list[tuple[int, bool]], keep: bool, prefilter: bool, circuits: int = 1) -> Verdict:
        t0 = time.perf_counter()
        tr = trace(self.layout, pieces)
        if prefilter and (not tr.closed or tr.problems):
            reason = "; ".join(tr.problems) or "circuit does not close"
            return Verdict("prefilter", error=reason, wall=time.perf_counter() - t0)
        entrance, exit_ = self.layout.access_tiles()
        args = {
            "rideType": self.layout.ride_type,
            "rideObject": self.ride_object_index,
            "pieces": pieces_payload(tr.placed),
            "entrance": [entrance[0] * 32, entrance[1] * 32, entrance[2]],
            "exit": [exit_[0] * 32, exit_[1] * 32, exit_[2]],
            "maxTicks": max(MIN_TICKS, TICKS_PER_PIECE * len(tr.placed)) * circuits,
            "circuits": circuits,
            "keep": keep,
            "cars": self.layout.cars,
        }
        if self.layout.obstacles or self.layout.env is not None:
            args["sceneryRect"] = list(self.layout.area)
        if tr.cuts:
            args["cuts"] = [[x, y, units] for (x, y), units in sorted(tr.cuts.items())]
        path_tiles = []
        if self.layout.paths and self.layout.env is not None:
            if self.planner is not None:
                path_tiles = self.planner.submit(paths.plan_in_worker, tr.placed).result()
            else:
                path_tiles = paths.plan(self.layout, tr.placed)
            args["paths"] = {"tiles": path_tiles}
        if self.layout.decor and self.layout.env is not None:
            avoid = {(t[0], t[1]) for t in path_tiles}
            args["decor"] = {"identifier": self.layout.decor,
                             "tiles": [t for t in decor.plan(self.layout, tr.placed, tr.cuts) if tuple(t) not in avoid]}
        try:
            r = self.game.call("evaluate", args, timeout=EVALUATE_TIMEOUT)
        except (GameError, OSError) as e:
            return Verdict("error", error=str(e), wall=time.perf_counter() - t0)
        v = Verdict(r["stage"], error=r.get("error"), ticks=r.get("ticks", 0), wall=time.perf_counter() - t0,
                    speed_before=r.get("speedBefore"), decor=r.get("decor", 0), paths=r.get("paths", 0))
        if r.get("sceneryLost"):
            return Verdict("scenery", error=f"build removed {r['sceneryLost']} scenery items", wall=v.wall)
        if "index" in r:
            # Index into the full placed list (station first); report it relative to `pieces`.
            v.build_index = r["index"] - self.layout.station_len
        st = r.get("stats")
        if st:
            v.stats = st
            if v.rated:
                v.excitement = st["excitement"] / 100
                v.intensity = st["intensity"] / 100
                v.nausea = st["nausea"] / 100
        return v

    def close(self) -> None:
        self.game.close()


class JudgePool:
    """N judges on worker threads; submit() returns a Future[Verdict]."""

    def __init__(self, layout: Layout, workers: int):
        self.layout = layout
        self._jobs: queue.Queue = queue.Queue()
        self._threads = []
        self._judges: list[Judge] = []
        self._lock = threading.Lock()
        self._errors: list[Exception] = []
        self._started = threading.Semaphore(0)
        self.planner = None
        if layout.paths and layout.env is not None:
            from concurrent.futures import ProcessPoolExecutor

            self.planner = ProcessPoolExecutor(max_workers=max(2, workers // 2), initializer=paths.init_worker,
                                               initargs=(layout,))
        # Each worker thread launches and owns its game for the pool's lifetime:
        # PR_SET_PDEATHSIG fires when the *thread* that spawned the game exits.
        for _ in range(workers):
            t = threading.Thread(target=self._run, daemon=True)
            t.start()
            self._threads.append(t)
        for _ in range(workers):
            self._started.acquire()
        if self._errors:
            self.close()
            raise self._errors[0]

    @property
    def size(self) -> int:
        return len(self._judges)

    def _run(self) -> None:
        try:
            judge = Judge(self.layout, planner=self.planner)
            with self._lock:
                self._judges.append(judge)
        except Exception as e:  # noqa: BLE001 - surfaced in __init__
            self._errors.append(e)
            return
        finally:
            self._started.release()
        while True:
            job = self._jobs.get()
            if job is None:
                return
            pieces, circuits, fut = job
            try:
                fut.set_result(judge.evaluate(pieces, circuits=circuits))
            except Exception as e:  # noqa: BLE001 - delivered to the caller
                fut.set_exception(e)

    def submit(self, pieces: list[tuple[int, bool]], circuits: int = 1) -> Future:
        fut: Future = Future()
        self._jobs.put((pieces, circuits, fut))
        return fut

    def map(self, batch: list[list[tuple[int, bool]]], circuits: list[int] | None = None) -> list[Verdict]:
        laps = circuits or [1] * len(batch)
        futs = [self.submit(p, c) for p, c in zip(batch, laps)]
        return [f.result() for f in futs]

    def close(self) -> None:
        for _ in self._threads:
            self._jobs.put(None)
        for j in self._judges:
            j.close()
        if self.planner is not None:
            self.planner.shutdown(cancel_futures=True)
