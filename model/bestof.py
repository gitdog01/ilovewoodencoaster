"""best-of-N: 후보를 여러 개 뽑아 게임으로 검증하고 최고를 고른다 (설계 결정 5).

왜 필요한가. LM 은 조건을 "대체로" 맞추지 확실히 맞추지 못한다. 게임이 1.7초에
평점을 매겨주므로, 뽑아놓고 실제로 재보고 고르는 쪽이 모델을 더 키우는 것보다
싸다. 배치가 거부되는 설계(약 23%)도 여기서 자연스럽게 걸러진다.

점수는 프로젝트 목표 그대로다: **격렬도가 cap 을 넘으면 실격, 아니면 흥미도.**

(2026-09-19 전까지는 "요청한 4개 지표와의 거리"를 쟀다. 그 때문에 재학습 비교에서
두 번 틀린 결론을 냈다 -- 흥미도를 5.06 -> 5.59 로 올린 모델이 격렬도를 7.18 ->
9.38 로 올렸다는 이유로 감점됐다. 둘 다 10 이하라 후자가 낫다.)
"""


def score(stats, target=None, intensity_cap=10.0):
    """후보 하나의 점수. 높을수록 좋다. 실격이면 None.

    target 은 안 쓴다 (호출부 호환용). 요청값에 가까운지는 목표가 아니다.
    """
    if stats["intensity"] > intensity_cap:
        return None                     # 손님이 안 탄다 -- 흥미도가 높아도 소용없다
    return stats["excitement"]


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
