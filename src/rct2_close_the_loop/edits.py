"""Circuit-preserving edits.

A segment edit replaces track[i:j] with a new run of pieces that starts in
the same state and ends in exactly the same state (position, direction,
slope, bank) as the old run, so the circuit stays closed by construction.

The new run is a short random walk from the start state followed by an exact
completion looked up in a table of every piece sequence up to COMPLETION_DEPTH
long, keyed by the displacement it produces in its own frame.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from .track import Layout, State, ride_groups, rot, segments, step, trace

COMPLETION_DEPTH = 4
MAX_PER_KEY = 48
UP_SLOPES = {2, 4, 10}
STEEP_UP = {4, 10}  # 60 and 90 degrees up
LIFT_HILL_STEEP_GROUP = 4  # TrackGroup::liftHillSteep

Piece = tuple[int, bool]


@dataclass
class Edit:
    op: str
    i: int
    j: int
    removed: list[Piece]
    inserted: list[Piece]

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "i": self.i,
            "j": self.j,
            "removed": [list(p) for p in self.removed],
            "inserted": [list(p) for p in self.inserted],
        }


def relative(a: State, b: State) -> tuple[int, int, int, int, int, int]:
    """b expressed in a's frame (a at origin facing direction 0), plus b's slope/bank."""
    dx, dy = rot(b.x - a.x, b.y - a.y, (4 - a.d) & 3)
    return (dx, dy, b.z - a.z, (b.d - a.d) & 3, b.slope, b.bank)


class EditGenerator:
    def __init__(self, layout: Layout, pieces: frozenset[int], seed: int | None = None,
                 max_window: int = 8, max_walk: int = 6):
        self.layout = layout
        self.rng = random.Random(seed)
        self.max_window = max_window
        self.max_walk = max_walk
        # A chain lift on a steep-up piece needs the ride's liftHillSteep group (TrackPlaceAction:
        # "Too steep for lift hill"); Twister and Hyper-Twister lack it.
        self.steep_lift = LIFT_HILL_STEEP_GROUP in ride_groups(layout.ride_type_name)
        self.by_entry: dict[tuple[int, int], list[int]] = defaultdict(list)
        for t in sorted(pieces):
            s = segments()[t]
            self.by_entry[(s.begin_slope, s.begin_bank)].append(t)
        self.table: dict[tuple[int, int], dict[tuple, list[tuple[int, ...]]]] = {}
        for entry in list(self.by_entry):
            self.table[entry] = self._build_table(entry)

    def _build_table(self, entry: tuple[int, int]) -> dict[tuple, list[tuple[int, ...]]]:
        origin = State(0, 0, 0, 0, entry[0], entry[1])
        table: dict[tuple, list[tuple[int, ...]]] = defaultdict(list)
        frontier = [(origin, ())]
        for _ in range(COMPLETION_DEPTH):
            nxt = []
            for st, seq in frontier:
                for t in self.by_entry.get((st.slope, st.bank), ()):
                    _, ns = step(st, t)
                    nseq = seq + (t,)
                    bucket = table[relative(origin, ns)]
                    if len(bucket) < MAX_PER_KEY:
                        bucket.append(nseq)
                    else:
                        k = self.rng.randrange(len(bucket) + 1)
                        if k < MAX_PER_KEY:
                            bucket[k] = nseq
                    nxt.append((ns, nseq))
            frontier = nxt
        return dict(table)

    # ------------------------------------------------------------ operators

    def states(self, track: list[Piece]) -> list[State]:
        """State before each piece of `track` (after the station), plus the closing state."""
        state = self.layout.start()
        for _ in range(self.layout.station_len):
            _, state = step(state, 1)
        out = [state]
        for t, _ in track:
            _, state = step(state, t)
            out.append(state)
        return out

    def can_lift(self, t: int) -> bool:
        s = segments().get(t)
        if s is None or not s.allows_lift or not (s.begin_slope in UP_SLOPES or s.end_slope in UP_SLOPES):
            return False
        return self.steep_lift or not (s.begin_slope in STEEP_UP or s.end_slope in STEEP_UP)

    def _lifts(self, run: list[int], chain: bool) -> list[Piece]:
        return [(t, chain and self.can_lift(t)) for t in run]

    def segment(self, track: list[Piece], tries: int = 200):
        max_window, max_walk = self.max_window, self.max_walk
        n = len(track)
        sts = self.states(track)
        for _ in range(tries):
            w = self.rng.randint(1, min(max_window, n))
            i = self.rng.randint(0, n - w)
            j = i + w
            a, b = sts[i], sts[j]
            walk: list[int] = []
            st = a
            for _ in range(self.rng.randint(0, max_walk)):
                opts = self.by_entry.get((st.slope, st.bank))
                if not opts:
                    break
                t = self.rng.choice(opts)
                walk.append(t)
                _, st = step(st, t)
            comps = self.table.get((st.slope, st.bank), {}).get(relative(st, b))
            if not comps:
                continue
            run = walk + list(self.rng.choice(comps))
            removed = track[i:j]
            if run == [t for t, _ in removed]:
                continue
            chain = any(l for _, l in removed) if self.rng.random() < 0.7 else self.rng.random() < 0.5
            inserted = self._lifts(run, chain)
            cand = track[:i] + inserted + track[j:]
            tr = trace(self.layout, cand)
            if not tr.closed:
                raise AssertionError(f"segment edit broke closure at [{i},{j}): {tr.problems}")
            if tr.problems:
                continue
            return cand, Edit("segment", i, j, removed, inserted)
        return None

    def lift_toggle(self, track: list[Piece]):
        """Flip the chain lift on one maximal run of lift-capable uphill pieces."""
        runs = []
        start = None
        for k, (t, _) in enumerate(track + [(-1, False)]):
            ok = self.can_lift(t)
            if ok and start is None:
                start = k
            elif not ok and start is not None:
                runs.append((start, k))
                start = None
        if not runs:
            return None
        i, j = self.rng.choice(runs)
        removed = track[i:j]
        flip = not all(l for _, l in removed)
        inserted = [(t, flip) for t, _ in removed]
        return track[:i] + inserted + track[j:], Edit("lift", i, j, removed, inserted)

    def propose(self, track: list[Piece]):
        if self.rng.random() < 0.1:
            r = self.lift_toggle(track)
            if r:
                return r
        return self.segment(track)
