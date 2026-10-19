"""Deliverables for a track: a saved park with the coaster built, screenshots, and an
animation of the design evolving from the first loop to the final coaster."""

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


def camera(layout: Layout) -> tuple[int, int, int, int]:
    """World x, y, z to centre on, and a zoom that fits the area in a 1920x1200 frame."""
    x0, y0, x1, y1 = layout.area
    span = max(x1 - x0, y1 - y0)
    return (x0 + x1) * TILE // 2, (y0 + y1) * TILE // 2, layout.ground_z, 0 if span <= 26 else 1


def screenshot(park: Path, img: Path, layout: Layout, rotation: int = 0, zoom: int | None = None,
               size: tuple[int, int] = (1920, 1200)) -> None:
    cx, cy, cz, auto_zoom = camera(layout)
    z = auto_zoom if zoom is None else zoom
    # The screenshot command reads the default user data dir (game path from `pyrct2 setup`).
    subprocess.run(
        [str(CLI), "screenshot", str(park), str(img), str(size[0]), str(size[1]), str(cx), str(cy), str(cz), str(z), str(rotation)],
        check=True, capture_output=True, timeout=120,
    )


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

    shots = []
    for rotation in range(4):
        img = out / f"{name}_r{rotation}.png"
        screenshot(park, img, layout, rotation, zoom)
        shots.append(img.name)
    summary = {"name": name, "verdict": verdict.to_dict(), "track": [list(p) for p in track], "park": park.name, "screenshots": shots}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def evolution_frames(run_dir: Path, frames: int = 24) -> list[dict]:
    """Evaluations where the run's best goal-feasible excitement improved, thinned to `frames`."""
    best, out = None, []
    with open(run_dir / "evals.jsonl") as f:
        for line in f:
            r = json.loads(line)
            v = r["verdict"]
            if v["stage"] != "rated" or v["I"] >= 7.68 or v["N"] >= 5.12:
                continue
            if best is None or v["E"] > best + 1e-9:
                best = v["E"]
                out.append({"eval": r["eval"], "t": r["t"], "track": r["track"], "verdict": v})
    if len(out) <= frames:
        return out
    step = (len(out) - 1) / (frames - 1)
    return [out[round(i * step)] for i in range(frames)]


def animate(layout: Layout, run_dir: Path, name: str, frames: int = 24, rotation: int = 0) -> Path:
    """Render each improvement of a run with the same camera and join them into a GIF."""
    from PIL import Image, ImageDraw, ImageFont

    out = RESULTS / name
    (out / "frames").mkdir(parents=True, exist_ok=True)
    picks = evolution_frames(run_dir, frames)
    with open(run_dir / "evals.jsonl") as f:
        t0 = json.loads(f.readline())["t"]
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 34)
    images = []
    for k, fr in enumerate(picks):
        judge = Judge(layout)  # fresh instance per frame: kept rides and cut land do not carry over
        try:
            judge.evaluate([tuple(p) for p in fr["track"]], keep=True)
            judge.game.call("save", {"filename": f"{name}_f{k}"})
        finally:
            judge.close()
        park = RUNTIME / "save" / f"{name}_f{k}.park"
        img_path = out / "frames" / f"{k:02d}.png"
        screenshot(park, img_path, layout, rotation)
        park.unlink(missing_ok=True)
        img = Image.open(img_path).convert("RGB").resize((960, 600))
        d = ImageDraw.Draw(img)
        v = fr["verdict"]
        label = f"eval {fr['eval']:>6}  {(fr['t'] - t0) / 60:5.1f} min   E {v['E']:.2f}  I {v['I']:.2f}  N {v['N']:.2f}"
        d.rectangle([0, 0, 960, 52], fill=(18, 22, 17))
        d.text((16, 8), label, font=font, fill=(236, 239, 232))
        images.append(img)
    gif = out / f"{name}.gif"
    durations = [700] * (len(images) - 1) + [2500]
    images[0].save(gif, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True)
    return gif
