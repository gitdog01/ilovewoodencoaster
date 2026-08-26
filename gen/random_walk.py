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


def _pick(candidates, pos, anchor):
    """높이 회복 방향을 살짝 선호하는 가중 무작위 선택."""
    weights = []
    for t in candidates:
        w = WEIGHTS.get(t, 1)
        if pos.z > anchor.z and t in (C.FLAT_TO_DOWN25, C.DOWN25, C.DOWN25_TO_FLAT):
            w *= 3
        if pos.z < anchor.z and t in (C.FLAT_TO_UP25, C.UP25, C.UP25_TO_FLAT):
            w *= 3
        weights.append(w)
    return random.choices(candidates, weights=weights, k=1)[0]


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
    undo = 0
    visited = set()
    while len(sequence) < max_pieces:
        p = env.pos
        pos = Pos(p["x"], p["y"], p["z"], p["direction"])
        visited.add(pos.key())

        valid = env.c.valid_next(env.ride_id)["validPieces"]
        valid = [t for t in valid if t not in C.STATION_PIECES]
        valid = sim.legal_moves(pos, valid, bounds, visited)
        remaining = max_pieces - len(sequence)
        valid = [t for t in valid
                 if sim.closable(sim.advance(pos, t), anchor, remaining - 1)]

        if not valid:
            if not sequence or undo > max_undo:
                return None
            env.undo()
            sequence.pop()
            undo += 1
            continue

        t = _pick(valid, pos, anchor)
        ok, _, complete = env.step(t, chain=False)
        if not ok:
            undo += 1
            continue
        sequence.append((t, False))
        if complete:
            return sequence

    return None
