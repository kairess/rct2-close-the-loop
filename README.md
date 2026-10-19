# rct2-close-the-loop

OpenRCT2를 심판으로 써서 롤러코스터를 설계하는 실험. 닫힌 회로를 먼저 깔고, 구간을 편집할 때마다 게임이 직접 레이팅을 매긴다.
설계 배경: [OpenRCT2 코스터 설계: 하나씩 지어보기 vs 생성+심판](https://claude.ai/artifact/8ybd2vsZAVMDbqQ6NLTuwP)

## 구성

| 구성 요소 | 위치 | 역할 |
| --- | --- | --- |
| OpenRCT2 v0.5.6 | `.vendor/OpenRCT2/` (git 제외) | 게임 엔진, 헤드리스 `host` 모드로 실행 |
| RCT2 Triple Thrill Pack | Steam 설치 경로 | 원본 게임 데이터 |
| openrct2-bridge v1.8.0 | `~/.config/OpenRCT2/plugin/` | 게임 안에서 TCP로 액션·상태를 노출하는 플러그인 |
| [pyrct2](https://pypi.org/project/pyrct2/) 0.10.0 | `.venv` (uv) | 브리지를 쓰는 Python 클라이언트, 트랙 조각 단위 빌드 지원 |

## 설치

```bash
./scripts/setup_env.sh   # 몇 번을 다시 돌려도 안전함
```

이 스크립트가 하는 일은 다음과 같다.
- OpenRCT2를 받아서 프로젝트 안에 둔다.
- 빠진 `libzip5`를 sudo 없이 바이너리 옆에 둔다.
- `~/.config/OpenRCT2/config.ini`에 게임 경로, 로컬 전용 호스트, 마스터 서버 광고 끄기, 디버깅 도구 켜기를 설정한다.
- `uv sync`와 `pyrct2 setup`을 실행한다.

RCT2를 다른 곳에 설치했다면 `RCT2_PATH=...`로 경로를 지정한다.

## 확인

```bash
uv run python scripts/smoke_test.py
```

헤드리스로 게임을 띄운 다음 26조각짜리 닫힌 회로(체인 리프트 언덕 1개)를 짓고, 시험 운행을 돌려 레이팅을 읽는다. 기대 출력은 다음과 같다. 몇 번을 돌려도 같은 값이 나온다.

```
tested in 2000 ticks (1.3s wall)
excitement=1.69 intensity=1.90 nausea=1.30
```

## 알아둘 점

- **레이팅은 `TESTING`으로만 나온다.** `SIMULATING`은 열차를 돌리기만 하고 측정은 하지 않아서 레이팅이 계속 미정(-1)이다. `TESTING`을 쓰려면 역에 입구와 출구가 있어야 한다. 채점이 끝났는지는 `lifecycleFlags & 0x2`(TESTED)로 판단한다.
- **게임 속도 8을 쓴다.** `gamesetspeed`에 8을 넣으면 초당 약 1600틱으로 돈다. 속도 1은 약 40틱, 속도 4는 약 280틱이다. 속도 8은 config의 `debugging_tools = true`가 필요하다.
- **조각 배치가 병목이 될 수 있다.** 조각 하나를 놓는 데 약 60ms가 걸려서 26조각에 1.6초가 걸렸다. 시험 운행(1.3초)보다 길다.
- **API 버전 경고는 아직 무해하다.** pyrct2는 플러그인 API v111 기준으로 생성됐고 OpenRCT2 v0.5.6은 v124라서 `UserWarning`이 뜬다. 지금까지 쓴 액션은 모두 정상 동작했다.
- **진행 과정을 눈으로 볼 수 있다.** `RCT2.launch(..., headless=False)`로 띄우면 게임 창에서 조각이 놓이는 모습이 보인다. GUI만 따로 실행하려면 `.vendor/OpenRCT2/openrct2`를 쓴다.
