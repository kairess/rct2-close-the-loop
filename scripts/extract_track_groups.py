"""Extract enabled track groups per coaster ride type from OpenRCT2 C++ sources.

    uv run python scripts/extract_track_groups.py <OpenRCT2 source root>

Writes data/track_groups_rtd.json: {RideTypeDescriptorName: [group ids]}, using
the numeric order of `enum class TrackGroup` (ride/ted/TrackGroup.h). Only
`enabledTrackGroups` are taken; `extraTrackGroups` need the
"enable all drawable track pieces" cheat and are left out on purpose.
"""

import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "src" / "openrct2"
enum_src = (root / "ride" / "ted" / "TrackGroup.h").read_text()
body = enum_src[enum_src.index("enum class TrackGroup"):]
body = body[body.index("{") + 1 : body.index("};")]
names = [re.sub(r"[=,].*", "", line).strip() for line in body.splitlines()]
names = [n for n in names if n and not n.startswith("//")]
group_id = {n: i for i, n in enumerate(names)}

out = {}
for header in sorted((root / "ride" / "rtd" / "coaster").glob("*.h")):
    text = header.read_text()
    m = re.search(r"\.enabledTrackGroups\s*=\s*\{([^}]*)\}", text)
    if not m:
        continue
    groups = re.findall(r"TrackGroup::(\w+)", m.group(1))
    out[header.stem] = sorted(group_id[g] for g in groups)

dest = Path(__file__).resolve().parents[1] / "data" / "track_groups_rtd.json"
dest.write_text(json.dumps(out, indent=1))
print(f"{len(out)} ride types, {len(group_id)} track groups -> {dest}")
