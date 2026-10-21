"""Extract every coaster's rating table from OpenRCT2 C++ sources.

    uv run python scripts/extract_rating_tables.py <OpenRCT2 source root>

Writes data/rating_tables.json: {RideTypeDescriptorName: {base: [E, I, N], unrel, shelter, relax,
mods: [[modifier, threshold, excitement, intensity, nausea], ...]}}, read from the `.RatingsData`
block of each header in src/openrct2/ride/rtd/coaster/. Ratings are in hundredths
(RideRating::make(3, 85) -> 385).
"""

import json
import re
import sys
from pathlib import Path

DEST = Path(__file__).resolve().parents[1] / "data" / "rating_tables.json"
RATING = r"RideRating::make\([^)]*\)"
ARG = r"((?:RideRating::make\([^)]*\)|MakeFixed16_2dp\([^)]*\)|[^,}])+)"


def value(s: str) -> int:
    s = s.strip()
    m = re.match(r"(?:RideRating::make|MakeFixed16_2dp)\((\d+),\s*(\d+)\)", s)
    if m:
        return int(m.group(1)) * 100 + int(m.group(2))
    return int(s, 0)


def main() -> None:
    headers = Path(sys.argv[1]) / "src" / "openrct2" / "ride" / "rtd" / "coaster"
    out = {}
    for header in sorted(headers.glob("*.h")):
        text = header.read_text()
        i = text.find(".RatingsData")
        if i < 0:
            continue
        block = text[i:]
        base = re.search(rf"\{{\s*({RATING}),\s*({RATING}),\s*({RATING})\s*\}}", block)
        rest = re.match(r"\s*,\s*(\d+)\s*,\s*([\w-]+)\s*,\s*(true|false)", block[base.end():])
        mods = re.findall(rf"\{{\s*RatingsModifierType::(\w+),\s*{ARG},\s*{ARG},\s*{ARG},\s*{ARG}\}}", block)
        out[header.stem] = {
            "base": [value(base.group(k)) for k in (1, 2, 3)],
            "unrel": int(rest.group(1)),
            "shelter": rest.group(2),
            "relax": rest.group(3) == "true",
            "mods": [(m[0], *(value(x) for x in m[1:])) for m in mods],
        }
    DEST.write_text(json.dumps(out, indent=0))
    print(f"{len(out)} coaster ride types -> {DEST}")


if __name__ == "__main__":
    main()
