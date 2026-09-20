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
import json
import math
import os
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


_MEASURED = None


def _measured_footprints(path=None):
    """scripts/09_extract_footprints.py 가 실측한 표. 없으면 빈 dict.

    키는 "조각타입:진입방향", 값은 진입 타일 기준 상대좌표 목록이다.
    게임에서 직접 잰 값이라 아래 바운딩 박스 추정보다 정확하다.
    """
    global _MEASURED
    if _MEASURED is None:
        path = path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "footprints.json")
        try:
            with open(path, encoding="utf-8") as fp:
                raw = json.load(fp)
            _MEASURED = {k: tuple(tuple(c) for c in v["cells"])
                         for k, v in raw.items()}
        except (OSError, ValueError, KeyError):
            _MEASURED = {}
    return _MEASURED


def _footprint_deltas(dx, dy, dz):
    """조각이 깔리는 타일의 **추정** (진입 타일 기준 상대 좌표).

    **이건 폴백이다.** footprints.json 에 실측값이 있으면 Planner 가 그걸 쓴다
    (scripts/09_extract_footprints.py). 실측 표에 없는 조합만 여기로 온다.

    진입/진출 타일의 바운딩 박스로 잡는다. 2026-09-13 에 게임과 대조해보니
    이 추정에는 문제가 두 개 있다:

    1. **진입 타일을 빼는 게 틀렸다.** 게임은 조각을 **진입 타일부터** 놓고
       진출 타일은 안 쓴다. 아래 코드는 정반대라, 점유 기록이 조각 하나만큼
       앞으로 밀린다. 직선이 이어지는 구간에서는 집합이 거의 같아서 오래
       안 들켰다. 84개 조합 전부에서 진입 타일 1개씩, 총 84타일(실측의 36.8%)을
       놓치고 있었다.
    2. **과대 claim.** 전체로 실측의 1.35배를 잡는다 (5칸 턴은 실제 7타일인데
       11타일). 거부를 막아주는 대신 설계 공간을 그만큼 좁힌다.

    고치지 않고 남겨둔 이유: 어휘 21종은 이미 실측 표로 덮여 있어서 이 경로를
    안 탄다. 어휘를 넓히면 09_extract_footprints.py 를 다시 돌릴 것 -- 헬릭스류는
    이 추정으로 179~216타일이 나와서 쓸 수가 없다.
    """
    # 2026-09-13: **진입 타일을 넣고 진출 타일을 뺀다.** 실측 표와 같은 규약이다.
    # 예전에는 정반대였는데, 그 상태로 폴백을 타면 그 조각이 다음 조각의 진입
    # 타일을 차지해서 **항상 충돌로 걸린다.** 브레이크를 어휘에 넣었더니 트랙
    # 24개에서 한 번도 안 쓰이길래 찾았다 (브레이크만 실측 표에 없어서 폴백을 탔다).
    if abs(dx) + abs(dy) <= 1:
        return ((0, 0, 0),)
    x0, x1 = sorted((0, dx))
    y0, y1 = sorted((0, dy))
    z0, z1 = sorted((0, dz))
    return tuple((a, b, c)
                 for a in range(x0, x1 + 1)
                 for b in range(y0, y1 + 1)
                 for c in range(z0, z1 + 1)
                 if (a, b, c) != (dx, dy, dz))


class Occupancy:
    """트랙이 이미 쓴 타일. 자기충돌 검사용.

    z 를 정확히 비교하면 안 된다. 게임은 트랙 위아래로 여유(clearance)를
    요구해서, 한두 칸 차이로 겹쳐 있는 트랙도 배치를 거부한다. ztol 은
    "이만큼 안에 다른 트랙이 있으면 겹친 걸로 본다"는 세로 여유.
    """

    __slots__ = ("cells", "ztol", "_band")

    def __init__(self, ztol=2, cells=(), _raw=None):
        self.ztol = ztol
        self._band = tuple(range(-ztol, ztol + 1))
        self.cells = set(_raw) if _raw is not None else set()
        if _raw is None:
            self.add(cells)

    def blocked(self, cells):
        # 조회가 A* 안쪽 루프라 여기서는 셀당 딱 한 번만 본다.
        have = self.cells
        for c in cells:
            if c in have:
                return True
        return False

    def add(self, cells):
        # 넣을 때 위아래 여유만큼 미리 펼쳐 둔다 (넣는 일은 훨씬 드물다).
        have = self.cells
        for x, y, z in cells:
            for dz in self._band:
                have.add((x, y, z + dz))

    def copy(self):
        return Occupancy(self.ztol, _raw=self.cells)


