"""Social-media videos of the record coaster, in Korean and English (ko, en; both by default).

    uv run python scripts/make_videos.py search [ko|en]     # the search, one picture per new best
    uv run python scripts/make_videos.py ride [ko|en]       # film guests arriving, queuing and riding it
    uv run python scripts/make_videos.py ride-edit [ko|en]  # re-edit the ride video from recorded frames

Frames come from the game itself. Each search frame is the track at one of the run's new bests,
built (with its own paths and trees) in the decorated surroundings, saved, and rendered with the
CLI screenshot command; the pictures change on the beat of the music. The ride video is filmed
inside a running game (on a virtual display, since only a game with a renderer can capture and the
CLI screenshot does not draw guests or trains): ordinary guests arrive through the park entrance,
queue, board, ride and get off, while the plugin captures the view every few ticks. Videos are
encoded with ffmpeg (1920x1080, 30 fps) with public-domain music from the game's data.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.signal import stft

from rct2_close_the_loop.design import layout_from_run
from rct2_close_the_loop.game import OPENRCT2, RUNTIME, Game, wait_ready
from rct2_close_the_loop.judge import Judge
from rct2_close_the_loop.results import CLI

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "results" / "showcase" / "lakeside"
OUT = ROOT / "results" / "video"
RUNS = [ROOT / "runs" / "20261020-130505-hypertwister@flat40", ROOT / "runs" / "20261020-135124-hypertwister@flat40+"]
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
LOOK = {"track": [28, 2, 2], "vehicle": [2, 28, 0], "station": "rct2.station.classical", "trees": None, "paths": None}
W, H, FPS = 1920, 1080, 30
CAMERA = (3840, 3904, 112)  # centre of the scene in world units


# Public-domain recordings from OpenRCT2's OpenMusic (its ragtime and fairground organ styles),
# read from the game's own data.
MUSIC_DIR = OPENRCT2.parent / "data" / "object" / "official" / "music"
MUSIC = {"search": ("openrct2.music.ragtime2", "music/0.ogg"),  # Dill Pickles Rag, Charles L. Johnson, 1906
         "ride": ("openrct2.music.fairground2", "music/3.ogg")}  # El Capitan, John Philip Sousa, 1896

# The game's own names for the rating bands (one band per 2.56).
BANDS = {"ko": ["낮음", "보통", "높음", "매우 높음", "극한", "초극한"],
         "en": ["Low", "Medium", "High", "Very high", "Extreme", "Ultra-Extreme"]}
TEXT = {
    "ko": {
        "s_title": "게임이 직접 채점하며 코스터를 설계한다",
        "s_sub": "OpenRCT2 · 하이퍼 트위스터 · 40×40 호숫가",
        "s_note": "레이팅 치트 없음 · 후보마다 게임이 시험 운행하고 레이팅한다",
        "s_head": "탐색 중 · 최고 기록 경신 {k}/{K}",
        "s_at": "평가 {n:,}번째 · {m:.0f}분",
        "s_done": "완성 · 꾸민 공원에서 다시 시험 운행",
        "s_done_small": "강도 {I:.2f} · 멀미도 {N:.2f} · 평가 {n:,}번 · {m:.0f}분",
        "axis": "평가 횟수 (로그 눈금)",
        "ticks": ["1", "10", "100", "1천", "1만"],
        "E": "흥미도 {E:.2f}",
        "r_title": "진짜 손님이 탄다",
        "r_sub": "흥미도 {E:.2f} 하이퍼 트위스터 · OpenRCT2",
        "r_note": "보통 손님 {g:,}명 · 탈지 말지는 게임의 손님 AI가 정한다",
        "arrive": ("개장", "손님 입장", "입구로 들어와 공원을 걷는다"),
        "queue": ("대기줄 · {r:.0f}배속", "대기 {q}명", "줄 서는 것도 손님 스스로"),
        "station": ("역 · {r:.0f}배속", "앞 열차 도착", "내리는 중 {a}명 · 대기 {q}명"),
        "board": ("탑승 · {r:.0f}배속", "탑승 {a}명", "정원 {s}명 · 대기 {q}명", "만석! 리프트로 출발"),
        "ride": ("주행 · {r:.0f}배속", "{b} · 가까이", "{b} · 멀리서 · 터널은 빨리 감기"),
        "hud": ("속도", "탑승", "{a}명", "주행 시간"),
        "unload": ("도착", "무사히 한 바퀴", "{a}명이 내린다", "{a}명 하차 · 다음 손님 탑승 {b}명"),
        "end": ("게임이 직접 매긴 레이팅", "강도 {I:.2f} · 멀미도 {N:.2f}", "레이팅 치트 없음 · 동기 출발 없음 · 코스터 한 대"),
    },
    "en": {
        "s_title": "Designing a coaster, scored by the game itself",
        "s_sub": "OpenRCT2 · Hyper-Twister · 40×40 lakeside",
        "s_note": "No rating cheats · every candidate is test-run and rated by the game",
        "s_head": "Searching · new best {k}/{K}",
        "s_at": "Evaluation #{n:,} · {m:.0f} min",
        "s_done": "Finished · test-run again in the decorated park",
        "s_done_small": "Intensity {I:.2f} · Nausea {N:.2f} · {n:,} evaluations · {m:.0f} min",
        "axis": "evaluations (log scale)",
        "ticks": ["1", "10", "100", "1k", "10k"],
        "E": "Excitement {E:.2f}",
        "r_title": "Real guests ride it",
        "r_sub": "Excitement {E:.2f} Hyper-Twister · OpenRCT2",
        "r_note": "{g:,} ordinary guests · the game's guest AI decides who rides",
        "arrive": ("Park opens", "Guests arrive", "In through the gate and into the park"),
        "queue": ("Queue · {r:.0f}× speed", "{q} in line", "Guests join the queue on their own"),
        "station": ("Station · {r:.0f}× speed", "Train comes in", "{a} getting off · {q} in line"),
        "board": ("Boarding · {r:.0f}× speed", "{a} aboard", "{s} seats · {q} in line", "Full! Up the lift hill"),
        "ride": ("Ride · {r:.0f}× speed", "{b} · close up", "{b} · wide · tunnels fast-forwarded"),
        "hud": ("Speed", "Riders", "{a}", "Ride time"),
        "unload": ("Back", "One full lap", "{a} riders get off", "{a} off · next guests boarding {b}"),
        "end": ("Ratings by the game itself", "Intensity {I:.2f} · Nausea {N:.2f}", "No rating cheats · no synchronised departures · one coaster"),
    },
}


def band(e: float, lang: str) -> str:
    return BANDS[lang][min(5, int(e * 100) >> 8)]


@functools.cache
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


def music(name: str) -> bytes:
    obj, member = MUSIC[name]
    return zipfile.ZipFile(MUSIC_DIR / f"{obj}.parkobj").read(member)


def beats(ogg: bytes, bpm0: float = 110.0, tight: float = 100.0) -> list[float]:
    """Beat times in seconds: spectral-flux onsets, the tempo from their autocorrelation (near bpm0),
    and the beats placed by dynamic programming (Ellis 2007)."""
    sr, hop = 22050, 256
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(sr), "-f", "s16le",
                          "pipe:1"], input=ogg, capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, np.int16).astype(float) / 32768
    _, _, z = stft(x, sr, nperseg=1024, noverlap=1024 - hop)
    env = np.maximum(0, np.diff(np.log1p(100 * np.abs(z)), axis=1)).sum(0)
    env = np.maximum(0, env - np.convolve(env, np.ones(32) / 32, "same"))
    env /= env.std()
    fps = sr / hop
    ac = np.correlate(env, env, "full")[len(env):]
    lag = np.arange(1, len(ac) + 1)
    bpm = 60 * fps / lag
    weight = np.exp(-0.5 * (np.log2(bpm / bpm0) / 0.9) ** 2) * ((bpm > 60) & (bpm < 200))
    period = int(lag[np.argmax(ac * weight)])
    prev = np.arange(-2 * period, -period // 2)
    penalty = -tight * np.log(-prev / period) ** 2
    score, back = env.copy(), np.full(len(env), -1)
    for t in range(len(env)):
        idx = t + prev
        ok = idx >= 0
        if ok.any():
            c = score[idx[ok]] + penalty[ok]
            j = int(np.argmax(c))
            score[t], back[t] = env[t] + c[j], idx[ok][j]
    t = int(np.argmax(score[-2 * period:])) + len(env) - 2 * period
    out = []
    while t >= 0:
        out.append(t / fps)
        t = back[t]
    return out[::-1]


def encode(seq: Path, mp4: Path, audio: bytes | None = None) -> None:
    """H.264 at a bitrate social sites take without re-encoding much (about 12 Mbit/s at 1080p30).
    Music is levelled to -14 LUFS, cut to the video's length and faded out over its last 3 s."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(seq / "%05d.jpg")]
    if audio is not None:
        (seq / "music.ogg").write_bytes(audio)
        secs = len(list(seq.glob("*.jpg"))) / FPS
        cmd += ["-i", str(seq / "music.ogg"), "-filter_complex",
                f"[1:a]atrim=0:{secs:.3f},loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={secs - 3:.3f}:d=3[a]",
                "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-tune", "animation", "-crf", "21", "-maxrate", "12M",
            "-bufsize", "24M", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)]
    subprocess.run(cmd, check=True)


