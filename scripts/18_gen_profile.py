"""세대별 특징표. 학습 때 세대 비중을 정하는 근거.

    python scripts/18_gen_profile.py

게임 없이 dataset.jsonl 만 본다. "쓸 만한 트랙" = 우든 요건 충족 + 격렬도 <= 10
(평점 반토막도, 격렬도 실격도 아닌 것). 흥미도 분포는 그 안에서 잰다.
"""
import collections
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import importlib                                        # noqa: E402
gap = importlib.import_module("11_human_gap")


def main():
    by = collections.defaultdict(list)
    for l in open(os.path.join(REPO, "data", "dataset.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        g = (r.get("meta") or {}).get("gen_label", "?")
        # gen14 대조군(run14b)은 같은 코드에 gen11 언덕 설정이라 따로 본다.
        if g == "gen14" and r.get("hill_kmax") is None:
            g = "gen14b"
        by[g].append(r)
    def key(g):
        n = g[3:].rstrip("b")
        return (int(n) if n.isdigit() else 99, g)
    order = sorted(by, key=key)
    print(f"{'세대':<6}{'개수':>7}{'요건%':>7}{'격<=10%':>8}{'쓸만한':>7}"
          f"{'흥미중앙':>8}{'p90':>6}{'최고':>6}{'5.5+':>6}{'낙하':>5}{'에어':>6}"
          f"{'길이':>6}{'조각':>5}")
    for g in order:
        rs = by[g]
        ms = [r["stats"] for r in rs]
        req = [m for m in ms if gap.meets(m)]
        ok = [m for m in req if m["intensity"] <= 10]
        if not ok:
            print(f"{g:<6}{len(rs):>7}  (쓸 만한 트랙 없음)")
            continue
        ex = sorted(m["excitement"] for m in ok)
        air = [m.get("totalAirTime", 0) for m in ok]
        print(f"{g:<6}{len(rs):>7}{len(req)/len(ms):>7.0%}{len(ok)/max(1,len(req)):>8.0%}"
              f"{len(ok):>7}{st.median(ex):>8.2f}{ex[int(.9*len(ex))]:>6.2f}{ex[-1]:>6.2f}"
              f"{sum(e >= 5.5 for e in ex):>6}{st.median(m['numDrops'] for m in ok):>5.0f}"
              f"{st.median(air):>6.2f}{st.median(m['rideLength'] for m in ok):>6.0f}"
              f"{st.median(len(r['sequence']) for r in rs):>5.0f}")


if __name__ == "__main__":
    main()
