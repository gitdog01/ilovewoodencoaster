"""3단계: 절차적 생성 + 대량 라벨링 -> data/dataset.jsonl

트랙 설계는 전부 오프라인(gen/random_walk.py + geom/planner.py)에서 끝나고,
게임은 "짓고 평점 매기는 라벨러"로만 쓴다.

에피소드마다 부지/리프트 높이/본체 길이를 무작위로 흔든다. 한 가지 설정으로만
뽑으면 평점이 좁은 구간에 뭉쳐서(E 0.5 부근) 조건부 생성 학습에 쓸 게 없다.
"""
import sys, os, json, random, argparse

# 콘솔 코드페이지(한국어 Windows는 cp949)가 못 쓰는 문자 하나 때문에
# 20분짜리 수집이 UnicodeEncodeError로 통째로 죽는 걸 막는다.
# 실제로 실패 분기의 em-dash 하나 때문에 수집이 죽은 적이 있다.
sys.stdout.reconfigure(errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geom.simulator import Bounds, TrackSimulator
from gen.random_walk import generate_episode
from rct.client import RCTClient
from rct.env import WoodenCoasterEnv

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=50)
ap.add_argument("--out", default="data/dataset.jsonl")
ap.add_argument("--height", type=int, default=60)
ap.add_argument("--seed", type=int, default=None,
                help="병렬 수집 시 인스턴스마다 다른 값을 주면 겹치지 않는다.")
ap.add_argument("--speed", type=int, default=8,
                help="게임 시뮬레이션 속도 (평점 대기가 전체 시간의 대부분이라 "
                     "8로 올리면 트랙당 몇 배 빨라진다). 1이면 실시간.")
ap.add_argument("--port", type=int, default=None,
                help="특정 인스턴스에 붙는다 (병렬 수집용). "
                     "생략하면 기존처럼 첫 빈 포트를 자동 탐색.")
args = ap.parse_args()

random.seed(args.seed if args.seed is not None else os.getpid())

sim = TrackSimulator("geometry.json")
origin = (67, 66, 14)
DIRECTION = 0


def sample_config():
    """에피소드 한 개의 부지/모양 설정. 넓게 흔들어 평점 분포를 벌린다."""
    width = random.choice([20, 24, 28, 32, 36])
    depth = random.choice([16, 20, 24, 28, 32])
    lift = random.randint(3, 9)          # 더 높이면 격렬도가 10을 넘어 무용지물
    wander = random.randint(10, min(60, width + depth))
    close = max(20, (width + depth) // 2 + 8)
    # 뱅크(커빙) 성향. 켜면 좌우G가 내려가 격렬도가 낮은 순한 트랙, 끄면
    # 맨턴 위주로 격렬한 트랙이 나온다. 둘 다 있어야 조건부 생성이 배운다.
    banked = random.random() < 0.5
    return width, depth, lift, wander, close, banked


os.makedirs(os.path.dirname(args.out), exist_ok=True)
ok = 0
ports = [args.port] if args.port else range(8080, 8090)
with RCTClient.discover(ports=ports) as c, open(args.out, "a", encoding="utf-8") as fp:
    c.set_game_speed(args.speed)
    env = WoodenCoasterEnv(c, origin=origin)
    for i in range(args.n):
        width, depth, lift, wander, close, banked = sample_config()
        bounds = Bounds.plot(origin, DIRECTION, width, depth, args.height)
        seq = generate_episode(env, sim, bounds, max_pieces=250,
                               lift_pieces=lift, wander_steps=wander,
                               close_budget=close, banked=banked)
        if seq is None:
            print(f"[{i+1}/{args.n}] 폐곡선 실패 (w={width} d={depth} lift={lift})")
            continue
        stats = env.evaluate()
        if stats is None:
            print(f"[{i+1}/{args.n}] 평점 실패 (조각 {len(seq)}개) - "
                  "열차가 한 바퀴를 못 돌았을 가능성")
            continue
        fp.write(json.dumps({
            "sequence": seq, "stats": stats,
            "bounds": {"width": width, "depth": depth, "height": args.height},
            "lift_pieces": lift,
            "banked": banked,
            "station": 3,
        }, ensure_ascii=False) + "\n")
        fp.flush()
        ok += 1
        print(f"[{i+1}/{args.n}] E={stats['excitement']:.2f} "
              f"I={stats['intensity']:.2f} N={stats['nausea']:.2f} "
              f"좌우G={stats['maxLateralGs']:.2f} "
              f"({len(seq)}조각, w={width} d={depth} lift={lift}, "
              f"{'뱅크' if banked else '맨턴'})")
print(f"\n수집 완료: {ok}/{args.n} -> {args.out}")
