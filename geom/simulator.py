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
