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


# 학습 데이터에 **실제로 나온** 버킷 범위 (`scripts/check_buckets.py` 실측,
# 2026-09-12 / 108,296개 기준). 여기 밖의 버킷은 한 번도 학습되지 않아서
# 임베딩이 초기값 그대로다 -- 추론 때 그런 토큰을 넣으면 모델이 처음 보는
# 조건을 받는 셈이라 출력이 조용히 망가진다.
#
# 부지(width/depth)는 UI 스피너가 12까지 내려가는데 수집기는 width>=20,
# depth>=16 만 뽑았다. 부지 제약 자체는 constrained decoding 이 기하로 강제하므로
# 조건 토큰만 학습된 범위로 눌러도 작은 부지에 짓는 건 그대로 된다.
# height/station 은 수집기가 아예 안 흔들어서 버킷이 하나뿐이다.
#
# 수집기가 이 범위를 넓히면 check_buckets.py 를 다시 돌려 여기를 고칠 것.
SEEN_BUCKETS = {
    "width":   (4, 6),
    "depth":   (3, 6),
    "height":  (4, 4),
    "station": (1, 1),
}


# 생성기가 **실제로 만들 수 있는** 지표 구간 (2026-09-13 실측, gen2+ 107,431개).
#
# 평점은 연속이 아니다. 어휘 21종으로 만들 수 있는 트랙의 평점은 몇 개의 띠에
# 몰리고 그 사이는 **하나도 없다.** 격렬도는 3.91 다음이 5.14 이고, 10.39 다음이
# 13.23 이다. 유저가 격렬도 4.5 를 요청하면 원리적으로 못 맞춘다.
#
# 생성기 손잡이로는 안 메워진다 (실증): 첫 낙하 높이를 연속으로 흔들어봤지만
# (drop_frac) 최고속도가 안 바뀌어서 구멍이 그대로였다. 격렬도는 최고속도의
# **계단 함수**다 -- 속도 37 -> 격렬 3.44, 속도 38 -> 5.25 로 건너뛴다.
# 사이를 채우려면 속도를 중간값으로 만들 수단, 즉 **브레이크**가 필요한데
# 어휘에 없다 (CLAUDE.md "조각 어휘 47% 공백").
#
# 좌우G만 0.64~3.53 이 통째로 연속이다. 조건으로 쓰기 제일 좋은 지표.
REACHABLE = {
    "exc":  [(0.28, 0.38), (0.55, 0.66), (0.92, 1.87), (2.10, 2.96),
             (4.24, 4.24), (4.48, 4.48), (4.72, 6.00)],
    "int":  [(0.31, 0.36), (0.60, 0.82), (1.22, 1.84), (2.46, 3.91),
             (5.14, 7.91), (8.12, 8.39), (8.55, 10.39), (13.23, 14.74)],
    "nau":  [(0.17, 0.20), (0.36, 0.45), (0.73, 1.04), (1.50, 2.57),
             (3.17, 4.35), (4.99, 5.00), (5.19, 6.04), (6.43, 6.69),
             (8.36, 9.05)],
    "latg": [(0.64, 3.53)],
}


def snap(name, value):
    """요청값을 도달 가능한 값으로 당긴다. (값, 안내문 또는 None) 을 돌려준다.

    구멍 안의 값을 그대로 두면 모델이 조용히 엉뚱한 걸 내놓는다. 가까운 쪽
    끝으로 당기고, 얼마나 움직였는지 호출부가 유저에게 알릴 수 있게 한다.
    """
    bands = REACHABLE.get(name)
    if not bands or any(lo <= value <= hi for lo, hi in bands):
        return value, None
    best = min((lo if value < lo else hi for lo, hi in bands),
               key=lambda e: abs(e - value))
    return best, f"{name} {value:g} 는 만들 수 없어 {best:g} 로 맞췄습니다"


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
        """조건 값 -> 토큰 ID. 학습에 없던 버킷은 SEEN_BUCKETS 로 눌러준다."""
        ids = []
        for name, edges in COND_SPECS.items():
            v = values.get(name)
            if v is None:
                continue
            b = _bucket(v, edges)
            lo, hi = SEEN_BUCKETS.get(name, (0, len(edges) - 2))
            ids.append(self.stoi[f"<{name}={min(max(b, lo), hi)}>"])
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
