# ilovewoodencoaster

OpenRCT2 우든 롤러코스터 트랙을 생성하는 작은 언어모델과 플러그인.

## 구조

```
rct/        게임 통신 (TCP 클라이언트, 환경 래퍼, 상수)
geom/       지오메트리 추출 + 순수 파이썬 시뮬레이터
gen/        절차적 트랙 생성기
data/       수집된 (조건, 시퀀스, 평점) 데이터셋
model/      토크나이저 + 학습 코드
plugin/     최종 OpenRCT2 플러그인
scripts/    단계별 실행 스크립트
```

## 준비

1. OpenRCT2 0.5.0+ 설치, RCT2 원본 에셋 연결
2. `markusklock/openrct2-ridecreation-api` 빌드 후 `.js`를
   `Documents/OpenRCT2/plugin/` 에 복사
3. `openrct2.com` 으로 실행하고 평지 샌드박스 공원 로드
4. 시나리오에 Wooden Roller Coaster 오브젝트가 있는지 확인

## 실행

```bash
python scripts/00_smoke.py            # 연결 확인
python scripts/01_extract_geometry.py # geometry.json 생성
python scripts/02_hello_coaster.py    # 코스터 하나 짓고 평점
python scripts/03_collect.py --n 100  # 데이터 수집
```

설계 배경과 진행 상황은 `CLAUDE.md` 참고.
