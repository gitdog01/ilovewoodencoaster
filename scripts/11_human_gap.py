"""사람이 만든 스톡 우든 코스터와 우리 데이터를 같은 통계로 나란히 놓는다.

    python scripts/11_human_gap.py

게임 없이 돈다. 두 가지를 찍는다.

1. **우든 코스터 요건.** OpenRCT2 는 우든 코스터가 아래 넷 중 하나라도 못
   채우면 흥미/격렬/멀미를 전부 나눈다 (실측으로 약 절반):
       주행 길이 >= 370m, 낙하 >= 2회, 최고 낙하 >= 12, 음의 G <= 0.10
   dataset.jsonl 에서 요건 미달인 트랙 중 흥미도 4.2 이상은 **0개**다.
   경계가 칼같이 맞아서 이게 흥미도 "계단"의 정체다.

2. **사람 vs 우리.** TD6 헤더에서 평점 외 통계를 뽑아 API 단위로 맞춘다.
   필드 위치는 OpenRCT2 TD6Track 구조체와 1바이트가 어긋나 있어서 원시 바이트를
   보고 역산했다 (평점 0x5C 는 10_vocab_coverage.py 에서 검증된 위치):
       0x51 최고속 (x9/4 = 표시 mph)   0x52 평균속 (x9/4)
       0x53 주행 길이 m (2바이트 LE)   0x55/0x56/0x57 수직+/수직-/좌우 G (x0.32)
       0x59 낙하 수 (하위 6비트)        0x5A 최고 낙하 (원시 z)
       0x81/0x82 필요 부지 가로/세로
   근거: 전부 이 해석에서 물리적으로 그럴듯한 값이 나오고, 평균속은 우리 데이터와
   같은 범위(15.75 vs 17)라 단위가 맞는다. 에어타임(0x4A?)은 단위를 못 맞춰 뺐다.
"""
import argparse
import glob
import importlib
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
cov = importlib.import_module("10_vocab_coverage")

# (API 필드, 문턱, 비교) -- OpenRCT2 우든 코스터 요건
REQUIREMENTS = [
    ("rideLength", 370, ">="),
    ("numDrops", 2, ">="),
    ("highestDropHeight", 12, ">="),
    ("maxNegativeVerticalGs", 0.10, "<="),
]
KEYS = ["maxSpeed", "averageSpeed", "rideLength", "maxPositiveVerticalGs",
        "maxNegativeVerticalGs", "maxLateralGs", "numDrops",
        "highestDropHeight", "excitement", "intensity", "width", "depth"]


def meets(stats):
    return all(stats[k] >= v if op == ">=" else stats[k] <= v
               for k, v, op in REQUIREMENTS)


def stock_stats(folder, ride_type):
    files = sorted({os.path.normcase(os.path.realpath(p))
                    for pat in ("*.TD6", "*.td6")
                    for p in glob.glob(os.path.join(folder, pat))})
    out = []
    for f in files:
        d = cov.rle_decode(open(f, "rb").read()[:-4])
        if d[0] != ride_type:
            continue
        s8 = lambda b: (b ^ 0x80) - 0x80   # noqa: E731
        out.append({
            "maxSpeed": d[0x51] * 9 / 4, "averageSpeed": d[0x52] * 9 / 4,
            "rideLength": d[0x53] | d[0x54] << 8,
            "maxPositiveVerticalGs": d[0x55] * 0.32,
            "maxNegativeVerticalGs": s8(d[0x56]) * 0.32,
            "maxLateralGs": d[0x57] * 0.32,
            "numDrops": d[0x59] & 0x3F, "highestDropHeight": d[0x5A],
            "excitement": d[0x5C] / 10, "intensity": d[0x5D] / 10,
            "width": d[0x81], "depth": d[0x82],
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(REPO, "data", "dataset.jsonl"))
    ap.add_argument("--tracks", default=None)
    ap.add_argument("--cap", type=float, default=10.0, help="격렬도 상한")
    ap.add_argument("--check-predictor", action="store_true",
                    help="gen/requirements.py 예측이 실제 요건 판정과 맞는지 본다")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8") if l.strip()]
    if args.check_predictor:
        from gen.requirements import meets as pred_meets
        tab = {}
        for r in rows:
            k = (pred_meets([tuple(p) for p in r["sequence"]]), meets(r["stats"]))
            tab[k] = tab.get(k, 0) + 1
        tp, fp_, fn = tab.get((True, True), 0), tab.get((True, False), 0), tab.get((False, True), 0)
        print(f"== 요건 예측기 ({len(rows):,}개)")
        print(f"  정밀도 {tp / max(1, tp + fp_):.1%} (통과 예측 중 실제 충족)")
        print(f"  재현율 {tp / max(1, tp + fn):.1%} (실제 충족 중 통과 예측)")
        return
    flat = [dict(r["stats"], width=r["bounds"]["width"], depth=r["bounds"]["depth"])
            for r in rows]

    # -- 1. 요건 -------------------------------------------------------------
    ok = [s for s in flat if meets(s)]
    bad = [s for s in flat if not meets(s)]
    print(f"== 우든 코스터 요건 ({len(flat):,}개)")
    print(f"  요건 충족 {len(ok):,} ({len(ok) / len(flat):.1%})  "
          f"흥미 중앙 {st.median(s['excitement'] for s in ok):.2f}")
    print(f"  요건 미달 {len(bad):,} ({len(bad) / len(flat):.1%})  "
          f"흥미 중앙 {st.median(s['excitement'] for s in bad):.2f}  "
          f"흥미 4.2 이상 {sum(s['excitement'] >= 4.2 for s in bad)}개")
    for k, v, op in REQUIREMENTS:
        miss = sum(not (s[k] >= v if op == '>=' else s[k] <= v) for s in flat)
        print(f"    {k} {op} {v}: 못 채움 {miss / len(flat):.1%}")

    # -- 2. 사람 vs 우리 -----------------------------------------------------
    folder = args.tracks or next((p for p in cov.DEFAULT_TRACKS if os.path.isdir(p)), None)
    if not folder:
        sys.exit("TD6 폴더를 못 찾았습니다. --tracks 로 지정하세요.")
    human = stock_stats(folder, cov.C.RIDE_TYPE_WOODEN)
    good = [s for s in ok if s["intensity"] <= args.cap]
    top = sorted(good, key=lambda s: -s["excitement"])[:200]
    print(f"\n== 사람 스톡 {len(human)}개 vs 우리 (요건 충족 + 격렬도 <= {args.cap:g}, "
          f"{len(good):,}개)")
    print(f"  {'':22s} {'사람 중앙':>9s} {'사람 범위':>13s} {'우리 중앙':>9s} {'우리 상위200':>11s}")
    for k in KEYS:
        h = [s[k] for s in human]
        print(f"  {k:22s} {st.median(h):9.2f} {min(h):6.1f}~{max(h):6.1f} "
              f"{st.median(s[k] for s in good):9.2f} {st.median(s[k] for s in top):11.2f}")


if __name__ == "__main__":
    main()
