"""After a benchmark split has run: summary table, gallery, evolution animation, report page.

    uv run python scripts/finish_bench.py <split> <report_dir> [run dirs...]

Without run dirs it takes every runs/*/ whose design.json names a condition of the split.
The animation shows the real-map condition that met the goal with the highest excitement
(or, failing that, any condition with the highest excitement).
"""

import json
import subprocess
import sys
from pathlib import Path

from rct2_close_the_loop.design import layout_from_run
from rct2_close_the_loop.results import RESULTS, animate

ROOT = Path(__file__).resolve().parents[1]


def runs_for(split: str) -> list[Path]:
    out = []
    for d in sorted((ROOT / "runs").glob("2026*/")):
        meta = d / "design.json"
        if meta.exists() and f"/{split}/" in json.loads(meta.read_text())["condition"]:
            out.append(d)
    return out


def main() -> None:
    split, report_dir = sys.argv[1], Path(sys.argv[2])
    runs = [Path(p) for p in sys.argv[3:]] or runs_for(split)
    py = [sys.executable]
    subprocess.run(py + ["scripts/summarize_bench.py", split, *map(str, runs)], check=True, cwd=ROOT)
    subprocess.run(py + ["scripts/gallery.py", split, *map(str, runs)], check=True, cwd=ROOT)
    bench = json.loads((RESULTS / f"benchmark_{split}.json").read_text())
    rows = [r for r in bench["rows"] if r["best_feasible"]]
    real = [r for r in rows if r["kind"] == "real" and r["goal"]]
    pick = max(real or rows, key=lambda r: (r["best_goal"] or r["best_feasible"])[0])
    run = ROOT / "runs" / pick["run"]
    layout, _meta = layout_from_run(run)
    name = f"evolution_{split}_{pick['condition']}"
    animate(layout, run, name, frames=24, rotation=0)
    best = pick["best_goal"] or pick["best_feasible"]
    cond = json.loads((ROOT / "data" / "bench" / split / f"{pick['condition']}.json").read_text())
    title = cond["scenario"].removesuffix(".SC6") if cond["kind"] == "real" else f"무작위 지형 #{cond['seed']}"
    caption = (f"{title}: 첫 회로에서 15분 탐색 끝까지, 목표 조건을 지키며 흥미도가 오를 때마다 찍은 장면이다. "
               f"최종 E {best[0]:.2f} / I {best[1]:.2f} / N {best[2]:.2f}.")
    anim = {"path": str((RESULTS / name / f"{name}.webp").relative_to(ROOT)), "caption": caption}
    (RESULTS / f"anim_{split}.json").write_text(json.dumps(anim, ensure_ascii=False, indent=1))
    subprocess.run(py + ["scripts/build_report.py", split, str(report_dir), "--anim", anim["path"],
                         "--anim-caption", caption], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
