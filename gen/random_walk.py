"""절차적 트랙 생성기 (3단계).

설계 전체를 오프라인(geom/planner.py)에서 끝내고, 완성된 폐곡선 시퀀스만
게임에 한 번 짓는다.

예전에는 게임 안에서 조각을 하나씩 놓아보며 무작위로 헤맸는데, 스테이션
진입점에 (x, y, z, 방향, 경사, 뱅크) 6개가 전부 일치하도록 우연히 도달할
확률이 사실상 0이라 폐곡선이 거의 안 나왔다. 지금은
  1) 체인리프트 언덕을 깔고
  2) 무작위 워크로 모양을 뽑은 다음
  3) A* 로 스테이션까지 정확히 닫는다
는 세 단계를 전부 파이썬에서 하고, 실패하면 게임 왕복 없이 다시 뽑는다.
"""

import random

from geom.planner import Occupancy, Planner, State, _in_bounds
from geom.simulator import Bounds, TrackSimulator
from rct import constants as C
from rct.env import WoodenCoasterEnv

# 우든 코스터에서 자주 쓰이는 조각 위주로 가중치.
#
# 뱅크(커빙) 없는 턴은 좌우G를 그대로 손님한테 넘겨서 격렬도를 급격히 올린다.
# 실측: 평턴 위주 트랙의 좌우G가 1.75~2.87 (실제 롤코 목표는 1.5 이하),
# 그 트랙들의 격렬도가 6.4~9.1까지 올라갔다. 그래서 턴은 기본적으로
# "뱅크 진입 -> 뱅크턴 -> 뱅크 해제"로 돌게 가중치를 몰아준다.
WEIGHTS = {
    C.FLAT: 3, C.FLAT_TO_UP25: 2, C.UP25: 2, C.UP25_TO_FLAT: 2,
    C.FLAT_TO_DOWN25: 3, C.DOWN25: 3, C.DOWN25_TO_FLAT: 3,
    # 커빙 없는 맨턴 -- 좌우G의 주범이라 최소한만 남긴다.
    C.TURN_L5: 1, C.TURN_R5: 1, C.TURN_L3: 1, C.TURN_R3: 1,
    # 뱅크턴. 3칸 뱅크턴(44/45)은 원래 목록에 아예 빠져 있었다.
    C.BANKED_TURN_L5: 6, C.BANKED_TURN_R5: 6,
    C.BANKED_TURN_L3: 4, C.BANKED_TURN_R3: 4,
    # 뱅크 진출입. 이게 낮으면 뱅크턴을 쓰고 싶어도 진입을 못 한다.
    C.FLAT_TO_LEFT_BANK: 4, C.FLAT_TO_RIGHT_BANK: 4,
    C.LEFT_BANK_TO_FLAT: 3, C.RIGHT_BANK_TO_FLAT: 3,
    C.LEFT_BANK: 1, C.RIGHT_BANK: 1,
}

# 커빙 없는 맨턴. 좌우G를 그대로 손님한테 넘겨 격렬도를 밀어올린다.
#
# WEIGHTS 는 무작위 워크에만 먹고 A* 에는 안 먹는다. 그런데 맨턴은 1조각,
# 뱅크턴은 진입+턴+해제로 3조각이라 최단 경로를 찾는 A* 는 항상 맨턴을 고른다.
# 조각별 비용을 매겨봤더니 균일 비용일 때 잘 먹던 가지치기가 풀려 탐색이
# 몇십 배로 터졌다. 그래서 "맨턴 빼고 한 번, 안 되면 넣고 한 번"으로 간다.
PLAIN_TURNS = frozenset((C.TURN_L5, C.TURN_R5, C.TURN_L3, C.TURN_R3))

