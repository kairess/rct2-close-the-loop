"""Ratings of the track designs that ship with RCT2 (the Tracks folder), for comparison.

    uv run python scripts/builtin_designs.py

TD6 files are RCT2 run-length encoded (minus a 4-byte checksum). The header holds
the ride type (0x00), excitement/intensity/nausea x10 (0x5B-0x5D), the vehicle
object name (0x74) and the space required in tiles (0x80-0x81), as read by
OpenRCT2's T6Importer. Ratings are the ones RCT2 stored with each design.
"""

import json
from pathlib import Path

from rct2_close_the_loop.game import rct2_path

ROOT = Path(__file__).resolve().parents[1]
NAMES = json.loads((ROOT / "data" / "track_groups_from_bridge.json").read_text())["rideTypeNames"]


def rle_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        c = data[i]
        i += 1
        if c & 0x80:
            out += bytes([data[i]]) * (257 - c)
            i += 1
        else:
            out += data[i:i + c + 1]
            i += c + 1
    return bytes(out)


def read_td6(path: Path) -> dict:
    raw = rle_decode(path.read_bytes()[:-4])
    ride_type = raw[0x00]
    return {
        "file": path.name,
        "ride_type": NAMES[ride_type] if ride_type < len(NAMES) else ride_type,
        "vehicle": raw[0x74:0x7C].decode("latin-1").strip(),
        "E": raw[0x5B] / 10,
        "I": raw[0x5C] / 10,
        "N": raw[0x5D] / 10,
        "space": [raw[0x80], raw[0x81]],
    }


def main() -> None:
    designs = []
    for f in sorted((rct2_path() / "Tracks").glob("*.TD6")):
        try:
            designs.append(read_td6(f))
        except (IndexError, UnicodeDecodeError):
            continue
    coasters = [d for d in designs if d["ride_type"] and str(d["ride_type"]).endswith("_rc")]
    goal = [d for d in coasters if d["E"] >= 7.68 and d["I"] < 7.68 and d["N"] < 5.12]
    small_goal = [d for d in goal if max(d["space"]) <= 24]
    print(f"{len(designs)} designs, {len(coasters)} roller coasters; meet our goal: {len(goal)}; "
          f"of those within 24x24: {len(small_goal)}")
    by_type = {}
    for d in coasters:
        by_type.setdefault(d["ride_type"], []).append(d)
    for t, ds in sorted(by_type.items(), key=lambda kv: -max(x["E"] for x in kv[1])):
        best = max(ds, key=lambda x: x["E"])
        print(f"  {t:28s} n={len(ds):2d} max E {best['E']:.2f} (I {best['I']:.2f}, N {best['N']:.2f}, {best['space'][0]}x{best['space'][1]})")
    out = ROOT / "results" / "builtin_designs.json"
    out.write_text(json.dumps({"designs": designs, "coasters": len(coasters), "meet_goal": len(goal),
                               "meet_goal_within_24": len(small_goal)}, indent=1))
    print("->", out)


if __name__ == "__main__":
    main()
