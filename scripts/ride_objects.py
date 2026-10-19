"""Rating multipliers and train specs of every installed coaster vehicle object.

    uv run python scripts/ride_objects.py

Writes data/ride_objects.json: per object its ride types, excitement/intensity/nausea
multipliers (rating += rating * m / 128), max height, car limits, car mass, seats.
"""

import json
from pathlib import Path

from rct2_close_the_loop.game import Game, wait_ready

ROOT = Path(__file__).resolve().parents[1]
NAMES = json.loads((ROOT / "data" / "track_groups_from_bridge.json").read_text())["rideTypeNames"]


def main() -> None:
    with Game() as g:
        wait_ready(g)
        objs = g.call("ride_objects", {}, timeout=300)
    for o in objs:
        o["rideTypeNames"] = [NAMES[t] if t < len(NAMES) else t for t in o["rideType"] if t != 255]
    coasters = [o for o in objs if any(str(n).endswith("_rc") for n in o["rideTypeNames"])]
    out = ROOT / "data" / "ride_objects.json"
    out.write_text(json.dumps(objs, indent=1))
    print(f"{len(objs)} ride objects, {len(coasters)} coaster vehicles -> {out}")
    for o in sorted(coasters, key=lambda o: -o["excitement"])[:40]:
        print(f"{o['identifier']:32s} {','.join(map(str, o['rideTypeNames']))[:34]:34s} E{o['excitement']:>4} I{o['intensity']:>4} "
              f"N{o['nausea']:>4} cars {o['minCars']}-{o['maxCars']} mass {o['carMass']} seats {o['numSeats']} h {o['maxHeight']}")


if __name__ == "__main__":
    main()
