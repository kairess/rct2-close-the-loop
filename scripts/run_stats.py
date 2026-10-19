"""Trajectory and best design of design runs (any goal).

    uv run python scripts/run_stats.py runs/<dir> [...] [--icap 10.35]
"""

import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("runs", nargs="+", type=Path)
ap.add_argument("--icap", type=float, default=10.35)
args = ap.parse_args()
for d in args.runs:
    rows = [json.loads(line) for line in open(d / "progress.jsonl")]
    traj = " ".join(f"{r['minutes']:.0f}m:{r['best'].split('/')[0]}" for r in rows[:: max(1, len(rows) // 6)])
    best, n = None, 0
    for line in open(d / "evals.jsonl"):
        r = json.loads(line)
        v = r["verdict"]
        n += 1
        if v["stage"] == "rated" and v["I"] < args.icap and (best is None or v["E"] > best["verdict"]["E"]):
            best = r
    v = best["verdict"]
    st = v["stats"]
    print(f"{d.name}: evals {n}  best E{v['E']} I{v['I']} N{v['N']}  time {st.get('rideTime')}s  len {st.get('rideLength')}  "
          f"avg {st.get('averageSpeed')} max {st.get('maxSpeed')}  drops {st.get('numDrops')}  air {st.get('totalAirTime')}  "
          f"cars {st.get('cars')}  laps {best.get('circuits', 1)}  trees {v.get('decor')}")
    print(f"   {traj}")
