"""Fast judge: predict the game's ratings from track geometry alone.

Trained on the search logs (evals.jsonl). Features are piece-type counts plus
geometry the ratings code cares about: drops, crests, turns by kind, height
profile, ground contact, and track passing over track (proximity/shelter).
Used as a pre-filter: generate many edits, send only the most promising to
the game.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from .track import Layout, piece_tiles, segments, trace

UP = {2, 4, 10}
DOWN = {6, 8, 18}


def _kind(t: int) -> dict[str, bool]:
    s = segments()[t]
    turn = s.end_dir != s.begin_dir
    sloped = s.begin_slope != 0 or s.end_slope != 0
    banked = s.begin_bank in (2, 4) or s.end_bank in (2, 4)
    return {
        "turn": turn,
        "turn_flat": turn and not sloped and not banked,
        "turn_banked": turn and banked and not sloped,
        "turn_sloped": turn and sloped,
        "up": s.begin_slope in UP or s.end_slope in UP,
        "down": s.begin_slope in DOWN or s.end_slope in DOWN,
        "steep": s.begin_slope in (4, 8, 10, 18) or s.end_slope in (4, 8, 10, 18),
        "inversion": s.is_inversion,
        "banked": banked,
    }


@dataclass
class FeatureSpace:
    layout: Layout
    piece_types: list[int]

    def __post_init__(self):
        self.index = {t: i for i, t in enumerate(self.piece_types)}
        self.kinds = {t: _kind(t) for t in self.piece_types}
        self.kind_names = list(next(iter(self.kinds.values())).keys())

    @property
    def names(self) -> list[str]:
        return (
            [f"n_{t}" for t in self.piece_types]
            + [f"k_{k}" for k in self.kind_names]
            + [
                "pieces", "lift_pieces", "max_z", "mean_z", "ground_elems", "ground_frac",
                "stacked_tiles", "stack_close", "drops", "max_drop", "sum_drop", "crests", "valleys",
                "unlifted_climb", "tiles_used", "lift_top", "post_lift_peak_margin", "elements",
            ]
        )

    def features(self, track: list[tuple[int, bool]]) -> np.ndarray:
        counts = np.zeros(len(self.piece_types))
        kinds = dict.fromkeys(self.kind_names, 0)
        lift_pieces = 0
        for t, lift in track:
            counts[self.index[t]] += 1
            for k, v in self.kinds[t].items():
                kinds[k] += v
            lift_pieces += lift
        tr = trace(self.layout, track, check=False)
        g = self.layout.ground_z
        zs = []
        tiles: dict[tuple[int, int], list[int]] = {}
        ground = 0
        for p in tr.placed:
            for tx, ty, z in piece_tiles(p.x, p.y, p.z, p.d, p.type):
                zs.append(z - g)
                tiles.setdefault((tx, ty), []).append(z)
                ground += z == g
        stacked = sum(1 for v in tiles.values() if len(v) > 1 and max(v) - min(v) >= 32)
        close = sum(1 for v in tiles.values() if len(v) > 1 and 32 <= max(v) - min(v) <= 96)
        # Height profile along the circuit (connection heights after each piece).
        heights = [p.z - g for p in tr.placed]
        drops, max_drop, sum_drop, crests, valleys = 0, 0, 0, 0, 0
        run_top = None
        prev_dir = 0
        for a, b in zip(heights, heights[1:] + heights[:1]):
            d = (b > a) - (b < a)
            if d < 0 and prev_dir >= 0:
                run_top = a
                if prev_dir > 0:
                    crests += 1
            if d > 0 and prev_dir < 0:
                valleys += 1
            if d >= 0 and prev_dir < 0 and run_top is not None:
                drop = run_top - a
                drops += 1
                max_drop = max(max_drop, drop)
                sum_drop += drop
            if d != 0:
                prev_dir = d
        # Energy proxy: highest point reached on a chain lift vs highest point after it without lift.
        lift_top, unlifted_climb, peak_after = 0, 0, 0
        for p, h in zip(tr.placed[self.layout.station_len:], heights[self.layout.station_len:]):
            if p.lift:
                lift_top = max(lift_top, h)
            else:
                peak_after = max(peak_after, h)
                if self.kinds.get(p.type, {}).get("up"):
                    unlifted_climb += 1
        geo = [
            len(track), lift_pieces, max(zs) if zs else 0, float(np.mean(zs)) if zs else 0, ground,
            ground / max(1, len(zs)), stacked, close, drops, max_drop, sum_drop, crests, valleys,
            unlifted_climb, len(tiles), lift_top, lift_top - peak_after, len(zs),
        ]
        return np.concatenate([counts, np.array([kinds[k] for k in self.kind_names], dtype=float), np.array(geo, dtype=float)])

    def matrix(self, tracks: list[list[tuple[int, bool]]]) -> np.ndarray:
        return np.vstack([self.features(t) for t in tracks])


def load_records(run_dirs: list[Path]) -> list[dict]:
    out = []
    for d in run_dirs:
        with open(d / "evals.jsonl") as f:
            for line in f:
                r = json.loads(line)
                if r["verdict"]["stage"] in ("rated", "timeout", "stalled", "crashed"):
                    out.append({"track": [tuple(p) for p in r["track"]], "verdict": r["verdict"]})
    return out


class Surrogate:
    def __init__(self, space: FeatureSpace, seed: int = 0):
        self.space = space
        kw = dict(max_iter=400, learning_rate=0.08, max_leaf_nodes=48, l2_regularization=1.0, random_state=seed)
        self.models = {k: HistGradientBoostingRegressor(**kw) for k in ("E", "I", "N")}
        self.rated = HistGradientBoostingClassifier(**kw)

    def fit(self, records: list[dict]) -> Surrogate:
        X = self.space.matrix([r["track"] for r in records])
        y_rated = np.array([r["verdict"]["stage"] == "rated" for r in records])
        self.rated.fit(X, y_rated)
        Xr = X[y_rated]
        for k, m in self.models.items():
            m.fit(Xr, np.array([r["verdict"][k] for r in records if r["verdict"]["stage"] == "rated"]))
        return self

    def predict(self, tracks: list[list[tuple[int, bool]]]) -> dict[str, np.ndarray]:
        X = self.space.matrix(tracks)
        out = {k: m.predict(X) for k, m in self.models.items()}
        out["p_rated"] = self.rated.predict_proba(X)[:, 1]
        return out
