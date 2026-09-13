"""CLAUDE.md 의 데이터 통계 주장을 dataset.jsonl 로 재계산해 대조한다.

    python scripts/verify_claims.py

문서에 박아둔 숫자는 조용히 낡는다 -- 수집을 더 하거나 dedupe 기준이 바뀌면
전부 어긋난다. 2026-09-13 gen5 수집 후 기준으로 맞춰뒀다. 어긋남이 뜨면 **문서를
고칠 것.** 여기 있는 기대값은 문서의 사본이고, 문서가 정본이다.

같이 볼 것: `scripts/check_buckets.py` (조건 토큰이 살아 있는지).
어긋남이 있으면 종료 코드 1.
"""
import collections
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gen.random_walk import PLAIN_TURNS         # noqa: E402

PATH = os.path.join(REPO, "data", "dataset.jsonl")
if not os.path.isfile(PATH):
    sys.exit(f"데이터가 없습니다: {PATH}\n먼저 scripts/build_dataset.py 를 돌리세요.")

rows = []
with open(PATH, encoding="utf-8") as fp:
    for line in fp:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

gens = collections.Counter((r.get("meta") or {}).get("gen_label", "없음") for r in rows)
size_mb = os.path.getsize(PATH) / 1024 / 1024
results = []


def check(label, claimed, actual, ok=None):
    results.append(((claimed == actual) if ok is None else ok, label, claimed, actual))


print(f"레코드 {len(rows)}개, 파일 {size_mb:.0f}MB")
print(f"세대: {dict(gens.most_common())}\n")

check("dataset.jsonl 총 개수", 140868, len(rows))
check("파일 크기(MB)", 146, round(size_mb), abs(size_mb - 146) < 2)
check("gen2+ 개수", 140868, sum(v for k, v in gens.items() if k != "gen1"))
# dataset.jsonl 을 --min-gen gen2 로 다시 만들어서 gen1 은 아예 안 들어간다.
check("gen1 개수", 0, gens["gen1"])

FIELDS = [
    ("흥미도", "excitement", 0.27, 2.38, 6.00),
    ("격렬도", "intensity", 0.28, 3.17, 14.74),
    ("멀미도", "nausea", 0.17, 1.76, 9.05),
    ("좌우G", "maxLateralGs", 0.47, 2.29, 3.53),
    ("최고속도", "maxSpeed", 21, 35, 47),
]
for name, key, cmin, cmed, cmax in FIELDS:
    vals = [r["stats"][key] for r in rows]
    amin, amed, amax = min(vals), st.median(vals), max(vals)
    check(f"{name} min", cmin, round(amin, 2), abs(amin - cmin) < 0.02)
    check(f"{name} 중앙", cmed, round(amed, 2), abs(amed - cmed) < 0.02)
    check(f"{name} max", cmax, round(amax, 2), abs(amax - cmax) < 0.02)

lens = [len(r["sequence"]) for r in rows]
check("조각 수 min", 19, min(lens))
check("조각 수 max", 109, max(lens))

over10 = sum(1 for r in rows if r["stats"]["intensity"] > 10)
check("격렬도 10 초과 개수", 6669, over10)
check("격렬도 10 초과 비율(%)", 4.7, round(100 * over10 / len(rows), 1),
      abs(100 * over10 / len(rows) - 4.7) < 0.1)

# gen4 banked 레버 표 (CLAUDE.md "수집 결과")
g4 = [r for r in rows if (r.get("meta") or {}).get("gen_label") == "gen4"]
for flag, cn, cplain, clatg, cint in [(True, 37916, 1.0, 1.94, 3.05),
                                      (False, 35261, 14.0, 2.48, 3.33)]:
    sub = [r for r in g4 if bool(r.get("banked")) is flag]
    check(f"gen4 banked={flag} n", cn, len(sub))
    if not sub:
        continue
    plain = st.median(sum(p[0] in PLAIN_TURNS for p in r["sequence"]) for r in sub)
    latg = st.median(r["stats"]["maxLateralGs"] for r in sub)
    inten = st.median(r["stats"]["intensity"] for r in sub)
    check(f"gen4 banked={flag} 맨턴중앙", cplain, plain, abs(plain - cplain) < 0.51)
    check(f"gen4 banked={flag} 좌우G중앙", clatg, round(latg, 2), abs(latg - clatg) < 0.02)
    check(f"gen4 banked={flag} 격렬중앙", cint, round(inten, 2), abs(inten - cint) < 0.02)

p95 = sorted(lens)[int(len(lens) * 0.95)]
check("시퀀스 p95 (data.py 주석)", 69, p95, abs(p95 - 69) <= 1)

print(f"{'':2} {'주장':<32} {'문서':>10} {'실제':>10}")
bad = 0
for ok, label, claimed, actual in results:
    if not ok:
        bad += 1
    print(f"{'OK' if ok else 'XX':2} {label:<32} {str(claimed):>10} {str(actual):>10}")
print(f"\n{len(results) - bad}/{len(results)} 일치, 어긋남 {bad}건")
if bad:
    print("CLAUDE.md 의 해당 숫자를 고치거나, 데이터가 왜 바뀌었는지 확인할 것.")
sys.exit(1 if bad else 0)
