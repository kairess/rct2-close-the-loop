"""Experiment layouts: which coaster, where its station sits, and the area it must stay in."""

from __future__ import annotations

from itertools import product

from .track import Layout, trace

GROUND_Z = 112  # flat fixture park: land at height 14 (x8 world units)

# 24x24 tile area; station runs +x (direction 2) along the area's low-y edge.
WOODEN_24 = Layout(
    ride_type_name="wooden_rc",
    ride_type=52,
    ride_object="rct2.ride.ptct1",
    station_tile=(104, 102),
    station_dir=2,
    station_len=4,
    ground_z=GROUND_Z,
    area=(100, 100, 124, 124),
    max_height=320,
)

# Same area and station, Giga Coaster (base ratings E3.85/I0.40/N0.35 vs wooden E3.20/I2.60/N2.00).
# min_separation 24: the game checks clearance per quarter tile, and track touching its own
# track (zero gap) or passing 2-10 height units above it earns proximity points.
GIGA_24 = Layout(
    ride_type_name="giga_rc",
    ride_type=68,
    ride_object="rct2.ride.intst",
    station_tile=(104, 102),
    station_dir=2,
    station_len=4,
    ground_z=GROUND_Z,
    area=(100, 100, 124, 124),
    max_height=680,
    min_separation=24,
)

# Giga with tunnels allowed: track may dip below the land (z 112) down to z 32.
# Only underground track counts as sheltered in the ratings (Vehicle.cpp shelter check).
GIGA_24U = Layout(
    ride_type_name="giga_rc",
    ride_type=68,
    ride_object="rct2.ride.intst",
    station_tile=(104, 102),
    station_dir=2,
    station_len=4,
    ground_z=GROUND_Z,
    area=(100, 100, 124, 124),
    max_height=680,
    min_z=32,
)

# Twister with Floorless Twister trains (multipliers E+10/I+5/N+10 of 128): vertical loops,
# corkscrews and rolls without cheats, and any inversion waives the drop/negative-G requirements.
TWISTER_24 = Layout(
    ride_type_name="TwisterRollerCoaster",
    ride_type=51,
    ride_object="rct2.ride.bmfl",
    station_tile=(104, 102),
    station_dir=2,
    station_len=4,
    ground_z=GROUND_Z,
    area=(100, 100, 124, 124),
    max_height=320,
    min_separation=24,
)

LAYOUTS = {"wooden_24": WOODEN_24, "giga_24": GIGA_24, "giga_24u": GIGA_24U, "twister_24": TWISTER_24}

LEFT3 = 42
RIGHT3 = 43
FLAT = 0
FLAT_TO_UP25, UP25, UP25_TO_FLAT = 6, 4, 9
FLAT_TO_DOWN25, DOWN25, DOWN25_TO_FLAT = 12, 10, 15


def _hill(up: bool, h: int) -> list[tuple[int, bool]]:
    if up:
        return [(FLAT_TO_UP25, True)] + [(UP25, True)] * h + [(UP25_TO_FLAT, True)]
    return [(FLAT_TO_DOWN25, False)] + [(DOWN25, False)] * h + [(DOWN25_TO_FLAT, False)]


def oval(layout: Layout, hill: int = 0, turn: int = LEFT3, max_side: int = 30) -> list[tuple[int, bool]]:
    """Largest closed rectangle (four 3-tile turns) that passes the space pre-filter.

    With hill > 0 the first side climbs on a chain lift (hill UP25 pieces) and the
    third side drops back down, which is the simplest track a coaster train can run.
    """
    best: list[tuple[int, bool]] | None = None
    best_len = -1
    n_hill = hill + 2 if hill else 0
    for a, b in product(range(n_hill, max_side), range(max_side)):
        for c in range(n_hill, max_side):
            side_a = (_hill(True, hill) if hill else []) + [(FLAT, False)] * (a - n_hill)
            side_c = [(FLAT, False)] * (c - n_hill) + (_hill(False, hill) if hill else [])
            pieces = (
                side_a + [(turn, False)]
                + [(FLAT, False)] * b + [(turn, False)]
                + side_c + [(turn, False)]
                + [(FLAT, False)] * b + [(turn, False)]
            )
            tr = trace(layout, pieces)
            if tr.closed and not tr.problems and len(pieces) > best_len:
                best, best_len = pieces, len(pieces)
    if best is None:
        raise ValueError("no closed oval fits the layout")
    return best
