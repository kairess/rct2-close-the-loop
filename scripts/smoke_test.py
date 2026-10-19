"""Smoke test: build a closed-circuit coaster headless and let the game rate it.

Checks the whole loop the design doc relies on:
launch headless -> lay a closed circuit -> test run -> read ratings from the game.

    uv run python scripts/smoke_test.py

Notes from bring-up (OpenRCT2 v0.5.6, bridge v1.8.0):
- SIMULATING runs the train but never records stats, so ratings stay undefined.
  TESTING does, and it needs an entrance and exit on the station.
- Game speed 8 (hyper) needs `debugging_tools = true` in OpenRCT2's config.ini.
  It runs ~1600 ticks/s vs ~40 at speed 1; this coaster rates in ~2000 ticks.
"""

import time

from pyrct2._generated.enums import Direction, RideStatus, TrackElemType
from pyrct2._generated.objects import RideObjects
from pyrct2.client import RCT2
from pyrct2.scenarios import Scenario
from pyrct2.world._tile import Tile

HYPER_SPEED = 8
TICK_CHUNK = 250
MAX_TICKS = 20_000
LIFECYCLE_TESTED = 1 << 1


def build_hill_loop(game: RCT2):
    """Closed rectangular circuit with one chain-lift hill (R3 turns, [3, 5, 6, 5])."""
    coaster = game.rides.create_tracked_ride(
        obj=RideObjects.rollercoaster.LADYBIRD_TRAINS,
        station_origin=Tile(100, 100),
        station_length=3,
        direction=Direction.EAST,
    )

    coaster.place(TrackElemType.FLAT_TO_UP25, chain_lift=True)
    coaster.place(TrackElemType.UP25, chain_lift=True)
    coaster.place(TrackElemType.UP25_TO_FLAT)
    coaster.place(TrackElemType.RIGHT_QUARTER_TURN3_TILES)

    for _ in range(5):
        coaster.place(TrackElemType.FLAT)
    coaster.place(TrackElemType.RIGHT_QUARTER_TURN3_TILES)

    coaster.place(TrackElemType.FLAT_TO_DOWN25)
    coaster.place(TrackElemType.DOWN25)
    coaster.place(TrackElemType.DOWN25_TO_FLAT)
    for _ in range(3):
        coaster.place(TrackElemType.FLAT)
    coaster.place(TrackElemType.RIGHT_QUARTER_TURN3_TILES)

    for _ in range(5):
        coaster.place(TrackElemType.FLAT)
    coaster.place(TrackElemType.RIGHT_QUARTER_TURN3_TILES)

    # Station runs east along y=100, so entrance and exit sit on either side of it.
    coaster.place_entrance(Tile(101, 99))
    coaster.place_exit(Tile(101, 101))
    return coaster


def test_run(game: RCT2, coaster) -> int:
    """Put the ride in test mode and advance until the game marks it tested. Returns ticks used."""
    game.actions.ride_set_status(ride=coaster.data.id, status=RideStatus.TESTING)
    ticks = 0
    while ticks < MAX_TICKS:
        game.advance_ticks(TICK_CHUNK)
        ticks += TICK_CHUNK
        coaster.refresh()
        if coaster.data.lifecycleFlags & LIFECYCLE_TESTED:
            return ticks
    raise TimeoutError(f"ride not tested after {MAX_TICKS} ticks (status={coaster.data.status})")


def main() -> None:
    t0 = time.perf_counter()
    with RCT2.launch(Scenario.TEST_PARK_LARGE) as game:
        print(f"launched in {time.perf_counter() - t0:.1f}s")
        game.park.cheats.build_in_pause_mode()
        game.park.cheats.sandbox_mode()
        game.park.cheats.disable_all_breakdowns()
        game.execute("gamesetspeed", {"speed": HYPER_SPEED})
        game.advance_ticks(10)

        t1 = time.perf_counter()
        coaster = build_hill_loop(game)
        print(
            f"built {len(coaster.pieces)} pieces in {time.perf_counter() - t1:.2f}s, "
            f"circuit_complete={coaster.circuit_complete}"
        )
        assert coaster.circuit_complete, "circuit did not close"

        t2 = time.perf_counter()
        ticks = test_run(game, coaster)
        d = coaster.data
        print(f"tested in {ticks} ticks ({time.perf_counter() - t2:.1f}s wall)")
        print(
            f"excitement={d.excitement / 100:.2f} intensity={d.intensity / 100:.2f} "
            f"nausea={d.nausea / 100:.2f}"
        )
        print(
            f"maxSpeed={d.maxSpeed} rideLength={d.rideLength} rideTime={d.rideTime} "
            f"drops={d.numDrops} maxPosG={d.maxPositiveVerticalGs} maxLatG={d.maxLateralGs}"
        )
        assert d.excitement >= 0, "no ratings produced"
    print(f"OK, total {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
