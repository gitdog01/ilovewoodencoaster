"""geometry.json 에 빠진 "중간 경사" 조각을 다단계로 추출한다 (60도 계열).

    python scripts/14_extract_slopes.py --port 8095

**왜 따로 필요한가.** `01_extract_geometry.py` 는 각 조각을 **평지 스테이션 바로
뒤**에서만 시험한다. 게임 규칙상 `Up25ToUp60` 은 이미 up25 로 올라가는 중에만
놓을 수 있으므로 그 방식으로는 절대 안 잡힌다 (문서의 "중간 경사" 한계).
그래서 60도 계열 6종(5/7/8/11/13/14)이 163종짜리 표에서 빠져 있었다.

여기서는 목표 조각의 **진입 경사에 맞는 리드인**을 먼저 깔고 나서 측정한다:

    up25   진입 -> [FlatToUp25, Up25]
    up60   진입 -> [FlatToUp25, Up25, Up25ToUp60]
    down25 진입 -> [FlatToDown25, Down25]
    down60 진입 -> [FlatToDown25, Down25, Down25ToDown60]

측정은 리드인 **다음** 조각 하나의 좌표 변화만 본다 (`place()` 가 돌려주는
nextEndpoint 의 차). 경사/뱅크 값은 게임의 세그먼트 정보를 그대로 쓴다.

결과는 기존 `geometry.json` 에 **덧붙인다** (있는 항목은 안 건드린다).
새 조각을 어휘에 넣으면 `09_extract_footprints.py` 도 다시 돌려야 한다 --
`Planner` 가 실측 footprint 표를 우선 쓰기 때문이다.
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from rct import constants as C          # noqa: E402
from rct.client import RCTClient        # noqa: E402

# 진입 경사를 만들어주는 리드인. 조각 번호로 적는다 (경사 코드는 게임에서 읽는다).
LEAD_INS = {
    "up25": [C.FLAT_TO_UP25, C.UP25],
    "up60": [C.FLAT_TO_UP25, C.UP25, C.UP25_TO_UP60],
    "down25": [C.FLAT_TO_DOWN25, C.DOWN25],
    "down60": [C.FLAT_TO_DOWN25, C.DOWN25, C.DOWN25_TO_DOWN60],
}
# 60도 계열. (조각, 어떤 진입 경사가 필요한가)
TARGETS = [
    (C.UP25_TO_UP60, "up25"), (C.UP60, "up60"), (C.UP60_TO_UP25, "up60"),
    (C.DOWN25_TO_DOWN60, "down25"), (C.DOWN60, "down60"),
    (C.DOWN60_TO_DOWN25, "down60"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--out", default=os.path.join(REPO, "geometry.json"))
    # 내리막 리드인이 땅에 안 박히고 오르막이 지지대 한계에 안 걸리는 높이.
    ap.add_argument("--z", type=int, default=40)
    args = ap.parse_args()

    with open(args.out, encoding="utf-8") as fp:
        table = json.load(fp)
    before = len(table)

    c = RCTClient(port=args.port)
    segs = {s["type"]: s for s in c.all_track_segments()}
    obj = next(o["index"] for o in c.list_ride_objects()
               if C.RIDE_TYPE_WOODEN in o.get("rideType", []))

    added = 0
    for target, need in TARGETS:
        for direction in range(4):
            c.delete_all_rides()
            ride = c.create_ride(C.RIDE_TYPE_WOODEN, obj)
            p = c.place(ride, C.RIDE_TYPE_WOODEN, 67, 66, args.z, direction,
                        C.BEGIN_STATION)
            if p is None:
                print(f"  {target} dir={direction}: 스테이션 실패")
                continue
            at = p["nextEndpoint"]
            ok = True
            for piece in LEAD_INS[need]:
                p = c.place(ride, C.RIDE_TYPE_WOODEN, at["x"], at["y"], at["z"],
                            at["direction"], piece)
                if p is None:
                    print(f"  {target} dir={direction}: 리드인 {piece} 실패")
                    ok = False
                    break
                at = p["nextEndpoint"]
            if not ok:
                continue

            p = c.place(ride, C.RIDE_TYPE_WOODEN, at["x"], at["y"], at["z"],
                        at["direction"], target)
            if p is None:
                print(f"  {target} dir={direction}: 목표 조각 배치 거부")
                continue
            end = p["nextEndpoint"]
            seg = segs[target]
            table[f"{target}:{direction}"] = {
                "type": target,
                "name": C.NAMES.get(target, seg.get("description")),
                "inDirection": direction,
                "dx": end["x"] - at["x"], "dy": end["y"] - at["y"],
                "dz": end["z"] - at["z"],
                "outDirection": end["direction"],
                "beginSlope": seg.get("beginSlope"), "endSlope": seg.get("endSlope"),
                "beginBank": seg.get("beginBank"), "endBank": seg.get("endBank"),
                "turnDirection": seg.get("turnDirection"),
            }
            added += 1
            print(f"  {target:>3} dir={direction} d=({end['x']-at['x']:>3},"
                  f"{end['y']-at['y']:>3},{end['z']-at['z']:>4}) "
                  f"out={end['direction']} slope {seg.get('beginSlope')}->"
                  f"{seg.get('endSlope')}  {C.NAMES.get(target)}")
    c.delete_all_rides()
    c.close()

    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False, indent=2)
    print(f"\n[OK] {added}개 추가 ({before} -> {len(table)}) -> {args.out}")


if __name__ == "__main__":
    main()
