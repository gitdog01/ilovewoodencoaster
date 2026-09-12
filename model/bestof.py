"""best-of-N: 후보를 여러 개 뽑아 게임으로 검증하고 최고를 고른다 (설계 결정 5).

왜 필요한가. LM 은 조건을 "대체로" 맞추지 확실히 맞추지 못한다. 게임이 1.7초에
평점을 매겨주므로, 뽑아놓고 실제로 재보고 고르는 쪽이 모델을 더 키우는 것보다
싸다. 배치가 거부되는 설계(약 23%)도 여기서 자연스럽게 걸러진다.

점수는 **제약 하 최적화**로 매긴다. 흥미도 최대화가 아니다:
격렬도가 10을 넘으면 손님이 안 타므로 그건 실격이고, 그 아래에서 요청한
목표에 가까우면서 흥미도가 높은 쪽을 고른다.
"""

import math


def score(stats, target, intensity_cap=10.0):
    """후보 하나의 점수. 높을수록 좋다. 실격이면 None.

    target 에 있는 지표만 본다 (없는 건 무시).
    """
    if stats["intensity"] > intensity_cap:
        return None                     # 손님이 안 탄다 -- 흥미도가 높아도 소용없다

    # 요청값과의 거리. 지표마다 스케일이 달라서 대략적인 폭으로 나눠 정규화한다.
    scale = {"exc": 2.0, "int": 3.0, "nau": 2.0, "latg": 0.8}
    key = {"exc": "excitement", "int": "intensity",
           "nau": "nausea", "latg": "maxLateralGs"}
    dist = 0.0
    for k, field in key.items():
        if k in target:
            dist += ((stats[field] - target[k]) / scale[k]) ** 2
    dist = math.sqrt(dist)

    # 목표 근접이 우선, 동률이면 흥미도가 높은 쪽.
    return -dist + 0.1 * stats["excitement"]


def pick_best(env, seqs, target, limit=None, intensity_cap=10.0, verbose=True,
              clear="all"):
    """후보들을 실제로 짓고 평점을 받아 최고를 고른다.

    반환: (최고 시퀀스, 최고 stats, 시도 기록). 하나도 못 지으면 (None, None, 기록).

    clear 는 env.reset() 에 그대로 넘어간다. 유저 공원에서 돌릴 때는 "own" 을
    줘야 한다 -- 기본값 "all" 은 공원의 라이드를 전부 지운다.
    """
    tried = []
    best = (None, None, float("-inf"))
    for i, seq in enumerate(seqs[:limit] if limit else seqs):
        env.reset(station_length=3, clear=clear)
        _placed, complete = env.build(seq)
        if not complete:
            tried.append({"i": i, "ok": False, "why": "배치/폐곡선 실패"})
            continue
        stats = env.evaluate()
        if stats is None:
            tried.append({"i": i, "ok": False, "why": "평점 실패"})
            continue
        sc = score(stats, target, intensity_cap)
        tried.append({"i": i, "ok": True, "stats": stats, "score": sc})
        if verbose:
            tag = "실격(격렬도 초과)" if sc is None else f"점수 {sc:+.2f}"
            print(f"    후보 {i:2d}: E={stats['excitement']:.2f} "
                  f"I={stats['intensity']:.2f} latg={stats['maxLateralGs']:.2f}"
                  f"  {tag}")
        if sc is not None and sc > best[2]:
            best = (seq, stats, sc)
    return best[0], best[1], tried
