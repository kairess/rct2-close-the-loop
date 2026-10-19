"""Build each benchmark run's best coaster in its park, save the park and screenshots.

    uv run python scripts/gallery.py <split> [--suffix _posthoc] runs/2026*/

For every run of the split the best goal-meeting track is rebuilt (or, if the
goal was missed, the best one with I < 7.68 and N < 5.12), with its trees, saved
to results/gallery/<split>_<condition>/ and screenshot from four sides. It is
also rated once without trees, to show what the theming adds. A track whose
rating a fresh instance does not reproduce is skipped for the next best one.
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


def candidates(run: Path, limit: int = 12) -> list[dict]:
    """Distinct tracks with I and N under the goal limits, highest excitement first."""
    best: dict[str, dict] = {}
    for line in open(run / "evals.jsonl"):
        r = json.loads(line)
        v = r["verdict"]
        if v["stage"] != "rated" or v["I"] >= GOAL[1] or v["N"] >= GOAL[2]:
            continue
        key = json.dumps([r["track"], r.get("circuits", 1)])
        if key not in best:
            best[key] = r
    return sorted(best.values(), key=lambda r: (-r["verdict"]["E"], r["eval"]))[:limit]


def reproduced(verdict: dict, search: dict) -> bool:
    return verdict["stage"] == "rated" and all(verdict[k] == search[k] for k in ("E", "I", "N"))


def main() -> None:
    split, runs, suffix = sys.argv[1], sys.argv[2:], ""
    if runs[:1] == ["--suffix"]:
        suffix, runs = runs[1], runs[2:]
    out = RESULTS / "gallery"
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / f"{split}.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for run in map(Path, runs):
        if not (run / "design.json").exists():
            continue
        layout, meta = layout_from_run(run)
        if f"/{split}/" not in meta["condition"]:
            continue
        name = f"{split}_{meta['condition_name']}{suffix}"
        # The best track whose rating a fresh game instance reproduces exactly.
        tried = []
        for best in candidates(run):
            track = [tuple(p) for p in best["track"]]
            circuits = best.get("circuits", 1)
            summary = render(layout, track, name, zoom=None, circuits=circuits, out=out / name)
            tried.append({"eval": best["eval"], "fresh": {k: summary["verdict"][k] for k in ("stage", "E", "I", "N")}})
            if reproduced(summary["verdict"], best["verdict"]):
                break
        else:
            print(run.name, "no feasible track" if not tried else "no track reproduced in a fresh instance")
            if not tried:
                continue
        judge = Judge(dataclasses.replace(layout, decor=None))
        try:
            bare = judge.evaluate(track, circuits=circuits)
        finally:
            judge.close()
        summary.update({"condition": meta["condition_name"], "kind": meta.get("kind"), "run": run.name,
                        "eval": best["eval"], "search_verdict": best["verdict"], "tried": tried,
                        "without_trees": bare.to_dict()})
        for k, shot in enumerate(summary["screenshots"]):
            img = crop_to_area(Image.open(out / name / shot).convert("RGB"), layout, k)
            img = img.resize((960, round(960 * img.height / img.width)), Image.LANCZOS)
            img.save(out / name / f"thumb_r{k}.jpg", quality=84)
        (out / name / "summary.json").write_text(json.dumps(summary, indent=1))
        index[name] = {k: summary[k] for k in ("condition", "kind", "run", "eval", "park", "screenshots")}
        index[name]["verdict"] = {k: summary["verdict"][k] for k in ("E", "I", "N", "decor")}
        index[name]["without_trees"] = {k: bare.to_dict()[k] for k in ("E", "I", "N")}
        index_path.write_text(json.dumps(index, indent=1))
        v = summary["verdict"]
        print(f"{name}: E{v['E']}/I{v['I']}/N{v['N']} trees={v['decor']} (bare E{bare.excitement})")


if __name__ == "__main__":
    main()
