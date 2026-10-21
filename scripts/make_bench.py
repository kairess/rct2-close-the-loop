"""Freeze the benchmark conditions (run once per split, before any held-out run).

    uv run python scripts/make_bench.py            # development and held-out conditions
    uv run python scripts/make_bench.py heldout_b  # the second held-out split

Synthetic conditions are baked into data/bench/parks/; real ones name a scenario from the local
RCT2 install.
"""

import sys

from rct2_close_the_loop.bench import generate_all, generate_heldout_b

if sys.argv[1:] == ["heldout_b"]:
    generate_heldout_b()
else:
    generate_all()
