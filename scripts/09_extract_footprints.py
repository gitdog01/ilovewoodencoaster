"""조각이 실제로 쓰는 타일을 게임에서 실측한다 -> footprints.json

    python scripts/09_extract_footprints.py --port 8080

**왜 필요한가.** `geom/planner.py` 의 `_footprint_deltas()` 는 조각이 어떤 타일을
차지하는지 진입/진출 바운딩 박스로 **추정**한다. `getAllTrackSegments` 가 블록
목록을 안 주기 때문이었다. 그 추정에 두 가지 문제가 있다 (2026-09-13 실측):

1. **위치가 한 조각 밀려 있다.** 게임은 조각을 **진입 타일부터** 놓고 진출 타일은
   안 쓴다. 추정은 정반대로 진입 타일을 빼고 진출 타일을 넣는다. 직선이
   이어지는 구간에서는 집합이 거의 같아서 여태 안 들켰다.
2. **과대 claim.** 트랙 하나에 21~115 타일을 실제보다 더 잡는다. 배치 거부를
   막아주는 대신 설계 공간을 그만큼 좁힌다.

이 스크립트는 조각을 하나 놓을 때마다 `getRideTiles` 를 찍어 **차집합**을 본다.
그러면 그 조각이 새로 차지한 타일이 정확히 나온다. 무작위 트랙을 여러 개
지으면서 어휘를 훑는다 (조각마다 적절한 진입 상태를 따로 만들 필요가 없다).

결과는 `(조각타입, 진입방향)` -> `[(dx, dy, dz), ...]` (진입 타일 기준 상대좌표).

**해봤지만 되돌린 것: z 두께 전개.** 조각은 z 로 두께가 있고(평지 3칸, 경사
조각은 6칸까지) `Occupancy` 는 균일한 ztol 밴드밖에 모른다. 그래서 baseZ~
clearanceZ 를 층층이 펼쳐 넣어봤는데 (조합당 셀 2.7 -> 11.3개), 실측 결과
**순손실이었다**: 배치 거부는 평균 4.2% -> 3.1% 로 1포인트 좋아지는 대신
폐곡선이 144/144 -> 128/144 (-11%) 로 깎였다. best-of-N 에서는 후보 수가 곧
품질이라 이 교환이 손해다. 다시 시도하려면 이 숫자보다 나은지부터 볼 것.
"""
import argparse
import collections
import json
import os
import sys
import time

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gen.random_walk import generate_episode          # noqa: E402
from geom.simulator import Bounds, TrackSimulator     # noqa: E402
from rct import constants as C                        # noqa: E402
from rct.client import RCTClient                      # noqa: E402
from rct.env import WoodenCoasterEnv                  # noqa: E402

ORIGIN = (67, 66, 14)
DIRECTION = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--tracks", type=int, default=25, help="지어볼 트랙 수")
    ap.add_argument("--out", default=os.path.join(REPO, "footprints.json"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fresh", action="store_true",
                    help="기존 footprints.json 을 버리고 새로 쓴다 (기본은 병합)")
    args = ap.parse_args()

    import random
    random.seed(args.seed)

    sim = TrackSimulator("geometry.json")
    c = RCTClient(port=args.port)
    c.set_game_speed(1)          # 평점은 안 볼 거라 속도를 올릴 필요가 없다
    env = WoodenCoasterEnv(c, origin=ORIGIN)

    # (type, in_direction) -> {상대좌표 튜플: 본 횟수}
    seen = collections.defaultdict(collections.Counter)
    conflicts = []
    t0 = time.time()

    for i in range(args.tracks):
        width = random.choice([24, 28, 32])
        depth = random.choice([20, 24, 28])
        bounds = Bounds.plot(ORIGIN, DIRECTION, width, depth, 60)
        seq = generate_episode(env, sim, bounds, max_pieces=250,
                               lift_pieces=random.randint(4, 9),
                               wander_steps=random.randint(20, 45),
                               close_budget=28,
                               banked=random.random() < 0.5)
        if seq is None:
            continue

        env.reset(station_length=3, clear="all")
        prev = {(t["x"], t["y"], t["baseZ"]) for t in c.ride_tiles(env.ride_id)["tiles"]}
        for ttype, chain in seq:
            before = dict(env.pos)
            ok, _pos, _done = env.step(ttype, chain)
            if not ok:
                break
            now = {(t["x"], t["y"], t["baseZ"]) for t in c.ride_tiles(env.ride_id)["tiles"]}
            added = now - prev
            prev = now
            if not added:
                continue
            # 진입 타일 기준 상대좌표. z 는 tileCoordinateZ (raw / 8).
            rel = tuple(sorted((x - before["x"], y - before["y"],
                                bz // 8 - before["z"]) for x, y, bz in added))
            key = (ttype, before["direction"])
            seen[key][rel] += 1

        print(f"[{i+1}/{args.tracks}] 조각 {len(seq)}개, "
              f"조합 {len(seen)}개 수집, {time.time()-t0:.0f}초")

    # 같은 (조각, 방향) 에서 다른 모양이 나오면 기록해 둔다 (경사에 따라 dz 가
    # 달라질 수 있다 -- 그런 건 최빈값을 쓰되 눈에 띄게 남긴다).
    out = {}
    for (ttype, direction), shapes in sorted(seen.items()):
        best, n = shapes.most_common(1)[0]
        out[f"{ttype}:{direction}"] = {
            "type": ttype,
            "name": C.NAMES.get(ttype, str(ttype)),
            "direction": direction,
            "cells": [list(x) for x in best],
            "n": n,
            "variants": len(shapes),
        }
        if len(shapes) > 1:
            conflicts.append((C.NAMES.get(ttype, ttype), direction, len(shapes),
                              dict(shapes.most_common(3))))

    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(f"\n{len(out)}개 조합 -> {args.out}")

    if conflicts:
        print(f"\n모양이 여러 개인 조합 {len(conflicts)}개 "
              "(대개 경사에 따라 dz 가 달라지는 것. 최빈값을 썼다):")
        for name, d, k, _ in conflicts[:12]:
            print(f"  {name:<28} dir={d}  모양 {k}종")

    c.delete_all_rides()


if __name__ == "__main__":
    main()