def caption(img: Image.Image, title: str, big: str, small: str, chip: str | None = None,
            chip_on: bool = False) -> Image.Image:
    """Top-left box: a title, a big number with an optional band chip beside it, and a line below.
    The box grows to fit the text."""
    img = img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    big_w = d.textlength(big, font=font(72))
    chip_w = d.textlength(chip, font=font(34)) + 36 if chip else 0
    width = max(d.textlength(title, font=font(32)), big_w + (chip_w + 24 if chip else 0),
                d.textlength(small, font=font(28)) + 2)
    d.rounded_rectangle([40, 36, max(760, 96 + width), 228], radius=18, fill=(12, 18, 30, 190))
    d.text((68, 52), title, font=font(32), fill=(220, 230, 240))
    d.text((68, 92), big, font=font(72), fill=(255, 214, 64))
    if chip:
        x = 68 + big_w + 24
        d.rounded_rectangle([x, 116, x + chip_w, 168], radius=26,
                            fill=(255, 214, 64, 255) if chip_on else (255, 255, 255, 40))
        d.text((x + chip_w / 2, 142), chip, font=font(34), fill=(12, 18, 30) if chip_on else (220, 230, 240),
               anchor="mm")
    d.text((70, 182), small, font=font(28), fill=(200, 210, 220))
    return img


