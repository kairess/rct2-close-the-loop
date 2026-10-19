"""Energy-height check: can the train get over every hill?

A chain lift carries the train to the top of the lift; after that it coasts,
and friction eats a little height per piece. If an unlifted piece rises above
the remaining energy height the train will roll back (the game reports a
stall/timeout). The two constants are fitted to logged evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass

from .track import Layout, Placed, segments, trace

UP = {2, 4, 10}


@dataclass(frozen=True)
class EnergyModel:
    # Defaults are the grid-search fit on 3000 logged evaluations (2026-10-19).
    friction: float = 1.0  # world z units lost per piece while coasting
    margin: float = 0.0  # z units the train must stay under its energy height
    launch: float = 48.0  # energy height the station launch provides above the station
    lift_boost: float = 48.0  # chain speed carries the train this far above the top of a lift

    def first_stall(self, layout: Layout, placed: list[Placed]) -> int | None:
        """Index into `placed` of the first piece the train likely cannot climb, or None."""
        g = layout.ground_z
        energy = layout.ground_z + self.launch
        for k, p in enumerate(placed):
            s = segments()[p.type]
            top = p.z + max(s.begin_z, s.end_z, max(e[2] for e in s.elements))
            if p.lift:
                energy = max(energy, top + self.lift_boost)
                continue
            if top > energy - self.margin and (s.begin_slope in UP or s.end_slope in UP):
                return k
            energy -= self.friction
            energy = max(energy, g)
        return None

    def ok(self, layout: Layout, pieces: list[tuple[int, bool]]) -> bool:
        tr = trace(layout, pieces, check=False)
        return self.first_stall(layout, tr.placed) is None


def fit(layout: Layout, records: list[dict]) -> tuple[EnergyModel, dict]:
    """Grid-search constants that best separate stalled/timeout from rated tracks."""
    traced = [(trace(layout, r["track"], check=False).placed, r["verdict"]["stage"] == "rated") for r in records]
    best = None
    grid = [
        (f, mg, la, lb)
        for f in (0.0, 0.5, 1.0, 2.0)
        for mg in (0.0, 8.0, 16.0)
        for la in (0.0, 16.0, 32.0, 48.0)
        for lb in (0.0, 16.0, 32.0, 48.0, 64.0)
    ]
    for friction, margin, launch, lift_boost in grid:
        m = EnergyModel(friction, margin, launch, lift_boost)
        tp = fp = tn = fn = 0
        for placed, rated in traced:
            pred_ok = m.first_stall(layout, placed) is None
            if pred_ok and rated:
                tp += 1
            elif pred_ok and not rated:
                fp += 1
            elif not pred_ok and rated:
                fn += 1
            else:
                tn += 1
        # Rejecting a good track costs more than evaluating a bad one: weight misses 4x.
        stats = {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "cost": fp + 4 * fn}
        if best is None or stats["cost"] < best[1]["cost"]:
            best = (m, stats)
    return best
