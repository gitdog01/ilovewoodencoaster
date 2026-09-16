# ilovewoodencoaster

OpenRCT2 우든 롤러코스터 트랙을 생성하는 작은 언어모델(sLLM)과 플러그인.

**목표: 원하는 크기의 부지에서, 격렬도가 너무 높지 않게 하면서, 흥미도를 최대로.**
지표 4개를 다 지정받는 게 아니라 **부지 크기만 주고 나머지는 제약 하 최적화**다
(격렬도가 10을 넘으면 손님이 안 탄다).

![1단계: 손으로 짠 첫 폐곡선 코스터](%EC%B2%AB_%EC%99%84%EC%84%B1_.png)

*1단계 산출물 — `scripts/02_hello_coaster.py` 가 지은 첫 폐곡선 코스터.
흥미 0.27 / 격렬 0.30 / 멀미 0.18. 여기서 시작했다.*

<video src="https://raw.githubusercontent.com/gitdog01/ilovewoodencoaster/main/1%EB%8B%A8%EA%B3%84%EC%98%81%EC%83%81.mp4" controls muted loop width="640"></video>

*1단계 실행 영상 (약 6초) — 재생이 안 되면 [1단계영상.mp4](1%EB%8B%A8%EA%B3%84%EC%98%81%EC%83%81.mp4) 를 직접 열면 된다.*

## 어떻게 동작하는가

게임을 라벨러로 쓴다. 절차적 생성기로 유효한 트랙을 대량으로 만들고 OpenRCT2 가
흥미도/격렬도/멀미도를 매기게 한 뒤, 그 (조건, 시퀀스, 평점) 쌍으로 조건부 생성
모델을 학습한다.

```
[BOS][exc=8][int=6][cost=2][width=12][station=4][SEP] <트랙 조각들> [EOS]
```

추론은 네 단계다.

1. **LM 이 조건부로 후보를 뽑는다** (`model/gpt.py`)
2. **constrained decoding 이 매 스텝 불가능한 조각을 마스킹한다** (`model/constrain.py`)
   — 조각 연결 규칙과 부지 경계는 학습으로 안 지켜진다. 기하로 강제해야 한다.
3. **A\* 가 스테이션까지 정확히 닫는다** (`geom/planner.py`, `model/hybrid.py`)
   — 폐곡선은 (x, y, z, 방향, 경사, 뱅크) 6개가 전부 일치해야 해서 샘플링으로는 안 나온다.
4. **게임이 채점하고 best-of-N 으로 고른다** (`model/bestof.py`)

## 지금까지의 결과

| 문제 | 전 | 후 | 어디서 고쳤나 |
|---|---|---|---|
| 부지 준수 | 12~20% | **100%** | `model/constrain.py` |
| 폐곡선 완성 | 0% | **100%** | `model/hybrid.py` (A\* 마무리) |
| 게임의 배치 거부 | 16.7% | **4.2%** | 실측 footprint + 입구/출구 예약 + `plan_safe` |
| 트랙 하나당 시간 | 33초 | **5~10초** | 설계를 파이썬에서 끝내고 게임 왕복 1회 |

- **데이터 140,868개** (`data/dataset.jsonl`, 인스턴스 25개 병렬로 시간당 약 9,300개)
- **모델 4.79M 파라미터**, val 0.6365, RTX 5070 에서 **1.2분** 학습
- **게임 종단 검증**: 요청 흥미/격렬/좌우G `2.5/2.0/1.2` -> 실측 `1.90/2.10/1.15`,
  `5.5/8.0/3.0` -> `5.02/7.05/2.92`. 요청한 목표값을 실제로 맞춘다.

### 아직 사람한테 밀린다 (이게 진짜 병목이다)

RCT2 스톡 우든 코스터 30개를 뜯어 우리 데이터와 비교한 결과:

| | 흥미도 중앙 | 격렬도 중앙 | 조각 수 중앙 |
|---|---|---|---|
| **사람 (스톡 30개)** | **7.90** | 4.65 | **127** |
| 우리 생성기 (140,868개) | 2.40 | 3.17 | 47 |

사람은 **흥미도가 더 높으면서 격렬도는 더 낮다.** 트레이드오프 곡선 위에 있는 게
아니라 그냥 밀린다 (우리 최대 6.00 < 사람 중앙 7.90). 제일 눈에 띄는 차이는
**조각 수 47 vs 127** 이고, 그 다음이 어휘다 — 생성기가 쓰는 조각 21종은 스톡
코스터 조각의 **53.5%** 밖에 못 덮는다 (60도 경사 14.7%, 대각선 11.9% 가 통째로 빠져 있다).

```bash
python scripts/10_vocab_coverage.py   # 이 커버리지 분석을 다시 돌린다
```

## 진행 상황

- [x] 0단계 — 플러그인 설치, 연결 확인
- [x] 1단계 — 손으로 짠 코스터 하나 짓고 평점 받기 (위 사진/영상)
- [x] 2단계 — 조각 지오메트리 추출 (`geometry.json`, 652개 조합)
- [x] 3단계 — 대량 수집 (140,868개, 세대 gen2~gen5)
- [x] 4단계 — 학습 + 조건부 생성 + constrained decoding + best-of-N
- [~] 5단계 — 게임 안 플러그인 UI (지도 메뉴 -> "우든 코스터 생성기").
      `scripts/08_daemon.py` 를 띄워둬야 동작한다.

## 구조

