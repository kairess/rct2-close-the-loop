# rct2-close-the-loop

OpenRCT2를 심판으로 써서 롤러코스터를 설계하는 실험이다. 닫힌 회로를 먼저 깔고, 회로가 닫힌 상태를 유지하는 구간 편집을 반복하며, 편집할 때마다 게임이 직접 시험 운행하고 레이팅을 매긴다.

- 설계 배경: [OpenRCT2 코스터 설계: 하나씩 지어보기 vs 생성+심판](https://claude.ai/artifact/8ybd2vsZAVMDbqQ6NLTuwP)
- 목표와 완료 기준: [docs/GOAL.md](docs/GOAL.md)
- 진행 기록: [docs/LOG.md](docs/LOG.md)

## 구성

| 구성 요소 | 위치 | 역할 |
| --- | --- | --- |
| OpenRCT2 v0.5.6 | `.vendor/OpenRCT2/` (git 제외) | 게임 엔진. 헤드리스 `host` 모드로 띄운다 |
| RCT2 Triple Thrill Pack | Steam 설치 경로 | 원본 게임 데이터 |
| rct2loop 플러그인 | `plugin/rct2loop.js` | 요청 한 번에 트랙을 짓고, 시험 운행하고, 레이팅을 받고, 철거한다 |
| 실험용 사용자 폴더 | `runtime/` (git 제외) | 실험 인스턴스 전용 config와 플러그인. 사용자의 `~/.config/OpenRCT2`와 분리되어 있다 |
| 조각 기하 데이터 | `data/track_segments.json` | 게임에서 받은 조각 350종의 끝 위치, 방향, 경사, 뱅크, 차지하는 칸 |
| Python 패키지 | `src/rct2_close_the_loop/` | 기하 모델, 판정기 풀, 편집 연산, 탐색, 분석 |

| 모듈 | 내용 |
| --- | --- |
| `track.py` | 게임의 TrackDesign 배치 규칙을 옮긴 기하 모델. 회로 닫힘 계산과 공간 사전 검사 |
| `game.py`, `judge.py` | 헤드리스 인스턴스 실행, JSON-lines 통신, 병렬 판정기 풀(오류·주기적 재시작) |
| `edits.py` | 회로 보존 구간 편집. 무작위 걸음에 4조각 이내 정확 완성을 붙인다 |
| `search.py` | 담금질(배치 단위) |
| `mapelites.py` | MAP-Elites(강도 × 멀미도 칸, 적합도 = 흥미도, 비동기) |
| `surrogate.py`, `physics.py` | 빠른 심판 실험(그래디언트 부스팅, 에너지 높이 모델) |
| `results.py`, `report.py`, `analysis.py` | 공원 저장과 스크린샷, 근거 수집, 실행 요약 |

## 설치

```bash
./scripts/setup_env.sh   # 몇 번을 다시 돌려도 안전함
```

이 스크립트가 하는 일은 다음과 같다.
- OpenRCT2를 받아서 프로젝트 안에 둔다.
- 빠진 `libzip5`를 sudo 없이 바이너리 옆에 둔다.
- `~/.config/OpenRCT2/config.ini`에 게임 경로, 로컬 전용 호스트, 마스터 서버 광고 끄기, 디버깅 도구를 설정한다. pyrct2와 스크린샷 명령이 이 설정을 읽는다. 실험 인스턴스는 `runtime/config.ini`를 따로 쓴다.
- `uv sync`와 `pyrct2 setup`을 실행한다.

RCT2를 다른 곳에 설치했다면 `RCT2_PATH=...`로 경로를 지정한다.

## 사용법

```bash
uv run python scripts/smoke_test.py                          # pyrct2로 하는 기본 동작 확인
uv run rct2loop search --layout giga_24 --hill 8 --minutes 25      # 담금질
uv run rct2loop mapelites --layout giga_24 --init runs/<run>/best.json   # MAP-Elites
uv run rct2loop evaluate runs/<run>/best.json --layout giga_24     # 새 인스턴스에서 다시 평가
uv run rct2loop render runs/<run>/best.json NAME --layout giga_24  # results/NAME/ 에 공원 파일과 스크린샷
uv run rct2loop stats runs/<run>/                                  # 단계별 결과 수, G2 지표, 최고 트랙
uv run rct2loop report runs/*/                                     # results/report.json
```

레이아웃은 다음과 같다.

| 이름 | 내용 |
| --- | --- |
| `wooden_24`, `giga_24`, `twister_24` | 평평한 빈 24×24 영역의 목재·기가·트위스터 코스터 |
| `giga_24u` | 지하 허용(실험용). 평지에서는 터널 입구에 지형 작업이 필요해 아직 쓸 수 없다 |
| `<차종>@<지형>` | 차종은 `giga`, `twister`, `wooden` 중 하나, 지형은 `hills24`, `trees24`, `hilltrees24`, `small16`, `center24` 중 하나다(S2 조건) |

지형은 `scripts/make_terrains.py`가 만든다. 명세는 `data/terrains/`, 공원 파일은 `data/parks/`에 저장된다. S2 실험은 `scripts/run_s2.sh <차종> <분> <seed>`로 돌리고, `scripts/summarize_s2.py runs/...`로 요약한다.

`docs/RATINGS.md`에는 레이팅 규칙(요구 조건, 보너스, 근접 점수, 측정 방식)과 적용 현황을 정리해 두었다.

실행마다 `runs/<시각>-<레이아웃>/`이 생기고 다음 파일이 남는다.
- `evals.jsonl`: 평가마다 한 줄. 편집 전 트랙의 eval id, 편집, 편집 후 전체 트랙, 판정, 점수
- `progress.jsonl`: 라운드(또는 일정 평가 수)마다 요약
- `best.json`: 최고 트랙
- `config.json`: 실행 설정과 git 리비전

## 알아둘 점

- **레이팅은 `TESTING`으로만 나온다.** `SIMULATING`은 측정하지 않는다. 시험 운행에는 입구와 출구가 필요하다.
- **게임 속도 8(하이퍼)로 돈다.** 프레임당 128틱이고, 이 플러그인 기준으로 초당 약 4800틱이다. 실험용 config에서 `debugging_tools = true`가 필요하다.
- **시나리오가 끝나면 속도가 1로 돌아간다.** 기본 공원의 목표 기한이 지나면 `ScenarioEnd()`가 속도를 되돌린다. 그래서 setup에서 목표를 "Have fun"으로 바꾸고, 평가마다 속도를 다시 확인한다.
- **언덕을 못 넘는 열차는 일찍 끝낸다.** 선두 차량이 1500틱 동안 새 트랙 칸에 가지 못하면 `stalled`로 처리한다.
- **허용 조각은 공식 트랙 그룹 표로 정한다.** `trackplace` 액션은 차종의 트랙 그룹을 검사하지 않는다. 그래서 브리지 플러그인에 내장된 C++ 생성 표(`data/track_groups_from_bridge.json`)를 쓴다. 대각선, 그룹 0, 브레이크류, 케이블 리프트는 제외한다.
- **스크린샷은 CLI로 찍는다.** 헤드리스에서 `captureImage`를 부르면 게임이 비정상 종료한다. 그래서 공원을 저장한 뒤 CLI `screenshot` 명령으로 렌더링한다. 호스트 모드의 저장은 커스텀 게임 액션 안에서만 된다.
