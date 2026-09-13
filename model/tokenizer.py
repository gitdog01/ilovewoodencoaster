"""트랙 시퀀스 <-> 토큰 ID 변환 (4단계).

시퀀스 형태:
    [BOS] <조건 토큰들> [SEP] <트랙 토큰들> [EOS]

조건 토큰은 버킷팅된 목표값이다. 학습 때는 게임이 매긴 실제 라벨을 넣고,
추론 때는 유저가 플러그인 UI에 입력한 목표값을 넣는다 (Decision Transformer 방식).
"""

from rct import constants as C

SPECIAL = ["<pad>", "<bos>", "<eos>", "<sep>"]

# (조각, 체인리프트) 쌍이 하나의 토큰.
#
# **토큰 ID 순서는 절대 건드리지 말 것. 새 조각은 맨 뒤에만 붙인다.**
# C.BUILDABLE 은 조각 번호 정렬이라, 번호가 중간인 조각을 NAMES 에 추가하면
# 그 뒤의 ID 가 전부 밀린다. 실제로 브레이크(99)를 넣었더니 체인 토큰이 1씩
# 밀려서 **기존 체크포인트가 리프트 조각을 통째로 잘못 읽게 됐다.**
# 그래서 v1 어휘(비체인 27종 + 체인 4종)의 자리를 고정하고 새 조각은 뒤에 붙인다.
_V1 = (0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21,
       22, 23, 32, 33, 42, 43, 44, 45)
_NEW = tuple(t for t in C.BUILDABLE if t not in _V1)
TRACK_TOKENS = ([(t, False) for t in _V1]
                + [(t, True) for t in C.CHAINABLE]
                + [(t, False) for t in _NEW])

# 조건 버킷. **실제 수집 분포에 맞춰 잘랐다** (처음 33,171개 기준. 140,868개로
# 다시 확인해도 빈 버킷은 안 생긴다 -- `scripts/check_buckets.py`).
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
# 140,868개 기준. 2026-09-13 재확인해도 그대로다). 여기 밖의 버킷은 한 번도 학습되지 않아서
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


# 생성기가 **실제로 만들 수 있는** 지표 구간 (2026-09-13 실측, 140,868개).
#
# **주의: 이 구멍들은 생각보다 덜 중요하다** (2026-09-13 밤 확인). 프로젝트 목표가
# "지표 4개를 맞추기"가 아니라 "격렬도 10 이하로 흥미도 최대"로 정리됐고, 사람이
# 만든 스톡 우든 코스터 30개는 격렬도가 **최대 5.50** 이라 구멍 구간(4.0~5.0,
# 10.5~13.5)에 아예 안 들어간다. 여기를 메우는 건 우선순위가 낮다.
#
# 평점은 연속이 아니다. 어휘 21종으로 만들 수 있는 트랙의 평점은 몇 개의 띠에
# 몰리고 그 사이는 **하나도 없다.** 격렬도는 3.91 다음이 5.14 이고, 10.39 다음이
# 13.23 이다. 유저가 격렬도 4.5 를 요청하면 원리적으로 못 맞춘다.
#
# 생성기 손잡이로는 안 메워진다. 두 가지를 실증으로 반증했다:
#   - 첫 낙하 높이를 연속으로 흔들기(drop_frac): 최고속도가 안 바뀌어 구멍 그대로.
#   - **브레이크를 어휘에 넣기(gen5, 33,391개)**: 트랙의 38% 가 브레이크를 쓰는데도
#     격렬도 4.0~5.0 이 여전히 **0개**. 브레이크 유무로 격렬 중앙이 3.03 vs 3.03 이고
#     brake_speed 와도 단조 관계가 없다.
# 격렬도는 최고속도의 **계단 함수**다 (속도 37 -> 3.44, 38 -> 5.25). 최고속도는
# 첫 낙하 바닥에서 정해지고 리프트 높이가 정수라, 중간값을 만들 수단이 아직 없다.
#
# 좌우G만 0.64~3.53 이 통째로 연속이다. 조건으로 쓰기 제일 좋은 지표.
REACHABLE = {
    "exc":  [(0.27, 0.38), (0.55, 0.66), (0.92, 1.87), (2.10, 2.96),
             (4.24, 4.24), (4.48, 4.48), (4.72, 6.00)],           # 범위의 58%
    "int":  [(0.28, 0.36), (0.59, 0.82), (1.21, 1.84), (2.46, 3.91),
             (5.06, 7.91), (8.07, 8.39), (8.55, 10.39), (13.23, 14.74)],  # 62%
    "nau":  [(0.17, 0.45), (0.73, 1.04), (1.50, 2.57), (3.17, 4.35),
             (4.99, 5.00), (5.19, 6.04), (6.42, 6.69), (8.35, 9.05)],     # 53%
    "latg": [(0.47, 3.53)],                                       # 100% (연속)
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
