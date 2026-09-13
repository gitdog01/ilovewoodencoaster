"""고수준 환경 래퍼: 시퀀스 하나를 받아 짓고 평점을 돌려준다.

3단계 대량 라벨링의 작업 단위가 이 클래스다.
"""

import time

from . import constants as C
from .client import RCTClient, RCTError


class WoodenCoasterEnv:
    def __init__(self, client: RCTClient, origin=(67, 66, 14), direction=0,
                 brake_speed=25):
        self.c = client
        self.origin = origin
        self.direction = direction
        # 브레이크 조각을 놓을 때 쓸 속도. 0 이면 열차가 거기서 서서 평점이
        # 안 나온다 (실측). 40 이상은 배치가 거부된다. 어휘에 브레이크가 없으면
        # 이 값은 아무 데도 안 쓰인다.
        self.brake_speed = brake_speed
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
    def reset(self, station_length=3, clear="all"):
        """새 라이드 + 스테이션까지 깔아둔다.

        clear:
          "all"  공원의 라이드를 전부 지운다. **수집기 전용이다.**
                 빈 샌드박스를 전제로 하고, 평점이 주변 라이드에 영향받으므로
                 수집 때는 매번 비우는 게 맞다.
          "own"  이 env 가 직전에 만든 라이드만 지운다. 유저 공원에 붙는
                 경로(생성기 UI/데몬)는 반드시 이쪽이어야 한다 -- "all" 이면
                 유저가 지어둔 라이드까지 통째로 날아간다.
          None   아무것도 안 지운다. 후보를 남겨두고 비교하고 싶을 때.
        """
        if clear == "all":
            self.c.delete_all_rides()
        elif clear == "own":
            if self.ride_id is not None:
                self.c.delete_ride(self.ride_id)
        elif clear is not None:
            raise ValueError(f"clear 는 'all'/'own'/None 중 하나: {clear!r}")
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

        if self.c.place_entrance_exit(self.ride_id) is None:
            # strict=False라 조용히 실패할 수 있음 -- startRideTest가 나중에
            # 원인 모를 에러로 죽으면 대개 이게 원인이니 눈에 띄게 남겨둔다.
            print(f"[env] 경고: placeEntranceExit 실패 (ride {self.ride_id}). "
                  "테스트 시작이 나중에 실패할 수 있음.")
        self.pos = pos
        self.complete = False
        return dict(pos)

    def release(self):
        """지금 라이드를 "내 것"에서 놓아준다.

        clear="own" 은 이 env 가 만든 직전 라이드를 지우는데, 유저에게 완성품으로
        넘긴 트랙까지 그러면 다음 요청 때 방금 만들어준 코스터가 사라진다.
        넘기고 나면 이걸 불러서 env 가 잊게 한다.
        """
        rid, self.ride_id = self.ride_id, None
        return rid

    def step(self, track_type, chain=False):
        """조각 하나 배치. (성공여부, 다음위치, 폐곡선여부)"""
        p = self.c.place(self.ride_id, C.RIDE_TYPE_WOODEN, self.pos["x"],
                         self.pos["y"], self.pos["z"], self.pos["direction"],
                         track_type, chain=chain,
                         brake_speed=(self.brake_speed
                                      if track_type in C.BRAKES else 0))
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
    def evaluate(self, timeout=30, poll=0.25):
        """테스트 주행 후 평점을 기다린다. 실패 시 None.

        속도 8이면 평점이 나오기까지 실제로 몇 초면 되므로, timeout 은
        "열차가 한 바퀴를 못 돈다"를 빨리 포기하는 값으로 잡는다.
        """
        if not self.complete:
            return None
        try:
            self.c.start_test(self.ride_id)
        except RCTError as e:
            # 대량 수집 중 하나가 startRideTest에서 죽으면 배치 전체가 멈추므로,
            # 여기서 흡수하고 "평점 없음"으로 취급한다 (호출부가 이미 그렇게 처리함).
            print(f"[env] 테스트 시작 실패, 이 트랙은 건너뜀: {e}")
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.c.measurements(self.ride_id)
            if s and s.get("excitement", 0) > 0:
                return s
            time.sleep(poll)
        return None
