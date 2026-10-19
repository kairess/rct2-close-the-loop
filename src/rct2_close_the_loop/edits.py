"""Circuit-preserving edits.

A segment edit replaces track[i:j] with a new run of pieces that starts in
the same state and ends in exactly the same state (position, direction,
slope, bank) as the old run, so the circuit stays closed by construction.

The new run is a short random walk from the start state followed by an exact
completion looked up in a table of every piece sequence up to COMPLETION_DEPTH
long, keyed by the displacement it produces in its own frame.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from functools import cache

from .track import DATA, Layout, State, rot, segments, step, trace

COMPLETION_DEPTH = 4
MAX_PER_KEY = 48
UP_SLOPES = {2, 4, 10}

Piece = tuple[int, bool]


@cache
def rating_flags() -> tuple[frozenset[int], frozenset[int]]:
    """Track types the game counts as an inversion (normalToInversion) and as a helix piece,
    extracted from OpenRCT2's TrackData.cpp into data/track_flags.json."""
    raw = json.loads((DATA / "track_flags.json").read_text())
    return frozenset(raw["normalToInversion"]), frozenset(raw["helix"])


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
                 max_window: int = 8, max_walk: int = 6, max_inversions: int | None = None,
                 max_helix: int | None = None):
        self.layout = layout
        self.rng = random.Random(seed)
        self.max_window = max_window
        self.max_walk = max_walk
        # Rating priors: excitement counts at most 6 inversions and 5 helix pieces; beyond
        # that they only add intensity and nausea, so such candidates are not worth a test.
        self.max_inversions = max_inversions
        self.max_helix = max_helix
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

    def table_size(self) -> int:
        return sum(len(v) for t in self.table.values() for v in t.values())

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

    def _lifts(self, run: list[int], chain: bool) -> list[Piece]:
        out = []
        for t in run:
            s = segments()[t]
            up = s.begin_slope in UP_SLOPES or s.end_slope in UP_SLOPES
            out.append((t, chain and up and s.allows_lift))
        return out

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
            if not self.within_priors(cand):
                continue
            tr = trace(self.layout, cand)
            if not tr.closed:
                raise AssertionError(f"segment edit broke closure at [{i},{j}): {tr.problems}")
            if tr.problems:
                continue
            return cand, Edit("segment", i, j, removed, inserted)
        return None

    def within_priors(self, track: list[Piece]) -> bool:
        inv, helix = rating_flags()
        if self.max_inversions is not None and sum(t in inv for t, _ in track) > self.max_inversions:
            return False
        if self.max_helix is not None and sum(t in helix for t, _ in track) > self.max_helix:
            return False
        return True

    def lift_toggle(self, track: list[Piece]):
        """Flip the chain lift on one maximal run of lift-capable uphill pieces."""
        runs = []
        start = None
        for k, (t, _) in enumerate(track + [(-1, False)]):
            s = segments().get(t)
            ok = s is not None and s.allows_lift and (s.begin_slope in UP_SLOPES or s.end_slope in UP_SLOPES)
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
