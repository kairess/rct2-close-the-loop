"""The showcase park without its coaster: remove the ride and the footpaths inside the coaster zone.

    uv run python scripts/surroundings.py results/showcase/lakeside

Used to render the search frames in the finished scene (each frame builds its own track, paths and trees).
"""

import json
import shutil
import sys
from pathlib import Path

from rct2_close_the_loop.game import RUNTIME, Game, wait_ready


def main() -> None:
    out = Path(sys.argv[1])
    scene = json.loads((out / "scene.json").read_text())
    x0, y0, x1, y1 = scene["zone"]
    with Game(park=out / "showcase.park") as g:
        wait_ready(g)
        g.call("setup", {"sandbox": True})
        print(g.call("actions", {"list": [["ridedemolish", {"ride": 0, "modifyType": 0}]]}))
        scan = g.call("scan", {"rect": [x0, y0, x1, y1]}, timeout=120)
        acts = []
        for tx, ty, base, clear, slope, water, owned, rights, edge, others in scan["tiles"]:
            for kind, b, c, ride in others:
                if kind == "footpath":
                    acts.append(["footpathremove", {"x": tx * 32, "y": ty * 32, "z": b}])
        res = g.call("actions", {"list": acts}, timeout=300)
        print(f"removed {sum(r['ok'] for r in res)} of {len(acts)} zone footpath tiles")
        g.call("save", {"filename": "surroundings"})
    shutil.copyfile(RUNTIME / "save" / "surroundings.park", out / "surroundings.park")
    print("->", out / "surroundings.park")


if __name__ == "__main__":
    main()
