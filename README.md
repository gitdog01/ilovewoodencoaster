# ilovewoodencoaster

OpenRCT2 우든 롤러코스터 트랙을 생성하는 작은 언어모델과 플러그인.

## 구조

```
rct/        게임 통신 (TCP 클라이언트, 환경 래퍼, 상수)
geom/       지오메트리 추출 + 순수 파이썬 시뮬레이터
gen/        절차적 트랙 생성기
data/       수집된 (조건, 시퀀스, 평점) 데이터셋
model/      토크나이저 + 학습 코드
plugin/     ridecreation-api 패치 정본 (아래 참고). 최종 생성 플러그인도 여기 갈 예정
scripts/    단계별 실행 스크립트
```

## 준비

1. OpenRCT2 0.5.0+ 설치, RCT2 원본 에셋 연결
2. **`plugin/ridecreation-api.js` 를 `Documents/OpenRCT2/plugin/` 에 복사.**
   이건 `markusklock/openrct2-ridecreation-api` 에 패치 두 개를 얹은 정본이다
   (`getNextValidSegments` 부재 대응 + 포트 고정). 원본을 그대로 쓰면 트랙 배치가
   깨지고 병렬 수집도 안 된다 — 자세한 건 `CLAUDE.md`.
3. `openrct2.com` 으로 실행하고 평지 샌드박스 공원 로드
   (`openrct2.exe` 로 실행하면 플러그인 로그가 안 보인다)
4. 시나리오에 Wooden Roller Coaster 오브젝트가 있는지 확인

## 실행

```bash
python scripts/00_smoke.py            # 연결 확인
python scripts/01_extract_geometry.py # geometry.json 생성
python scripts/02_hello_coaster.py    # 코스터 하나 짓고 평점
python scripts/03_collect.py --n 100  # 데이터 수집
python scripts/build_dataset.py       # part 파일 -> dataset.jsonl (세대 태깅 + dedupe)
python scripts/04_train.py            # 조건부 생성 모델 학습 (RTX 5070 기준 1.2분)
python scripts/05_sample.py --constrained   # 조건이 먹히는지 평가
python scripts/07_bestof.py --exc 5 --int 8 --latg 2.5   # 목표 -> 트랙 하나
python scripts/08_daemon.py           # 게임 안 UI 를 받는 데몬 (5단계)
```

`07_bestof.py` 가 전체 흐름이다: LM 이 조건부로 후보를 뽑고 -> A* 가 스테이션까지
닫고 -> 게임이 채점하고 -> 제약(격렬도 상한) 아래에서 최고를 고른다.

### 병렬 수집

인스턴스를 여러 개 띄우면 그 배로 빨라진다. 다만 **창을 그냥 여러 개 띄우면 안 된다**
— Windows에서는 모든 인스턴스가 8080에 겹쳐 붙어서 서로의 트랙을 지운다
(이유는 `CLAUDE.md` 의 "병렬 수집"). 대신:

```bash
python scripts/setup_instances.py --n 4   # 인스턴스별 폴더 + 포트 고정 (한 번만)
python scripts/run_instances.py --n 4     # 4개 실행 + 공원 로드 + 포트 확인
```

그 다음 터미널 4개에서 `--port` 를 다르게 주고 `03_collect.py` 를 돌린다
(`run_instances.py` 가 명령줄을 그대로 찍어준다).

설계 배경과 진행 상황은 `CLAUDE.md` 참고.