def improvements(icap: float = 10.35) -> list[dict]:
    """Every new best (E, with intensity under the cap) across the run and its continuation. `n`
    numbers the evaluations from 1 across both runs (each run's own `eval` starts at 0)."""
    out, best, t_off, n_off = [], None, 0.0, 0
    for run in RUNS:
        rows = [json.loads(line) for line in open(run / "evals.jsonl")]
        t0 = rows[0]["t"]
        for r in rows:
            v = r["verdict"]
            if v["stage"] == "rated" and v["I"] < icap and (best is None or v["E"] > best + 1e-9):
                best = v["E"]
                out.append({"track": r["track"], "circuits": r.get("circuits", 1), "E": v["E"], "I": v["I"],
                            "minutes": t_off + (r["t"] - t0) / 60, "n": n_off + r["eval"] + 1})
        t_off += (rows[-1]["t"] - t0) / 60
        n_off += len(rows)
    return out


def search_totals() -> tuple[int, float]:
    """Evaluations and minutes of both runs together."""
    n, minutes = 0, 0.0
    for run in RUNS:
        rows = [json.loads(line) for line in open(run / "evals.jsonl")]
        n += len(rows)
        minutes += (rows[-1]["t"] - rows[0]["t"]) / 60
    return n, minutes


def render_keys(picks: list[dict], workers: int = 8) -> None:
    """The track at each pick, built with its own paths and trees in the decorated surroundings and
    shot from the scene's camera: search_frames/n<eval>.png, and .json with the rating it gets there."""
    work = OUT / "search_frames"
    work.mkdir(parents=True, exist_ok=True)
    layout, _ = layout_from_run(RUNS[0])
    layout = dataclasses.replace(layout, park=str(SCENE / "surroundings.park"), theme=LOOK)

    def one(fr):
        img_path = work / f"n{fr['n']:05d}.png"
        if img_path.exists():
            return
        judge = Judge(layout)
        try:
            v = judge.evaluate([tuple(p) for p in fr["track"]], keep=True, circuits=fr["circuits"])
            judge.game.call("save", {"filename": f"vid_{fr['n']:05d}"})
        finally:
            judge.close()
        park = RUNTIME / "save" / f"vid_{fr['n']:05d}.park"
        shot(park, img_path)
        park.unlink(missing_ok=True)
        (work / f"n{fr['n']:05d}.json").write_text(json.dumps({"E": v.excitement, "I": v.intensity}))
        print(f"eval {fr['n']}: search E{fr['E']}  scene E{v.excitement}", flush=True)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, picks))


