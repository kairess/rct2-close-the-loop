"""Dress a designed coaster up as a park scene: promenade, entrance, stalls, gardens, colours.

    uv run python scripts/showcase.py results/extreme/best40/best40.park results/showcase/lakeside

The coaster zone (the design's area) keeps its own exit path, queue and trees. Around it:
- a promenade ring one tile outside the zone, joining the coaster's exit path where it reaches the edge;
- an avenue south to a park entrance, with a fountain plaza;
- lamps, benches and litter bins along the promenade, stalls facing it;
- a garden band of mixed trees, bushes and flowers;
- the coaster recoloured (red track, white supports, white trains with red trim) with a classical station;
- the park's guest spawns moved to a short road outside the new entrance (the base park's spawn
  led to an entrance with no paths, so guests never got in).
Writes <out>/showcase.park, <out>/scene.json and <out>/surroundings.park (the same scene without the
coaster and the footpaths inside its zone, for rendering the search frames in it: each frame builds
its own track, paths and trees), and prints the coaster's ratings after dressing.
"""

import json
import random
import shutil
import sys
from pathlib import Path

from rct2_close_the_loop.game import RUNTIME, Game, wait_ready

ZONE = (100, 100, 140, 140)  # x0, y0, x1, y1 of the coaster zone (flat40)
GROUND = 112
BAND = 9  # garden band width outside the promenade
PATH = "rct2.footpath_surface.tarmac"
QUEUE = "rct2.footpath_surface.queue_blue"
RAILINGS = "rct2.footpath_railings.wood"
LAMP, BENCH, BIN = "rct2.footpath_item.lamp2", "rct2.footpath_item.benchpl", "rct2.footpath_item.litter1"
ENTRANCE = "rct2.park_entrance.pkent1"
TREES = ["rct2.scenery_small.tco", "rct2.scenery_small.tbp", "rct2.scenery_small.tce", "rct2.scenery_small.tsp",
         "rct2.scenery_small.tas", "rct2.scenery_small.tcrp"]
BUSHES = ["rct2.scenery_small.tsh0", "rct2.scenery_small.tsh2", "rct2.scenery_small.tsh3", "rct2.scenery_small.tsh5",
          "rct2.scenery_small.tsh1", "rct2.scenery_small.tsh4"]
FLOWERS = ["rct2.scenery_small.tjf"]
FOUNTAINS = ["rct2.scenery_small.tdf", "rct2.scenery_small.ttf"]
STATUES = ["rct2.scenery_small.tstd", "rct2.scenery_small.thrs"]
# Stalls: (ride object, ride type).
STALLS = [("rct2.ride.drnks", 30), ("rct2.ride.burgb", 28), ("rct2.ride.icecr2", 28), ("rct2.ride.souvs", 32),
          ("rct2.ride.infok", 35), ("rct2.ride.balln", 32), ("rct2.ride.popcs", 28), ("rct2.ride.tlt1", 36)]
COLOURS = {"track": [28, 2, 2], "vehicle": [2, 28, 0]}  # bright red / white / white, white trains with red trim
STATION = "rct2.station.classical"


def ring_tiles():
    x0, y0, x1, y1 = ZONE
    out = []
    for x in range(x0 - 1, x1 + 1):
        out += [(x, y0 - 1), (x, y1)]
    for y in range(y0, y1):
        out += [(x0 - 1, y), (x1, y)]
    return sorted(set(out))


