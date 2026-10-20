"""Social-media videos of the record coaster.

    uv run python scripts/make_videos.py search   # the search, frame by frame, in the decorated park
    uv run python scripts/make_videos.py ride     # guests arriving, queuing and riding it
    uv run python scripts/make_videos.py ride-edit  # re-edit the ride video from recorded frames

Frames come from the game itself. Each search frame is the track at one of the run's improvements,
built (with its own paths and trees) in the decorated surroundings, saved, and rendered with the
CLI screenshot command. The ride video is filmed inside a running game (on a virtual display, since
only a game with a renderer can capture and the CLI screenshot does not draw guests or trains):
ordinary guests arrive through the park entrance, queue, board, ride and get off, while the plugin
captures the view every few ticks. Videos are encoded with ffmpeg (1920x1080, 30 fps).
"""

from __future__ import annotations

import dataclasses
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rct2_close_the_loop.design import layout_from_run
from rct2_close_the_loop.game import RUNTIME, Game, wait_ready
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


def encode(seq: Path, mp4: Path) -> None:
    """H.264 at a bitrate social sites take without re-encoding much (about 12 Mbit/s at 1080p30)."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(seq / "%05d.jpg"),
                    "-c:v", "libx264", "-preset", "slow", "-tune", "animation", "-crf", "21", "-maxrate", "12M",
                    "-bufsize", "24M", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)


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
    encode(seq, mp4)
    print("->", mp4, f"{n / FPS:.1f} s")
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


def ride_edit(ride_secs: float = 26) -> Path:
    shots = json.loads((RIDE_DIR / "shots.json").read_text())
    rating = shots["ratings"]
    E, I, N = rating["excitement"] / 100, rating["intensity"] / 100, rating["nausea"] / 100
    seq = OUT / "ride_seq"
    shutil.rmtree(seq, ignore_errors=True)
    seq.mkdir(parents=True)
    n = 0

    def emit(img: Image.Image, count: int = 1):
        nonlocal n
        for _ in range(count):
            img.save(seq / f"{n:05d}.jpg", quality=92)
            n += 1

    def speedup(frames: list[dict], out_frames: int) -> float:
        return (frames[-1]["tick"] - frames[0]["tick"]) / TICKS_PER_SECOND / (out_frames / FPS)

    wide = load(shots["wide"][0], close=False)
    # Title.
    title = wide.copy()
    d = ImageDraw.Draw(title, "RGBA")
    d.rectangle([0, 0, W, H], fill=(8, 12, 20, 150))
    d.text((W // 2, H // 2 - 80), "진짜 손님이 탄다", font=font(76), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, H // 2 + 20), f"흥미도 {E:.2f} 하이퍼 트위스터 · OpenRCT2", font=font(40), fill=(255, 214, 64), anchor="mm")
    d.text((W // 2, H // 2 + 90), "보통 손님 1,200명 · 탈지 말지는 게임의 손님 AI가 정한다", font=font(30), fill=(210, 220, 230), anchor="mm")
    emit(title, int(FPS * 2.5))
    # Arrival, close up.
    for f in pick_even(shots["arrive"], int(FPS * 4)):
        emit(caption(load(f, True), "개장", "손님 입장", "입구로 들어와 공원을 걷는다"))
    # The queue filling up again while the train is out (time lapse of its last lap).
    queue = [f for f in shots["queue"] if f["tick"] >= shots["queue"][-1]["tick"] - 11000]
    picks = pick_even(queue, int(FPS * 5))
    rate = speedup(queue, len(picks))
    for f in picks:
        emit(caption(load(f, True), f"대기줄 · {rate:.0f}배속", f"대기 {f['queue']}명", "줄 서는 것도 손님 스스로"))
    # Boarding (the station is under the trees), then out of the trees and up the lift hill.
    board = shots["board"]
    picks = pick_even(board, int(FPS * 6))
    rate = speedup(board, len(picks))
    loading = False
    for f in picks:
        loading = loading or f["car"][3] == "waiting_for_passengers"
        if not loading:  # the previous train pulling in and its riders getting off
            emit(caption(load(f, True), f"역 · {rate:.0f}배속", "앞 열차 도착", f"내리는 중 {f['aboard']}명 · 대기 {f['queue']}명"))
            continue
        small = "만석! 리프트로 출발" if f["aboard"] >= SEATS else f"정원 {SEATS}명 · 대기 {f['queue']}명"
        emit(caption(load(f, True), f"탑승 · {rate:.0f}배속", f"탑승 {f['aboard']}명", small))
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
    prev = None
    for (frames, close), wgt in zip(segs, weights):
        k = max(2, round(FPS * ride_secs * wgt / sum(weights)))
        picks = pick_distance(frames, k)
        rate = speedup(frames, k)
        for j, f in enumerate(picks):
            t = secs(f)
            img = caption(load(f, close), f"주행 · {rate:.0f}배속", f"흥미도 {E:.2f}",
                          "극한 · 가까이" if close else "극한 · 멀리서 · 터널은 빨리 감기")
            img = hud(img, [("속도", f"{f['kmh']} km/h"), ("탑승", f"{f['aboard']}명"),
                            ("주행 시간", f"{int(t // 60)}:{int(t % 60):02d} / {int(total // 60)}:{int(total % 60):02d}")])
            if prev is not None and j < 8:  # dissolve between close and wide
                img = Image.blend(prev, img, (j + 1) / 9)
            emit(img)
        prev = img
    # Back into the station and off.
    unload = shots["unload"]
    riders = max(f["aboard"] for f in ride)
    for f in pick_even(unload, int(FPS * 4)):
        small = (f"{riders}명 하차 · 다음 손님 탑승 {f['aboard']}명" if f["car"][3] == "waiting_for_passengers"
                 else f"{riders}명이 내린다")
        emit(caption(load(f, True), "도착", "무사히 한 바퀴", small))
    # End card.
    end = wide.copy()
    d = ImageDraw.Draw(end, "RGBA")
    d.rounded_rectangle([W // 2 - 480, H // 2 - 200, W // 2 + 480, H // 2 + 200], radius=24, fill=(12, 18, 30, 210))
    d.text((W // 2, H // 2 - 120), "게임이 직접 매긴 레이팅", font=font(36), fill=(220, 230, 240), anchor="mm")
    d.text((W // 2, H // 2 - 20), f"흥미도 {E:.2f} · 극한", font=font(84), fill=(255, 214, 64), anchor="mm")
    d.text((W // 2, H // 2 + 80), f"강도 {I:.2f} · 멀미도 {N:.2f}", font=font(40), fill=(220, 230, 240), anchor="mm")
    d.text((W // 2, H // 2 + 145), "치트 없음 · 동기 출발 없음 · 코스터 한 대", font=font(30), fill=(190, 200, 210), anchor="mm")
    emit(end, FPS * 4)
    mp4 = OUT / "ride.mp4"
    encode(seq, mp4)
    print("->", mp4, f"{n / FPS:.1f} s")
    return mp4


def ride_video() -> Path:
    record()
    return ride_edit()


if __name__ == "__main__":
    {"search": search, "ride": ride_video, "ride-edit": ride_edit}[sys.argv[1]]()
