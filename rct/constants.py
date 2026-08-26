"""OpenRCT2 우든 코스터 관련 상수.

트랙 조각 ID는 ridecreation-api 플러그인이 노출하는 집합이다.
헬릭스/브레이크/S-bend/워터스플래시는 아직 플러그인에 없다 (5단계에서 확장 예정).
"""

RIDE_TYPE_WOODEN = 52

# --- 트랙 조각 ID -------------------------------------------------------
FLAT = 0
END_STATION = 1
BEGIN_STATION = 2
MIDDLE_STATION = 3

UP25 = 4
UP60 = 5
FLAT_TO_UP25 = 6
UP25_TO_UP60 = 7
UP60_TO_UP25 = 8
UP25_TO_FLAT = 9

DOWN25 = 10
DOWN60 = 11
FLAT_TO_DOWN25 = 12
DOWN25_TO_DOWN60 = 13
DOWN60_TO_DOWN25 = 14
DOWN25_TO_FLAT = 15

TURN_L5 = 16
TURN_R5 = 17
TURN_L3 = 42
TURN_R3 = 43

FLAT_TO_LEFT_BANK = 18
FLAT_TO_RIGHT_BANK = 19
LEFT_BANK_TO_FLAT = 20
RIGHT_BANK_TO_FLAT = 21
LEFT_BANK = 32
RIGHT_BANK = 33

BANKED_TURN_L5 = 22
BANKED_TURN_R5 = 23
BANKED_TURN_L3 = 44
BANKED_TURN_R3 = 45

STATION_PIECES = (BEGIN_STATION, MIDDLE_STATION, END_STATION)
CHAINABLE = (FLAT_TO_UP25, UP25, UP60)

NAMES = {
    FLAT: "Flat", END_STATION: "EndStation", BEGIN_STATION: "BeginStation",
    MIDDLE_STATION: "MiddleStation", UP25: "Up25", UP60: "Up60",
    FLAT_TO_UP25: "FlatToUp25", UP25_TO_UP60: "Up25ToUp60",
    UP60_TO_UP25: "Up60ToUp25", UP25_TO_FLAT: "Up25ToFlat",
    DOWN25: "Down25", DOWN60: "Down60", FLAT_TO_DOWN25: "FlatToDown25",
    DOWN25_TO_DOWN60: "Down25ToDown60", DOWN60_TO_DOWN25: "Down60ToDown25",
    DOWN25_TO_FLAT: "Down25ToFlat",
    TURN_L5: "LeftQuarterTurn5", TURN_R5: "RightQuarterTurn5",
    TURN_L3: "LeftQuarterTurn3", TURN_R3: "RightQuarterTurn3",
    FLAT_TO_LEFT_BANK: "FlatToLeftBank", FLAT_TO_RIGHT_BANK: "FlatToRightBank",
    LEFT_BANK_TO_FLAT: "LeftBankToFlat", RIGHT_BANK_TO_FLAT: "RightBankToFlat",
    LEFT_BANK: "LeftBank", RIGHT_BANK: "RightBank",
    BANKED_TURN_L5: "BankedLeftQuarterTurn5", BANKED_TURN_R5: "BankedRightQuarterTurn5",
    BANKED_TURN_L3: "LeftBankedQuarterTurn3", BANKED_TURN_R3: "RightBankedQuarterTurn3",
}

# 생성 모델이 다루는 조각 집합 (스테이션은 프리픽스로 따로 처리)
BUILDABLE = tuple(t for t in sorted(NAMES) if t not in STATION_PIECES)
