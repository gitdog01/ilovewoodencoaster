"""LM 제안 + A* 마무리 (설계 결정 4/5).

역할 분담이 핵심이다:
  LM   -- "어떤 모양이 조건을 만족하는가". 조건부 스타일을 담당.
  A*   -- "스테이션으로 정확히 되돌아오기". 기하학적 정확성을 담당.

왜 나누는가: 폐곡선은 스테이션 진입점의 6-튜플(x, y, z, 방향, 경사, 뱅크)에
전부 일치해야 성립한다. 마스킹은 한 스텝 앞만 보므로 여기에 우연히 도달할
확률이 사실상 0이다 (실측: constrained decoding 만으로 폐곡선 0%, 닫히기 전
EOS 를 막아도 0%에 길이만 짧아졌다). gen/random_walk.py 가 무작위 워크에 A*
마무리를 붙여 폐곡선 0% -> 40% 를 만든 것과 정확히 같은 구조다.

절차:
  1. LM 이 constrained decoding 으로 본체를 뽑는다. 이때 reserve 로
     "언제든 A* 가 되돌아올 여지"를 유지한다.
  2. 끝 상태에서 A* 로 스테이션까지 닫는다.
  3. 안 닫히면 LM 출력을 조금씩 되감으며 다시 시도한다.
"""

import torch

from geom.planner import Occupancy, State
from gen.random_walk import PLAIN_TURNS, planner_for
from model.constrain import BoundsConstraint


def station_states(sim, origin, direction, station_length=3,
                   reserve_entrance=True):
    """스테이션의 (끝 상태, 진입점, 점유 타일) 을 시뮬레이터로 계산한다.

    좌표를 손으로 가정하면 안 된다. 방향 0 은 -x 로 진행하는데 +y 로 가정했다가
    오프라인에서는 100% 닫히는데 게임에 지으면 전부 실패했다 (게임의 실제
    스테이션 끝은 (64,66,14), 가정값은 (67,69,14) 였다).

    타일 계산은 geom/simulator.station_tiles 하나로 모았다 -- 수집기
    (gen/random_walk) 와 추론 경로가 같은 규칙을 써야 한다. 예전에는 여기에
    사본이 있어서 한쪽만 고치면 갈라졌다.
    """
    from geom.simulator import station_tiles
    tiles, p = station_tiles(sim, origin, direction, station_length,
                             reserve_entrance=reserve_entrance)
    # 스테이션은 평지/뱅크 없음이라 slope=bank=0.
    start = State(p.x, p.y, p.z, p.direction, 0, 0)
    goal = State(origin[0], origin[1], origin[2], direction, 0, 0)
    return start, goal, tiles


def _follow(P, s, seq, bounds, occupied):
    """조각열을 따라간 뒤 (끝상태, 점유타일). 못 놓으면 (None, None)."""
    from geom.planner import _in_bounds
    used = Occupancy(occupied.ztol)
    for t, _chain in seq:
        hit = next(((nxt, cs) for tt, nxt, cs in P.successors(s) if tt == t), None)
        if hit is None:
            return None, None
        nxt, cells = hit
        if not _in_bounds(bounds, nxt) or occupied.blocked(cells) or used.blocked(cells):
            return None, None
        used.add(cells)
        s = nxt
    return s, used.cells


def generate_closed(model, tok, cond, sim, bounds, start: State, goal: State,
                    n, device, close_budget=24, temperature=0.9, top_k=None,
                    max_new_tokens=120, rewinds=(0, 2, 4, 7, 11),
                    station_tiles=(), ztol=2):
    """조건을 주고 폐곡선 트랙 n개를 시도한다. [(조각, 체인), ...] 목록을 반환.

    닫는 데 실패한 후보는 결과에서 빠진다 (best-of-N 이므로 몇 개만 살아도 된다).

    ztol 은 자기충돌로 볼 세로 여유다. 2026-09-13 에 2/4/6/8 을 게임으로 재봤는데
    **배치 성공률에 유의한 차이가 없었다** -- 시드 간 분산(12포인트)이 효과보다
    크다 (CLAUDE.md "새로 알게 된 것 3"). 기본값 2 를 유지한다. 다시 재려면
    시드를 여러 개 쓸 것. 하나만 보면 단조 상승처럼 보여서 속는다.
    """
    P = planner_for(sim)
    prefix = ([tok.stoi["<bos>"]] + tok.encode_condition(**cond)
              + [tok.stoi["<sep>"]])
    x = torch.tensor([prefix] * n, dtype=torch.long, device=device)

    seed = list(station_tiles) or [start.cell(), goal.cell()]
    # max_token: 모델이 낼 수 있는 토큰 폭. 어휘가 늘기 전에 학습한 체크포인트를
    # 돌리면 새 토큰이 마스크 인덱스 범위를 넘어 CUDA assert 로 죽는다.
    con = BoundsConstraint(sim, tok, bounds, start, goal, n, ztol=ztol,
                           reserve=close_budget, seed_cells=seed,
                           max_token=model.cfg.vocab_size)
    out = model.generate(x, max_new_tokens=max_new_tokens,
                         temperature=temperature, top_k=top_k,
                         eos_id=tok.stoi["<eos>"], allowed_fn=con)

    eos = tok.stoi["<eos>"]
    results = []
    for row in out.tolist():
        body = row[len(prefix):]
        if eos in body:
            body = body[:body.index(eos)]
        seq = tok.decode(body)
        if not seq:
            continue
        closed = _close(P, seq, goal, start, bounds, close_budget, rewinds,
                        seed, ztol)
        if closed is not None:
            results.append(closed)
    return results


def _close(P, seq, goal, start, bounds, close_budget, rewinds, seed_cells,
           ztol=2):
    """LM 이 뽑은 본체 뒤에 A* 꼬리를 붙인다. 실패하면 None."""
    base = Occupancy(ztol, list(seed_cells))
    for back in rewinds:
        if back >= len(seq):
            break
        head = seq[:len(seq) - back] if back else seq
        end, cells = _follow(P, start, head, bounds, base)
        if end is None:
            continue
        occ = base.copy()
        occ.add(cells)
        # 맨턴 없이 먼저 닫아본다. 맨턴은 좌우G를 그대로 올려서 조건을
        # 어기는 방향이라, 마무리 구간이 조건을 망치지 않게 한다.
        tail = P.plan_safe(end, goal, bounds, occ, budget=close_budget + 8,
                           exclude=PLAIN_TURNS)
        if tail is None:
            tail = P.plan_safe(end, goal, bounds, occ, budget=close_budget)
        if tail is not None:
            return head + [(t, False) for t in tail]
    return None
