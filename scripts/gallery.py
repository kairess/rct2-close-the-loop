"""Build each benchmark run's best coaster in its park, save the park and screenshots.

    uv run python scripts/gallery.py <split> runs/2026*/

For every run of the split the best goal-meeting track is rebuilt (or, if the
goal was missed, the best one with I < 7.68 and N < 5.12), with its trees, saved
to results/gallery/<split>_<condition>/ and screenshot from four sides. It is
also rated once without trees, to show what the theming adds.
"""

import dataclasses
import json
import sys
from pathlib import Path

from PIL import Image

from rct2_close_the_loop.design import layout_from_run
from rct2_close_the_loop.judge import Judge
from rct2_close_the_loop.results import RESULTS, crop_to_area, render

GOAL = (7.68, 7.68, 5.12)


def pick(run: Path) -> dict | None:
    best = None
    for line in open(run / "evals.jsonl"):
        r = json.loads(line)
        v = r["verdict"]
        if v["stage"] != "rated" or v["I"] >= GOAL[1] or v["N"] >= GOAL[2]:
            continue
        if best is None or v["E"] > best["verdict"]["E"]:
            best = r
    return best


def main() -> None:
    split = sys.argv[1]
    out = RESULTS / "gallery"
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / f"{split}.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for run in map(Path, sys.argv[2:]):
        if not (run / "design.json").exists():
            continue
        layout, meta = layout_from_run(run)
        if f"/{split}/" not in meta["condition"]:
            continue
        best = pick(run)
        if best is None:
            print(run.name, "no feasible track")
            continue
        name = f"{split}_{meta['condition_name']}"
        track = [tuple(p) for p in best["track"]]
        circuits = best.get("circuits", 1)
        summary = render(layout, track, name, zoom=None, circuits=circuits, out=out / name)
        judge = Judge(dataclasses.replace(layout, decor=None))
        try:
            bare = judge.evaluate(track, circuits=circuits)
        finally:
            judge.close()
        summary.update({"condition": meta["condition_name"], "kind": meta.get("kind"), "run": run.name,
                        "eval": best["eval"], "search_verdict": best["verdict"],
                        "without_trees": bare.to_dict()})
        for k, shot in enumerate(summary["screenshots"]):
            img = crop_to_area(Image.open(out / name / shot).convert("RGB"), layout, k)
            img.save(out / name / f"thumb_r{k}.jpg", quality=85)
        (out / name / "summary.json").write_text(json.dumps(summary, indent=1))
        index[name] = {k: summary[k] for k in ("condition", "kind", "run", "eval", "park", "screenshots")}
        index[name]["verdict"] = {k: summary["verdict"][k] for k in ("E", "I", "N", "decor")}
        index[name]["without_trees"] = {k: bare.to_dict()[k] for k in ("E", "I", "N")}
        index_path.write_text(json.dumps(index, indent=1))
        v = summary["verdict"]
        print(f"{name}: E{v['E']}/I{v['I']}/N{v['N']} trees={v['decor']} (bare E{bare.excitement})")


if __name__ == "__main__":
    main()
