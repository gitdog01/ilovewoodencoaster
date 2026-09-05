"""4단계 평가: 조건을 주고 뽑아서, 조건이 실제로 먹히는지 본다.

    python scripts/05_sample.py --n 40

두 가지를 따로 본다.

1. **형식 유효성** -- 뽑은 조각열이 게임 규칙상 이어지는가, 부지 안에 있는가,
   스테이션으로 정확히 닫히는가. 설계 결정 4번대로 폐곡선은 학습으로 안 되므로
   여기가 낮게 나오는 건 예상된 것이고, 그래서 constrained decoding 이 필요하다.

2. **조건 반응성** -- 조건 토큰을 바꿨을 때 출력이 실제로 달라지는가.
   이게 안 되면 폐곡선을 아무리 고쳐도 조건부 생성이 아니다. 형식 유효성과
   독립적으로 재야 해서, 닫히지 않은 시퀀스도 조각 구성은 볼 수 있게 했다.
"""
import argparse
import collections
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from geom.planner import Occupancy, State
from geom.simulator import Bounds, TrackSimulator
from gen.random_walk import PLAIN_TURNS, planner_for
from model.gpt import GPT, GPTConfig
from model.tokenizer import TrackTokenizer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGIN = (67, 66, 14)
DIRECTION = 0

BANKED_TURNS = frozenset((22, 23, 44, 45))


def load(ckpt_path, device):
    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    cfg = GPTConfig(**ck["cfg"])
    model = GPT(cfg).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model, ck


def check(seq, sim, bounds):
    """조각열을 오프라인 시뮬레이터로 따라가 본다.

    반환: (규칙상_이어지는_조각수, 부지_안인가, 스테이션에_닫혔는가)
    """
    P = planner_for(sim)
    s = State(ORIGIN[0], ORIGIN[1] + 3, ORIGIN[2], DIRECTION, 0, 0)
    goal = State(ORIGIN[0], ORIGIN[1], ORIGIN[2], DIRECTION, 0, 0)
    occ = Occupancy(2)
    n_ok, inside = 0, True
    from geom.planner import _in_bounds
    for t, _chain in seq:
        hit = next(((nxt, cs) for tt, nxt, cs in P.successors(s) if tt == t), None)
        if hit is None:
            break                      # 게임 규칙상 이어붙일 수 없는 조각
        nxt, cs = hit
        n_ok += 1
        if not _in_bounds(bounds, nxt):
            inside = False
        occ.add(cs)
        s = nxt
    closed = (n_ok == len(seq) and s.key() == goal.key())
    return n_ok, inside, closed


def sample(model, tok, cond, n, device, temperature=0.9, top_k=None):
    ids = [tok.stoi["<bos>"]] + tok.encode_condition(**cond) + [tok.stoi["<sep>"]]
    x = torch.tensor([ids] * n, dtype=torch.long, device=device)
    out = model.generate(x, max_new_tokens=120, temperature=temperature,
                         top_k=top_k, eos_id=tok.stoi["<eos>"])
    # 배치로 뽑으면 generate 는 "전부" EOS 를 낼 때만 멈춘다. 행마다 자기 EOS
    # 에서 잘라야 한다 -- 안 자르면 EOS 뒤에 계속 붙은 토큰까지 세어서 길이가
    # 학습 분포(중앙 47)의 두 배로 나오고 유효성도 엉뚱하게 낮게 찍힌다.
    eos = tok.stoi["<eos>"]
    seqs = []
    for row in out.tolist():
        body = row[len(ids):]
        if eos in body:
            body = body[:body.index(eos)]
        seqs.append(tok.decode(body))
    return seqs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=os.path.join(REPO, "model", "ckpt.pt"))
    ap.add_argument("--n", type=int, default=40, help="조건마다 뽑을 개수")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--top-k", type=int, default=None)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = TrackTokenizer()
    model, ck = load(args.ckpt, device)
    print(f"체크포인트 step={ck['step']} val={ck['val_loss']:.4f}  device={device}")

    sim = TrackSimulator("geometry.json")
    bounds = Bounds.plot(ORIGIN, DIRECTION, 28, 24, 60)
    site = {"width": 28, "depth": 24, "height": 60, "station": 3}

    # 조건 반응성: 좌우G만 바꿔가며 나머지는 고정한다.
    # 좌우G 는 유일하게 연속인 지표라 조건 신호로 제일 낫다 (버킷 설계 참고).
    trials = [
        ("좌우G 낮게", dict(exc=2.5, int=3.0, nau=1.5, latg=1.2, **site)),
        ("좌우G 중간", dict(exc=2.5, int=3.0, nau=1.5, latg=2.2, **site)),
        ("좌우G 높게", dict(exc=2.5, int=3.0, nau=1.5, latg=3.2, **site)),
        ("격렬도 낮게", dict(exc=2.5, int=0.8, nau=1.5, latg=2.2, **site)),
        ("격렬도 높게", dict(exc=2.5, int=12.0, nau=1.5, latg=2.2, **site)),
        ("흥미도 높게", dict(exc=5.5, int=6.0, nau=3.5, latg=2.5, **site)),
    ]

    print(f"\n조건마다 {args.n}개 (temperature={args.temperature})\n")
    print(f"{'조건':<14} {'길이':>5} {'맨턴':>5} {'뱅크턴':>6} {'리프트':>6} "
          f"{'규칙OK':>7} {'부지내':>6} {'폐곡선':>6}")
    for label, cond in trials:
        seqs = sample(model, tok, cond, args.n, device, args.temperature, args.top_k)
        lens, plains, banks, lifts = [], [], [], []
        rule_ok = inside_ok = closed_ok = 0
        for s in seqs:
            if not s:
                continue
            lens.append(len(s))
            plains.append(sum(1 for t, _ in s if t in PLAIN_TURNS))
            banks.append(sum(1 for t, _ in s if t in BANKED_TURNS))
            lifts.append(sum(1 for _, c in s if c))
            n_ok, inside, closed = check(s, sim, bounds)
            rule_ok += (n_ok == len(s))
            inside_ok += inside
            closed_ok += closed
        n = max(1, len(lens))
        print(f"{label:<14} {st.median(lens):5.0f} {st.median(plains):5.1f} "
              f"{st.median(banks):6.1f} {st.median(lifts):6.1f} "
              f"{rule_ok/n*100:6.0f}% {inside_ok/n*100:5.0f}% {closed_ok/n*100:5.0f}%")

    print("\n폐곡선이 낮은 건 예상된 결과다 (설계 결정 4: 학습으로 안 됨).")
    print("여기서 봐야 할 건 조건별로 조각 구성이 실제로 갈리는가다.")


if __name__ == "__main__":
    main()
