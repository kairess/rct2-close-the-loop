"""Social-media videos of the record coaster.

    uv run python scripts/make_videos.py search   # the search, frame by frame, in the decorated park
    uv run python scripts/make_videos.py ride     # guests riding it (see ride())

Frames come from the game itself: each search frame is the track at one of the run's improvements,
built (with its own paths and trees) in the decorated surroundings, saved, and rendered with the
CLI screenshot command; the video is then encoded with ffmpeg (1920x1080, 30 fps).
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rct2_close_the_loop.design import layout_from_run
from rct2_close_the_loop.game import RUNTIME
from rct2_close_the_loop.judge import Judge
from rct2_close_the_loop.results import CLI

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "results" / "showcase" / "lakeside"
OUT = ROOT / "results" / "video"
RUNS = [ROOT / "runs" / "20261020-130505-hypertwister@flat40", ROOT / "runs" / "20261020-135124-hypertwister@flat40+"]
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
LOOK = {"track": [6, 2, 2], "vehicle": [18, 6, 2], "station": "rct2.station.classical", "trees": None, "paths": None}
W, H, FPS = 1920, 1080, 30
CAMERA = (3840, 3904, 112)  # centre of the scene in world units


def font(size: int) -> ImageFont.FreeTypeFont:
    for i in range(10):
        f = ImageFont.truetype(FONT, size, index=i)
        if "KR" in " ".join(f.getname()):
            return f
    return ImageFont.truetype(FONT, size)


def shot(park: Path, img: Path, centre=CAMERA, zoom: int = 1, rotation: int = 0, size=(W, H)) -> Image.Image:
    x, y, z = centre
    subprocess.run([str(CLI), "screenshot", str(park), str(img), str(size[0]), str(size[1]), str(int(x)), str(int(y)),
                    str(int(z)), str(zoom), str(rotation)], check=True, capture_output=True, timeout=180)
    return Image.open(img).convert("RGB")


def caption(img: Image.Image, title: str, big: str, small: str) -> Image.Image:
    img = img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([40, 36, 760, 228], radius=18, fill=(12, 18, 30, 190))
    d.text((68, 52), title, font=font(32), fill=(220, 230, 240))
    d.text((68, 92), big, font=font(72), fill=(255, 214, 64))
    d.text((70, 182), small, font=font(28), fill=(200, 210, 220))
    return img


def improvements(icap: float = 10.35) -> list[dict]:
    """Every new best (E, with intensity under the cap) across the run and its continuation."""
    out, best, t_off = [], None, 0.0
    for run in RUNS:
        rows = [json.loads(line) for line in open(run / "evals.jsonl")]
        t0 = rows[0]["t"]
        for r in rows:
            v = r["verdict"]
            if v["stage"] == "rated" and v["I"] < icap and (best is None or v["E"] > best + 1e-9):
                best = v["E"]
                out.append({"track": r["track"], "circuits": r.get("circuits", 1), "E": v["E"],
                            "minutes": t_off + (r["t"] - t0) / 60, "eval": r["eval"]})
        t_off += (rows[-1]["t"] - t0) / 60
    return out


def thin(items: list[dict], n: int) -> list[dict]:
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def search(n_frames: int = 30) -> Path:
    work = OUT / "search_frames"
    work.mkdir(parents=True, exist_ok=True)
    layout, meta = layout_from_run(RUNS[0])
    layout = dataclasses.replace(layout, park=str(SCENE / "surroundings.park"), theme=LOOK)
    picks = thin(improvements(), n_frames)
    keys = []
    for k, fr in enumerate(picks):
        img_path = work / f"key_{k:02d}.png"
        if not img_path.exists():
            judge = Judge(layout)
            try:
                v = judge.evaluate([tuple(p) for p in fr["track"]], keep=True, circuits=fr["circuits"])
                judge.game.call("save", {"filename": f"vid_{k:02d}"})
            finally:
                judge.close()
            park = RUNTIME / "save" / f"vid_{k:02d}.park"
            shot(park, img_path)
            park.unlink(missing_ok=True)
            (work / f"key_{k:02d}.json").write_text(json.dumps({"E": v.excitement, "I": v.intensity, **{k2: fr[k2] for k2 in ("minutes", "eval")}}))
        info = json.loads((work / f"key_{k:02d}.json").read_text())
        keys.append((Image.open(img_path).convert("RGB"), info))
        print(f"frame {k}: {info['minutes']:.1f} min  E{info['E']}")
    # Finished park: the decorated scene with the record coaster, from four sides.
    finals = [shot(SCENE / "showcase.park", work / f"final_r{r}.png", rotation=r) for r in range(4)]
    # Assemble: title, the search (hold + crossfade), then the finished park.
    seq = OUT / "search_seq"
    shutil.rmtree(seq, ignore_errors=True)
    seq.mkdir(parents=True)
    n = 0

    def emit(img: Image.Image, count: int = 1):
        nonlocal n
        for _ in range(count):
            img.save(seq / f"{n:05d}.jpg", quality=92)
            n += 1

    title = keys[0][0].copy()
    d = ImageDraw.Draw(title, "RGBA")
    d.rectangle([0, 0, W, H], fill=(8, 12, 20, 150))
    d.text((W // 2, H // 2 - 80), "게임이 직접 채점하며 코스터를 설계한다", font=font(64), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, H // 2 + 20), "OpenRCT2 · 하이퍼 트위스터 · 40×40 호숫가", font=font(40), fill=(255, 214, 64), anchor="mm")
    d.text((W // 2, H // 2 + 90), "치트 없음 · 평가마다 게임이 시험 운행하고 레이팅한다", font=font(30), fill=(210, 220, 230), anchor="mm")
    emit(title, FPS * 2)
    keys = [(img, info) for img, info in keys if info.get("E") is not None]  # a track the scene refused

    def label(img, info):
        return caption(img, "탐색 중 · 게임이 매긴 흥미도", f"흥미도 {info['E']:.2f}",
                       f"탐색 {info['minutes']:.0f}분 · 평가 {info['eval']:,}번째")

    # Crossfade the pictures only; the caption switches halfway so numbers never overlap.
    for (a, ia), nxt in zip(keys, keys[1:] + [None]):
        emit(label(a, ia), 10)
        if nxt is not None:
            b, ib = nxt
            for t in range(1, 7):
                emit(label(Image.blend(a, b, t / 7), ia if t < 4 else ib))
    final_e = json.loads((SCENE / "rating.json").read_text())["E"] if (SCENE / "rating.json").exists() else 12.06
    for r, img in enumerate(finals):
        emit(caption(img, "완성: 꾸민 공원에서 다시 시험 운행", f"흥미도 {final_e:.2f} · 극한", "강도 9.99 · 멀미도 8.75 · 길·대기열·가판대·정원"),
             int(FPS * (2.5 if r == 0 else 1.5)))
    mp4 = OUT / "search.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(seq / "%05d.jpg"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(mp4)], check=True)
    print("->", mp4, f"{n / FPS:.1f} s")
    return mp4


if __name__ == "__main__":
    {"search": search}[sys.argv[1]]()
