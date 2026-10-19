#!/usr/bin/env bash
# S2 with an explicit search configuration, so configurations can be compared on the same conditions.
#   ./scripts/run_s2_cfg.sh <ride> <minutes> <seed> <layout regex> <tag> [search args...]
#   e.g. ./scripts/run_s2_cfg.sh twister 15 21 . v3 --chains 4 --priors --iprice-start 0.5 --iprice-end 0.05
set -uo pipefail
ride="$1"
minutes="$2"
seed="$3"
only="$4"
tag="$5"
shift 5
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
  [[ "$layout" =~ $only ]] || continue
  out="runs/s2/${layout//@/_}-seed${seed}-${tag}.out"
  echo "$(date '+%H:%M:%S') start $layout (hill $hill) [$tag] $*"
  uv run rct2loop search --layout "$layout" --hill "$hill" --minutes "$minutes" --evals 1000000 \
    --seed "$seed" --t0 0.3 --t1 0.02 "$@" > "$out" 2>&1
  echo "$(date '+%H:%M:%S') done $layout: $(grep -E 'run dir' "$out" | head -1)"
done
