# CLAUDE.md — 프로젝트 인수인계

## 한 줄 요약
OpenRCT2용 "우든 롤러코스터 트랙 생성 플러그인"을 만들고, 그 안에 들어갈
작은 트랜스포머(sLLM)를 직접 학습시킨다.

## 핵심 설계 결정 (이미 내린 것들)

1. **LLM 스케일이 아니다.** 트랙 = 어휘 100 미만, 길이 100~400의 토큰 시퀀스.
   nanoGPT급(5~10M 파라미터)이면 충분. 로컬 NVIDIA GPU로 몇 시간.

2. **게임을 라벨러로 쓴다.** 공개된 우든 코스터 디자인은 수천 개 수준이라
   부족하다. 절차적 생성기로 유효 트랙을 대량 생성하고 OpenRCT2가
   흥미도/격렬도/멀미도를 매기게 한다. 사람 디자인은 스타일 파인튜닝용 소량.

3. **조건부 생성 (Decision Transformer 방식).** 시퀀스 앞에 목표 지표와
   부지 제약을 버킷 토큰으로 붙여 학습한다.
   `[BOS][exc=8][int=6][cost=2][width=12][station=4][SEP] <트랙> [EOS]`
   추론 시 유저가 플러그인 UI에 넣은 값을 그대로 프리픽스로 사용.

4. **폐곡선/충돌은 학습으로 해결 안 된다.** constrained decoding 필수.
   매 스텝 geom/simulator.py 로 불가능한 토큰을 마스킹한다.

5. **최종 형태는 LM proposal + best-of-N.** 여러 후보를 뽑아 게임으로 검증하고
   최고를 고른다. 플러그인 UX로도 "후보 3개 제시"가 자연스럽다.

## 의존하는 외부 물건
- OpenRCT2 0.5.0 이상 (quickjs-ng 스크립팅 엔진 필요)
- `markusklock/openrct2-ridecreation-api` 플러그인 — TCP JSON API.
  8080부터 시작해 빈 포트를 잡는다. `rct/client.py`의 `discover()`가 자동 탐색.
- Windows에서 플러그인 로그를 보려면 `openrct2.exe`가 아니라 `openrct2.com` 실행.
  플러그인은 타이틀 화면이 아니라 **공원 로드 후** 시작된다.

## 알려진 제약 / TODO
- 플러그인이 노출하는 조각에 **헬릭스, 브레이크, S-bend, 워터스플래시가 없다.**
  우든 코스터 평점에 꽤 영향이 크므로 5단계에서 플러그인을 포크해 확장해야 함.
- **`geom/simulator.py`/`geom/planner.py`는 조각의 시작/끝 타일만 추적한다.
  5칸/3칸 턴처럼 여러 타일을 쓸고 지나가는 조각의 중간 점유를 모른다.
  이게 지금 3단계 수집의 유일한 병목이다** — 오프라인 설계는 100% 성공하는데
  게임에 지을 때 20~50번째 조각쯤에서 자기 트랙과 겹쳐 거부당한다
  (진단: 실패 96건이 전부 `build_fail`, `plan_fail` 0건).
  `getAllTrackSegments`는 조각의 타일 블록 목록을 안 내려주므로, 턴 조각의
  점유 타일을 손으로 정의하거나(quarter turn 5 = 7블록, 3 = 4블록) 실측해서
  Planner 의 occupied 검사에 넣어야 한다. 고치면 성공률이 크게 오를 것.
- 격렬도가 10을 넘으면 손님이 안 탄다. 흥미도 최대화가 아니라 **제약 하 최적화.**
- 평점은 주변 주경, 근처 동일 라이드 등에 영향받는다. 라벨링은 반드시 빈 평지에서.

## 진행 상황
- [x] 0단계: OpenRCT2 + 플러그인 설치, 공원 로드
- [x] 0단계 확인: `python scripts/00_smoke.py`
- [x] 2단계: `python scripts/01_extract_geometry.py` -> geometry.json (652개 조합, origin z=30
      + UP25/DOWN25류 16개는 실측값으로 수동 보충, 아래 TODO 참고)
