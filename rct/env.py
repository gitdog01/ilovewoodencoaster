"""고수준 환경 래퍼: 시퀀스 하나를 받아 짓고 평점을 돌려준다.

3단계 대량 라벨링의 작업 단위가 이 클래스다.
"""

import time

from . import constants as C
from .client import RCTClient, RCTError


class WoodenCoasterEnv:
    def __init__(self, client: RCTClient, origin=(67, 66, 14), direction=0):
        self.c = client
        self.origin = origin
        self.direction = direction
        self.ride_object = self._find_wooden_object()
        self.ride_id = None

    def _find_wooden_object(self):
        for o in self.c.list_ride_objects():
            if C.RIDE_TYPE_WOODEN in o.get("rideType", []):
                return o["index"]
        raise RCTError(
            "우든 코스터 오브젝트가 로드되지 않았습니다. "
            "시나리오 편집기의 라이드 오브젝트 선택에서 Wooden Roller Coaster를 추가하세요."
        )

    # -- 에피소드 --------------------------------------------------------
    def reset(self, station_length=3):
        """공원을 비우고 새 라이드 + 스테이션까지 깔아둔다."""
        self.c.delete_all_rides()
        self.ride_id = self.c.create_ride(C.RIDE_TYPE_WOODEN, self.ride_object)

        x, y, z = self.origin
        pos = {"x": x, "y": y, "z": z, "direction": self.direction}
        self.anchor = dict(pos)

        pieces = [C.BEGIN_STATION] + [C.MIDDLE_STATION] * (station_length - 2) \
                 + [C.END_STATION]
        for t in pieces:
            p = self.c.place(self.ride_id, C.RIDE_TYPE_WOODEN,
                             pos["x"], pos["y"], pos["z"], pos["direction"], t)
            if p is None:
                raise RCTError(f"스테이션 배치 실패 @ {pos} type={t}. origin을 평지로 바꿔보세요.")
            pos = p["nextEndpoint"]

        self.c.place_entrance_exit(self.ride_id)
        self.pos = pos
        self.complete = False
        return dict(pos)

    def step(self, track_type, chain=False):
        """조각 하나 배치. (성공여부, 다음위치, 폐곡선여부)"""
        p = self.c.place(self.ride_id, C.RIDE_TYPE_WOODEN, self.pos["x"],
                         self.pos["y"], self.pos["z"], self.pos["direction"],
                         track_type, chain=chain)
        if p is None:
            return False, self.pos, False
        self.pos = p["nextEndpoint"]
        self.complete = bool(p.get("isCircuitComplete"))
        return True, dict(self.pos), self.complete

    def undo(self):
        p = self.c.delete_last(self.ride_id)
        if p and p.get("nextEndpoint"):
            self.pos = p["nextEndpoint"]
        return p

    def build(self, sequence, stop_on_complete=True):
        """[(track_type, chain), ...] 를 순서대로 배치."""
        placed = 0
        for track_type, chain in sequence:
            ok, _, complete = self.step(track_type, chain)
            if not ok:
                return placed, False
            placed += 1
            if complete and stop_on_complete:
                return placed, True
        return placed, self.complete

    # -- 평가 ------------------------------------------------------------
    def evaluate(self, timeout=90, poll=1.0):
        """테스트 주행 후 평점을 기다린다. 실패 시 None."""
        if not self.complete:
            return None
        self.c.start_test(self.ride_id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.c.stats(self.ride_id)
            if s and s.get("excitement", 0) > 0:
                return {
                    "excitement": s["excitement"],
                    "intensity": s["intensity"],
                    "nausea": s["nausea"],
                }
            time.sleep(poll)
        return None
