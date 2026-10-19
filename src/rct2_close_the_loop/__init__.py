import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="rct2loop", description="Coaster design with OpenRCT2 as the judge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="loop-first segment-edit search")
    s.add_argument("--layout", default="wooden_24")
    s.add_argument("--workers", type=int, default=14)
    s.add_argument("--batch", type=int, default=28)
    s.add_argument("--evals", type=int, default=20000)
    s.add_argument("--minutes", type=float, default=120)
    s.add_argument("--t0", type=float, default=0.6)
    s.add_argument("--t1", type=float, default=0.02)
    s.add_argument("--hill", type=int, default=6)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--init", type=Path, help="best.json (or any JSON with a 'track') to start from")
    s.add_argument("--stop-on-goal", action="store_true")

    e = sub.add_parser("evaluate", help="re-evaluate a track in a fresh game instance")
    e.add_argument("file", type=Path, help="JSON with a 'track' field (e.g. runs/.../best.json)")
    e.add_argument("--layout", default="wooden_24")
    e.add_argument("--repeat", type=int, default=3)

    r = sub.add_parser("render", help="build a track, save the park and take screenshots into results/<name>/")
    r.add_argument("file", type=Path, help="JSON with a 'track' field")
    r.add_argument("name")
    r.add_argument("--layout", default="wooden_24")
    r.add_argument("--zoom", type=int, default=0)

    st = sub.add_parser("stats", help="summarize search runs")
    st.add_argument("runs", type=Path, nargs="+")
    st.add_argument("--trajectory", action="store_true")

    args = parser.parse_args()
    if args.cmd == "stats":
        from .analysis import summarize_run

        for run_dir in args.runs:
            s = summarize_run(run_dir)
            if not args.trajectory:
                s.pop("trajectory")
            print(json.dumps(s, indent=1))
        return
    from .layouts import LAYOUTS

    layout = LAYOUTS[args.layout]
    if args.cmd == "search":
        from .search import SearchConfig, run

        cfg = SearchConfig(
            layout_name=args.layout, workers=args.workers, batch=args.batch, max_evals=args.evals,
            max_minutes=args.minutes, t0=args.t0, t1=args.t1, hill=args.hill, seed=args.seed,
            stop_on_goal=args.stop_on_goal,
        )
        initial = None
        if args.init:
            initial = [tuple(p) for p in json.loads(args.init.read_text())["track"]]
        run(cfg, layout, initial)
    elif args.cmd == "evaluate":
        from .judge import Judge
        from .search import meets_goal

        track = [tuple(p) for p in json.loads(args.file.read_text())["track"]]
        judge = Judge(layout)
        try:
            for k in range(args.repeat):
                v = judge.evaluate(track)
                print(json.dumps({"repeat": k, "goal": meets_goal(v), **v.to_dict()}))
        finally:
            judge.close()
    elif args.cmd == "render":
        from .results import render

        track = [tuple(p) for p in json.loads(args.file.read_text())["track"]]
        summary = render(layout, track, args.name, zoom=args.zoom)
        print(json.dumps({k: v for k, v in summary.items() if k != "track"}, indent=1))
