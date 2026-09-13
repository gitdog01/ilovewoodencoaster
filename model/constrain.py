"""Constrained decoding: 매 스텝 불가능한 조각을 마스킹한다 (설계 결정 4).

베이스라인 평가에서 나온 숫자가 이 모듈이 필요한 이유다:
    조각 연결 규칙  92~100%   <- 학습으로 거의 다 배웠다
    부지 안         12~20%    <- 못 배운다
    폐곡선          0~5%      <- 못 배운다

조각 연결은 지역적 규칙(직전 조각의 경사/뱅크만 보면 됨)이라 LM 이 잘 배우지만,
부지와 폐곡선은 **처음부터 지금까지의 좌표 누적**에 달려 있다. 트랜스포머가
토큰 시퀀스에서 좌표를 적분해내길 기대하느니, 시뮬레이터로 정확히 계산해서
불가능한 토큰을 막는 쪽이 싸고 확실하다.

`Bounds` 는 stateful 이다 -- generate 가 매 스텝 부르면 새로 붙은 토큰만
소비해서 상태를 갱신한다. 매번 처음부터 다시 따라가면 O(n^2) 이 된다.
"""

from geom.planner import Occupancy, State, _in_bounds
from gen.random_walk import planner_for
from model.tokenizer import TRACK_TOKENS


class BoundsConstraint:
    """부지 이탈과 자기충돌을 막는 마스크.

    allow_eos_only_when_closed=True 면 스테이션에 정확히 닫히기 전에는 EOS 를
    막는다. 그 경우 막다른 길에 빠지면 허용 토큰이 하나도 없어질 수 있으므로,
    generate 는 그때 그냥 멈춘다 (gpt.py 의 NaN 체크).
    """

    def __init__(self, sim, tok, bounds, start: State, goal: State,
                 n_rows, ztol=2, allow_eos_only_when_closed=False,
                 reserve=None, seed_cells=None, max_token=None):
        self.P = planner_for(sim)
        self.tok = tok
        self.bounds = bounds
        self.goal = goal
        self.eos = tok.stoi["<eos>"]
        self.only_closed = allow_eos_only_when_closed
        # reserve: "닫는 데 남겨둘 조각 수". 매 스텝 h(다음상태, goal) <= reserve
        # 를 유지해서, LM 이 아무리 멀리 뻗어도 A* 가 되돌아올 여지를 남긴다.
        # geom/planner.py 의 wander() 와 같은 장치다 -- 이게 없으면 LM 이
        # 부지 반대편에서 끝나버려서 A* 마무리가 시작도 못 한다.
        self.reserve = reserve
        # 토큰 ID -> 조각 타입. 체인 여부는 지오메트리에 영향이 없다.
        self.piece_of = {tok.track_start + i: t
                         for i, (t, _chain) in enumerate(TRACK_TOKENS)}
        # 조각 타입 -> 그 타입을 쓰는 토큰 ID들 (체인 있는 것/없는 것)
        self.tokens_of = {}
        for tid, t in self.piece_of.items():
            self.tokens_of.setdefault(t, []).append(tid)

        # 모델의 출력 폭. 어휘가 늘기 전 체크포인트를 돌릴 때 필요하다.
        self.max_token = max_token
        self.state = [start] * n_rows
        seed = list(seed_cells) if seed_cells else [start.cell(), goal.cell()]
        self.occ = [Occupancy(ztol, list(seed)) for _ in range(n_rows)]
        self.consumed = [None] * n_rows   # 각 행에서 이미 반영한 토큰 개수
        self.dead = [False] * n_rows

    def _advance(self, row, tid):
        """토큰 하나를 반영. 못 놓는 조각이면 그 행을 죽은 것으로 표시."""
        t = self.piece_of.get(tid)
        if t is None:
            return                      # 특수 토큰(BOS/SEP/조건)은 무시
        s = self.state[row]
        hit = next(((nxt, cs) for tt, nxt, cs in self.P.successors(s) if tt == t),
                   None)
        if hit is None:
            self.dead[row] = True
            return
        nxt, cells = hit
        self.state[row] = nxt
        self.occ[row].add(cells)

    def __call__(self, row, ids):
        """generate 가 부르는 콜백. 허용 토큰 ID 목록을 준다."""
        ids = ids.tolist() if hasattr(ids, "tolist") else list(ids)
        if self.consumed[row] is None:
            # 첫 호출: 프리픽스는 전부 특수/조건 토큰이라 상태에 영향이 없다.
            self.consumed[row] = len(ids)
        for tid in ids[self.consumed[row]:]:
            self._advance(row, tid)
        self.consumed[row] = len(ids)

        if self.dead[row]:
            return []

        s = self.state[row]
        occ = self.occ[row]
        allowed = []
        for t, nxt, cells in self.P.successors(s):
            if not _in_bounds(self.bounds, nxt):
                continue
            if occ.blocked(cells):
                continue
            if self.reserve is not None and self.P.h(nxt, self.goal) > self.reserve:
                continue
            allowed.extend(self.tokens_of.get(t, ()))

        closed = s.key() == self.goal.key()
        if not self.only_closed or closed:
            allowed.append(self.eos)
        if self.max_token is not None:
            # 어휘가 늘기 전에 학습한 체크포인트는 출력 폭이 좁다. 걸러내지 않으면
            # 마스크 인덱스가 범위를 벗어나 **CUDA device-side assert** 로 죽는다
            # (브레이크를 어휘에 넣고 옛 ckpt 를 돌렸다가 당했다).
            allowed = [t for t in allowed if t < self.max_token]
        return allowed
