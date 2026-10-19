#!/usr/bin/env bash
# After the frozen held-out run: official deliverables, then the post-hoc fixes and re-runs.
#   ./scripts/morning.sh <report_dir>
set -uo pipefail
cd "$(dirname "$0")/.."
report="$1"
say() { echo "$(date '+%H:%M:%S') $*"; }

# Official runs = the frozen run's own log, in order.
mapfile -t RUNS < <(grep -o 'done [a-z0-9_]*: /[^ ]*' runs/bench/driver-heldout-seed1.log | awk '{print $3}' | grep '/runs/')
say "official runs: ${#RUNS[@]}"
uv run python scripts/finish_bench.py heldout "$report" "${RUNS[@]}" || say "finish_bench failed"
cp results/benchmark_heldout.json results/benchmark_heldout_official.json

# Post-hoc: the two fixes found by the frozen run, then only the conditions they affected.
git cherry-pick 769a947 b8d7cb5 && say "fixes applied: $(git rev-parse --short HEAD)"
POST=()
for c in real_alpineadventures syn201; do
  say "post-hoc $c"
  out="runs/bench/posthoc-$c-seed1.out"
  uv run rct2loop design "data/bench/heldout/$c.json" --seed 1 > "$out" 2>&1
  last="$(tail -1 "$out")"
  say "done $c: $last"
  [ -d "$last" ] && POST+=("$last")
done
if [ ${#POST[@]} -gt 0 ]; then
  uv run python scripts/summarize_bench.py heldout --only-runs "${POST[@]}" --out results/benchmark_heldout_posthoc.json
  uv run python scripts/gallery.py heldout --suffix _posthoc "${POST[@]}"
fi
anim_path=$(python3 -c "import json;print(json.load(open('results/anim_heldout.json'))['path'])")
anim_caption=$(python3 -c "import json;print(json.load(open('results/anim_heldout.json'))['caption'])")
note="보류 실행이 찾아낸 버그 두 개(경사 칸 높이, 좁은 영역의 시작 회로)를 고친 뒤 이 조건만 다시 돌린 결과다. 공식 집계에는 넣지 않았다."
uv run python scripts/build_report.py heldout "$report" --anim "$anim_path" --anim-caption "$anim_caption" \
  ${POST:+--posthoc results/benchmark_heldout_posthoc.json} --posthoc-note "$note"
say "morning done"