```
rct/             게임 통신 (TCP 클라이언트, 환경 래퍼, 상수)
geom/            지오메트리 추출 + 순수 파이썬 시뮬레이터 + A* 플래너
gen/             절차적 트랙 생성기
model/           토크나이저 + GPT + constrained decoding + best-of-N
plugin/          ridecreation-api 패치 정본 (아래 참고)
scripts/         단계별 실행 스크립트
data/            수집된 데이터셋 (gitignore)
geometry.json    조각 연결 규칙 (게임에서 추출)
footprints.json  조각이 실제로 점유하는 타일 (게임에서 실측)
track_names.json 조각 ID -> 이름표
```

## 준비

1. OpenRCT2 0.5.0+ 설치 (quickjs-ng 스크립팅 엔진 필요), RCT2 원본 에셋 연결
2. **`plugin/ridecreation-api.js` 를 `Documents/OpenRCT2/plugin/` 에 복사.**
   이건 `markusklock/openrct2-ridecreation-api` 에 패치를 얹은 정본이다
   (`getNextValidSegments` 부재 대응 + 포트 고정 + `getRideTiles`/`getTileElements`/
   `deleteRide`/`findFreePlot` 엔드포인트 추가). 원본을 그대로 쓰면 트랙 배치가
   깨지고 병렬 수집도 안 된다 — 자세한 건 `CLAUDE.md`.
3. `openrct2.com` 으로 실행하고 평지 샌드박스 공원 로드
   (`openrct2.exe` 로 실행하면 플러그인 로그가 안 보인다. 플러그인은 타이틀 화면이
   아니라 **공원 로드 후** 시작된다)
4. 시나리오에 Wooden Roller Coaster 오브젝트가 있는지 확인
5. `pip install -r requirements.txt` (0~3단계는 표준 라이브러리만으로 돈다.
   torch 는 4단계부터)

## 실행

```bash
python scripts/00_smoke.py                 # 연결 확인
python scripts/01_extract_geometry.py      # geometry.json 생성
python scripts/02_hello_coaster.py         # 코스터 하나 짓고 평점 (위 사진)
python scripts/09_extract_footprints.py    # footprints.json 실측 (어휘 늘리면 다시)
python scripts/03_collect.py --n 100       # 데이터 수집
python scripts/build_dataset.py --min-gen gen2   # part -> dataset.jsonl (세대 태깅 + dedupe)
python scripts/04_train.py                 # 조건부 생성 모델 학습 (RTX 5070 기준 1.2분)
python scripts/05_sample.py --constrained  # 조건이 먹히는지 평가
python scripts/07_bestof.py --exc 5 --int 8 --latg 2.5   # 목표 -> 트랙 하나
python scripts/08_daemon.py                # 게임 안 UI 를 받는 데몬 (5단계)
```

`07_bestof.py` 가 전체 흐름이다: LM 이 조건부로 후보를 뽑고 -> A\* 가 스테이션까지
닫고 -> 게임이 채점하고 -> 제약(격렬도 상한) 아래에서 최고를 고른다.

### 병렬 수집

인스턴스를 여러 개 띄우면 그 배로 빨라진다. 다만 **창을 그냥 여러 개 띄우면 안 된다**
— Windows 에서는 모든 인스턴스가 8080 에 겹쳐 붙어서 서로의 트랙을 지운다
(이유는 `CLAUDE.md` 의 "병렬 수집"). 대신:

```bash
python scripts/setup_instances.py --n 25   # 인스턴스별 폴더 + 포트 고정 (한 번만)
python scripts/run_instances.py --n 25     # 실행 + 공원 로드 + 포트 확인
python scripts/collect_all.py --n 25 --each 5000 --seed-base 500 --tag run4
python scripts/collect_watchdog.py --n 25 --tag run4 --seed-base 500   # 죽은 인스턴스를 5분마다 되살린다
```

수집기는 트랙 하나가 끝날 때마다 자기 part 파일에 append 하므로 **아무 때나 끊어도
모은 건 남는다.** `--seed-base` 는 안 쓴 값으로 줄 것 (겹치면 같은 트랙이 다시 나온다).
합칠 때 `cat` 하지 말고 `build_dataset.py` 를 쓸 것 — 세대 태깅과 중복 제거를 한다.

### 검증

```bash
python scripts/verify_claims.py    # CLAUDE.md 의 데이터 통계 32개를 데이터로 대조
python scripts/check_buckets.py    # 조건 토큰이 실제로 조건 노릇을 하는지
```

둘 다 게임 없이 돈다. **수집을 더 하면 `verify_claims.py` 가 깨진다 — 그때 문서
숫자를 같이 고칠 것.**

## 알려진 한계

- **어휘가 절반이다.** 생성기 21종 = 스톡 코스터의 53.5%. 60도 경사는
  `geometry.json` 에 이미 있어서 생성기만 고치면 되고, 대각선은 다단계 추출이 필요하다.
- **평점 축에 도달 불가 구간이 있다.** 흥미도/격렬도/멀미도는 값이 덩어리로 뭉쳐
  있어서 (격렬도는 4.0~5.0, 10.5~13.5 가 아예 0개) 그 사이를 요청해도 못 만든다.
  `model/tokenizer.py` 의 `REACHABLE` / `snap()` 이 가까운 값으로 당기고 그 사실을 알린다.
  좌우G 만 유일하게 연속이라 조건으로 제일 믿을 만하다.
- **평점은 주변 환경에 영향받는다.** 라벨링은 반드시 빈 평지에서.
- 한국어 Windows 콘솔은 cp949 라 em-dash 같은 문자를 `print()` 하면 스크립트가
  통째로 죽는다. 출력에는 ASCII 문장부호만 쓸 것.

설계 배경, 실측 기록, 되돌린 시도들까지 전부 `CLAUDE.md` 에 있다.
