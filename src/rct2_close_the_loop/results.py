"""Deliverables for a track: a saved park with the coaster built, plus screenshots."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .game import OPENRCT2, RUNTIME
from .judge import Judge
from .track import TILE, Layout

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
CLI = OPENRCT2.with_name("openrct2-cli")


def render(layout: Layout, track: list[tuple[int, bool]], name: str, zoom: int = 0) -> dict:
    """Build the track in a fresh instance, save the park, re-rate it, and screenshot it."""
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    judge = Judge(layout)
    try:
        verdict = judge.evaluate(track, keep=True)
        judge.game.call("save", {"filename": name})
    finally:
        judge.close()
    park = out / f"{name}.park"
    shutil.copyfile(RUNTIME / "save" / f"{name}.park", park)

    x0, y0, x1, y1 = layout.area
    cx, cy = (x0 + x1) * TILE // 2, (y0 + y1) * TILE // 2
    shots = []
    for rotation in range(4):
        img = out / f"{name}_r{rotation}.png"
        # The screenshot command reads the default user data dir (game path from `pyrct2 setup`).
        subprocess.run(
            [str(CLI), "screenshot", str(park), str(img), "1920", "1200", str(cx), str(cy), str(zoom), str(rotation)],
            check=True, capture_output=True, timeout=120,
        )
        shots.append(img.name)
    summary = {"name": name, "verdict": verdict.to_dict(), "track": [list(p) for p in track], "park": park.name, "screenshots": shots}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary
