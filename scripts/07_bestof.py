"""완성된 파이프라인: 목표를 주면 트랙 하나를 내놓는다 (설계 결정 5).

    python scripts/07_bestof.py --exc 5 --int 8 --latg 2.5 --n 16

LM 이 후보를 뽑고(조건부) -> A* 가 닫고 -> 게임이 채점하고 -> 최고를 고른다.
5단계 플러그인 UI 가 결국 이 흐름을 감싸게 된다.

OpenRCT2 인스턴스가 떠 있어야 한다:
    python scripts/run_instances.py --n 1 --headless
"""
import argparse
import os
import sys

sys.stdout.reconfigure(errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from geom.simulator import Bounds, TrackSimulator
from model.bestof import pick_best
from model.gpt import GPT, GPTConfig
from model.hybrid import generate_closed, station_states
from model.tokenizer import TrackTokenizer
from rct import constants as C
from rct.client import RCTClient
from rct.env import WoodenCoasterEnv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGIN = (67, 66, 14)
DIRECTION = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=os.path.join(REPO, "model", "ckpt.pt"))
    ap.add_argument("--exc", type=float, default=5.0, help="목표 흥미도")
    ap.add_argument("--int", dest="intensity", type=float, default=8.0,
                    help="목표 격렬도")
    ap.add_argument("--nau", type=float, default=3.0, help="목표 멀미도")
    ap.add_argument("--latg", type=float, default=2.5, help="목표 좌우G")
    ap.add_argument("--width", type=int, default=28)
    ap.add_argument("--depth", type=int, default=24)
    ap.add_argument("--n", type=int, default=16, help="뽑을 후보 수")
    ap.add_argument("--build", type=int, default=10, help="실제로 지어볼 개수")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--cap", type=float, default=10.0,
                    help="격렬도 상한. 넘으면 손님이 안 타므로 실격.")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = TrackTokenizer()
    ck = torch.load(args.ckpt, map_location=device, weights_only=False)
    model = GPT(GPTConfig(**ck["cfg"])).to(device)
    model.load_state_dict(ck["model"])
    model.eval()

    sim = TrackSimulator("geometry.json")
    bounds = Bounds.plot(ORIGIN, DIRECTION, args.width, args.depth, 60)
    start, goal, st_tiles = station_states(sim, ORIGIN, DIRECTION, 3)
    target = {"exc": args.exc, "int": args.intensity,
              "nau": args.nau, "latg": args.latg}
    cond = dict(target, width=args.width, depth=args.depth, height=60, station=3)

    print(f"목표: 흥미 {args.exc} / 격렬 {args.intensity} / 멀미 {args.nau} "
          f"/ 좌우G {args.latg}   (격렬도 상한 {args.cap})")
    print(f"부지: {args.width} x {args.depth}\n")

    seqs = generate_closed(model, tok, cond, sim, bounds, start, goal,
                           args.n, device, temperature=args.temperature,
                           station_tiles=st_tiles)
    print(f"후보 생성: {len(seqs)}/{args.n} 폐곡선 성공")
    if not seqs:
        sys.exit("폐곡선 후보를 못 만들었습니다. --n 을 늘려보세요.")

    ports = [args.port] if args.port else range(8080, 8110)
    client = RCTClient.discover(ports=ports)
    client.set_game_speed(8)
    env = WoodenCoasterEnv(client, origin=ORIGIN)

    print("\n게임 채점:")
    seq, stats, tried = pick_best(env, seqs, target, limit=args.build,
                                  intensity_cap=args.cap)
    built = sum(1 for t in tried if t["ok"])
    print(f"\n  지어진 것 {built}/{len(tried)}")
    if seq is None:
        sys.exit("조건을 만족하는 트랙이 없습니다. --n 을 늘리거나 목표를 완화하세요.")

    print(f"\n[선택된 트랙] 조각 {len(seq)}개")
    print(f"  흥미도 {stats['excitement']:.2f}  (목표 {args.exc})")
    print(f"  격렬도 {stats['intensity']:.2f}  (목표 {args.intensity}, 상한 {args.cap})")
    print(f"  멀미도 {stats['nausea']:.2f}  (목표 {args.nau})")
    print(f"  좌우G  {stats['maxLateralGs']:.2f}  (목표 {args.latg})")
    print(f"  최고속도 {stats['maxSpeed']}  최고낙하 {stats['highestDropHeight']}")

    # 마지막에 선택된 트랙을 게임에 남겨둔다 (눈으로 확인할 수 있게).
    env.reset(station_length=3)
    env.build(seq)
    print("\n선택된 트랙을 공원에 남겨뒀습니다.")


if __name__ == "__main__":
    main()
