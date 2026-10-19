#!/usr/bin/env bash
# S2: run the same search on every terrain condition with the same budget.
#   ./scripts/run_s2.sh <ride> <minutes> <seed>     e.g. ./scripts/run_s2.sh twister 12 21
set -uo pipefail
ride="${1:-twister}"
minutes="${2:-12}"
seed="${3:-21}"
cd "$(dirname "$0")/.."
mkdir -p runs/s2
# layout, starting hill height (the 16x16 area only fits a 4-step lift on its first side)
conditions=(
  "${ride}_24:6"
  "${ride}@hills24:6"
  "${ride}@trees24:6"
  "${ride}@hilltrees24:6"
  "${ride}@small16:4"
  "${ride}@center24:6"
)
for c in "${conditions[@]}"; do
  layout="${c%%:*}"
  hill="${c##*:}"
  out="runs/s2/${layout//@/_}-seed${seed}.out"
  echo "$(date '+%H:%M:%S') start $layout (hill $hill)"
  uv run rct2loop search --layout "$layout" --hill "$hill" --minutes "$minutes" --evals 1000000 \
    --seed "$seed" --t0 0.3 --t1 0.02 --slack 0.05 > "$out" 2>&1
  echo "$(date '+%H:%M:%S') done $layout: $(grep -E 'run dir' "$out" | head -1)"
done
