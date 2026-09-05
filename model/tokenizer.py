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

# 조건 버킷. **실제 수집 분포(gen2+ 33171개)에 맞춰 잘랐다.**
#
# 원래는 흥미도를 [0,3,4,5,6,6.5,...,9,99] 로 잘라놨는데, 실측을 대보니 11개 중
# 7개가 완전히 비고 77.7%가 버킷 0에 뭉쳤다. 조건 토큰이 사실상 3종밖에 안 돼서
# 조건부 생성이 성립하지 않는다.
#
# 이유: RCT2 평점이 소수의 양자화된 입력에서 계산되는 데다 생성기가 흔드는
# 손잡이도 몇 개 안 돼서, 평점이 연속이 아니라 **덩어리로 뭉친다.** 실측:
#   흥미도  덩어리 3개 (0.28~0.66 / 0.92~2.82 / 4.78~6.00), 고유값 275개뿐
#   격렬도  덩어리 6개
#   멀미도  덩어리 8개
#   좌우G   덩어리 1개 -- 0.66~3.53 이 연속으로 채워진다
# 그래서 경계를 덩어리 사이에 두고, 빈 버킷이 안 생기게 했다.
#
# latg(좌우G)를 새로 넣은 이유: 위에서 보듯 **유일하게 연속인 지표**라 해상도가
# 제일 높다. 격렬도의 실질적 원인이기도 해서 모델이 잡기 쉬운 신호다.
# cost(건설비)는 뺐다 -- 수집 레코드에 그 필드가 아예 없어서 학습에 못 쓴다.
# 넣으려면 플러그인에서 먼저 내려받아야 한다 (TODO).
COND_SPECS = {
    "exc":     [0, 0.8, 1.6, 3.0, 99],                    # 흥미도
    "int":     [0, 1.0, 2.2, 4.5, 7.0, 10.0, 99],         # 격렬도 (10이 손님 이탈선)
    "nau":     [0, 0.6, 1.2, 2.2, 3.0, 4.7, 99],          # 멀미도
    "latg":    [0, 1.4, 1.8, 2.1, 2.35, 2.6, 2.85, 99],   # 좌우G
    "width":   [0, 8, 12, 16, 20, 24, 32, 999],           # 부지 가로
    "depth":   [0, 8, 12, 16, 20, 24, 32, 999],           # 부지 세로
    "height":  [0, 16, 24, 32, 48, 64, 999],              # 최대 높이
    "station": [0, 3, 4, 5, 6, 7, 999],                   # 플랫폼 길이
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