# 맨턴을 선호하는 반대쪽 성향. 뱅크는 격렬도를 흥미도와 맞바꾸는 레버라
# (실측: 같은 리프트 높이에서 좌우G 3.02/격렬 9.22/흥미 5.21 <-> 좌우G 0.96/
# 격렬 2.81/흥미 2.60), 데이터셋은 양쪽 영역을 다 덮어야 조건부 생성이
# "격렬도 6짜리 흥미도 최대" 같은 요청을 배울 수 있다.
WEIGHTS_PLAIN = dict(WEIGHTS)
WEIGHTS_PLAIN.update({
    C.TURN_L5: 4, C.TURN_R5: 4, C.TURN_L3: 3, C.TURN_R3: 3,
    C.BANKED_TURN_L5: 1, C.BANKED_TURN_R5: 1,
    C.BANKED_TURN_L3: 1, C.BANKED_TURN_R3: 1,
    C.FLAT_TO_LEFT_BANK: 1, C.FLAT_TO_RIGHT_BANK: 1,
})

_PLANNERS = {}


def planner_for(sim: TrackSimulator):
    """시뮬레이터 하나당 Planner 하나 (조각 인덱싱 재사용)."""
    key = id(sim)
    if key not in _PLANNERS:
        _PLANNERS[key] = Planner(sim, WEIGHTS)
    return _PLANNERS[key]


def _lift(lift_pieces):
    return ([(C.FLAT_TO_UP25, True)] + [(C.UP25, True)] * lift_pieces
            + [(C.UP25_TO_FLAT, True)])


def _drop(drop_pieces):
    """리프트 직후의 첫 낙하. 열차 속도의 원천이라 없으면 트랙이 밋밋해진다."""
    return ([C.FLAT_TO_DOWN25] + [C.DOWN25] * drop_pieces + [C.DOWN25_TO_FLAT])


def _exits(P, s, bounds, occupied):
    """이 상태에서 실제로 놓을 수 있는 조각 수.

    RCT 조각은 예외 없이 최소 한 칸 전진하므로, 부지 끝에서 벽을 마주보면
    제자리 회전이 불가능해 그대로 막다른 길이 된다. 0이면 여기서 끝.
    """
    return sum(1 for _t, nxt, cells in P.successors(s)
               if _in_bounds(bounds, nxt) and not occupied.blocked(cells))


def _follow(P, s, types, bounds, occupied):
    """정해진 조각열을 시뮬레이터로 따라간다.

    (다음상태, 새로 점유한 타일들) 또는 규칙/부지/충돌 위반이면 (None, None).
    occupied 는 건드리지 않는다 -- 호출부가 성공했을 때만 합친다.
    """
    used = Occupancy(occupied.ztol)
    for t in types:
        hit = next(((nxt, cs) for tt, nxt, cs in P.successors(s) if tt == t), None)
        if hit is None:
            return None, None
        nxt, cs = hit
        if not _in_bounds(bounds, nxt) or occupied.blocked(cs) or used.blocked(cs):
            return None, None
        used.add(cs)
        s = nxt
    return s, used.cells


