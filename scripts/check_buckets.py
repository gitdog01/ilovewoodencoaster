"""조건 토큰이 실제로 조건 노릇을 하는지 본다 (학습 전 점검).

    python scripts/check_buckets.py

`COND_SPECS` 의 버킷 경계는 **수집 분포에 맞춰 자른 값**이라, 수집기를 고치거나
데이터가 늘면 다시 맞는지 봐야 한다. 보는 건 두 가지다:

1. **빈 버킷.** 학습에서 한 번도 안 나온 조건 토큰은 임베딩이 초기값 그대로다.
   추론 때 유저가 그 버킷에 해당하는 값을 넣으면 모델이 처음 보는 토큰을 받는다.
2. **상수 버킷.** 한 버킷에 100% 가 몰리면 그 조건은 정보가 0이다. 프리픽스
   자리만 차지하고, UI 에서 그 값을 조절해도 모델은 반응할 수 없다.

실제로 2026-09-12 점검에서 `height` 와 `station` 이 둘 다 100% 한 버킷이었다.
수집기(`03_collect.py`)가 높이를 `--height` 고정값으로, 스테이션을 3으로만
쓰기 때문이다. 고치려면 `sample_config()` 가 그 둘도 흔들어야 한다.

시퀀스 길이도 같이 찍는다 -- `max_len` 을 넘는 레코드는 학습에서 통째로 버려진다.
"""
import argparse
import collections
import json
import os
import sys

sys.stdout.reconfigure(errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.data import condition_of                     # noqa: E402
from model.tokenizer import COND_SPECS, _bucket         # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(REPO, "data", "dataset.jsonl"))
    ap.add_argument("--max-len", type=int, default=128,
                    help="model/data.py 의 max_len 과 같은 값")
    ap.add_argument("--prefix", type=int, default=None,
                    help="프리픽스 토큰 수. 생략하면 COND_SPECS 에서 계산")
    args = ap.parse_args()

    # <bos> + 조건 토큰들 + <sep> ... <eos>
    prefix = args.prefix if args.prefix is not None else len(COND_SPECS) + 3

    counts = {k: collections.Counter() for k in COND_SPECS}
    lens = collections.Counter()
    gens = collections.Counter()
    n = 0
    with open(args.data, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            gens[(r.get("meta") or {}).get("gen_label", "없음")] += 1
            cond = condition_of(r)
            for name, edges in COND_SPECS.items():
                counts[name][_bucket(cond[name], edges)] += 1
            lens[len(r["sequence"])] += 1
            n += 1

    if not n:
        sys.exit(f"레코드가 없습니다: {args.data}")

    print(f"{args.data}\n  레코드 {n}개, 세대 {dict(gens.most_common())}\n")

    dead, empty = [], []
    for name, edges in COND_SPECS.items():
        cells = []
        for i in range(len(edges) - 1):
            c = counts[name][i]
            pct = 100 * c / n
            mark = "." if c else "X"      # X = 빈 버킷
            cells.append(f"{mark}{pct:5.1f}%")
            if not c:
                empty.append(f"{name}[{edges[i]},{edges[i + 1]})")
        top = max(counts[name].values())
        if top == n:
            dead.append(name)
        used = sum(1 for i in range(len(edges) - 1) if counts[name][i])
        print(f"  {name:8s} 버킷 {used}/{len(edges)-1} 사용  " + " ".join(cells))

    print()
    if dead:
        print(f"  [상수] {', '.join(dead)} -- 100%가 한 버킷이다. 조건으로 쓸 수 없다.")
    if empty:
        print(f"  [빈 버킷] {len(empty)}개: {', '.join(empty[:8])}"
              + (" ..." if len(empty) > 8 else ""))
    if not dead and not empty:
        print("  모든 조건 버킷이 살아 있다.")

    tot = sum(lens.values())
    keys = sorted(lens)
    print(f"\n  조각 수 {keys[0]}~{keys[-1]}", end="")
    for q in (0.5, 0.9, 0.99):
        acc = 0
        for k in keys:
            acc += lens[k]
            if acc >= tot * q:
                print(f", p{int(q * 100)}={k}", end="")
                break
    over = sum(v for k, v in lens.items() if k + prefix > args.max_len)
    print(f"\n  max_len={args.max_len} 초과로 버려지는 레코드: "
          f"{over}개 ({100 * over / tot:.2f}%)")


if __name__ == "__main__":
    main()
