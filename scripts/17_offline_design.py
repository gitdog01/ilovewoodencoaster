"""생성기 설정 변형을 게임 없이 짝지어 비교한다 (설계 단계 지표만).

    python scripts/17_offline_design.py --n 200 --variants base,small1,small2
    python scripts/17_offline_design.py --n 200 --variants base,small1 --hills 8-12

같은 시드로 sample 한 부지/리프트 설정을 변형마다 똑같이 넣어서 **짝지어** 잰다
(2026-09-20 에 40개 비짝 표본으로 잡음을 효과로 착각한 적이 있다).

지표는 gen/requirements.predict 가 보는 것 -- 낙하 수(게임과 100% 일치),
최고 낙하(100% 일치), 설계 길이 -- 와 설계 성공률. 에어타임/음의 G 는 게임에서만
나오므로 여기서 결론 내지 말 것. 평점 공식에서 낙하 1회는 흥미도 +0.069
(9회 상한), 최고 낙하 1 은 +0.003 이다 (scripts/16_rating_breakdown.py).
"""
import argparse
import os
import random
import statistics as st
import sys
import time

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

from gen.random_walk import plan_episode                 # noqa: E402
from gen.requirements import predict                     # noqa: E402
from geom.planner import State                           # noqa: E402
from geom.simulator import Bounds, TrackSimulator, station_tiles   # noqa: E402

ORIGIN, DIRECTION = (67, 66, 14), 0

VARIANTS = {
    "base":   {},
    "small0": {"hill_kmax": 0},
    "small1": {"hill_kmax": 1},
    "small2": {"hill_kmax": 2},
    "small3": {"hill_kmax": 3},
    # 언덕 사이 워크 길이 (기본 6). 0 이면 둔덕을 연달아 붙인다.
    "s0tight": {"hill_kmax": 0, "hill_spread": 2},
    "s1tight": {"hill_kmax": 1, "hill_spread": 2},
    "s0zero": {"hill_kmax": 0, "hill_spread": 0},
}


def sample(rng, hills_rng):
    """03_collect.sample_config 와 같은 분포 (gen11 기본값)."""
    width = rng.choice([20, 24, 28, 32, 36])
    depth = rng.choice([16, 20, 24, 28, 32])
    lift = rng.randint(10, 13) if rng.random() < 0.2 else rng.randint(6, 9)
    wander = rng.randint(20, min(120, 2 * (width + depth)))
    close = max(20, (width + depth) // 2 + 8)
    banked = rng.random() < 0.5
    hills = rng.randint(*hills_rng)
    return dict(width=width, depth=depth, lift=lift, wander=wander, close=close,
                banked=banked, hills=hills)


def design(sim, cfg, extra, seed):
    random.seed(seed)
    cells, end = station_tiles(sim, ORIGIN, DIRECTION, station_length=3)
    station_end = State(end.x, end.y, end.z, end.direction, 0, 0)
    goal = State(ORIGIN[0], ORIGIN[1], ORIGIN[2], DIRECTION, 0, 0)
    bounds = Bounds.plot(ORIGIN, DIRECTION, cfg["width"], cfg["depth"], 60)
    t0 = time.monotonic()
    seq = None
    for _ in range(6):      # generate_episode 의 build_attempts 와 같은 재시도
        seq = plan_episode(sim, station_end, goal, bounds, station_cells=cells,
                           lift_pieces=cfg["lift"], wander_steps=cfg["wander"],
                           close_budget=cfg["close"], banked=cfg["banked"],
                           hills=cfg["hills"], ztol=2, require=True,
                           **{"hill_spread": 6, **extra})
        if seq is not None:
            break
    return seq, time.monotonic() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--variants", default="base,small1")
    ap.add_argument("--hills", default="4-9", help="언덕 수 범위 (gen11 은 4-9)")
    args = ap.parse_args()
    hills_rng = tuple(int(v) for v in args.hills.split("-"))

    sim = TrackSimulator("geometry.json")
    names = args.variants.split(",")
    res = {v: [] for v in names}
    rng = random.Random(args.seed)
    for i in range(args.n):
        cfg = sample(rng, hills_rng)
        for v in names:
            seq, dt = design(sim, cfg, VARIANTS[v], args.seed * 100000 + i)
            res[v].append((seq, dt))
    print(f"n={args.n} hills={args.hills}")
    print(f"{'variant':<8} {'성공':>6} {'낙하 중앙':>8} {'낙하>=9':>8} {'최고낙하':>8} "
          f"{'길이 중앙':>9} {'조각 중앙':>9} {'설계초':>7}")
    for v in names:
        ok = [s for s, _ in res[v] if s]
        pr = [predict(s) for s in ok]
        print(f"{v:<8} {len(ok)/args.n:6.0%} "
              f"{st.median(p['drops'] for p in pr):8.1f} "
              f"{sum(p['drops'] >= 9 for p in pr)/max(1,len(pr)):8.0%} "
              f"{st.median(p['drop_height'] for p in pr):8.1f} "
              f"{st.median(p['length'] for p in pr):9.0f} "
              f"{st.median(len(s) for s in ok):9.0f} "
              f"{st.mean(dt for _, dt in res[v]):7.1f}")


if __name__ == "__main__":
    main()
