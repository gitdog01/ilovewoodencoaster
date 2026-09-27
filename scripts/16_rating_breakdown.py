"""흥미도를 OpenRCT2 공식의 항별로 분해해서 사람(스톡) vs 우리를 비교한다.

    python scripts/16_rating_breakdown.py

게임 없이 돈다. **평점 공식을 역공학하지 않고 원문을 옮겼다** (2026-09-27):
  OpenRCT2 src/openrct2/ride/rtd/coaster/WoodenRollerCoaster.h  (계수)
  OpenRCT2 src/openrct2/ride/RideRatings.cpp                   (항 계산)

측정값(getRideMeasurements)만으로 계산되는 항:
  기본 3.20 / 길이 / 최고속 / 평균속 / 주행시간 / G / 낙하 / 에어타임
측정값으로 못 보는 항은 전부 **잔차** 로 모인다:
  턴(평지/뱅크/경사 턴 수, 특수 조각) / 쉘터(터널) / 근접(proximity) / 주경 /
  칸 수 / 차량 오브젝트 배수

단위 (공식 내부값 <- API 값):
  speed>>16 = mph * 4/9      (ToHumanReadableSpeed = speed*9 >> 18)
  G 는 소수 둘째자리 정수 (x100)
  에어타임 내부 = 초 * 100/3  (ToHumanReadableAirTime = t*3/100)
정수 절삭을 무시해서 항마다 +-0.01 정도 틀린다. 합으로 보면 +-0.05 안쪽.

전제: 요건 4개 충족 + 격렬도 < 10 인 트랙만 본다 (반토막 / 격렬도 감점 없음).
"""
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import importlib                                        # noqa: E402
gap = importlib.import_module("11_human_gap")


def terms(m):
    """측정값 -> 항별 흥미도 기여 (단위: 흥미도 점수)."""
    spd = m["maxSpeed"] * 4 / 9
    avg = m["averageSpeed"] * 4 / 9
    pos = m["maxPositiveVerticalGs"] * 100
    neg = m["maxNegativeVerticalGs"] * 100
    lat = m["maxLateralGs"] * 100
    air = m.get("totalAirTime", 0) * 100 / 3
    g = (pos * 5242 / 65536 + max(-250, min(0, neg)) * -15728 / 65536
         + min(150, lat) * 26214 / 65536)
    drops = (min(9, m["numDrops"]) * 728177 / 65536
             + m["highestDropHeight"] * 2 * 16000 / 65536)
    t = {
        "base": 320,
        "length": min(m["rideLength"], 6000) * 873 / 65536,
        "maxSpeed": spd * 44281 / 65536,
        "avgSpeed": avg * 364088 / 65536,
        "duration": min(m["rideTime"], 150) * 26214 / 65536,
        "gforces": g * 40960 / 65536,
        "drops": drops * 40777 / 65536,
        "airtime": min(air, 200) / 8,
    }
    return {k: v / 100 for k, v in t.items()}


def summarize(label, rows):
    tt = [terms(m) for m in rows]
    known = [sum(t.values()) for t in tt]
    resid = [m["excitement"] - k for m, k in zip(rows, known)]
    out = {k: st.median(t[k] for t in tt) for k in tt[0]}
    out["(known sum)"] = st.median(known)
    out["residual"] = st.median(resid)
    out["excitement"] = st.median(m["excitement"] for m in rows)
    return label, len(rows), out


def main():
    stock = [json.loads(l)["flat"] for l in
             open(os.path.join(REPO, "data", "stock_on_flat.jsonl"), encoding="utf-8")]
    stock = [m for m in stock if m and gap.meets(m) and m["intensity"] < 10]

    ours_all, ours_new = [], []
    for l in open(os.path.join(REPO, "data", "dataset.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        m = r["stats"]
        if not (gap.meets(m) and m["intensity"] < 10) or "totalAirTime" not in m:
            continue
        ours_all.append(m)
        g = (r.get("meta") or {}).get("gen_label", "")
        if g in ("gen6", "gen7", "gen8", "gen9", "gen10", "gen11", "gen12", "gen13"):
            ours_new.append(m)
    top = sorted(ours_all, key=lambda m: -m["excitement"])[:200]

    cols = [summarize("사람 (빈 평지)", stock), summarize("우리 gen6+", ours_new),
            summarize("우리 전체", ours_all), summarize("우리 상위 200", top)]
    keys = list(cols[0][2])
    print(f"{'항':<14}" + "".join(f"{c[0]:>16}" for c in cols))
    print(f"{'n':<14}" + "".join(f"{c[1]:>16}" for c in cols))
    for k in keys:
        print(f"{k:<14}" + "".join(f"{c[2][k]:>16.2f}" for c in cols))

    # 측정값 원본 중앙도 같이 (항 차이가 어디서 오는지)
    print()
    for k in ["maxSpeed", "averageSpeed", "rideTime", "rideLength", "numDrops",
              "highestDropHeight", "maxPositiveVerticalGs", "maxNegativeVerticalGs",
              "maxLateralGs", "totalAirTime"]:
        vals = [st.median(m[k] for m in rows) for rows in
                (stock, ours_new, ours_all, top)]
        print(f"{k:<22}" + "".join(f"{v:>12.2f}" for v in vals))


if __name__ == "__main__":
    main()
