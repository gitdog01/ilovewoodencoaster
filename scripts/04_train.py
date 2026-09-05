"""4단계: 조건부 트랙 생성 모델 학습.

    python scripts/04_train.py --steps 4000

data/dataset.jsonl (build_dataset.py 로 만든 것)을 읽어 작은 GPT를 학습한다.
train/val 손실을 같이 찍는다 -- 데이터가 약 2M 토큰뿐이라 과적합이 기본값이고,
val 이 갈라지는 지점을 봐야 한다.
"""
import argparse
import math
import os
import random
import sys
import time

sys.stdout.reconfigure(errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from model.data import TrackDataset
from model.gpt import GPT, GPTConfig
from model.tokenizer import TrackTokenizer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument("--data", default=os.path.join(REPO, "data", "dataset.jsonl"))
ap.add_argument("--out", default=os.path.join(REPO, "model", "ckpt.pt"))
ap.add_argument("--steps", type=int, default=4000)
ap.add_argument("--batch-size", type=int, default=64)
ap.add_argument("--lr", type=float, default=3e-4)
ap.add_argument("--warmup", type=int, default=100)
ap.add_argument("--eval-every", type=int, default=250)
ap.add_argument("--eval-batches", type=int, default=20)
ap.add_argument("--n-layer", type=int, default=6)
ap.add_argument("--n-head", type=int, default=8)
ap.add_argument("--n-embd", type=int, default=256)
ap.add_argument("--dropout", type=float, default=0.1)
ap.add_argument("--seed", type=int, default=0)
args = ap.parse_args()

torch.manual_seed(args.seed)
device = "cuda" if torch.cuda.is_available() else "cpu"

tok = TrackTokenizer()
ds = TrackDataset(args.data, tok)
print(ds, f"device={device}")

cfg = GPTConfig(vocab_size=len(tok), block_size=128, n_layer=args.n_layer,
                n_head=args.n_head, n_embd=args.n_embd, dropout=args.dropout)
model = GPT(cfg).to(device)
print(f"파라미터 {model.n_params()/1e6:.2f}M")

opt = torch.optim.AdamW(model.parameters(), lr=args.lr, betas=(0.9, 0.95),
                        weight_decay=0.1)
rng = random.Random(args.seed)


def lr_at(step):
    """워밍업 후 코사인 감쇠."""
    if step < args.warmup:
        return args.lr * (step + 1) / args.warmup
    t = (step - args.warmup) / max(1, args.steps - args.warmup)
    return args.lr * 0.5 * (1 + math.cos(math.pi * t))


@torch.no_grad()
def evaluate():
    model.eval()
    out = {}
    for split in ("train", "val"):
        tot = 0.0
        for _ in range(args.eval_batches):
            x, y = ds.batch(split, args.batch_size, device, rng)
            _, loss = model(x, y)
            tot += loss.item()
        out[split] = tot / args.eval_batches
    model.train()
    return out


best = float("inf")
t0 = time.time()
for step in range(args.steps):
    for g in opt.param_groups:
        g["lr"] = lr_at(step)
    x, y = ds.batch("train", args.batch_size, device, rng)
    _, loss = model(x, y)
    opt.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step()

    if (step + 1) % args.eval_every == 0 or step == args.steps - 1:
        m = evaluate()
        el = time.time() - t0
        flag = ""
        if m["val"] < best:
            best = m["val"]
            torch.save({"model": model.state_dict(), "cfg": cfg.__dict__,
                        "step": step + 1, "val_loss": best}, args.out)
            flag = "  <- 저장"
        print(f"[{step+1:5d}/{args.steps}] train {m['train']:.4f}  "
              f"val {m['val']:.4f}  lr {lr_at(step):.2e}  {el/60:.1f}분{flag}")

print(f"\n끝. 최고 val 손실 {best:.4f} -> {args.out}")
