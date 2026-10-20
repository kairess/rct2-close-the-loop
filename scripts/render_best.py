"""Rebuild a run's best track (optionally with the path planner and trees), save the park and screenshots.

    uv run python scripts/render_best.py runs/<dir> <name> [--paths] [--icap 10.35]

Writes results/extreme/<name>/: park, 4 screenshots and crops, summary.json (verdict from a fresh instance).
"""

import argparse
import dataclasses
import json
from pathlib import Path

from PIL import Image

from rct2_close_the_loop.design import layout_from_run
from rct2_close_the_loop.results import RESULTS, crop_to_area, render


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("name")
    ap.add_argument("--paths", action="store_true")
    ap.add_argument("--icap", type=float, default=10.35)
    args = ap.parse_args()
    layout, meta = layout_from_run(args.run)
    if args.paths:
        layout = dataclasses.replace(layout, paths=True)
    best = None
    for line in open(args.run / "evals.jsonl"):
        r = json.loads(line)
        v = r["verdict"]
        if v["stage"] == "rated" and v["I"] < args.icap and (best is None or v["E"] > best["verdict"]["E"]):
            best = r
    out = RESULTS / "extreme" / args.name
    track = [tuple(p) for p in best["track"]]
    summary = render(layout, track, args.name, zoom=None, circuits=best.get("circuits", 1), out=out)
    for k, shot in enumerate(summary["screenshots"]):
        img = crop_to_area(Image.open(out / shot).convert("RGB"), layout, k)
        img.resize((960, round(960 * img.height / img.width)), Image.LANCZOS).save(out / f"thumb_r{k}.jpg", quality=84)
    summary.update({"run": args.run.name, "eval": best["eval"], "search_verdict": best["verdict"], "paths": args.paths,
                    "config": meta["config"]})
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    v = summary["verdict"]
    print(f"{args.name}: E{v['E']} I{v['I']} N{v['N']} paths {v.get('paths')} trees {v.get('decor')} -> {out}")


if __name__ == "__main__":
    main()
