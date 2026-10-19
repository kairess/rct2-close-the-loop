"""Build the report page from benchmark results.

    uv run python scripts/build_report.py <split> <out_dir> [--anim results/<name>/<name>.webp --anim-run <run dir>]

Reads results/benchmark_<split>.json (summarize_bench.py), results/gallery/<split>.json
(gallery.py), the condition files and results/builtin_designs.json, and writes
<out_dir>/rct2-report.html plus the images it shows into <out_dir>/img/.
"""

import argparse
import json
import shutil
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SPLIT_LABEL = {"heldout": "보류 조건", "dev": "개발 조건"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--anim", type=Path)
    ap.add_argument("--anim-caption", default="")
    args = ap.parse_args()

    out = args.out_dir
    img = out / "img"
    img.mkdir(parents=True, exist_ok=True)
    bench = json.loads((RESULTS / f"benchmark_{args.split}.json").read_text())
    gallery_index = json.loads((RESULTS / "gallery" / f"{args.split}.json").read_text())
    builtin = json.loads((RESULTS / "builtin_designs.json").read_text())

    conds, gallery = {}, {}
    for r in bench["rows"]:
        name = r["condition"]
        c = json.loads((ROOT / "data" / "bench" / args.split / f"{name}.json").read_text())
        c["tiles"] = len(c.pop("area_tiles"))
        c.pop("park", None)
        conds[name] = c
        key = f"{args.split}_{name}"
        g = gallery_index.get(key)
        if g:
            for k in range(4):
                shutil.copyfile(RESULTS / "gallery" / key / f"thumb_r{k}.jpg", img / f"{key}_r{k}.jpg")
            gallery[name] = {"img": f"img/{key}", "verdict": g["verdict"], "without_trees": g["without_trees"]}
    shutil.copyfile(RESULTS / "report" / "img" / "final_r0.png", img / "final_r0.png")

    anim = None
    if args.anim:
        shutil.copyfile(args.anim, img / "evolution.webp")
        anim = {"src": "img/evolution.webp", "caption": args.anim_caption,
                "alt": "첫 직사각형 회로가 탐색을 거치며 언덕과 회전이 많은 코스터로 바뀌는 과정"}

    n, ok = bench["n"], bench["success"]
    coasters = [d for d in builtin["designs"] if str(d["ride_type"]).endswith("_rc")]
    med = statistics.median(d["E"] for d in coasters)
    ours = sorted((r["best_goal"] or r["best_feasible"] or [0])[0] for r in bench["rows"])
    trees = [g["verdict"]["E"] - g["without_trees"]["E"] for g in gallery.values()
             if g["without_trees"].get("E") is not None]
    tree_gain = statistics.median(trees) if trees else 0.0
    real = [r for r in bench["rows"] if conds[r["condition"]]["kind"] == "real"]
    syn = [r for r in bench["rows"] if conds[r["condition"]]["kind"] != "real"]

    dev_note = ""
    dev_path = RESULTS / "benchmark_dev.json"
    if args.split != "dev" and dev_path.exists():
        dev = json.loads(dev_path.read_text())
        dev_note = (f" 설정을 고를 때 쓴 개발 조건(실제 맵 4곳, 무작위 지형 6곳)에서는 "
                    f"{dev['success']}/{dev['n']}였다.")

    data = {
        "split": args.split,
        "split_label": SPLIT_LABEL.get(args.split, args.split),
        "bench": bench,
        "conds": conds,
        "gallery": gallery,
        "anim": anim,
        "lead": (f"공원 파일과 영역만 주면 땅을 읽고, 역을 놓고, 게임이 매긴 레이팅만 보고 코스터를 설계한다. "
                 f"개발에 쓰지 않은 {n}개 조건(실제 RCT2 시나리오 맵 {len(real)}곳, 새 무작위 지형 {len(syn)}곳)에서 "
                 f"조건마다 15분씩 돌려 <strong>{ok}곳에서 흥미도 Very High(7.68 이상)</strong>를 "
                 f"강도·멀미도 제한 안에서 달성했다."),
        "gallery_intro": (f"카드마다 그 조건에서 찾은 가장 좋은 코스터다. 강도 7.68, 멀미도 5.12 미만을 지킨 트랙 중 고른 것이다. "
                          f"새 게임 인스턴스에서 다시 짓고 레이팅한 값이며, 공원 파일은 <code>results/gallery/</code>에 있다. "
                          f"사진을 누르면 다른 방향에서 볼 수 있다."),
        "table_intro": (f"성공 {ok}/{n}(실제 맵 {sum(r['goal'] for r in real)}/{len(real)}, "
                        f"무작위 지형 {sum(r['goal'] for r in syn)}/{len(syn)}). "
                        f"\"첫 달성\"은 15분 가운데 목표를 처음 만족한 시각이다. 조건은 실행 전에 고정된 코드로 뽑았고, "
                        f"이 조건들로 설정을 고치지 않았다." + dev_note),
        "human": (f"RCT2에 들어 있는 사람 설계 롤러코스터 {len(coasters)}개 중 이 목표(E ≥ 7.68, I &lt; 7.68, N &lt; 5.12)를 "
                  f"만족하는 것은 <strong>{builtin['meet_goal']}개</strong>이고, 24×24 안에 들어가는 것은 "
                  f"{builtin['meet_goal_within_24']}개다. 사람 설계의 흥미도 중앙값은 {med:.2f}이고, "
                  f"이 알고리즘이 조건별로 낸 최고 흥미도의 중앙값은 {statistics.median(ours):.2f}다. "
                  f"다만 사람 설계는 대부분 훨씬 넓은 땅을 쓰고, 레이팅은 경치 없이 저장된 값이다."),
        "limits": [
            f"<strong>나무가 흥미도의 일부다.</strong> 같은 트랙을 나무 없이 매기면 흥미도가 중앙값 {tree_gain:.2f} 낮다. "
            "경치 보너스는 게임이 의도한 규칙이지만, 순수한 트랙 형태만의 점수는 아니다.",
            "<strong>사람이 보기 좋은 모양은 아니다.</strong> 근접·회전·낙하 보너스를 채우려고 낮게 꼬인 트랙이 많다. "
            "레이팅 외의 미감은 목표에 넣지 않았다.",
            "<strong>입장 동선은 짓지 않는다.</strong> 입구와 출구 앞 칸을 비워 두지만, 공원 길과 잇는 일은 사람이 해야 한다.",
            "<strong>돈과 연구는 끈다.</strong> 실제 시나리오에서는 예산과 연구 상태에 따라 지을 수 없는 조각이 있을 수 있다.",
        ],
    }
    template = (ROOT / "scripts" / "report_template.html").read_text()
    page = template.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False))
    (out / "rct2-report.html").write_text(page)
    print("->", out / "rct2-report.html", f"{ok}/{n}")


if __name__ == "__main__":
    main()
