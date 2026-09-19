"""dataset.jsonl -> 학습용 토큰 배치 (4단계).

레코드 하나가 시퀀스 하나가 된다:
    [BOS] <조건 토큰들> [SEP] <트랙 토큰들> [EOS]

조건은 **게임이 매긴 실제 라벨**을 버킷팅해서 넣는다 (Decision Transformer).
추론 때는 유저가 원하는 목표값을 같은 자리에 넣으면 된다.

손실은 [SEP] 다음부터만 계산한다. 조건 프리픽스는 주어지는 입력이지
맞춰야 할 답이 아니다 -- 여기에 손실을 걸면 모델이 "조건 분포"를 외우는 데
용량을 쓴다.
"""

import json
import random

import torch

from model.tokenizer import TrackTokenizer

PAD_ID = 0          # tokenizer.SPECIAL[0] == "<pad>"
IGNORE = -100       # cross_entropy 가 무시하는 라벨


def condition_of(record):
    """레코드에서 조건 값을 뽑는다. 학습 라벨 = 게임이 매긴 실제 평점."""
    s, b = record["stats"], record["bounds"]
    return {
        "exc": s["excitement"], "int": s["intensity"], "nau": s["nausea"],
        "latg": s["maxLateralGs"],
        "width": b["width"], "depth": b["depth"], "height": b["height"],
        "station": record.get("station", 3),
    }


GEN_ORDER = ["gen1", "gen2", "gen3", "gen4", "gen5", "gen6"]


class TrackDataset:
    def __init__(self, path, tok=None, val_frac=0.05, seed=0, max_len=128,
                 min_gen="gen2"):
        """min_gen: 이 세대 미만인 레코드는 버린다 (build_dataset.py 의 gen_label).

        dataset.jsonl 은 `--min-gen` 없이 만들면 gen1 까지 다 들어간다.
        gen1 은 `banked` 플래그가 무효라 라벨이 오염돼 있고 격렬도가 10을
        한 번도 안 넘어서, 조건부 학습에 섞으면 안 된다 (CLAUDE.md 참고).
        걸러 쓰는 쪽이 기본이므로 여기서 한 번 더 막는다.
        """
        self.tok = tok or TrackTokenizer()
        self.max_len = max_len
        min_i = GEN_ORDER.index(min_gen) if min_gen else -1
        rows, self.dropped_gen = [], 0
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if min_i >= 0:
                    g = (r.get("meta") or {}).get("gen_label")
                    # 세대를 모르는 레코드는 남긴다 -- build_dataset 을 안 거친
                    # part 파일을 직접 물릴 때 전부 날아가면 곤란하다.
                    if g in GEN_ORDER and GEN_ORDER.index(g) < min_i:
                        self.dropped_gen += 1
                        continue
                rows.append(r)

        self.items, self.skipped = [], 0
        for r in rows:
            ids = self.tok.encode([tuple(p) for p in r["sequence"]],
                                  condition=condition_of(r))
            if len(ids) > max_len:
                self.skipped += 1     # p95가 69라 잘리는 건 극소수
                continue
            # [SEP] 다음부터가 정답 구간.
            sep = ids.index(self.tok.stoi["<sep>"])
            self.items.append((ids, sep))

        rng = random.Random(seed)
        rng.shuffle(self.items)
        n_val = max(1, int(len(self.items) * val_frac))
        self.val = self.items[:n_val]
        self.train = self.items[n_val:]

    def __repr__(self):
        return (f"<TrackDataset train={len(self.train)} val={len(self.val)} "
                f"skipped={self.skipped} dropped_gen={self.dropped_gen} "
                f"vocab={len(self.tok)}>")

    def batch(self, split, batch_size, device, rng=None):
        """(x, y) 배치. y 는 조건 프리픽스 자리가 IGNORE 로 마스킹돼 있다."""
        pool = self.train if split == "train" else self.val
        rng = rng or random
        picks = [pool[rng.randrange(len(pool))] for _ in range(batch_size)]
        width = max(len(ids) for ids, _ in picks)

        x = torch.full((batch_size, width - 1), PAD_ID, dtype=torch.long)
        y = torch.full((batch_size, width - 1), IGNORE, dtype=torch.long)
        for b, (ids, sep) in enumerate(picks):
            t = torch.tensor(ids, dtype=torch.long)
            x[b, :len(t) - 1] = t[:-1]
            # 위치 i 의 정답은 ids[i+1]. sep 이후의 토큰만 맞추게 한다.
            y[b, sep:len(t) - 1] = t[sep + 1:]
        return x.to(device), y.to(device)
