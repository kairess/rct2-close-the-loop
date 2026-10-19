"""Measure the clearance of every element of every allowed track piece, per ride type.

    uv run python scripts/measure_clearance.py

Each piece is placed alone, high above flat land, and the track elements it creates are read
back from the map. Writes data/track_clearance.json: {ride_type_name: {type: [[dx, dy, base_dz,
clearance_dz], ...]}} with offsets for direction 0. Underground track needs the land surface at or
above an element's clearance (ConstructionClearance.cpp), which a fixed margin gets wrong for slopes.
"""

import json
from pathlib import Path

from rct2_close_the_loop.game import Game, wait_ready
from rct2_close_the_loop.layouts import BASES
from rct2_close_the_loop.track import piece_set

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    out_path = ROOT / "data" / "track_clearance.json"
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    with Game(park=ROOT / "data" / "bench" / "parks" / "flat24.park") as g:
        wait_ready(g)
        g.call("setup", {"sandbox": True})
        for key in ("twister", "hypertwister", "hypercoaster", "giga"):
            base = BASES[key]
            obj = g.call("load_object", {"identifier": base.ride_object})
            types = sorted(piece_set(base.ride_type_name) | {1, 2, 3})
            r = g.call("measure_clearance", {"rideType": base.ride_type, "rideObject": obj["index"], "types": types,
                                             "x": 112, "y": 112, "z": 400}, timeout=600)
            # Pieces that start half a height step up only sit at z = 8 mod 16.
            retry = [int(t) for t, v in r.items() if not isinstance(v, list)]
            if retry:
                r2 = g.call("measure_clearance", {"rideType": base.ride_type, "rideObject": obj["index"], "types": retry,
                                                  "x": 112, "y": 112, "z": 408}, timeout=600)
                for t, v in r2.items():
                    if isinstance(v, list):
                        r[t] = v  # offsets are relative to the placement height
            bad = {t: v for t, v in r.items() if not isinstance(v, list) or not v}
            out[base.ride_type_name] = {t: v for t, v in r.items() if isinstance(v, list) and v}
            print(f"{key}: {len(out[base.ride_type_name])} pieces measured, {len(bad)} failed {list(bad.items())[:3]}")
    out_path.write_text(json.dumps(out))
    print("->", out_path)


if __name__ == "__main__":
    main()
