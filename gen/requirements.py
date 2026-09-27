"""우든 코스터 요건을 게임 없이 시퀀스만 보고 예측한다.

OpenRCT2 는 우든 코스터가 아래 넷 중 하나라도 못 채우면 흥미/격렬/멀미를
전부 약 절반으로 깎는다 (CLAUDE.md "격차의 정체"). 2026-09-19 까지 수집한
데이터의 75% 가 여기 걸려 있었다. 설계 단계에서 거르면 게임 왕복 없이 막는다.

    주행 길이 >= 370m       조각 길이 합으로 예측 (오차 표준편차 2.6m)
    낙하 >= 2회             연속 내리막 구간 수 -- **데이터와 100% 일치**
    최고 낙하 >= 12         연속 내리막 구간의 최대 하강량 -- **100% 일치**
    음의 G <= 0.10          리프트 꼭대기보다 CREST_DEPTH 이상 낮은 곳에서
                            볼록 전환(오르막->평지, 평지->내리막)을 넘는가.
                            깊이 8 이상이면 99% 충족, 4 이하면 0%.

검증은 `python scripts/11_human_gap.py --check-predictor`.
"""

import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIN_LENGTH = 370          # m
MIN_DROPS = 2
MIN_DROP_HEIGHT = 12      # 원시 z (API highestDropHeight 와 같은 단위)
CREST_DEPTH = 8           # 원시 z. 실측 97.5% (8) / 92.0% (7) / 79.2% (6)

# rideLength(m) ~= 조각 길이 합 x 0.1415 + 11.5 (스테이션 3칸 포함, 140k 에서 적합).
# 오차 표준편차가 2.6m 라 3시그마만큼 여유를 둔다.
_LEN_SCALE, _LEN_BIAS, LENGTH_MARGIN = 0.1415, 11.5, 8

_UP25, _DOWN25, _FLAT = 2, 6, 0     # geometry.json 의 slope 값


def _load():
    with open(os.path.join(_REPO, "geometry.json"), encoding="utf-8") as fp:
        geo = json.load(fp)
    with open(os.path.join(_REPO, "track_names.json"), encoding="utf-8") as fp:
        names = json.load(fp)
    pieces = {v["type"]: v for v in geo.values()}
    length = {int(k): v["length"] for k, v in names.items()}
    return pieces, length


_PIECES, _LENGTH = _load()


def predict(seq):
    """시퀀스 [(조각, 체인), ...] -> 요건 관련 예측값."""
    length = sum(_LENGTH[t] for t, _ in seq) * _LEN_SCALE + _LEN_BIAS
    z, run, runs = 0, 0, []
    top, crest = None, -1
    for t, chain in seq:
        p = _PIECES[t]
        if chain:
            z += p["dz"]
            top = z
            continue
        b, e = p["beginSlope"], p["endSlope"]
        if top is not None and ((b == _FLAT and e == _DOWN25) or (b == _UP25 and e == _FLAT)):
            crest = max(crest, top - z)
        if p["dz"] < 0:
            run -= p["dz"]
        elif run:
            runs.append(run)
            run = 0
        z += p["dz"]
    if run:
        runs.append(run)
    return {"length": length, "drops": len(runs),
            "drop_height": max(runs, default=0), "crest_depth": crest}


def failures(seq):
    """못 채울 것으로 예측되는 요건 이름 목록. 비어 있으면 통과."""
    p = predict(seq)
    out = []
    if p["length"] < MIN_LENGTH + LENGTH_MARGIN:
        out.append("length")
    if p["drops"] < MIN_DROPS:
        out.append("drops")
    if p["drop_height"] < MIN_DROP_HEIGHT:
        out.append("drop_height")
    if p["crest_depth"] < CREST_DEPTH:
        out.append("neg_g")
    return out


def meets(seq):
    return not failures(seq)


# 리프트 뒤 모든 꼭대기가 리프트 꼭대기보다 이만큼은 낮아야 열차가 넘는다.
# 실측 (2026-09-27, gen13 설정 34개): 최소 여유 2~6 통과 2/7, 8 이상 26/27.
# 못 넘으면 열차가 골짜기에서 왕복해 테스트가 안 끝난다 (평점 없음).
MIN_CREST_MARGIN = 8


def crest_margin(seq):
    """리프트 꼭대기 - (리프트 뒤 가장 높은 꼭대기). 꼭대기가 없으면 큰 값."""
    z, top, last_chain, prof = 0, None, -1, []
    for i, (t, chain) in enumerate(seq):
        z += _PIECES[t]["dz"]
        if chain:
            top, last_chain = z, i
        prof.append(z)
    peaks = [prof[i] for i in range(last_chain + 2, len(prof) - 1)
             if prof[i] >= prof[i - 1] and prof[i] > prof[i + 1]]
    return min((top - p for p in peaks), default=99) if top is not None else 99


def clears_hills(seq):
    return crest_margin(seq) >= MIN_CREST_MARGIN


BRAKE_IDS = (99, 216)       # BRAKE, BLOCK_BRAKE (rct/constants.py)
MAX_BRAKE_SPEED = 39        # 40 이상은 게임이 배치를 거부한다


def brake_speed_needed(seq):
    """브레이크 뒤 언덕을 넘는 데 필요한 최소 브레이크 속도. 브레이크가 없으면 0.

    브레이크를 지나면 열차 속도가 brake_speed 로 깎이는데, 그 뒤에 브레이크보다
    높이 올라가는 구간이 있으면 못 넘고 골짜기에서 왕복한다 (평점 없음).
    실측 (gen14, 2026-09-27, 브레이크 뒤 최대 상승 x 속도대):
        속도 8~15 : 상승 0~2 통과 71/74, 4 는 8/12, 6 이상은 10/63
        속도 16~23: 상승 4 는 10/11, 6 은 22/31, 8 은 17/35
        속도 24~31: 상승 6 은 22/27, 8 은 20/31
    => 상승 h 를 넘으려면 대략 4h + 4. 설계를 버리지 말고 속도를 올린다 --
    흥미도 공식에 브레이크 항이 없어서 손해가 없다.

    **효과는 약하다** (게임 검증): 실패했던 설계 24개를 속도만 올려 다시 지으니
    5개만 통과했다 (0 -> 5/24). 상관은 강한데 인과는 약하다 -- 브레이크 뒤에
    크게 올라가는 설계는 속도와 무관하게 그 지점의 에너지가 모자란 경우가 많다.
    필요 속도가 36~39 로 나오는 설계는 전부 여전히 실패했다.
    """
    z, prof, brakes = 0, [], []
    for i, (t, _c) in enumerate(seq):
        if t in BRAKE_IDS:
            brakes.append((i, z))
        z += _PIECES[t]["dz"]
        prof.append(z)
    need = 0
    for k, (bi, bz) in enumerate(brakes):
        end = brakes[k + 1][0] if k + 1 < len(brakes) else len(prof)
        seg = prof[bi + 1:end]
        if seg:
            need = max(need, 4 * max(0, max(seg) - bz) + 4)
    return min(need, MAX_BRAKE_SPEED)

