#!/usr/bin/env bash
# After held-out set B: summary, gallery, and the report page with its section.
#   ./scripts/finish_heldout_b.sh <report_dir>
set -uo pipefail
cd "$(dirname "$0")/.."
report="$1"
mapfile -t RUNS < <(grep -o 'done [a-z0-9_]*: /[^ ]*' runs/bench/driver-heldout_b-seed1.log | awk '{print $3}' | grep '/runs/')
uv run python scripts/summarize_bench.py heldout_b "${RUNS[@]}"
uv run python scripts/gallery.py heldout_b "${RUNS[@]}"
anim_path=$(python3 -c "import json;print(json.load(open('results/anim_heldout.json'))['path'])")
anim_caption=$(python3 -c "import json;print(json.load(open('results/anim_heldout.json'))['caption'])")
note="보류 실행이 찾아낸 버그 두 개(경사 칸 높이, 좁은 영역의 시작 회로)를 고친 뒤 이 조건만 다시 돌린 결과다. 공식 집계에는 넣지 않았다."
xnote="첫 보류 실행에서 찾은 버그 두 개를 고친 코드를 깨끗하게 재려고, 실행 전에 고정된 코드로 새 조건 6곳(처음 보는 실제 시나리오 맵 3곳, 새 무작위 지형 3곳)을 더 뽑아 같은 설정·같은 15분으로 돌렸다."
uv run python scripts/build_report.py heldout "$report" --anim "$anim_path" --anim-caption "$anim_caption" \
  --posthoc results/benchmark_heldout_posthoc.json --posthoc-note "$note" --extra-split heldout_b --extra-note "$xnote"
echo "$(date '+%H:%M:%S') finish_heldout_b done"