class Planner:
    def __init__(self, sim, piece_types):
        self.sim = sim
        self.pieces = tuple(piece_types)
        # (진입방향, 진입경사, 진입뱅크) -> 붙일 수 있는 조각들
        self.by_entry = {}
        self.templates = {}
        self.max_xy = 1
        self.max_axis = 1
        self.max_dz = 1
        # 실측 표를 쓴 조합 / 바운딩 박스로 때운 조합 (진단용)
        self.measured_used = 0
        self.estimated = 0
        measured = _measured_footprints()
        for t in self.pieces:
            for d in range(4):
                e = sim.geo.get(f"{t}:{d}")
                if e is None or e.get("beginSlope") is None:
                    continue
                k = (d, e["beginSlope"], e["beginBank"])
                self.by_entry.setdefault(k, []).append((t, e))
                # 진입 타일 기준 상대 좌표로 미리 굳혀 둔다. A* 안쪽 루프에서
                # geometry dict 를 다시 뒤지지 않으려고.
                # 실측 표가 있으면 그걸 쓰고, 없는 조합만 바운딩 박스로 때운다.
                cells = measured.get(f"{t}:{d}")
                if cells is None:
                    cells = _footprint_deltas(e["dx"], e["dy"], e["dz"])
                    self.estimated += 1
                else:
                    self.measured_used += 1
                self.templates.setdefault(k, []).append((
                    t, e["dx"], e["dy"], e["dz"], e["outDirection"],
                    e["endSlope"], e["endBank"], cells,
                ))
                self.max_xy = max(self.max_xy, abs(e["dx"]) + abs(e["dy"]))
                self.max_axis = max(self.max_axis, abs(e["dx"]), abs(e["dy"]))
                self.max_dz = max(self.max_dz, abs(e["dz"]))

    # -- 기본 연산 -------------------------------------------------------
    def apply(self, s: State, e):
        return State(s.x + e["dx"], s.y + e["dy"], s.z + e["dz"],
                     e["outDirection"], e["endSlope"], e["endBank"])

    def successors(self, s: State):
        """(조각타입, 다음상태, 점유타일) 목록. 게임의 연결 규칙을 그대로 적용."""
        x, y, z = s.x, s.y, s.z
        out = []
        for t, dx, dy, dz, od, es, eb, deltas in self.templates.get(
                (s.direction, s.slope, s.bank), ()):
            out.append((
                t,
                State(x + dx, y + dy, z + dz, od, es, eb),
                tuple((x + a, y + b, z + c) for a, b, c in deltas),
            ))
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
             occupied=None, budget=40, max_expand=60000, exclude=()):
        """start 에서 goal 로 정확히 도달하는 조각열. 실패하면 None.

        occupied 는 Occupancy -- 자기 자신과 겹치지 않게 한다.
        budget 은 쓸 수 있는 최대 조각 수(=탐색 깊이 상한).
        exclude 는 아예 안 쓸 조각들.

        조각별 비용을 매겨 "싼 길"을 찾게도 해봤는데, 균일 비용일 때 잘 먹던
        가지치기가 풀려서 탐색이 몇십 배로 터졌다. 선호는 exclude 로 조각을
        빼고 두 번 부르는 쪽이 훨씬 싸게 먹힌다 (호출부 참고).
        """
        occupied = occupied if occupied is not None else Occupancy()
        if self.h(start, goal) > budget:
            return None

        openq = [(self.h(start, goal), 0, start.key(), start, ())]
        best = {start.key(): 0}
        expand = 0
        while openq:
            f, g, _k, s, path = heapq.heappop(openq)
            if s.key() == goal.key():
                return list(path)
            if g > best.get(s.key(), 1 << 30):
                continue
            expand += 1
            if expand > max_expand:
                return None
            if g >= budget:
                continue
            for t, nxt, cells in self.successors(s):
                if t in exclude:
                    continue
                if bounds is not None and not _in_bounds(bounds, nxt):
                    continue
                if nxt.key() != goal.key() and occupied.blocked(cells):
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

    def plan_safe(self, start: State, goal: State, bounds: Bounds = None,
                  occupied=None, budget=40, max_expand=60000, exclude=(),
                  repairs=4):
        """plan() 과 같지만 **꼬리가 자기 자신과 안 겹치는 것까지** 보장한다.

        plan() 의 A* 는 넘겨받은 occupied 만 본다. 경로가 진행하며 새로 쓰는
        타일은 추적하지 않아서 꼬리가 자기 자신을 가로지를 수 있다.
        2026-09-13 실측: 남은 배치 거부의 77% 가 이것이었다 ("파이썬도 그 자리에
        트랙이 있는 걸 아는데 거기 놨다"로 잡혔다).

        노드마다 점유 집합을 들고 다니면 best[] 의 지배 관계가 깨져서 (같은
        상태라도 지나온 타일이 다르면 다른 노드다) 탐색이 터진다. 그래서 나온
        답을 검사하고, 겹치면 겹치기 직전까지의 타일을 막고 다시 부른다.
        """
        occupied = occupied if occupied is not None else Occupancy()
        work = occupied
        for _ in range(repairs + 1):
            tail = self.plan(start, goal, bounds, work, budget, max_expand,
                             exclude)
            if tail is None:
                return None
            used, s, hit = Occupancy(work.ztol), start, None
            for i, t in enumerate(tail):
                nxt, cells = next(((n, c) for tt, n, c in self.successors(s)
                                   if tt == t), (None, None))
                if nxt is None:
                    hit = (i, ())
                    break
                if used.blocked(cells):
                    hit = (i, cells)
                    break
                used.add(cells)
                s = nxt
            if hit is None:
                return tail                      # 자기교차 없음
            # 겹치기 직전까지 쓴 타일을 막고 다시 찾는다.
            work = work.copy()
            work.cells |= used.cells
        return None

    # -- 무작위 워크 ------------------------------------------------------
    def _has_exit(self, s: State, bounds: Bounds, occ, extra=()):
        """이 상태에서 놓을 수 있는 조각이 하나라도 있나 (막다른 길 판정).

        extra 는 아직 occ 에 안 넣은 타일들 (지금 놓으려는 조각 자신).
        Occupancy 를 통째로 복사하면 워크 스텝마다 수천 개를 베끼게 되므로
        작은 집합으로 따로 본다.
        """
        band = occ._band
        blocked = {(x, y, z + dz) for x, y, z in extra for dz in band}
        for _t, nxt, cells in self.successors(s):
            if not _in_bounds(bounds, nxt) or occ.blocked(cells):
                continue
            if any(c in blocked for c in cells):
                continue
            return True
        return False

    def wander(self, start: State, goal: State, bounds: Bounds, occupied,
               steps, weights, reserve):
        """steps 개만큼 무작위로 뻗는다. 언제든 goal 로 닫을 여지를 남긴다.

        reserve 는 "닫는 데 남겨둘 조각 수". 매 스텝 h(다음상태, goal) <= reserve 를
        유지해서, 아무리 멀리 나가도 이론상 되돌아올 여지는 남긴다.
        (실제 닫기는 plan() 이 하고, 여기서는 h() 하한으로만 대충 걸러낸다.)

        **한 수 앞을 본다** (2026-09-20). RCT 조각은 예외 없이 한 칸 이상
        전진해서 제자리 회전이 없으므로, 부지 구석에서 벽을 마주보면 그 자리가
        끝이다. 실측: 워크가 중앙 **2스텝**만에 멈췄고 멈춘 이유는 거의 전부
        "모든 후보가 부지 밖"이었다. 트랙 길이가 468m 에서 포화된 원인이 이것이고,
        길이는 흥미도의 제일 강한 레버다 (50m 당 약 +0.15).
        그래서 다음 수가 막다른 길인 후보를 먼저 버린다. 전부 막다른 길이면
        어차피 끝이므로 그때는 원래대로 아무거나 고른다.
        """
        s = start
        seq = []
        occ = occupied.copy()
        for _ in range(steps):
            cands = []
            for t, nxt, cells in self.successors(s):
                if not _in_bounds(bounds, nxt):
                    continue
                if occ.blocked(cells):
                    continue
                if self.h(nxt, goal) > reserve:
                    continue
                cands.append((t, nxt, cells))
            if not cands:
                break
            alive = [c for c in cands if self._has_exit(c[1], bounds, occ, c[2])]
            cands = alive or cands
            ws = [weights.get(t, 1) for t, _, _ in cands]
            t, nxt, cells = random.choices(cands, weights=ws, k=1)[0]
            seq.append(t)
            occ.add(cells)
            s = nxt
        return seq, s, occ


def _in_bounds(b: Bounds, s: State):
    return (b.x_min <= s.x <= b.x_max and b.y_min <= s.y <= b.y_max
            and b.z_min <= s.z <= b.z_max)
