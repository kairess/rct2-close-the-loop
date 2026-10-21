"""Audit model of the coaster ratings: every ride type rated on the same ride statistics.

    uv run python scripts/rating_model.py [-v]

Re-implements OpenRCT2's rating modifiers (RideRatings.cpp) on the tables in
data/rating_tables.json (scripts/extract_rating_tables.py), so ride types and vehicles can be
compared before any search: average 40 mph, max 70 mph, 150 s, 9 drops, 6 inversions where the
ride has them, 300 proximity points and so on. Requirements are assumed met and lateral G stays
under the penalty. -v prints what each modifier added to excitement. Values are in hundredths.
"""

import json
import sys
from pathlib import Path

TABLES = json.loads((Path(__file__).resolve().parents[1] / "data" / "rating_tables.json").read_text())


def clamp(v: int) -> int:
    return max(0, min(32767, v))


def mph_to_velocity(mph: float) -> int:
    return int(mph * 262144 / 9)


def turns(s: dict) -> tuple[int, int, int]:
    e = i = n = 0
    h = s["helix"]
    e += (min(h, 9) * 254862) >> 16
    i += (min(h, 11) * 148945) >> 16
    n += (max(0, min(h - 5, 10)) * 0x140000) >> 16
    b = s["banked3"]
    e += (b * 0x3C000) >> 16
    i += (b * 0x14000) >> 16
    n += (b * 0x50000) >> 16
    s4, s3, s2, s1 = s["sloped"]
    e += (min(s4, 4) * 0x78000) >> 16
    e += (min(s3, 6) * 273066) >> 16
    e += (min(s2, 6) * 0x3AAAA) >> 16
    e += (min(s1, 7) * 187245) >> 16
    n += (min(s4, 8) * 0x78000) >> 16
    inv = s["inv"]
    e += (min(inv, 6) * 0x1AAAAA) >> 16
    i += (inv * 0x320000) >> 16
    n += (inv * 0x15AAAA) >> 16
    return e, i, n


def g_forces(s: dict) -> tuple[int, int, int]:
    p, ng, lat = s["posG"], s["negG"], s["latG"]
    e, i, n = (p * 5242) >> 16, (p * 52428) >> 16, (p * 17039) >> 16
    e += (max(-250, min(0, ng)) * -15728) >> 16
    i += ((ng - 100) * -52428) >> 16
    n += ((ng - 100) * -14563) >> 16
    e += (min(150, lat) * 26214) >> 16
    i += lat
    n += (lat * 21845) >> 16
    return e, i, n


def drops(s: dict) -> tuple[int, int, int]:
    d, h = s["drops"], s["dropH"]
    e, i, n = (min(9, d) * 728177) >> 16, (d * 928426) >> 16, (d * 655360) >> 16
    e += ((h * 2) * 16000) >> 16
    i += ((h * 2) * 32000) >> 16
    n += ((h * 2) * 10240) >> 16
    return e, i, n


def sheltered(s: dict) -> tuple[int, int, int]:
    length = s["shLen"]
    e, i, n = (min(length, 1000) * 9175) >> 16, (min(length, 2000) * 0x2666) >> 16, (min(length, 1000) * 0x4000) >> 16
    if s["shBank"]:
        e, n = e + 20, n + 15
    if s["shRot"]:
        e, n = e + 20, n + 15
    e += (min(s["shSec"], 11) * 774516) >> 16
    return e, i, n


SUBRATINGS = {"bonusGForces": g_forces, "bonusTurns": turns, "bonusDrops": drops, "bonusSheltered": sheltered}