def progress(img: Image.Image, imp: list[dict], k: int, n_max: int, lang: str) -> Image.Image:
    """Inset, drawn in place: the best excitement so far against evaluations (log
    scale) up to record k, over the game's rating bands."""
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = 40, H - 330, 600, H - 40  # bottom left: only trees there (the park entrance is bottom right)
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=(12, 18, 30, 190))
    px0, py0, px1, py1 = x0 + 36, y0 + 28, x1 - 150, y1 - 80
    muted, top = (150, 160, 175), 12.8
    X = lambda n: px0 + (px1 - px0) * math.log10(n) / math.log10(n_max)
    Y = lambda e: py1 - (py1 - py0) * min(e, top) / top
    now = int(imp[k]["E"] * 100) >> 8
    for b in range(5):
        if b:
            d.line([px0, Y(2.56 * b), px1, Y(2.56 * b)], fill=(255, 255, 255, 40), width=1)
        d.text((px1 + 16, Y(2.56 * b + 1.28)), BANDS[lang][b], font=font(24),
               fill=(255, 214, 64) if b == now else muted, anchor="lm")
    d.line([px0, py1, px1, py1], fill=(255, 255, 255, 90), width=2)
    for p in range(5):
        d.line([X(10 ** p), py1, X(10 ** p), py1 + 8], fill=(255, 255, 255, 90), width=2)
        d.text((X(10 ** p), py1 + 14), TEXT[lang]["ticks"][p], font=font(22), fill=muted, anchor="ma")
    d.text(((px0 + px1) / 2, y1 - 22), TEXT[lang]["axis"], font=font(22), fill=muted, anchor="mm")
    pts = []
    for a, nxt in zip(imp[:k + 1], imp[1:k + 1] + [None]):  # a record holds until the next one
        pts.append((X(a["n"]), Y(a["E"])))
        if nxt is not None:
            pts.append((X(nxt["n"]), Y(a["E"])))
    if len(pts) > 1:
        d.line(pts, fill=(150, 190, 230), width=3)
    cx, cy = X(imp[k]["n"]), Y(imp[k]["E"])
    d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=(255, 214, 64), outline=(12, 18, 30), width=3)
    return img


def final_ratings() -> tuple[float, float, float]:
    """The finished park's ratings, as the game gave them in the ride recording."""
    r = json.loads((RIDE_DIR / "shots.json").read_text())["ratings"]
    return r["excitement"] / 100, r["intensity"] / 100, r["nausea"] / 100


class Sequence:
    """Numbered JPEG frames for ffmpeg; a held picture is saved once and copied."""

    def __init__(self, path: Path):
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        self.path, self.n = path, 0

    def emit(self, img: Image.Image, count: int = 1) -> None:
        first = self.path / f"{self.n:05d}.jpg"
        for k in range(count):
            if k == 0:
                img.save(first, quality=92)
            else:
                shutil.copyfile(first, self.path / f"{self.n:05d}.jpg")
            self.n += 1


