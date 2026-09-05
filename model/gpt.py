"""트랙 생성용 작은 GPT (4단계).

nanoGPT 급이다. 어휘가 83개, 시퀀스가 최대 128 토큰이라 LLM 스케일이 전혀
아니다 -- 기본 설정이 약 4.7M 파라미터로, 데이터(약 2M 토큰)에 비하면 오히려
넉넉한 편이라 과적합을 봐야 한다. 학습 스크립트가 train/val 손실을 같이 찍는다.
"""

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
from torch.nn import functional as F


@dataclass
class GPTConfig:
    vocab_size: int = 83
    block_size: int = 128
    n_layer: int = 6
    n_head: int = 8
    n_embd: int = 256
    dropout: float = 0.1


class CausalSelfAttention(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        assert cfg.n_embd % cfg.n_head == 0
        self.n_head, self.n_embd = cfg.n_head, cfg.n_embd
        self.attn = nn.Linear(cfg.n_embd, 3 * cfg.n_embd)
        self.proj = nn.Linear(cfg.n_embd, cfg.n_embd)
        self.drop = nn.Dropout(cfg.dropout)
        self.p = cfg.dropout

    def forward(self, x):
        B, T, C = x.shape
        q, k, v = self.attn(x).split(C, dim=2)
        # (B, n_head, T, head_dim)
        q, k, v = (t.view(B, T, self.n_head, C // self.n_head).transpose(1, 2)
                   for t in (q, k, v))
        y = F.scaled_dot_product_attention(
            q, k, v, dropout_p=self.p if self.training else 0.0, is_causal=True)
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        return self.drop(self.proj(y))


class Block(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.ln1 = nn.LayerNorm(cfg.n_embd)
        self.attn = CausalSelfAttention(cfg)
        self.ln2 = nn.LayerNorm(cfg.n_embd)
        self.mlp = nn.Sequential(
            nn.Linear(cfg.n_embd, 4 * cfg.n_embd), nn.GELU(),
            nn.Linear(4 * cfg.n_embd, cfg.n_embd), nn.Dropout(cfg.dropout))

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        return x + self.mlp(self.ln2(x))


class GPT(nn.Module):
    def __init__(self, cfg: GPTConfig):
        super().__init__()
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg.vocab_size, cfg.n_embd)
        self.pos_emb = nn.Embedding(cfg.block_size, cfg.n_embd)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layer))
        self.ln_f = nn.LayerNorm(cfg.n_embd)
        self.head = nn.Linear(cfg.n_embd, cfg.vocab_size, bias=False)
        self.tok_emb.weight = self.head.weight      # weight tying
        self.apply(self._init)
        for n, p in self.named_parameters():
            if n.endswith("proj.weight") or n.endswith("mlp.2.weight"):
                nn.init.normal_(p, std=0.02 / math.sqrt(2 * cfg.n_layer))

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, std=0.02)

    def n_params(self):
        return sum(p.numel() for p in self.parameters())

    def forward(self, idx, targets=None):
        B, T = idx.shape
        assert T <= self.cfg.block_size, f"{T} > block_size {self.cfg.block_size}"
        pos = torch.arange(T, device=idx.device)
        x = self.drop(self.tok_emb(idx) + self.pos_emb(pos))
        for blk in self.blocks:
            x = blk(x)
        logits = self.head(self.ln_f(x))
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)),
                                   targets.reshape(-1), ignore_index=-100)
        return logits, loss

    @torch.no_grad()
    def generate(self, idx, max_new_tokens, temperature=1.0, top_k=None,
                 allowed_fn=None, eos_id=None):
        """토큰을 이어붙인다.

        allowed_fn(생성된_토큰들) -> 허용 토큰 ID 목록 을 주면 매 스텝
        나머지를 -inf 로 막는다. 폐곡선/충돌은 학습으로 안 되므로(설계 결정 4)
        constrained decoding 자리를 여기에 열어둔다.
        """
        for _ in range(max_new_tokens):
            window = idx[:, -self.cfg.block_size:]
            logits, _ = self(window)
            logits = logits[:, -1, :] / max(temperature, 1e-6)
            if allowed_fn is not None:
                mask = torch.full_like(logits, float("-inf"))
                for b in range(logits.size(0)):
                    ok = allowed_fn(b, idx[b])
                    if ok:
                        mask[b, list(ok)] = 0.0
                logits = logits + mask
            if top_k:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = float("-inf")
            probs = F.softmax(logits, dim=-1)
            if torch.isnan(probs).any():
                break                      # 허용 토큰이 하나도 없으면 여기서 끝
            nxt = torch.multinomial(probs, 1)
            idx = torch.cat([idx, nxt], dim=1)
            if eos_id is not None and (nxt == eos_id).all():
                break
        return idx
