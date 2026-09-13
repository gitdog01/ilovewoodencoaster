"""게임 없이 트랙 시퀀스를 따라가는 순수 파이썬 시뮬레이터.

constrained decoding의 심장. 매 스텝에서 "이 조각을 놓으면 어디로 가는가",
"부지를 벗어나는가", "스테이션으로 돌아올 수 있는가"를 게임에 묻지 않고 판단한다.

주의(TODO): 현재는 조각의 시작/끝 타일만 추적한다. 5칸 턴처럼 여러 타일을
차지하는 조각의 중간 타일 점유는 아직 계산하지 않으므로 자기충돌 검사가
완전하지 않다. 최종 검증은 게임에 맡기고, 여기서는 빠른 사전 필터로 쓴다.
"""

import json
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Pos:
    x: int
    y: int
    z: int
    direction: int

    def key(self):
        return (self.x, self.y, self.z, self.direction)


@dataclass
class Bounds:
    """유저가 지정하는 부지 제약."""
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    z_min: int
    z_max: int

    @classmethod
    def around(cls, origin, width, depth, height, z_slack=8):
        x, y, z = origin
        return cls(x - width // 2, x + width // 2,
                   y - depth // 2, y + depth // 2,
                   z - z_slack, z + height)

    @classmethod
    def plot(cls, origin, direction, width, depth, height, front=3):
        """스테이션을 부지 가장자리에 두는 부지.

        around()는 origin(=스테이션 진입점)을 한가운데 두는데, 트랙은 스테이션이
        바라보는 방향으로만 뻗어나가므로 절반이 낭비되고 리프트 언덕이 곧장
        부지 밖으로 나간다. 여기서는 width 를 "진행 방향 깊이", depth 를
        "좌우 폭"으로 보고 스테이션 뒤로는 front 칸만 남긴다.

        direction: 0=-x, 1=+y, 2=+x, 3=-y (게임의 방향 인코딩).
        """
        x, y, z = origin
        if direction in (0, 2):
            sx = -1 if direction == 0 else 1
            xs = sorted((x - sx * front, x + sx * width))
            ys = (y - depth // 2, y + depth // 2)
        else:
            sy = 1 if direction == 1 else -1
            ys = sorted((y - sy * front, y + sy * width))
            xs = (x - depth // 2, x + depth // 2)
        return cls(xs[0], xs[1], ys[0], ys[1], z, z + height)

    def contains(self, p: Pos):
        return (self.x_min <= p.x <= self.x_max
                and self.y_min <= p.y <= self.y_max
                and self.z_min <= p.z <= self.z_max)


class TrackSimulator:
    def __init__(self, geometry_path="geometry.json"):
        with open(geometry_path, encoding="utf-8") as fp:
            self.geo = json.load(fp)

    def delta(self, track_type, direction):
        return self.geo.get(f"{track_type}:{direction}")

    def advance(self, pos: Pos, track_type):
        """조각 하나를 적용한 다음 위치. 정의되지 않은 조합이면 None."""
        d = self.delta(track_type, pos.direction)
        if d is None:
            return None
        return Pos(pos.x + d["dx"], pos.y + d["dy"], pos.z + d["dz"],
                   d["outDirection"])

    def walk(self, start: Pos, sequence):
        """시퀀스를 따라가며 모든 중간 위치를 반환."""
        pos, path = start, [start]
        for t in sequence:
            nxt = self.advance(pos, t)
            if nxt is None:
                return path, False
            pos, _ = nxt, path.append(nxt)
        return path, True

    # -- 마스킹 ----------------------------------------------------------
    def legal_moves(self, pos: Pos, candidates, bounds: Bounds = None,
                    visited=None):
        """부지/중복을 위반하지 않는 후보만 남긴다.

        candidates 는 게임의 getValidNextPieces 결과(연결 규칙 통과분)를 넣는다.
        """
        out = []
        for t in candidates:
            nxt = self.advance(pos, t)
            if nxt is None:
                continue
            if bounds is not None and not bounds.contains(nxt):
                continue
            if visited is not None and nxt.key() in visited:
                continue
            out.append(t)
        return out

    def closable(self, pos: Pos, anchor: Pos, remaining, z_unit=8):
        """남은 조각 수로 anchor 까지 돌아갈 가능성이 있는지 낙관적 하한.

        admissible heuristic 이라 True 라고 반드시 닫히는 건 아니지만,
        False 면 확실히 못 닫으므로 가지치기에 쓸 수 있다.
        """
        manhattan = abs(pos.x - anchor.x) + abs(pos.y - anchor.y)
        drops = abs(pos.z - anchor.z) // z_unit
        turns = 0 if pos.direction == anchor.direction else 1
        return remaining >= manhattan + drops + turns


def station_tiles(sim, origin, direction, station_length=3,
                  reserve_entrance=True):
    """스테이션이 점유하는 타일 + 끝 위치.

    반환: (타일목록, 끝 Pos). 스테이션 조각(1/2/3)은 geometry.json 에 없어서
    (01_extract_geometry.py 가 스테이션 "다음" 조각만 테스트한다) 기하학적으로
    동일한 FLAT 으로 따라간다. 검증: origin (67,66,14) dir=0 에서 3칸 ->
    (64,66,14) 로, 게임의 env.reset() 반환값과 정확히 일치한다.

    이 타일들을 점유로 안 잡으면 트랙 꼬리가 플랫폼 위를 지나는 설계가 나오고
    게임이 배치를 거부한다 (실측: 배치 실패의 절반 이상이 이것이었다).

    **끝 위치는 타일 목록에 안 넣는다** (2026-09-13). 게임이 내려준 실제
    스테이션 조각은 station_length 개뿐이고 (실측: (65,66)/(66,66)/(67,66)),
    그 다음 칸 (64,66) 은 첫 트랙 조각이 점유하는 자리다. 실측 footprint
    (footprints.json) 를 쓰면 조각이 **진입 타일부터** 깔리므로, 여기를
    점유로 넣으면 첫 조각부터 막힌다.

    reserve_entrance: 입구/출구 건물 자리도 막는다. 플러그인
    (entranceExitPositionsFor) 이 스테이션 타일의 수직 이웃에 짓는데 파이썬은
    그 존재를 몰라서, 트랙이 스테이션 옆으로 돌아오면 게임이 거부했다
    (실측: 거부 21건 중 12건). 건물이 z 로 5칸이라 층층이 넣는다.
    """
    from rct import constants as C
    p = Pos(origin[0], origin[1], origin[2], direction)
    tiles = [(p.x, p.y, p.z)]
    for _ in range(station_length):
        nxt = sim.advance(p, C.FLAT)
        if nxt is None:
            raise RuntimeError("스테이션을 따라갈 수 없습니다")
        p = nxt
        if len(tiles) < station_length:
            tiles.append((p.x, p.y, p.z))
    if reserve_entrance:
        for tx, ty, tz in list(tiles):
            for nx, ny in entrance_candidates(tx, ty, direction):
                tiles += [(nx, ny, tz), (nx, ny, tz + 2), (nx, ny, tz + 4)]
    return tiles, p


def entrance_candidates(x, y, direction):
    """입구/출구가 놓일 수 있는 자리 (스테이션 타일의 수직 이웃 두 칸).

    플러그인의 entranceExitPositionsFor 와 같은 규칙. 어느 쪽에 실제로
    지어질지는 플러그인의 스캔 순서에 달려 있어서 양쪽 다 막는다.
    """
    if direction in (0, 2):
        return ((x, y - 1), (x, y + 1))
    return ((x - 1, y), (x + 1, y))
