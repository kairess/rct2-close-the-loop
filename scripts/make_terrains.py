"""Generate and bake the S2 terrain conditions into data/terrains and data/parks.

    uv run python scripts/make_terrains.py
"""

from rct2_close_the_loop.terrain import bake, generate

AREA24 = (100, 100, 124, 124)

CONDITIONS = [
    # name, seed, area, station tile, relief steps (16 z each), tree fraction of interior tiles
    ("hills24", 11, AREA24, (104, 102), 6, 0.0),
    ("trees24", 12, AREA24, (104, 102), 0, 0.2),
    ("hilltrees24", 13, AREA24, (104, 102), 6, 0.2),
    ("small16", 14, (102, 100, 118, 116), (106, 102), 0, 0.0),
    ("center24", 15, AREA24, (108, 111), 0, 0.0),
]

for name, seed, area, station, relief, trees in CONDITIONS:
    spec = generate(name, seed, area, station, relief_steps=relief, tree_frac=trees)
    path = bake(spec)
    print(f"{name}: raised {len(spec['heights'])} tiles, {len(spec['trees'])} trees -> {path}")