def search(lang: str = "ko") -> Path:
    """Every new best from evaluation 1 on, one picture each, cut on the beat of the music: two beats
    each for the first five (the big jumps), one beat up to the 40th, half a beat after that, and two
    beats for the first Extreme one. Then the finished park from four sides."""
    L = TEXT[lang]
    imp = improvements()
    render_keys(imp)
    work = OUT / "search_frames"
    n_max, minutes = search_totals()
    E, I, N = final_ratings()
    finals = [Image.open(p).convert("RGB") if p.exists() else shot(SCENE / "showcase.park", p, rotation=r)
              for r, p in enumerate(work / f"final_r{r}.png" for r in range(4))]
    audio = music("search")
    b = beats(audio, bpm0=100)
    grid = sorted(b + [(p + q) / 2 for p, q in zip(b, b[1:])])  # half beats
    seq = Sequence(OUT / f"search_seq_{lang}")
    h = 0

    def hold(img: Image.Image, halves: int):  # until the half beat `halves` on
        nonlocal h
        h += halves
        seq.emit(img, round(grid[h] * FPS) - seq.n)

    title = Image.open(work / f"n{imp[0]['n']:05d}.png").convert("RGB")
    d = ImageDraw.Draw(title, "RGBA")
    d.rectangle([0, 0, W, H], fill=(8, 12, 20, 150))
    d.text((W // 2, H // 2 - 80), L["s_title"], font=font(64), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, H // 2 + 20), L["s_sub"], font=font(40), fill=(255, 214, 64), anchor="mm")
    d.text((W // 2, H // 2 + 90), L["s_note"], font=font(30), fill=(210, 220, 230), anchor="mm")
    hold(title, 8)
    first_extreme = next(k for k, fr in enumerate(imp) if fr["E"] >= 10.24)
    for k, fr in enumerate(imp):
        if json.loads((work / f"n{fr['n']:05d}.json").read_text())["E"] is None:
            continue  # rated on flat land; the lake scene's terrain does not take this track
        img = caption(Image.open(work / f"n{fr['n']:05d}.png").convert("RGB"),
                      L["s_head"].format(k=k + 1, K=len(imp)), L["E"].format(E=fr["E"]),
                      L["s_at"].format(n=fr["n"], m=fr["minutes"]), chip=band(fr["E"], lang), chip_on=fr["E"] >= 10.24)
        hold(progress(img, imp, k, n_max, lang), 4 if k < 5 or k == first_extreme else 2 if k < 40 else 1)
    for r, halves in zip(range(4), (8, 4, 4, 8)):
        hold(caption(finals[r], L["s_done"], L["E"].format(E=E), L["s_done_small"].format(I=I, N=N, n=n_max, m=minutes),
                     chip=band(E, lang), chip_on=True), halves)
    mp4 = OUT / ("search.mp4" if lang == "ko" else f"search_{lang}.mp4")
    encode(seq.path, mp4, audio)
    print("->", mp4, f"{seq.n / FPS:.1f} s")
    return mp4


RIDE_DIR = OUT / "ride_frames"
D = [(-1, 0), (0, 1), (1, 0), (0, -1)]


def queue_tiles(g: Game, front: tuple[int, int]) -> list[list[int]]:
    """The coaster's queue line, walked from the tile in front of its entrance."""
    seen, order, todo = {front}, [], [front]
    while todo:
        x, y = todo.pop(0)
        els = [e for e in g.call("tile", {"x": x, "y": y}) if e["type"] == "footpath" and e.get("isQueue")]
        if not els:
            continue
        order.append([x, y])
        for k, (dx, dy) in enumerate(D):
            if els[0]["edges"] & (1 << k) and (x + dx, y + dy) not in seen:
                seen.add((x + dx, y + dy))
                todo.append((x + dx, y + dy))
    return order


def record(guests: int = 1200, display: str = ":91") -> None:
    """Film the shots in one game: arrival, the queue filling, a full train boarding, riding and
    unloading, and a wide view of the park. Frames go to <screenshots>/ride/<shot>/; metadata and
    the frames are copied to results/video/ride_frames/."""
    shutil.rmtree(RUNTIME / "screenshot" / "ride", ignore_errors=True)
    (RUNTIME / "screenshot" / "ride").mkdir(parents=True)  # the game creates only the last level
    xvfb = subprocess.Popen(["Xvfb", display, "-screen", "0", "1280x720x24"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    scene = json.loads((SCENE / "scene.json").read_text())
    shots = {}
    try:
        with Game(park=SCENE / "showcase.park", display=display) as g:
            wait_ready(g)
            g.call("setup", {"sandbox": True})
            ent = g.call("guests_info", {"limit": 0})["entrance"]
            ex, ey, d = ent["x"] // 32, ent["y"] // 32, ent["direction"]
            queue = queue_tiles(g, (ex - D[d][0], ey - D[d][1]))
            # Departure: wait for a full train, at most 180 s. An empty train that leaves the station
            # rolls back and forth in a valley mid-course (a light train loses more speed to drag;
            # two riders are enough to get round), so it must not leave empty. The ratings do not
            # depend on this setting.
            g.call("actions", {"list": [["parksetparameter", {"parameter": 1, "value": 0}],
                                        ["ridesetsetting", {"ride": 0, "setting": 1, "value": 3 | 8 | 128}],
                                        ["ridesetsetting", {"ride": 0, "setting": 3, "value": 180}],
                                        ["ridesetstatus", {"ride": 0, "status": 1}]]})
            film = lambda name, **kw: g.call("film", {"prefix": f"ride/{name}", "width": W, "height": H, **kw}, timeout=3000)
            # Arrival: guests come in through the entrance in groups.
            px, py = scene["entrance"]
            gate = {"x": (px - 2) * 32, "y": (py - 5) * 32, "z": GROUND}
            arrive, t = [], 0
            for k in range(40):
                g.call("spawn_guests", {"n": guests // 40}, timeout=60)
                r = film(f"arrive_{k:02d}", camera=gate, rotation=0, minDt=3, frames=6)
                arrive += [{**f, "tick": t + f["tick"], "dir": f"arrive_{k:02d}", "i": i} for i, f in enumerate(r["frames"])]
                t = arrive[-1]["tick"]
            shots["arrive"] = arrive
            # The queue fills until the train comes back for a full load. The station itself sits under
            # the design's trees (they earn its scenery bonus), so this view shows the ride entrance,
            # the queue and the lift hill, where the train comes out of the trees.
            lift = {"x": 3300, "y": 3560, "z": 190}
            r = film("queue", camera=lift, rotation=3, minDt=60, maxDt=60, frames=1200, minFrames=30,
                     stop=["arriving"], stopMinQueue=20, queue=queue)
            shots["queue"] = [{**f, "dir": "queue", "i": i} for i, f in enumerate(r["frames"])]
            print("queue:", r["reason"], len(r["frames"]), "frames, last", r["frames"][-1])
            # Boarding, until the full train is up the lift hill.
            r = film("board", camera=lift, rotation=3, minDt=4, maxDt=4, frames=3000, start=["arriving"],
                     maxWait=40000, stop=["travelling"], tail=700, queue=queue)
            shots["board"] = [{**f, "dir": "board", "i": i} for i, f in enumerate(r["frames"])]
            print("board:", r["reason"], len(r["frames"]), "frames, max aboard", max(f["aboard"] for f in r["frames"]))
            # The ride, following the middle car.
            r = film("ride", camera={"follow": True}, rotation=3, minDt=1, maxDt=6, px=10, frames=9000,
                     stop=["arriving"])
            shots["ride"] = [{**f, "dir": "ride", "i": i} for i, f in enumerate(r["frames"])]
            print("ride:", r["reason"], len(r["frames"]), "frames")
            # Back into the station and off.
            r = film("unload", camera=lift, rotation=3, minDt=4, maxDt=4, frames=3000,
                     stop=["waiting_for_passengers"], tail=400, queue=queue)
            shots["unload"] = [{**f, "dir": "unload", "i": i} for i, f in enumerate(r["frames"])]
            r = film("wide", camera={"x": 3840, "y": 3904, "z": GROUND}, rotation=3, frames=1)
            shots["wide"] = [{**r["frames"][0], "dir": "wide", "i": 0}]
            shots["ratings"] = g.call("ride_info", {})[0]
    finally:
        xvfb.terminate()
    shutil.rmtree(RIDE_DIR, ignore_errors=True)
    shutil.copytree(RUNTIME / "screenshot" / "ride", RIDE_DIR)
    (RIDE_DIR / "shots.json").write_text(json.dumps(shots))


GROUND = 112
TICKS_PER_SECOND = 40  # at normal game speed
SEATS = 36  # 10 cars; the plugin's guests_info reports the train's seats


def screen(rot: int, x: float, y: float, z: float) -> tuple[float, float]:
    return [(y - x, (x + y) / 2 - z), (-x - y, (y - x) / 2 - z), (x - y, (-x - y) / 2 - z), (x + y, (x - y) / 2 - z)][rot]


def pick_even(frames: list[dict], n: int) -> list[dict]:
    """n frames spread evenly over the shot's ticks."""
    t0, t1 = frames[0]["tick"], frames[-1]["tick"]
    out, j = [], 0
    for k in range(n):
        t = t0 + (t1 - t0) * k / max(1, n - 1)
        while j + 1 < len(frames) and abs(frames[j + 1]["tick"] - t) <= abs(frames[j]["tick"] - t):
            j += 1
        out.append(frames[j])
    return out


def pick_distance(frames: list[dict], n: int, tunnel: float = 0.3) -> list[dict]:
    """n frames at even steps of the camera's travel on screen (faster through tunnels, where the
    train cannot be seen), so the ride moves at a steady pace."""
    s, acc = [0.0], 0.0
    for a, b in zip(frames, frames[1:]):
        (x0, y0), (x1, y1) = screen(3, *a["mid"]), screen(3, *b["mid"])
        acc += math.hypot(x1 - x0, y1 - y0) * (tunnel if b["under"] else 1.0)
        s.append(acc)
    out, j = [], 0
    for k in range(n):
        target = acc * k / max(1, n - 1)
        while j + 1 < len(frames) and s[j + 1] <= target:
            j += 1
        out.append(frames[j])
    return out


def load(f: dict, close: bool) -> Image.Image:
    img = Image.open(RIDE_DIR / f["dir"] / f"{f['i']:05d}.png").convert("RGB")
    if close:  # the middle quarter, doubled: zoomed in one step further than the game allows
        img = img.crop((W // 4, H // 4, W // 4 + W // 2, H // 4 + H // 2)).resize((W, H), Image.NEAREST)
    return img


def hud(img: Image.Image, lines: list[tuple[str, str]]) -> Image.Image:
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0 = 40, H - 40 - 64 * len(lines) - 24
    d.rounded_rectangle([x0, y0, x0 + 520, H - 40], radius=18, fill=(12, 18, 30, 190))
    for k, (label, value) in enumerate(lines):
        y = y0 + 20 + 64 * k
        d.text((x0 + 28, y + 10), label, font=font(28), fill=(200, 210, 220))
        d.text((x0 + 492, y), value, font=font(44), fill=(255, 214, 64), anchor="ra")
    return img


def ride_edit(lang: str = "ko", ride_secs: float = 26) -> Path:
    L = TEXT[lang]
    shots = json.loads((RIDE_DIR / "shots.json").read_text())
    E, I, N = final_ratings()
    seq = Sequence(OUT / f"ride_seq_{lang}")
    emit = seq.emit

    def speedup(frames: list[dict], out_frames: int) -> float:
        return (frames[-1]["tick"] - frames[0]["tick"]) / TICKS_PER_SECOND / (out_frames / FPS)

    wide = load(shots["wide"][0], close=False)
    # Title.
    title = wide.copy()
    d = ImageDraw.Draw(title, "RGBA")
    d.rectangle([0, 0, W, H], fill=(8, 12, 20, 150))
    d.text((W // 2, H // 2 - 80), L["r_title"], font=font(76), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, H // 2 + 20), L["r_sub"].format(E=E), font=font(40), fill=(255, 214, 64), anchor="mm")
    d.text((W // 2, H // 2 + 90), L["r_note"].format(g=1200), font=font(30), fill=(210, 220, 230), anchor="mm")
    emit(title, int(FPS * 2.5))
    # Arrival, close up.
    for f in pick_even(shots["arrive"], int(FPS * 4)):
        emit(caption(load(f, True), *L["arrive"]))
    # The queue filling up again while the train is out (time lapse of its last lap).
    queue = [f for f in shots["queue"] if f["tick"] >= shots["queue"][-1]["tick"] - 11000]
    picks = pick_even(queue, int(FPS * 5))
    rate = speedup(queue, len(picks))
    head, big, small = L["queue"]
    for f in picks:
        emit(caption(load(f, True), head.format(r=rate), big.format(q=f["queue"]), small))
    # Boarding (the station is under the trees), then out of the trees and up the lift hill.
    board = shots["board"]
    picks = pick_even(board, int(FPS * 6))
    rate = speedup(board, len(picks))
    loading = False
    for f in picks:
        loading = loading or f["car"][3] == "waiting_for_passengers"
        if not loading:  # the previous train pulling in and its riders getting off
            head, big, small = L["station"]
            emit(caption(load(f, True), head.format(r=rate), big, small.format(a=f["aboard"], q=f["queue"])))
            continue
        head, big, small, full = L["board"]
        small = full if f["aboard"] >= SEATS else small.format(s=SEATS, q=f["queue"])
        emit(caption(load(f, True), head.format(r=rate), big.format(a=f["aboard"]), small))
    # The ride: close up for the first drops and the fast finale, wide in between, at an even
    # pace on screen.
    ride = shots["ride"]
    t0, t_end = ride[0]["tick"], ride[-1]["tick"]
    dep_tick = next(f["tick"] for f in board if f["car"][3] == "departing") - board[0]["tick"]
    t_ride0 = (t0 - (board[-1]["tick"] - dep_tick))  # ride time counts from departure
    secs = lambda f: (f["tick"] - t_ride0) / TICKS_PER_SECOND
    total = secs(ride[-1])
    cut1, cut2 = t0 + 45 * TICKS_PER_SECOND, t_end - 65 * TICKS_PER_SECOND
    segs = [([f for f in ride if f["tick"] < cut1], True), ([f for f in ride if cut1 <= f["tick"] < cut2], False),
            ([f for f in ride if f["tick"] >= cut2], True)]

    def travel(frames):
        out = 0.0
        for a_, b_ in zip(frames, frames[1:]):
            (x0, y0), (x1, y1) = screen(3, *a_["mid"]), screen(3, *b_["mid"])
            out += math.hypot(x1 - x0, y1 - y0) * (0.3 if b_["under"] else 1.0)
        return out

    weights = [travel(fr) * (2 if close else 1) for fr, close in segs]
    head, near, far = L["ride"]
    speed, riders, riders_n, clock = L["hud"]
    prev = None
    for (frames, close), wgt in zip(segs, weights):
        k = max(2, round(FPS * ride_secs * wgt / sum(weights)))
        picks = pick_distance(frames, k)
        rate = speedup(frames, k)
        for j, f in enumerate(picks):
            t = secs(f)
            img = caption(load(f, close), head.format(r=rate), L["E"].format(E=E),
                          (near if close else far).format(b=band(E, lang)))
            img = hud(img, [(speed, f"{f['kmh']} km/h"), (riders, riders_n.format(a=f["aboard"])),
                            (clock, f"{int(t // 60)}:{int(t % 60):02d} / {int(total // 60)}:{int(total % 60):02d}")])
            if prev is not None and j < 8:  # dissolve between close and wide
                img = Image.blend(prev, img, (j + 1) / 9)
            emit(img)
        prev = img
    # Back into the station and off.
    unload = shots["unload"]
    riders = max(f["aboard"] for f in ride)
    head, big, off, next_on = L["unload"]
    for f in pick_even(unload, int(FPS * 4)):
        small = (next_on.format(a=riders, b=f["aboard"]) if f["car"][3] == "waiting_for_passengers"
                 else off.format(a=riders))
        emit(caption(load(f, True), head, big, small))
    # End card.
    end = wide.copy()
    d = ImageDraw.Draw(end, "RGBA")
    head, sub, note = L["end"]
    big = f"{L['E'].format(E=E)} · {band(E, lang)}"
    half = max(480, d.textlength(big, font=font(84)) / 2 + 60, d.textlength(note, font=font(30)) / 2 + 60)
    d.rounded_rectangle([W // 2 - half, H // 2 - 200, W // 2 + half, H // 2 + 200], radius=24, fill=(12, 18, 30, 210))
    d.text((W // 2, H // 2 - 120), head, font=font(36), fill=(220, 230, 240), anchor="mm")
    d.text((W // 2, H // 2 - 20), big, font=font(84), fill=(255, 214, 64), anchor="mm")
    d.text((W // 2, H // 2 + 80), sub.format(I=I, N=N), font=font(40), fill=(220, 230, 240), anchor="mm")
    d.text((W // 2, H // 2 + 145), note, font=font(30), fill=(190, 200, 210), anchor="mm")
    emit(end, FPS * 4)
    mp4 = OUT / ("ride.mp4" if lang == "ko" else f"ride_{lang}.mp4")
    encode(seq.path, mp4, music("ride"))
    print("->", mp4, f"{seq.n / FPS:.1f} s")
    return mp4


if __name__ == "__main__":
    # make_videos.py search|ride|ride-edit [ko|en ...]
    langs = sys.argv[2:] or list(TEXT)
    if sys.argv[1] == "ride":
        record()
    for lang in langs:
        {"search": search, "ride": ride_edit, "ride-edit": ride_edit}[sys.argv[1]](lang)
