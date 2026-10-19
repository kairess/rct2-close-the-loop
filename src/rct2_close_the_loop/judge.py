"""The game as judge: build a track in OpenRCT2, test it, return its ratings."""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field

from .game import Game, GameError, wait_ready
from .track import Layout, pieces_payload, trace

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
        }


class Judge:
    """One game instance prepared for a layout's ride object."""

    def __init__(self, layout: Layout, slot: int | None = None):
        self.layout = layout
        self.slot = slot
        self.restarts = 0
        self._launch()

    def _launch(self) -> None:
        self.game = Game(slot=self.slot)
        self.slot = self.game.slot
        self.evals_since_launch = 0
        wait_ready(self.game)
        self.game.call("setup")
        obj = self.game.call("load_object", {"identifier": self.layout.ride_object})
        if self.layout.ride_type not in obj["rideType"]:
            raise GameError(f"{self.layout.ride_object} is not ride type {self.layout.ride_type}: {obj['rideType']}")
        self.ride_object_index = obj["index"]

    def restart(self) -> None:
        self.game.close()
        self.restarts += 1
        self._launch()

    def evaluate(self, pieces: list[tuple[int, bool]], keep: bool = False, prefilter: bool = True) -> Verdict:
        if self.evals_since_launch >= RESTART_EVERY and not keep:
            self.restart()
        v = self._evaluate(pieces, keep, prefilter)
        if v.stage == "error":
            # Lost sync with the instance (timeout, crash, closed socket): start over.
            self.restart()
        else:
            self.evals_since_launch += 1
        return v

    def _evaluate(self, pieces: list[tuple[int, bool]], keep: bool, prefilter: bool) -> Verdict:
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
            "maxTicks": max(MIN_TICKS, TICKS_PER_PIECE * len(tr.placed)),
            "keep": keep,
        }
        try:
            r = self.game.call("evaluate", args, timeout=EVALUATE_TIMEOUT)
        except (GameError, OSError) as e:
            return Verdict("error", error=str(e), wall=time.perf_counter() - t0)
        v = Verdict(r["stage"], error=r.get("error"), ticks=r.get("ticks", 0), wall=time.perf_counter() - t0,
                    speed_before=r.get("speedBefore"))
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
        lock = threading.Lock()
        errors: list[Exception] = []

        def start(i: int) -> None:
            try:
                j = Judge(layout)
                with lock:
                    self._judges.append(j)
            except Exception as e:  # noqa: BLE001 - surfaced below
                errors.append(e)

        starters = [threading.Thread(target=start, args=(i,)) for i in range(workers)]
        for t in starters:
            t.start()
        for t in starters:
            t.join()
        if errors:
            self.close()
            raise errors[0]
        for j in self._judges:
            t = threading.Thread(target=self._run, args=(j,), daemon=True)
            t.start()
            self._threads.append(t)

    @property
    def size(self) -> int:
        return len(self._judges)

    def _run(self, judge: Judge) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            pieces, fut = job
            try:
                fut.set_result(judge.evaluate(pieces))
            except Exception as e:  # noqa: BLE001 - delivered to the caller
                fut.set_exception(e)

    def submit(self, pieces: list[tuple[int, bool]]) -> Future:
        fut: Future = Future()
        self._jobs.put((pieces, fut))
        return fut

    def map(self, batch: list[list[tuple[int, bool]]]) -> list[Verdict]:
        futs = [self.submit(p) for p in batch]
        return [f.result() for f in futs]

    def close(self) -> None:
        for _ in self._threads:
            self._jobs.put(None)
        for j in self._judges:
            j.close()
