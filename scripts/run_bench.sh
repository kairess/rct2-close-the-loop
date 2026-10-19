#!/usr/bin/env bash
# Run the general pipeline on every condition of a benchmark split with the fixed configuration.
#   ./scripts/run_bench.sh <dev|heldout> <seed> [minutes override for dev only]
set -uo pipefail
split="$1"
seed="${2:-1}"
minutes="${3:-}"
cd "$(dirname "$0")/.."
mkdir -p runs/bench
for cond in data/bench/"$split"/*.json; do
  name="$(basename "$cond" .json)"
  out="runs/bench/${split}-${name}-seed${seed}.out"
  echo "$(date '+%H:%M:%S') start $name"
  if [ -n "$minutes" ]; then
    uv run rct2loop design "$cond" --seed "$seed" --minutes "$minutes" > "$out" 2>&1
  else
    uv run rct2loop design "$cond" --seed "$seed" > "$out" 2>&1
  fi
  echo "$(date '+%H:%M:%S') done $name: $(tail -1 "$out")"
done