- [x] 1단계: `python scripts/02_hello_coaster.py` -> 평점 출력 (흥미 0.27/격렬 0.30/멀미 0.18)
- [~] 3단계: `python scripts/03_collect.py --n 1000` — 파이프라인은 동작.
      성공률 ~40%, 트랙당 5~10초, 평점 E 0.58~5.15 / I 0.71~6.92 확보.
      남은 병목은 아래 "자기충돌" 항목 하나뿐.
- [ ] 4단계: 학습 코드 (model/ 아래, 아직 tokenizer.py만 있음)
- [ ] 5단계: OpenRCT2 플러그인 UI

## 알려진 제약 / TODO 추가
- **설치된 `markusklock/openrct2-ridecreation-api`에 `segment.getNextValidSegments`가 없어서
  `placeTrackPiece`/`getValidNextPieces` 응답이 항상 "not a function"으로 깨지는 버그가 있었음.**
  로컬 설치본(`Documents/OpenRCT2/plugin/ridecreation-api.js`)의 `computeValidNextPieces`를
  직접 패치해서 해결 (해당 함수 존재 여부를 체크하고 없으면 validPieces만 빈 배열로 처리,
  좌표(position/nextEndpoint)는 그대로 반환). 원본은 `ridecreation-api.js.bak`으로 보관.
  플러그인을 재설치/업데이트하면 이 패치가 사라지니 다시 적용해야 함.
- `rct/client.py`의 `place()`는 이제 조각의 `beginZ`(진입 z 오프셋, 8단위=tileCoordinateZ 1칸)를
  자동 보정한다. 내리막류 조각은 baseZ가 슬로프 낮은 쪽 기준이라 이 보정이 필요함.
- `01_extract_geometry.py`는 **항상 평지 스테이션 바로 다음에서만** 각 조각을 테스트하므로,
  UP25/DOWN25처럼 같은 경사 상태의 조각 뒤에만 이어질 수 있는 "중간 경사" 조각들은
  구조적으로 못 잡는다 (게임 룰이지 버그 아님). 636/1400개가 현재 방식의 사실상 상한.
  더 채우려면 조각별로 적절한 전환 조각을 먼저 놓고 테스트하는 다단계 추출이 필요함 (TODO).
- extract origin은 지면(z=14)보다 너무 높이 띄우면 "지지대 최대 높이" 제한에 걸린다.
  현재 z=30 (지면+16) 사용 중 — 내리막 조각이 땅에 안 박힐 정도로만 살짝 띄운 값.

## 다음에 할 일 (여기서부터 이어서)
0~2단계 끝났고, **3단계 수집 파이프라인이 실제로 돈다.** 이번에 구조를 갈아엎었다.

### 이번에 바뀐 것 (왜 바꿨는지)
예전 `gen/random_walk.py`는 **게임 안에서** 조각을 하나씩 놓아보며 무작위로
헤맸다. 폐곡선이 되려면 스테이션 진입점에 (x, y, z, 방향, 경사, 뱅크) 6개가
전부 일치해야 하는데 무작위 워크로 거기 우연히 도달할 확률은 사실상 0이라,
`--n 3` 을 돌리면 3/3 폐곡선 실패였다.

`geometry.json` 에 조각마다 begin/endSlope, begin/endBank 가 들어있다는 걸
발견해서(= 게임의 조각 연결 규칙을 오프라인에서 그대로 재현 가능),

- `geom/planner.py` (신규): 상태를 (x, y, z, 방향, 경사, 뱅크) 6-튜플로 두고
  A* 로 스테이션까지 **정확히** 닫는 조각열을 찾는다. `wander()` 는 무작위
  워크, `plan()` 은 폐곡선 마무리.
- `gen/random_walk.py`: 리프트 언덕 -> 첫 낙하 -> 무작위 본체 -> A* 복귀 순으로
  **설계를 전부 파이썬에서 끝내고**, 완성된 시퀀스만 게임에 한 번 짓는다.
  실패한 설계는 게임 왕복이 없으니 사실상 공짜.
- `geom/simulator.py`: `Bounds.plot()` 추가. 기존 `around()` 는 부지를 스테이션
  중심으로 잡는데, 트랙은 스테이션이 보는 방향으로만 뻗으므로 리프트 언덕이
  곧장 부지 밖으로 나가버렸다. `plot()` 은 스테이션을 부지 가장자리에 둔다.