def scene(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    x0, y0, x1, y1 = ZONE
    cx = (x0 + x1) // 2
    with Game(park=src) as g:
        wait_ready(g)
        g.call("setup", {"sandbox": True})
        idx = {}
        for ident in [PATH, QUEUE, RAILINGS, LAMP, BENCH, BIN, ENTRANCE, STATION] + TREES + BUSHES + FLOWERS \
                + FOUNTAINS + STATUES + [s[0] for s in STALLS]:
            idx[ident] = g.call("load_object", {"identifier": ident})["index"]

        def path(x, y, z=GROUND, queue=False):
            return ["footpathplace", {"x": x * 32, "y": y * 32, "z": z, "direction": 255,
                                      "object": idx[QUEUE if queue else PATH], "railingsObject": idx[RAILINGS],
                                      "slopeType": 0, "slopeDirection": 0, "constructFlags": 1 if queue else 0}]

        def scenery(x, y, ident, quadrant=0, direction=None):
            return ["smallsceneryplace", {"x": x * 32, "y": y * 32, "z": 0,
                                          "direction": rng.randrange(4) if direction is None else direction,
                                          "object": idx[ident], "quadrant": quadrant,
                                          "primaryColour": rng.choice([17, 28, 30, 5]), "secondaryColour": 2,
                                          "tertiaryColour": 0}]

        ring = ring_tiles()
        avenue = [(cx, y) for y in range(y1 + 1, y1 + BAND + 2)]
        plaza = [(x, y) for x in range(cx - 2, cx + 3) for y in range(y1 + 3, y1 + 6)]
        path_tiles = set(ring) | set(avenue) | set(plaza)
        acts = [path(x, y) for x, y in sorted(path_tiles)]
        # Park entrance at the south end of the avenue, facing it.
        ent_y = y1 + BAND + 2
        acts.append(["parkentranceplace", {"x": cx * 32, "y": ent_y * 32, "z": GROUND, "direction": 3,
                                           "footpathSurfaceObject": idx[PATH], "entranceObject": idx[ENTRANCE],
                                           "footpathTypeIsLegacy": False}])
        # Path furniture along the promenade and the avenue.
        for k, (x, y) in enumerate(ring + avenue):
            item = LAMP if k % 3 == 0 else BENCH if k % 3 == 1 else (BIN if k % 6 == 2 else None)
            if item:
                acts.append(["footpathadditionplace", {"x": x * 32, "y": y * 32, "z": GROUND, "object": idx[item]}])
        # Stalls on the outer side of the promenade, a few tiles apart, facing it.
        stall_spots = []
        for i, (obj, rtype) in enumerate(STALLS):
            side = i % 4
            t = 6 + (i // 4) * 14
            if side == 0:
                stall_spots.append((x0 + t, y0 - 2, 1, obj, rtype))
            elif side == 1:
                stall_spots.append((x1 + 1, y0 + t, 2, obj, rtype))
            elif side == 2:
                stall_spots.append((x0 + t, y1 + 1, 3, obj, rtype))
            else:
                stall_spots.append((x0 - 2, y0 + t, 0, obj, rtype))
        stall_spots = [(x + (3 if (x, y) in path_tiles else 0), y, d, o, t) for x, y, d, o, t in stall_spots]
        taken = set(path_tiles) | {(x, y) for x, y, *_ in stall_spots}
        for dx in range(-1, 2):
            taken.add((cx + dx, ent_y))
        # Fountains and statues around the plaza.
        for x, y in [(cx - 3, y1 + 3), (cx + 3, y1 + 3), (cx - 3, y1 + 5), (cx + 3, y1 + 5)]:
            acts.append(scenery(x, y, FOUNTAINS[(x + y) % len(FOUNTAINS)], direction=0))
            taken.add((x, y))
        for x, y in [(cx - 1, y1 + 7), (cx + 1, y1 + 7)]:
            acts.append(scenery(x, y, STATUES[x % len(STATUES)], direction=3))
            taken.add((x, y))
        # Garden band: flowers by the promenade, bushes, then trees further out.
        for x in range(x0 - BAND - 1, x1 + BAND + 1):
            for y in range(y0 - BAND - 1, y1 + BAND + 1):
                if x0 - 1 <= x <= x1 and y0 - 1 <= y <= y1 or (x, y) in taken:
                    continue
                d = max(x0 - 1 - x, x - x1, y0 - 1 - y, y - y1)  # tiles out from the promenade
                r = rng.random()
                if d == 1:
                    if r < 0.6:
                        for q in range(4):
                            acts.append(scenery(x, y, FLOWERS[0], quadrant=q))
                elif d <= 3:
                    if r < 0.45:
                        acts.append(scenery(x, y, rng.choice(BUSHES)))
                    elif r < 0.6:
                        acts.append(scenery(x, y, rng.choice(TREES)))
                elif r < 0.55:
                    acts.append(scenery(x, y, rng.choice(TREES)))
        # Inside the zone: lamps on the coaster's own paths, flowers and bushes beside them, trees on open grass.
        scan = g.call("scan", {"rect": [x0, y0, x1, y1]}, timeout=120)
        zone_paths, busy = [], set()
        for tx, ty, base, clear, slope, water, owned, rights, edge, others in scan["tiles"]:
            kinds = {o[0] for o in others}
            if "footpath" in kinds:
                zone_paths.append((tx, ty, [o[1] for o in others if o[0] == "footpath"][0]))
            if others or water or slope:
                busy.add((tx, ty))
        for k, (tx, ty, z) in enumerate(zone_paths):
            if k % 4 == 0:
                acts.append(["footpathadditionplace", {"x": tx * 32, "y": ty * 32, "z": z, "object": idx[LAMP]}])
        near_path = {(tx + dx, ty + dy) for tx, ty, _ in zone_paths for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        for x in range(x0, x1):
            for y in range(y0, y1):
                if (x, y) in busy:
                    continue
                r = rng.random()
                if (x, y) in near_path:
                    if r < 0.35:
                        acts.append(scenery(x, y, FLOWERS[0]))
                    elif r < 0.6:
                        acts.append(scenery(x, y, rng.choice(BUSHES)))
                elif r < 0.3:
                    acts.append(scenery(x, y, rng.choice(TREES)))
                elif r < 0.45:
                    acts.append(scenery(x, y, rng.choice(BUSHES)))
        # A road outside the entrance (unowned land, as peep spawns require) where guests arrive.
        road = [(cx, ent_y + k) for k in (1, 2, 3)]
        acts.append(["landsetrights", {"x1": (cx - 1) * 32, "y1": road[0][1] * 32, "x2": (cx + 1) * 32,
                                       "y2": road[-1][1] * 32, "setting": 0, "ownership": 0}])
        acts += [path(x, y) for x, y in road]
        res = g.call("actions", {"list": acts}, timeout=900)
        failed = [(a[0], r["error"]) for a, r in zip(acts, res) if not r["ok"]]
        print(f"scene: {len(acts)} actions, {len(failed)} refused; e.g. {failed[:4]}")
        # Guest spawns: find the old ones (where a few test guests appear), toggle them off by placing
        # a spawn on the same tile, then add ours at the end of the road, facing the entrance.
        g.call("spawn_guests", {"n": 6}, timeout=60)
        old = {(p_[0], p_[1], p_[2]) for p_ in g.call("guests_info", {"limit": 50})["sample"]}
        spawn_acts = [["peepspawnplace", {"x": x * 32, "y": y * 32, "z": z, "direction": 0}] for x, y, z in old]
        spawn_acts.append(["peepspawnplace", {"x": road[-1][0] * 32, "y": road[-1][1] * 32, "z": GROUND, "direction": 3}])
        spawn_acts.append(["cheatset", {"type": 21, "param1": 0, "param2": 0}])  # remove the test guests
        res = g.call("actions", {"list": spawn_acts})
        print("spawns: old", sorted(old), [r["ok"] or r["error"] for r in res])
        # Stalls: create each, place a 1x1 shop, open it.
        for x, y, d, obj, rtype in stall_spots:
            r = g.call("actions", {"list": [["ridecreate", {"rideType": rtype, "rideObject": idx[obj], "entranceObject": 0,
                                                           "colour1": 0, "colour2": 0, "inspectionInterval": 0}]]})
            ride_id = None
            info = g.call("ride_info", {})
            ride_id = max(ri["id"] for ri in info)
            r = g.call("actions", {"list": [["trackplace", {"x": x * 32, "y": y * 32, "z": GROUND, "direction": d,
                                                           "ride": ride_id, "trackType": 262, "rideType": rtype,
                                                           "brakeSpeed": 0, "colour": 0, "seatRotation": 4,
                                                           "trackPlaceFlags": 0, "isFromTrackDesign": False}],
                                            ["ridesetstatus", {"ride": ride_id, "status": 1}]]})
            print(f"stall {obj} at {(x, y)} dir {d}: {[x_['ok'] or x_['error'] for x_ in r]}")
        # The coaster: colours and station style.
        look = [["ridesetappearance", {"ride": 0, "type": k, "value": v, "index": 0}]
                for k, v in enumerate(COLOURS["track"])]
        look += [["ridesetappearance", {"ride": 0, "type": 3 + k, "value": v, "index": 0}]
                 for k, v in enumerate(COLOURS["vehicle"])]
        look.append(["ridesetappearance", {"ride": 0, "type": 7, "value": idx[STATION], "index": 0}])
        res = g.call("actions", {"list": look})
        print("coaster look:", [r["ok"] or r["error"] for r in res])
        # Let the ratings recalculate with the new surroundings before reading them.
        g.call("run_ticks", {"ticks": 4000}, timeout=300)
        g.call("save", {"filename": "showcase"})
        print("rides:", [(r["name"], r["excitement"], r["intensity"], r["status"]) for r in g.call("ride_info", {})])
    shutil.copyfile(RUNTIME / "save" / "showcase.park", out / "showcase.park")
    (out / "scene.json").write_text(json.dumps({"zone": ZONE, "entrance": [cx, ent_y], "stalls": [s[:2] for s in stall_spots]}))
    print("->", out / "showcase.park")


def surroundings(out: Path) -> None:
    """The showcase park without its coaster: the ride and the footpaths inside the coaster zone removed."""
    x0, y0, x1, y1 = json.loads((out / "scene.json").read_text())["zone"]
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
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    scene(src, out)
    surroundings(out)