def rate(name: str, s: dict, veh: dict) -> tuple[int, int, int, list, int]:
    """(excitement, intensity, nausea, excitement added per modifier, intensity-penalty loss)."""
    E, I, N = TABLES[name]["base"]
    added, seen = [], set()
    for kind, threshold, me, mi, mn in TABLES[name]["mods"]:
        if kind in seen:  # a duplicate alternative descriptor
            continue
        seen.add(kind)
        E0 = E
        if kind == "bonusLength":
            E = clamp(E + ((min(s["len"], threshold) * me) >> 16))
        elif kind == "bonusTrainLength":
            E = clamp(E + (((min(s["cars"], veh["maxcars"]) - 1) * me) >> 16))
        elif kind == "bonusMaxSpeed":
            m = mph_to_velocity(s["max"]) >> 16
            E, I, N = clamp(E + ((m * me) >> 16)), clamp(I + ((m * mi) >> 16)), clamp(N + ((m * mn) >> 16))
        elif kind == "bonusAverageSpeed":
            m = mph_to_velocity(s["avg"]) >> 16
            E, I = clamp(E + ((m * me) >> 16)), clamp(I + ((m * mi) >> 16))
        elif kind == "bonusDuration":
            E = clamp(E + ((min(s["time"], threshold) * me) >> 16))
        elif kind in SUBRATINGS:
            se, si, sn = SUBRATINGS[kind](s)
            E, I, N = clamp(E + ((se * me) >> 16)), clamp(I + ((si * mi) >> 16)), clamp(N + ((sn * mn) >> 16))
        elif kind == "bonusReversedTrains":
            if s.get("rev"):
                E, I, N = clamp(E + ((E * me) >> 7)), clamp(I + ((I * mi) >> 7)), clamp(N + ((N * mn) >> 7))
        elif kind == "bonusProximity":
            E = clamp(E + ((s["prox"] * me) >> 16))
        elif kind == "bonusScenery":
            E = clamp(E + ((s["scen"] * me) >> 16))
        if E != E0:
            added.append((kind, E - E0))
    # Intensity past 10.00, 11.00, 12.00, 13.20 and 14.50 each takes a quarter of the excitement.
    E0 = E
    for limit in (1000, 1100, 1200, 1320, 1450):
        if I >= limit:
            E -= E // 4
    penalty = E0 - E
    E, I, N = clamp(E + ((E * veh["em"]) >> 7)), clamp(I + ((I * veh["im"]) >> 7)), clamp(N + ((N * veh["nm"]) >> 7))
    air = s["air"]
    if veh["lim"]:
        E = clamp(E - (min(max(0, air - 96), 200) // 8))
    else:
        E = clamp(E + (min(air, 200) // 8))
    N = clamp(N + (max(0, air - 96 if veh["lim"] else air) // 16))
    return E, I, N, added, penalty


STATS = dict(avg=40, max=70, time=150, drops=9, dropH=40, inv=6, cars=10, prox=300, scen=235, helix=9, banked3=4,
             sloped=(4, 6, 6, 7), posG=350, negG=-30, latG=150, len=1500, shLen=0, shSec=0, shBank=0, shRot=0, air=0)
# (ride type, vehicle, vehicle: max cars, rating multipliers /128, limited air-time bonus, has inversions)
RIDES = [
    ("TwisterRollerCoaster", "bmfl", dict(maxcars=8, em=10, im=5, nm=10, lim=1), True),
    ("TwisterRollerCoaster", "bmsd", dict(maxcars=9, em=0, im=0, nm=0, lim=1), True),
    ("FlyingRollerCoaster", "bmair", dict(maxcars=8, em=0, im=0, nm=0, lim=1), True),
    ("LayDownRollerCoaster", "vekst", dict(maxcars=6, em=0, im=0, nm=0, lim=1), True),
    ("MultiDimensionRollerCoaster", "arrx", dict(maxcars=7, em=0, im=0, nm=0, lim=1), True),
    ("LSMLaunchedRollerCoaster", "modern_twister", dict(maxcars=6, em=0, im=0, nm=0, lim=0), True),
    ("HybridCoaster", "hybrid", dict(maxcars=6, em=0, im=0, nm=0, lim=0), True),
    ("SingleRailRollerCoaster", "single_rail", dict(maxcars=12, em=0, im=0, nm=0, lim=0), True),
    ("InvertedRollerCoaster", "nemt", dict(maxcars=9, em=0, im=0, nm=0, lim=1), True),
    ("VerticalDropCoaster", "bmvd", dict(maxcars=3, em=0, im=0, nm=0, lim=1), True),
    ("LIMLaunchedRollerCoaster", "premt1", dict(maxcars=7, em=0, im=0, nm=0, lim=1), True),
    ("CorkscrewRollerCoaster", "arrt1", dict(maxcars=9, em=0, im=10, nm=0, lim=1), True),
    ("LoopingRollerCoaster", "scht1", dict(maxcars=8, em=0, im=0, nm=0, lim=0), True),
    ("HyperTwister", "bmrb", dict(maxcars=10, em=15, im=3, nm=0, lim=0), False),
    ("Hypercoaster", "arrt2", dict(maxcars=8, em=15, im=0, nm=0, lim=0), False),
    ("GigaCoaster", "intst", dict(maxcars=9, em=0, im=0, nm=0, lim=0), False),
    ("WoodenRollerCoaster", "mft", dict(maxcars=12, em=4, im=0, nm=2, lim=0), True),
    ("StandUpRollerCoaster", "togst", dict(maxcars=9, em=0, im=0, nm=0, lim=1), True),
    ("CompactInvertedCoaster", "slcfo", dict(maxcars=7, em=8, im=12, nm=10, lim=1), True),
    ("SpiralRollerCoaster", "spdrcr", dict(maxcars=4, em=0, im=0, nm=0, lim=0), False),
]


def main() -> None:
    rows = []
    for name, vehicle, veh, has_inversions in RIDES:
        s = dict(STATS, inv=STATS["inv"] if has_inversions else 0, air=0 if veh["lim"] else 200)
        E, I, N, added, penalty = rate(name, s, veh)
        rows.append((E, name, vehicle, I, N, penalty, added))
    for E, name, vehicle, I, N, penalty, added in sorted(rows, reverse=True):
        print(f"{name:28s} {vehicle:14s} E={E / 100:5.2f} I={I / 100:5.2f} N={N / 100:5.2f} pen={penalty}")
        if "-v" in sys.argv:
            print("   ", added)


if __name__ == "__main__":
    main()
