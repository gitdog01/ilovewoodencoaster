"""오프라인 트랙 설계기: 게임에 묻지 않고 폐곡선 시퀀스를 통째로 만든다.

3단계 수집이 느렸던 이유는 게임 안에서 조각을 하나씩 놓아보며 무작위로
헤매기 때문이었다. 무작위 워크는 스테이션 진입점(x, y, z, 방향, 경사, 뱅크)에
정확히 도달할 확률이 사실상 0이라 폐곡선이 거의 안 만들어진다.

geometry.json 에는 조각마다 begin/endSlope, begin/endBank 가 들어있어서
"이 조각 뒤에 저 조각을 붙일 수 있는가"라는 게임 규칙을 오프라인에서 그대로
재현할 수 있다. 그래서 여기서는

    무작위 워크(변화) -> A* 로 스테이션까지 정확히 닫기(보장)

를 순수 파이썬으로 끝내고, 완성된 시퀀스만 게임에 한 번 짓는다.
게임 왕복이 사라지므로 실패한 시도는 사실상 공짜다.
"""

import heapq
import math
import random
from dataclasses import dataclass

from geom.simulator import Bounds


@dataclass(frozen=True)
class State:
    """트랙 끝단의 완전한 상태. 이 6개가 같으면 이어붙일 수 있는 조각도 같다."""
    x: int
    y: int
    z: int
    direction: int
    slope: int
    bank: int

    def key(self):
        return (self.x, self.y, self.z, self.direction, self.slope, self.bank)

    def cell(self):
        return (self.x, self.y, self.z)


class Planner:
    def __init__(self, sim, piece_types):
        self.sim = sim
        self.pieces = tuple(piece_types)
        # (진입방향, 진입경사, 진입뱅크) -> 붙일 수 있는 조각들
        self.by_entry = {}
        self.max_xy = 1
        self.max_axis = 1
        self.max_dz = 1
        for t in self.pieces:
            for d in range(4):
                e = sim.geo.get(f"{t}:{d}")
                if e is None or e.get("beginSlope") is None:
                    continue
                k = (d, e["beginSlope"], e["beginBank"])
                self.by_entry.setdefault(k, []).append((t, e))
                self.max_xy = max(self.max_xy, abs(e["dx"]) + abs(e["dy"]))
                self.max_axis = max(self.max_axis, abs(e["dx"]), abs(e["dy"]))
                self.max_dz = max(self.max_dz, abs(e["dz"]))

    # -- 기본 연산 -------------------------------------------------------
    def apply(self, s: State, e):
        return State(s.x + e["dx"], s.y + e["dy"], s.z + e["dz"],
                     e["outDirection"], e["endSlope"], e["endBank"])

    def successors(self, s: State):
        """(조각타입, 다음상태) 목록. 게임의 연결 규칙을 그대로 적용."""
        out = []
        for t, e in self.by_entry.get((s.direction, s.slope, s.bank), ()):
            out.append((t, self.apply(s, e)))
        return out

    def h(self, s: State, goal: State):
        """남은 조각 수의 낙관적 하한 (admissible)."""
        dx, dy = abs(s.x - goal.x), abs(s.y - goal.y)
        dz = abs(s.z - goal.z)
        # 한 조각이 옮겨주는 최대 거리로 나눈 하한. 한 축으로만 멀리 떨어져
        # 있을 때는 max_xy(대각 이동)보다 max_axis 쪽이 훨씬 타이트하다.
        n = max(math.ceil((dx + dy) / self.max_xy),
                math.ceil(max(dx, dy) / self.max_axis),
                math.ceil(dz / self.max_dz))
        if n == 0 and s.key() != goal.key():
            n = 1
        return n

    # -- 탐색 ------------------------------------------------------------
    def plan(self, start: State, goal: State, bounds: Bounds = None,
             occupied=None, budget=40, max_expand=60000):
        """start 에서 goal 로 정확히 도달하는 최단 조각열. 실패하면 None.

        occupied 는 이미 쓴 (x, y, z) 셀 집합 -- 자기 자신과 겹치지 않게 한다.
        budget 은 쓸 수 있는 최대 조각 수(=탐색 깊이 상한).
        """
        occupied = occupied or set()
        if self.h(start, goal) > budget:
            return None

        openq = [(self.h(start, goal), 0, start.key(), start, ())]
        best = {start.key(): 0}
        expand = 0
        while openq:
            f, g, _, s, path = heapq.heappop(openq)
            if s.key() == goal.key():
                return list(path)
            if g > best.get(s.key(), 1 << 30):
                continue
            expand += 1
            if expand > max_expand:
                return None
            if g >= budget:
                continue
            for t, nxt in self.successors(s):
                if bounds is not None and not _in_bounds(bounds, nxt):
                    continue
                if nxt.cell() in occupied and nxt.key() != goal.key():
                    continue
                ng = g + 1
                if ng >= best.get(nxt.key(), 1 << 30):
                    continue
                nh = self.h(nxt, goal)
                if ng + nh > budget:
                    continue
                best[nxt.key()] = ng
                heapq.heappush(openq, (ng + nh, ng, nxt.key(), nxt, path + (t,)))
        return None

    # -- 무작위 워크 ------------------------------------------------------
    def wander(self, start: State, goal: State, bounds: Bounds, occupied,
               steps, weights, reserve):
        """steps 개만큼 무작위로 뻗는다. 언제든 goal 로 닫을 여지를 남긴다.

        reserve 는 "닫는 데 남겨둘 조각 수". 매 스텝 h(다음상태, goal) <= reserve 를
        유지해서, 아무리 멀리 나가도 이론상 되돌아올 여지는 남긴다.
        (실제 닫기는 plan() 이 하고, 여기서는 h() 하한으로만 대충 걸러낸다.)
        """
        s = start
        seq = []
        occ = set(occupied)
        for _ in range(steps):
            cands = []
            for t, nxt in self.successors(s):
                if not _in_bounds(bounds, nxt):
                    continue
                if nxt.cell() in occ:
                    continue
                if self.h(nxt, goal) > reserve:
                    continue
                cands.append((t, nxt))
            if not cands:
                break
            ws = [weights.get(t, 1) for t, _ in cands]
            t, nxt = random.choices(cands, weights=ws, k=1)[0]
            seq.append(t)
            occ.add(nxt.cell())
            s = nxt
        return seq, s, occ


def _in_bounds(b: Bounds, s: State):
    return (b.x_min <= s.x <= b.x_max and b.y_min <= s.y <= b.y_max
            and b.z_min <= s.z <= b.z_max)
