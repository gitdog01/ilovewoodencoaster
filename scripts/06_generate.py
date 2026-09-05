"""LM 제안 + A* 마무리로 폐곡선 트랙을 뽑고, 게임으로 검증한다 (설계 결정 5).

    python scripts/06_generate.py --n 24                # 오프라인만
    python scripts/06_generate.py --n 24 --verify       # 게임에 짓고 평점까지

--verify 는 OpenRCT2 인스턴스가 떠 있어야 한다:
    python scripts/run_instances.py --n 1 --headless

이게 프로젝트의 진짜 종단 시험이다. "조건이 먹힌다"를 지금까지는 조각 구성
(맨턴/뱅크턴 개수)으로만 봤는데, 여기서는 **요청한 목표값과 게임이 실제로 매긴
평점**을 직접 비교한다.
"""
import argparse
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from geom.planner import State
from geom.simulator import Bounds, TrackSimulator
from model.hybrid import generate_closed, station_states
from model.tokenizer import TrackTokenizer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGIN = (67, 66, 14)
DIRECTION = 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=os.path.join(REPO, "model", "ckpt.pt"))
    ap.add_argument("--n", type=int, default=24, help="조건마다 시도할 후보 수")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--close-budget", type=int, default=24)
    ap.add_argument("--width", type=int, default=28)
    ap.add_argument("--depth", type=int, default=24)
    ap.add_argument("--verify", action="store_true",
                    help="게임에 실제로 짓고 평점을 받아 요청값과 비교한다.")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = TrackTokenizer()
    from model.gpt import GPT, GPTConfig
    ck = torch.load(args.ckpt, map_location=device, weights_only=False)
    model = GPT(GPTConfig(**ck["cfg"])).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    print(f"체크포인트 step={ck['step']} val={ck['val_loss']:.4f}  device={device}")

    sim = TrackSimulator("geometry.json")
    bounds = Bounds.plot(ORIGIN, DIRECTION, args.width, args.depth, 60)
    site = {"width": args.width, "depth": args.depth, "height": 60, "station": 3}
    # 좌표는 가정하지 말고 시뮬레이터로 계산한다 (방향 0 은 -x 로 진행한다).
    start, goal = station_states(sim, ORIGIN, DIRECTION, site["station"])

    # 요청 목표값. 게임이 실제로 이 근처를 내주는지가 시험 대상이다.
    targets = [
        ("순한 트랙",   dict(exc=2.5, int=2.0, nau=1.0, latg=1.2, **site)),
        ("보통",       dict(exc=2.5, int=3.0, nau=1.5, latg=2.2, **site)),
        ("격렬하게",    dict(exc=5.5, int=8.0, nau=4.0, latg=3.0, **site)),
    ]

    env = None
    if args.verify:
        from rct.client import RCTClient
        from rct.env import WoodenCoasterEnv
        ports = [args.port] if args.port else range(8080, 8110)
        client = RCTClient.discover(ports=ports)
        client.set_game_speed(8)
        env = WoodenCoasterEnv(client, origin=ORIGIN)

    for label, cond in targets:
        seqs = generate_closed(model, tok, cond, sim, bounds, start, goal,
                               args.n, device, close_budget=args.close_budget,
                               temperature=args.temperature)
        lens = [len(s) for s in seqs]
        print(f"\n[{label}] 요청 exc={cond['exc']} int={cond['int']} "
              f"latg={cond['latg']}")
        print(f"  폐곡선 성공 {len(seqs)}/{args.n} "
              f"({len(seqs)/args.n*100:.0f}%)"
              + (f", 길이 중앙 {st.median(lens):.0f}" if lens else ""))
        if not (args.verify and seqs):
            continue

        got = []
        for seq in seqs[:8]:              # 게임 검증은 비싸니 앞의 몇 개만
            env.reset(station_length=3)
            placed, complete = env.build(seq)
            if not complete:
                continue
            stats = env.evaluate()
            if stats:
                got.append(stats)
        if not got:
            print("  게임 검증: 배치/평점 실패")
            continue
        print(f"  게임 검증 {len(got)}개 ->"
              f" 흥미 {st.median(s['excitement'] for s in got):.2f}"
              f" / 격렬 {st.median(s['intensity'] for s in got):.2f}"
              f" / 좌우G {st.median(s['maxLateralGs'] for s in got):.2f}")


if __name__ == "__main__":
    main()