def plan_episode(sim: TrackSimulator, station_end: State, goal: State,
                 bounds: Bounds, lift_pieces=None, wander_steps=None,
                 close_budget=24, headroom=2, ztol=2, banked=True,
                 attempts=40):
    """게임 없이 폐곡선 시퀀스 하나를 설계한다. [(조각, 체인), ...] 또는 None.

    goal 은 스테이션 첫 조각의 진입점 -- 여기로 정확히 돌아오면 폐곡선이다.
    구조는 실제 우든 코스터를 따라 리프트 -> 첫 낙하 -> 본체 -> 스테이션 복귀.

    banked=True 면 턴을 되도록 뱅크(커빙)로 돌아 좌우G와 격렬도를 낮춘다.
    False 면 맨턴 위주로 격렬한 트랙을 뽑는다.
    """
    P = planner_for(sim)
    weights = WEIGHTS if banked else WEIGHTS_PLAIN

    for _ in range(attempts):
        n_lift = lift_pieces if lift_pieces is not None else random.randint(4, 14)
        lift = _lift(n_lift)

        # 1) 체인리프트 언덕. 부지를 벗어나면 이 시도는 버린다.
        occupied = Occupancy(ztol, [station_end.cell(), goal.cell()])
        top, cells = _follow(P, station_end, [t for t, _ in lift], bounds, occupied)
        if top is None:
            continue
        occupied.add(cells)

        # 2) 리프트 꼭대기보다 높이 올라가면 열차가 못 넘는다 -> 천장을 여기로.
        #    마찰 손실이 있으니 headroom 만큼 더 낮게 잡는다.
        rb = Bounds(bounds.x_min, bounds.x_max, bounds.y_min, bounds.y_max,
                    max(bounds.z_min, goal.z), min(bounds.z_max, top.z - headroom))

        # 3) 첫 낙하. 높이의 대부분을 여기서 속도로 바꾼다.
        n_drop = max(1, (top.z - goal.z) // 2 - random.randint(0, 2))
        drop, s = None, None
        while n_drop >= 1 and s is None:
            drop = _drop(n_drop)
            # 낙하 자체는 꼭대기에서 시작하므로 rb(천장 낮춤)가 아니라 원래 부지로 잰다.
            s, cells = _follow(P, top, drop, bounds, occupied)
            # 부지 끝까지 내려가면 벽을 마주본 채 막다른 길이 된다 -> 더 짧게.
            if s is not None:
                after = occupied.copy()
                after.add(cells)
                if _exits(P, s, rb, after) < 2:
                    s = None
            n_drop -= 1
        if s is None:
            continue
        occ0 = occupied.copy()
        occ0.add(cells)

        # 4) 무작위 워크로 본체 모양을 만든다.
        steps = wander_steps if wander_steps is not None else random.randint(15, 60)
        body, _, _ = P.wander(s, goal, rb, occ0, steps, weights,
                              reserve=close_budget)

        # 5) 스테이션까지 정확히 닫는다. 안 닫히면 워크를 되감으며 재시도.
        for back in (0, 2, 4, 7, 11):
            if back > len(body):
                break
            head = body[:len(body) - back] if back else body
            st, cells = _follow(P, s, head, rb, occ0)
            if st is None:
                continue
            occ1 = occ0.copy()
            occ1.add(cells)
            # 맨턴 없이 닫아보고, 정 안 되면 그때만 허용한다.
            # (뱅크턴은 진입/해제까지 3조각이라 예산을 좀 더 줘야 닫힌다.)
            tail = None
            if banked:
                tail = P.plan(st, goal, rb, occ1, budget=close_budget + 8,
                              exclude=PLAIN_TURNS)
            if tail is None:
                tail = P.plan(st, goal, rb, occ1, budget=close_budget)
            if tail is not None:
                return ([(t, True) for t, _ in lift]
                        + [(t, False) for t in drop + head + tail])
    return None


def generate_episode(env: WoodenCoasterEnv, sim: TrackSimulator, bounds: Bounds,
                     max_pieces=120, build_attempts=6, trace=None, **kw):
    """게임 안에 폐곡선 트랙 하나를 짓는다. [(조각, 체인), ...] 또는 None.

    설계는 오프라인이라 공짜지만, 시뮬레이터가 여러 타일짜리 턴 조각의 중간
    점유를 모르기 때문에(알려진 제약) 게임이 배치를 거부할 수 있다. 그럴 땐
    새로 설계해서 다시 짓는다.

    trace 에 리스트를 주면 시도마다 실패 사유를 넣어준다 (진단용).
    """
    for _ in range(build_attempts):
        start = env.reset()
        station_end = State(start["x"], start["y"], start["z"],
                            start["direction"], 0, 0)
        a = env.anchor
        goal = State(a["x"], a["y"], a["z"], a["direction"], 0, 0)

        seq = plan_episode(sim, station_end, goal, bounds, **kw)
        if seq is None:
            if trace is not None:
                trace.append(("plan_fail", 0, 0))
            continue
        if len(seq) > max_pieces:
            if trace is not None:
                trace.append(("too_long", 0, len(seq)))
            continue

        placed, complete = env.build(seq)
        if complete:
            return seq[:placed]
        if trace is not None:
            trace.append(("build_fail", placed, len(seq)))
    return None
