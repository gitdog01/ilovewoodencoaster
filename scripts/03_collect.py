"""3단계: 절차적 생성 + 대량 라벨링 -> data/dataset.jsonl"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geom.simulator import Bounds, TrackSimulator
from gen.random_walk import generate_episode
from rct.client import RCTClient
from rct.env import WoodenCoasterEnv

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=50)
ap.add_argument("--out", default="data/dataset.jsonl")
ap.add_argument("--width", type=int, default=24)
ap.add_argument("--depth", type=int, default=24)
ap.add_argument("--height", type=int, default=48)
args = ap.parse_args()

sim = TrackSimulator("geometry.json")
origin = (67, 66, 14)
bounds = Bounds.around(origin, args.width, args.depth, args.height)

os.makedirs(os.path.dirname(args.out), exist_ok=True)
ok = 0
with RCTClient.discover() as c, open(args.out, "a", encoding="utf-8") as fp:
    env = WoodenCoasterEnv(c, origin=origin)
    for i in range(args.n):
        seq = generate_episode(env, sim, bounds)
        if seq is None:
            print(f"[{i+1}/{args.n}] 폐곡선 실패")
            continue
        stats = env.evaluate()
        if stats is None:
            print(f"[{i+1}/{args.n}] 평점 실패 (조각 {len(seq)}개)")
            continue
        fp.write(json.dumps({
            "sequence": seq, "stats": stats,
            "bounds": {"width": args.width, "depth": args.depth, "height": args.height},
            "station": 3,
        }, ensure_ascii=False) + "\n")
        fp.flush()
        ok += 1
        print(f"[{i+1}/{args.n}] E={stats['excitement']:.2f} "
              f"I={stats['intensity']:.2f} N={stats['nausea']:.2f} "
              f"({len(seq)}조각)")
print(f"\n수집 완료: {ok}/{args.n} -> {args.out}")
