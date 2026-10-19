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
    s.add_argument("--slack", type=float, default=0.0, help="low-I/N tie-breaker weight")
    s.add_argument("--chains", type=int, default=1, help="independent annealing chains")
    s.add_argument("--icap-start", type=float, default=7.5, help="intensity cap in the score at the start")
    s.add_argument("--icap-end", type=float, default=7.5, help="intensity cap in the score at the end")
    s.add_argument("--reheat-after", type=int, default=60, help="rounds without a chain best before it restarts")
    s.add_argument("--priors", action="store_true", help="cap inversions at 6 and helix pieces at 5")
    s.add_argument("--iprice-start", type=float, default=0.0, help="price per unit of intensity at the start")
    s.add_argument("--iprice-end", type=float, default=0.0, help="price per unit of intensity at the end")
    s.add_argument("--circuits", default="1", help="laps per chain, cycled over chains, e.g. 1,1,1,2")
    s.add_argument("--stop-on-goal", action="store_true")

    m = sub.add_parser("mapelites", help="MAP-Elites over intensity x nausea, fitness = excitement")
    m.add_argument("--layout", default="wooden_24")
    m.add_argument("--workers", type=int, default=14)
    m.add_argument("--inflight", type=int, default=28)
    m.add_argument("--evals", type=int, default=30000)
    m.add_argument("--minutes", type=float, default=60)
    m.add_argument("--hill", type=int, default=6)
    m.add_argument("--seed", type=int, default=1)
    m.add_argument("--goal-bias", type=float, default=0.5)
    m.add_argument("--tournament", type=int, default=2)
    m.add_argument("--max-window", type=int, default=12)
    m.add_argument("--max-walk", type=int, default=8)
    m.add_argument("--init", type=Path, nargs="*", help="JSON files with a 'track' (best.json) or archive.json")
    m.add_argument("--init-run", type=Path, nargs="*", help="seed with the best track per (I, N) cell of earlier runs")
    m.add_argument("--stop-on-goal", action="store_true")

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

    dg = sub.add_parser("design", help="general pipeline: condition JSON (park + area) -> coaster")
    dg.add_argument("condition", type=Path)
    dg.add_argument("--seed", type=int, default=1)
    dg.add_argument("--minutes", type=float, help="override the fixed time budget (development only)")
    dg.add_argument("--ride", help="override the fixed ride type (development only)")
    dg.add_argument("--config", default="fixed", help="named configuration in design.CONFIGS (fixed, extreme)")
    dg.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a configuration value (JSON value), e.g. --set cars=10 --set circuits='\"1,1,3,3\"'")

    rp = sub.add_parser("report", help="collect evidence from runs into results/report.json")
    rp.add_argument("runs", type=Path, nargs="+")
    rp.add_argument("--out", type=Path, default=Path("results/report.json"))

    args = parser.parse_args()
    if args.cmd == "design":
        from .design import design

        overrides = {k: v for k, v in (("minutes", args.minutes), ("ride", args.ride)) if v is not None}
        for kv in args.set:
            key, _, value = kv.partition("=")
            try:
                overrides[key] = json.loads(value)
            except json.JSONDecodeError:
                overrides[key] = value
        print(design(args.condition, seed=args.seed, overrides=overrides, config=args.config))
        return
    if args.cmd == "report":
        from .report import collect

        rep = collect(args.runs, args.out)
        print(json.dumps(rep["totals"]), "->", args.out)
        for r in rep["runs"]:
            b = r["best"]
            print(f"{r['run']:40s} {r['method']:9s} {r['ride']:10s} evals={r['evals']:6d} "
                  f"g2={r['g2_rejects']}/{r['g2_sent']} goal_hits={r['goal_hits']} best=E{b['verdict']['E']}/I{b['verdict']['I']}/N{b['verdict']['N']}")
        return
    if args.cmd == "stats":
        from .analysis import summarize_run

        for run_dir in args.runs:
            s = summarize_run(run_dir)
            if not args.trajectory:
                s.pop("trajectory")
            print(json.dumps(s, indent=1))
        return
    from .layouts import get_layout

    layout = get_layout(args.layout)
    if args.cmd == "search":
        from .search import SearchConfig, run

        cfg = SearchConfig(
            layout_name=args.layout, workers=args.workers, batch=args.batch, max_evals=args.evals,
            max_minutes=args.minutes, t0=args.t0, t1=args.t1, hill=args.hill, seed=args.seed,
            slack=args.slack, chains=args.chains, i_cap_start=args.icap_start, i_cap_end=args.icap_end,
            reheat_after=args.reheat_after, priors=args.priors, i_price_start=args.iprice_start,
            i_price_end=args.iprice_end, circuits=args.circuits, stop_on_goal=args.stop_on_goal,
        )
        initial = None
        if args.init:
            initial = [tuple(p) for p in json.loads(args.init.read_text())["track"]]
        run(cfg, layout, initial)
    elif args.cmd == "mapelites":
        from .mapelites import MapElitesConfig, elites_from_run, run as run_me

        cfg = MapElitesConfig(
            layout_name=args.layout, workers=args.workers, inflight=args.inflight, max_evals=args.evals,
            max_minutes=args.minutes, hill=args.hill, seed=args.seed, goal_bias=args.goal_bias,
            tournament=args.tournament, max_window=args.max_window, max_walk=args.max_walk, stop_on_goal=args.stop_on_goal,
        )
        seeds = []
        for f in args.init or []:
            data = json.loads(f.read_text())
            entries = data if isinstance(data, list) else [data]
            seeds.extend([tuple(p) for p in e["track"]] for e in entries)
        for run_dir in args.init_run or []:
            seeds.extend(elites_from_run(run_dir))
        run_me(cfg, layout, seeds or None)
    elif args.cmd == "evaluate":
        from .judge import Judge
        from .search import meets_goal

        data = json.loads(args.file.read_text())
        track = [tuple(p) for p in data["track"]]
        judge = Judge(layout)
        try:
            for k in range(args.repeat):
                v = judge.evaluate(track, circuits=data.get("circuits", 1))
                print(json.dumps({"repeat": k, "goal": meets_goal(v), **v.to_dict()}))
        finally:
            judge.close()
    elif args.cmd == "render":
        from .results import render

        data = json.loads(args.file.read_text())
        track = [tuple(p) for p in data["track"]]
        summary = render(layout, track, args.name, zoom=args.zoom, circuits=data.get("circuits", 1))
        print(json.dumps({k: v for k, v in summary.items() if k != "track"}, indent=1))
