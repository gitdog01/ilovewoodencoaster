"""트랙 시퀀스 <-> 토큰 ID 변환 (4단계).

시퀀스 형태:
    [BOS] <조건 토큰들> [SEP] <트랙 토큰들> [EOS]

조건 토큰은 버킷팅된 목표값이다. 학습 때는 게임이 매긴 실제 라벨을 넣고,
추론 때는 유저가 플러그인 UI에 입력한 목표값을 넣는다 (Decision Transformer 방식).
"""

from rct import constants as C

SPECIAL = ["<pad>", "<bos>", "<eos>", "<sep>"]

# (조각, 체인리프트) 쌍이 하나의 토큰
TRACK_TOKENS = [(t, False) for t in C.BUILDABLE] + \
               [(t, True) for t in C.CHAINABLE]

COND_SPECS = {
    "exc":     [0, 3, 4, 5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 99],      # 흥미도
    "int":     [0, 3, 4, 5, 6, 7, 8, 9, 10, 99],                 # 격렬도
    "nau":     [0, 2, 3, 4, 5, 6, 99],                           # 멀미도
    "cost":    [0, 500, 1000, 1500, 2000, 3000, 5000, 10 ** 9],  # 건설비
    "width":   [0, 8, 12, 16, 20, 24, 32, 999],                  # 부지 가로
    "depth":   [0, 8, 12, 16, 20, 24, 32, 999],                  # 부지 세로
    "height":  [0, 16, 24, 32, 48, 64, 999],                     # 최대 높이
    "station": [0, 3, 4, 5, 6, 7, 999],                          # 플랫폼 길이
}


def _bucket(value, edges):
    for i in range(len(edges) - 1):
        if edges[i] <= value < edges[i + 1]:
            return i
    return len(edges) - 2


class TrackTokenizer:
    def __init__(self):
        self.itos = list(SPECIAL)
        for name, edges in COND_SPECS.items():
            for i in range(len(edges) - 1):
                self.itos.append(f"<{name}={i}>")
        for t, chain in TRACK_TOKENS:
            self.itos.append(f"{C.NAMES[t]}{'+chain' if chain else ''}")
        self.stoi = {s: i for i, s in enumerate(self.itos)}
        self.track_start = len(self.itos) - len(TRACK_TOKENS)

    def __len__(self):
        return len(self.itos)

    # -- 인코딩 ----------------------------------------------------------
    def encode_condition(self, **values):
        ids = []
        for name, edges in COND_SPECS.items():
            v = values.get(name)
            if v is None:
                continue
            ids.append(self.stoi[f"<{name}={_bucket(v, edges)}>"])
        return ids

    def encode(self, sequence, condition=None):
        ids = [self.stoi["<bos>"]]
        if condition:
            ids += self.encode_condition(**condition)
        ids.append(self.stoi["<sep>"])
        for t, chain in sequence:
            ids.append(self.track_start + TRACK_TOKENS.index((t, bool(chain))))
        ids.append(self.stoi["<eos>"])
        return ids

    def decode(self, ids):
        out = []
        for i in ids:
            j = i - self.track_start
            if 0 <= j < len(TRACK_TOKENS):
                out.append(TRACK_TOKENS[j])
        return out

    def track_token_ids(self):
        """생성 시 마스킹 대상이 되는 토큰 ID 범위."""
        return range(self.track_start, self.track_start + len(TRACK_TOKENS))
