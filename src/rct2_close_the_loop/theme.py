"""Make the coaster look like it belongs to the park around it.

A census of the park near the area (plugin `census`) gives the scenery, footpaths and terrain
already there. The theme copies them:

- trees: the park's own tree species (full-tile small scenery flagged as trees), in proportion;
- paths: the park's most common footpath surface, queue surface and railings;
- colours and station style: a palette chosen from the dominant terrain (ice and snow get white
  track with light blue and dark brown, red trains and the snow station; sand gets warm colours).

Colours and station style change nothing in the ratings; the trees count the same as any other
small scenery for the scenery and proximity bonuses.
"""

from __future__ import annotations

from pathlib import Path

from .game import Game, wait_ready

FULL_TILE = 1 << 0
IS_TREE = 1 << 28

# RCT2 colour indices: 0 black, 1 grey, 2 white, 7 light blue, 8 icy blue, 18 yellow, 19 dark yellow,
# 21 dark orange, 22 light brown, 24 dark brown, 27 saturated red, 28 bright red.
PALETTES = {
    "alpine": {"track": [2, 7, 24], "vehicle": [28, 2, 0], "station": "rct2.station.snow"},
    "desert": {"track": [22, 19, 24], "vehicle": [21, 2, 0], "station": "rct2.station.canvas_tent"},
    "default": {"track": [27, 18, 1], "vehicle": [2, 27, 0], "station": "rct2.station.plain"},
}
TERRAIN_PALETTE = {"ice": "alpine", "snow": "alpine", "sand": "desert", "sand_red": "desert",
                   "sand_brown": "desert", "martian": "desert"}


def census(park: Path, rect: tuple[int, int, int, int], sandbox: bool = False) -> dict:
    with Game(park=park) as g:
        wait_ready(g)
        g.call("setup", {"sandbox": sandbox})
        return g.call("census", {"rect": list(rect)}, timeout=120)


def _top(counts: dict, keep=lambda v: True) -> list[str]:
    return [k for k, v in sorted(counts.items(), key=lambda kv: -kv[1]["n"]) if keep(v)]


def build(c: dict, fallback_tree: str | None) -> dict:
    terrain = _top(c["terrain"])
    palette_name = TERRAIN_PALETTE.get(terrain[0].rsplit(".", 1)[-1], "default") if terrain else "default"
    palette = dict(PALETTES[palette_name])
    if palette["station"] not in c.get("stations", []):
        palette["station"] = None
    trees = _top(c["scenery"], lambda v: (v.get("flags", 0) & FULL_TILE) and (v.get("flags", 0) & IS_TREE))[:3]
    # Plant species in roughly the proportions the park has them (the plugin cycles through the list).
    weighted: list[str] = []
    if trees:
        total = sum(c["scenery"][t]["n"] for t in trees)
        for t in trees:
            weighted += [t] * max(1, round(6 * c["scenery"][t]["n"] / total))
    normal = _top(c["paths"], lambda v: not v.get("queue"))
    queue = _top(c["paths"], lambda v: v.get("queue"))
    railings = _top(c["railings"])
    paths = None
    if normal and queue and railings:
        paths = {"surface": normal[0], "queue": queue[0], "railings": railings[0]}
    return {
        "palette": palette_name,
        "terrain": terrain[0] if terrain else None,
        "track": palette["track"],
        "vehicle": palette["vehicle"],
        "station": palette["station"],
        "trees": weighted or ([fallback_tree] if fallback_tree else []),
        "paths": paths,
    }
