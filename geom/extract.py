"""각 (조각, 진입방향) 조합을 실제로 배치해보고 좌표 델타를 측정한다.

산출물 geometry.json 이 있으면 게임 없이도 트랙 끝 좌표를 계산할 수 있다.
= 2단계 지오메트리 시뮬레이터의 원본 데이터.
"""

import json

from rct import constants as C
from rct.client import RCTClient


def extract(client: RCTClient, origin=(67, 66, 14), out="geometry.json"):
    segs = {s["type"]: s for s in client.all_track_segments()}
    wooden_obj = next(o["index"] for o in client.list_ride_objects()
                      if C.RIDE_TYPE_WOODEN in o.get("rideType", []))
    table = {}
    x0, y0, z0 = origin

    for track_type in sorted(segs):
        if track_type in C.STATION_PIECES:
            continue
        for direction in range(4):
            client.delete_all_rides()
            ride_id = client.create_ride(C.RIDE_TYPE_WOODEN, wooden_obj)

            p = client.place(ride_id, C.RIDE_TYPE_WOODEN, x0, y0, z0,
                             direction, C.BEGIN_STATION)
            if p is None:
                continue
            start = p["nextEndpoint"]

            p = client.place(ride_id, C.RIDE_TYPE_WOODEN, start["x"], start["y"],
                             start["z"], start["direction"], track_type)
            if p is None:
                continue
            end = p["nextEndpoint"]

            seg = segs[track_type]
            table[f"{track_type}:{direction}"] = {
                "type": track_type,
                "name": C.NAMES.get(track_type, seg.get("description")),
                "inDirection": direction,
                "dx": end["x"] - start["x"],
                "dy": end["y"] - start["y"],
                "dz": end["z"] - start["z"],
                "outDirection": end["direction"],
                "beginSlope": seg.get("beginSlope"),
                "endSlope": seg.get("endSlope"),
                "beginBank": seg.get("beginBank"),
                "endBank": seg.get("endBank"),
                "turnDirection": seg.get("turnDirection"),
            }
            print(f"  {track_type:>3} dir={direction} "
                  f"d=({end['x']-start['x']:>3},{end['y']-start['y']:>3},"
                  f"{end['z']-start['z']:>4}) out={end['direction']}  "
                  f"{C.NAMES.get(track_type,'?')}")

    client.delete_all_rides()
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False, indent=2)
    print(f"\n[OK] {len(table)}개 조합 -> {out}")
    return table
