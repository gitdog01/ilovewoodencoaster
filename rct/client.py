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

        범위를 훑어서 **처음 응답하는** 인스턴스에 붙는다. 단일 인스턴스용이다.

        병렬 수집에는 쓰면 안 된다: 인스턴스를 여러 개 띄워도 discover()는 전부
        같은(가장 낮은) 포트에 붙어버린다. 병렬일 때는 `ports=[8081]` 처럼 포트를
        직접 지정할 것 (03_collect.py 의 `--port`). 인스턴스별 포트 고정은
        scripts/setup_instances.py 가 만들어준다.
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

    def ride_tiles(self, ride_id):
        """라이드가 실제로 점유한 타일 목록 (게임의 진짜 값).

        geom/planner.py 의 _footprint_deltas() 는 이걸 바운딩 박스로 추정하는데,
        그 추정이 맞는지 대조할 기준선이 여기다. baseZ/clearanceZ 는 raw 단위
        (8 = tileCoordinateZ 1칸).
        """
        return self.call("getRideTiles", {"rideId": ride_id})

    def find_free_plot(self, width, depth, direction=0, front=3, near=None):
        """width x depth 의 빈 평지를 찾아 스테이션 origin 을 돌려준다.

        생성기 origin 이 고정이라 요청할 때마다 같은 자리에 짓던 것을 푼다.
        타일을 하나씩 물어보면 부지 하나에 수백 번 왕복이라 게임 안에서 찾는다.
        """
        p = {"width": width, "depth": depth, "direction": direction,
             "front": front}
        if near:
            p["near"] = {"x": near[0], "y": near[1]}
        return self.call("findFreePlot", p, strict=False)

    def tile_elements(self, x, y):
        """타일 하나의 모든 엘리먼트 (지형/트랙/지지대/풍경).

        배치가 왜 거부됐는지 알려면 자기 트랙 말고 그 자리에 실제로 뭐가
        있는지를 봐야 한다.
        """
        return self.call("getTileElements", {"x": x, "y": y})

    def delete_ride(self, ride_id):
        """라이드 하나만 철거한다.

        유저 공원에 붙는 경로(생성기 UI)는 delete_all_rides() 를 쓰면 안 된다.
        수집기는 빈 공원을 전제로 하니 그쪽만 전체 삭제를 쓴다.
        """
        return self.call("deleteRide", {"rideId": ride_id}, strict=False)

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

    def set_game_speed(self, speed=8):
        """게임 시뮬레이션 속도. 8이면 라이드 테스트가 몇 초 만에 끝난다.

        평점은 시뮬레이션 시간 ~35초가 지나야 나오는데, 그동안 파이썬은
        그냥 기다리기만 한다. 대량 수집에서는 여기가 전체 시간의 대부분.
        """
        return self.call("setGameSpeed", {"speed": speed}, strict=False)

    def start_test(self, ride_id):
        return self.call("startRideTest", {"rideId": ride_id})

    def stats(self, ride_id):
        return self.call("getRideStats", {"rideId": ride_id}, strict=False)

    def measurements(self, ride_id):
        """평점 + 주행 실측값 (G, 에어타임, 속도, 낙하 수 ...).

        getRideStats 의 상위 집합. 격렬도가 왜 튀었는지는 평점 3개만 봐서는
        알 수 없고 maxLateralGs / maxPositiveVerticalGs 를 봐야 한다.
        """
        return self.call("getRideMeasurements", {"rideId": ride_id}, strict=False)
