"""Freeze the benchmark: development and held-out conditions (run once, before any held-out run).

    uv run python scripts/make_bench.py
"""

from rct2_close_the_loop.bench import generate_all

generate_all()
