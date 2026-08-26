"""절차적 트랙 생성기 (3단계).

시뮬레이터로 오프라인 가지치기 -> 게임에는 유망한 후보만 보낸다.
"""

import random

from geom.simulator import Bounds, Pos, TrackSimulator
from rct import constants as C
from rct.env import WoodenCoasterEnv

# 우든 코스터에서 자주 쓰이는 조각 위주로 가중치
WEIGHTS = {
    C.FLAT: 3, C.FLAT_TO_UP25: 2, C.UP25: 2, C.UP25_TO_FLAT: 2,
    C.FLAT_TO_DOWN25: 3, C.DOWN25: 3, C.DOWN25_TO_FLAT: 3,
    C.TURN_L5: 3, C.TURN_R5: 3, C.TURN_L3: 2, C.TURN_R3: 2,
    C.BANKED_TURN_L5: 2, C.BANKED_TURN_R5: 2,
    C.FLAT_TO_LEFT_BANK: 1, C.FLAT_TO_RIGHT_BANK: 1,
    C.LEFT_BANK_TO_FLAT: 1, C.RIGHT_BANK_TO_FLAT: 1,
}


def _weighted_order(candidates, pos, anchor):
    """높이 회복 방향을 살짝 선호하는 가중치로, 후보 전체를 무작위 순서로 정렬.

    (알려진 플러그인 제약: getValidNextPieces가 실제 연결 규칙을 못 내려주므로,
    여기서 나온 순서대로 하나씩 실제 배치를 시도해서 성공하는 걸 찾는다.)
    """
    weighted = []
    for t in candidates:
        w = WEIGHTS.get(t, 1)
        if pos.z > anchor.z and t in (C.FLAT_TO_DOWN25, C.DOWN25, C.DOWN25_TO_FLAT):
            w *= 3
        if pos.z < anchor.z and t in (C.FLAT_TO_UP25, C.UP25, C.UP25_TO_FLAT):
            w *= 3
        # A-ES 가중 셔플: key가 클수록 먼저 온다.
        key = random.random() ** (1.0 / w)
        weighted.append((key, t))
    weighted.sort(reverse=True)
    return [t for _, t in weighted]


def generate_episode(env: WoodenCoasterEnv, sim: TrackSimulator, bounds: Bounds,
                     max_pieces=120, max_undo=200, lift_pieces=4):
    """게임 안에서 한 바퀴 도는 트랙 하나를 만든다. 시퀀스 리스트를 반환."""
    start = env.reset()
    anchor = Pos(**{k: start[k] for k in ("x", "y", "z", "direction")})
    sequence = []

    # 1) 체인리프트 언덕부터 깔고 시작 (없으면 열차가 안 움직인다)
    lift = [(C.FLAT_TO_UP25, True)] + [(C.UP25, True)] * lift_pieces \
           + [(C.UP25_TO_FLAT, True)]
    for t, chain in lift:
        ok, _, _ = env.step(t, chain)
        if not ok:
            return None
        sequence.append((t, chain))

    # 2) 나머지는 무작위 워크 + 백트래킹
    #
    # 원래는 env.c.valid_next()(getValidNextPieces)로 "연결 가능한 조각"을 미리
    # 받아서 그중에서 골랐다. 근데 설치된 플러그인이 이 목록을 항상 빈 배열로
    # 돌려주는 문제가 있어서(알려진 제약, CLAUDE.md 참고), 대신 시뮬레이터로
    # geometry.json 상 정의된 후보만 추린 다음 무작위 순서로 실제 배치를
    # 하나씩 시도해서 게임이 받아주는 걸 찾는다.
    undo = 0
    visited = set()
    while len(sequence) < max_pieces:
        p = env.pos
        pos = Pos(p["x"], p["y"], p["z"], p["direction"])
        visited.add(pos.key())

        candidates = [t for t in WEIGHTS if t not in C.STATION_PIECES]
        candidates = sim.legal_moves(pos, candidates, bounds, visited)
        remaining = max_pieces - len(sequence)
        candidates = [t for t in candidates
                      if sim.closable(sim.advance(pos, t), anchor, remaining - 1)]

        placed = False
        for t in _weighted_order(candidates, pos, anchor):
            ok, _, complete = env.step(t, chain=False)
            if not ok:
                continue
            sequence.append((t, False))
            placed = True
            if complete:
                return sequence
            break

        if not placed:
            if not sequence or undo > max_undo:
                return None
            env.undo()
            sequence.pop()
            undo += 1

    return None
