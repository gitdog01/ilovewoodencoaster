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
- `geom/simulator.py`는 조각의 시작/끝 타일만 추적한다. 5칸 턴 같은 다중 타일
  조각의 중간 점유를 계산하지 않아 자기충돌 검사가 불완전하다. 최종 검증은 게임.
- 격렬도가 10을 넘으면 손님이 안 탄다. 흥미도 최대화가 아니라 **제약 하 최적화.**
- 평점은 주변 주경, 근처 동일 라이드 등에 영향받는다. 라벨링은 반드시 빈 평지에서.

## 진행 상황
- [x] 0단계: OpenRCT2 + 플러그인 설치, 공원 로드
- [ ] 0단계 확인: `python scripts/00_smoke.py`
- [ ] 2단계: `python scripts/01_extract_geometry.py` -> geometry.json
- [ ] 1단계: `python scripts/02_hello_coaster.py` -> 평점 출력
- [ ] 3단계: `python scripts/03_collect.py --n 1000`
- [ ] 4단계: 학습 코드 (model/ 아래, 아직 tokenizer.py만 있음)
- [ ] 5단계: OpenRCT2 플러그인 UI

## 다음에 할 일
`scripts/00_smoke.py`부터 순서대로 돌린다. `02_hello_coaster.py`의 SEQUENCE는
아직 폐곡선이 안 맞을 가능성이 높다 — 출력된 "끝위치 vs 시작"을 보고
직선 구간 개수를 조정하면 된다. geometry.json이 나오면 그 계산을 파이썬으로
자동화할 수 있다.
