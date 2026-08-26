"""ridecreation-api 플러그인용 TCP JSON 클라이언트."""

import json
import socket

DEFAULT_HOST = "127.0.0.1"
PORT_RANGE = range(8080, 8090)


class RCTError(RuntimeError):
    pass


class RCTClient:
    def __init__(self, host=DEFAULT_HOST, port=8080, timeout=60):
        self.host, self.port = host, port
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.f = self.sock.makefile("r", encoding="utf-8")
        self._segs_cache = None

    # -- 연결 ------------------------------------------------------------
    @classmethod
    def discover(cls, host=DEFAULT_HOST, ports=PORT_RANGE, verbose=True):
        """플러그인이 잡은 포트를 자동으로 찾는다.

        플러그인은 8080부터 시작해 사용 중이면 위로 올라가며 첫 빈 포트를 잡는다.
        headless 인스턴스를 여러 개 띄울 때도 이 함수로 각각 찾으면 된다.
        """
        for port in ports:
            try:
                c = cls(host, port, timeout=2)
                c.call("listAllRides")
                c.sock.settimeout(60)
                if verbose:
                    print(f"[rct] 연결됨 {host}:{port}")
                return c
            except Exception:
                continue
        raise RCTError(
            "플러그인을 찾지 못했습니다. 확인할 것:\n"
            "  1) openrct2.com 으로 실행했는지\n"
            "  2) 타이틀이 아니라 공원을 로드했는지\n"
            "  3) plugin 폴더에 빌드된 .js 가 있는지"
        )

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- 프로토콜 --------------------------------------------------------
    def call_full(self, endpoint, params=None):
        """success 여부와 무관하게 원본 응답 dict를 그대로 반환한다.

        일부 엔드포인트(예: 스테이션 조각 placeTrackPiece)는 게임에는 실제로
        반영되면서도 응답 조립 과정에서만 실패하는 플러그인 버그가 있어,
        error 메시지를 직접 들여다봐야 할 때 call() 대신 이걸 쓴다.
        """
        req = {"endpoint": endpoint}
        if params:
            req["params"] = params
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        line = self.f.readline()
        if not line:
            raise RCTError("연결이 끊겼습니다 (공원을 닫았거나 게임이 종료됨)")
        return json.loads(line)

    def call(self, endpoint, params=None, strict=True):
        resp = self.call_full(endpoint, params)
        if not resp.get("success"):
            if strict:
                raise RCTError(f"[{endpoint}] {resp.get('error')}")
            return None
        return resp.get("payload")

    # -- 엔드포인트 얇은 래퍼 ---------------------------------------------
    def list_ride_objects(self):
        return self.call("listLoadedRideObjects")

    def list_rides(self):
        return self.call("listAllRides")

    def delete_all_rides(self):
        return self.call("deleteAllRides")

    def all_track_segments(self):
        return self.call("getAllTrackSegments")

    def _z_offset(self, track_type):
        """조각의 진입 z 오프셋 (tileCoordinateZ 단위).

        게임은 일부 조각(주로 내리막류)의 트랙 엘리먼트 baseZ를 슬로프의
        "낮은 쪽" 기준으로 저장한다. 그래서 이런 조각은 실제 진입 높이보다
        beginZ만큼 낮은 z로 호출해야 이어붙는다 (raw 8 단위 = tileCoordinateZ 1칸).
        """
        if self._segs_cache is None:
            self._segs_cache = {s["type"]: s for s in self.all_track_segments()}
        seg = self._segs_cache.get(track_type)
        return (seg.get("beginZ", 0) // 8) if seg else 0

    def create_ride(self, ride_type, ride_object, colour1=0, colour2=0):
        return self.call("createRide", {
            "rideType": ride_type, "rideObject": ride_object,
            "entranceObject": 0, "colour1": colour1, "colour2": colour2,
        })["rideId"]

    def place_full(self, ride_id, ride_type, x, y, z, direction, track_type,
                   chain=False, brake_speed=0):
        """place()와 같은 요청을 보내되 원본 응답(dict)을 그대로 돌려준다."""
        return self.call_full("placeTrackPiece", {
            "tileCoordinateX": x, "tileCoordinateY": y, "tileCoordinateZ": z,
            "direction": direction, "ride": ride_id, "trackType": track_type,
            "rideType": ride_type, "brakeSpeed": brake_speed, "colour": 0,
            "seatRotation": 0, "trackPlaceFlags": 0, "isFromTrackDesign": True,
            "hasChainLift": bool(chain),
        })

    def place(self, ride_id, ride_type, x, y, z, direction, track_type,
              chain=False, brake_speed=0, strict=False):
        z -= self._z_offset(track_type)
        resp = self.place_full(ride_id, ride_type, x, y, z, direction, track_type,
                               chain, brake_speed)
        if not resp.get("success"):
            if strict:
                raise RCTError(f"[placeTrackPiece] {resp.get('error')}")
            return None
        return resp.get("payload")

    def delete_last(self, ride_id):
        return self.call("deleteLastTrackPiece", {"rideId": ride_id}, strict=False)

    def valid_next(self, ride_id):
        return self.call("getValidNextPieces", {"rideId": ride_id})

    def place_entrance_exit(self, ride_id):
        return self.call("placeEntranceExit", {"rideId": ride_id}, strict=False)

    def start_test(self, ride_id):
        return self.call("startRideTest", {"rideId": ride_id})

    def stats(self, ride_id):
        return self.call("getRideStats", {"rideId": ride_id}, strict=False)