- `rct/client.py`: `set_game_speed()` 추가. 평점은 시뮬 시간 ~35초가 지나야
  나오는데 이게 전체 시간의 대부분이었다. **속도 8이면 트랙당 30초 -> 0.4초.**
- `geometry.json`: 수동 보충한 16개 조합(UP25/UP25_TO_FLAT/DOWN25/DOWN25_TO_FLAT)의
  slope/bank 가 null 이라 planner 가 못 쓰던 걸 채웠다 (0=평지, 2=up25, 6=down25).
- `scripts/03_collect.py`: 에피소드마다 부지/리프트/길이를 무작위로 흔든다.
  한 설정으로만 뽑으면 평점이 E 0.5 부근에 뭉쳐서 조건부 생성 학습에 쓸 게 없다.

### 지금 성능
`--n 30` 기준 11/30 성공, 트랙당 5~10초, E 0.58~5.15 / I 0.71~6.92 / N 0.40~3.74.
(예전: 0/3 성공, 트랙당 33초, E 0.27~1.19)

### 바로 다음 할 일
1. **자기충돌 검사 보강** (성공률 40% -> 80%+ 기대). 위 "알려진 제약"의
   턴 조각 중간 타일 항목 참고. 이게 남은 실패의 100%다.
2. 그다음 `--n 1000` 본 수집 -> `data/dataset.jsonl` (아래 병렬 수집 참고).
3. 그다음이 4단계(학습 코드, model/ 아래 tokenizer.py만 있는 상태).

### 참고: 평점을 올리려다 알게 된 것
- 리프트를 높이면(10칸 이상) 흥미도는 안 오르고 **격렬도만 10~15로 폭주**한다.
  한 방에 떨어지는 직선 낙하라 G가 튄다. 격렬도 10 넘으면 손님이 안 타므로
  `sample_config()` 의 `lift` 는 3~9로 제한해뒀다.
- 흥미도는 리프트 높이보다 **트랙 길이와 조각 다양성**에서 나온다.
- 부지 끝에서 벽을 마주보면 그대로 막다른 길이다. RCT 조각은 예외 없이 최소
  한 칸 전진해서 제자리 회전이 없기 때문. `_exits()` 로 착지 지점에 여유를
  요구한다.

시작 전 체크리스트: OpenRCT2를 `openrct2.com`으로 실행하고 평지 샌드박스 공원을
로드해뒀는지 먼저 확인 (플러그인 패치는 `Documents/OpenRCT2/plugin/ridecreation-api.js`에
이미 적용돼 있음 — 플러그인을 재설치하지 않았다면 그대로 유지됨).

## 병렬 수집 (여러 OpenRCT2 인스턴스)
`03_collect.py`에 `--port` 옵션 추가해둠. 플러그인은 8080부터 시작해 빈 포트를
자동으로 잡으므로, OpenRCT2 창을 여러 개 띄우면(각각 평지 샌드박스 공원 로드)
순서대로 8080, 8081, 8082... 를 잡는다. 그 다음 터미널을 여러 개 열어서:

```bash
python scripts/03_collect.py --port 8080 --seed 0 --n 250 --out data/part_8080.jsonl
python scripts/03_collect.py --port 8081 --seed 1 --n 250 --out data/part_8081.jsonl
python scripts/03_collect.py --port 8082 --seed 2 --n 250 --out data/part_8082.jsonl
python scripts/03_collect.py --port 8083 --seed 3 --n 250 --out data/part_8083.jsonl
```
처럼 동시에 실행하면 인스턴스 수만큼 빨라진다. `--port` 생략하면 기존처럼
첫 빈 포트에 자동 접속 (단일 인스턴스일 때는 그대로 쓰면 됨).
`--seed` 는 인스턴스마다 다르게 준다 (생략하면 PID로 시드하므로 보통은 알아서
갈리지만, 명시하면 재현 가능해진다).
끝나고 `data/part_*.jsonl` 을 `cat`으로 합치면 됨 (전부 `data/*.jsonl` 이라
.gitignore에 이미 잡혀있어서 커밋 걱정은 안 해도 됨).
