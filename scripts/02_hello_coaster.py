"""1단계: 손으로 짠 코스터 하나 짓고 평점 받기."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rct import constants as C
from rct.client import RCTClient
from rct.env import WoodenCoasterEnv

SEQUENCE = [
    (C.FLAT_TO_UP25, True), (C.UP25, True), (C.UP25, True),
    (C.UP25, True), (C.UP25_TO_FLAT, True),
    (C.FLAT, False),
    (C.TURN_L5, False), (C.TURN_L5, False),
    (C.FLAT_TO_DOWN25, False), (C.DOWN25, False), (C.DOWN25, False),
    (C.DOWN25, False), (C.DOWN25_TO_FLAT, False),
    (C.FLAT, False), (C.FLAT, False),
    (C.TURN_L5, False), (C.TURN_L5, False),
    (C.FLAT, False), (C.FLAT, False), (C.FLAT, False),
]

with RCTClient.discover() as c:
    env = WoodenCoasterEnv(c, origin=(67, 66, 14))
    env.reset(station_length=3)
    placed, complete = env.build(SEQUENCE)
    print(f"배치 {placed}개, 폐곡선={complete}, 끝위치={env.pos}, 시작={env.anchor}")

    if not complete:
        sys.exit("아직 안 닫혔습니다. SEQUENCE를 조정하세요 (끝위치 vs 시작 비교).")

    stats = env.evaluate()
    if stats:
        print("=" * 40)
        print(f"  흥미도 {stats['excitement']:.2f}")
        print(f"  격렬도 {stats['intensity']:.2f}")
        print(f"  멀미도 {stats['nausea']:.2f}")
        print("=" * 40)
        print("\n[OK] 1단계 통과")
    else:
        print("평점 없음 — 게임이 일시정지 상태인지 확인하세요.")
