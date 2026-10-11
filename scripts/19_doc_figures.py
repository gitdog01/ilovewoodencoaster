"""문서(docs/)에 들어가는 그림을 다시 그린다.

    python scripts/19_doc_figures.py      # -> docs/media/fig_*.png

게임 없이 data/dataset.jsonl 만 본다. 수집을 더 하면 다시 돌릴 것.
"쓸 만한 트랙" 정의는 18_gen_profile.py 와 같다 (우든 요건 충족 + 격렬도 <= 10).
사람 기준선과 항별 분해 숫자는 CLAUDE.md 2026-09-24 / 09-27 절의 실측값이다.
"""
import collections
import importlib
import json
import os
import statistics as st
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                          # noqa: E402

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
gap = importlib.import_module("11_human_gap")
OUT = os.path.join(REPO, "docs", "media")

# dataviz 기본 팔레트 (밝은 면). 색은 항목을 따라간다.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "font.family": ["Malgun Gothic", "sans-serif"],
    "axes.unicode_minus": False, "font.size": 11,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
})

HUMAN_FLAT = 6.35          # 스톡 29개를 우리 빈 평지에 지어서 잰 흥미 중앙 (09-24)
EVENTS = {"gen6": "우든 요건을\n설계에서 보장", "gen8": "막다른 길\n회피",
          "gen13": "연속 둔덕\n(평점 공식 기반)"}


def gen_profile():
    by = collections.defaultdict(list)
    for line in open(os.path.join(REPO, "data", "dataset.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        g = (r.get("meta") or {}).get("gen_label", "?")
        if g == "gen14" and r.get("hill_kmax") is None:
            continue                     # gen14 대조군 (gen11 언덕 설정)
        by[g].append(r["stats"])
    rows = []
    for g in sorted(by, key=lambda g: int(g[3:]) if g[3:].isdigit() else 99):
        ms = by[g]
        ok = sorted(m["excitement"] for m in ms
                    if gap.meets(m) and m["intensity"] <= 10)
        if ok:
            rows.append((g, len(ms), len(ok) / len(ms), st.median(ok),
                         ok[int(.9 * len(ok))]))
    return rows


def fig_progress(rows):
    gens = [r[0].replace("gen", "") for r in rows]
    x = range(len(rows))
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True,
                                  gridspec_kw={"height_ratios": [2.2, 1]})
    ax.plot(x, [r[3] for r in rows], color=BLUE, lw=2, marker="o", ms=6,
            label="흥미도 중앙")
    ax.plot(x, [r[4] for r in rows], color=ORANGE, lw=2, marker="o", ms=6,
            label="흥미도 상위 10% (p90)")
    ax.axhline(HUMAN_FLAT, color=INK2, lw=1.2, ls="--")
    ax.text(len(rows) - 1, HUMAN_FLAT + 0.04, f"사람 디자인 중앙 (같은 빈 평지) {HUMAN_FLAT}",
            ha="right", va="bottom", color=INK2, fontsize=10)
    for i, r in enumerate(rows):
        if r[0] in EVENTS:
            ax.annotate(EVENTS[r[0]], (i, r[3]), xytext=(0, -62 if r[0] == "gen13" else -46),
                        textcoords="offset points", ha="center", fontsize=9,
                        color=INK2, arrowprops=dict(arrowstyle="-", color=INK2, lw=.8))
    ax.set_ylim(4.6, 6.5)
    ax.set_ylabel("흥미도 (쓸 만한 트랙)")
    ax.set_title("생성기 세대별 흥미도 -- 요건 충족 + 격렬도 10 이하 트랙만",
                 loc="left", fontsize=13, color=INK)
    ax.legend(loc="lower right", frameon=False)

    ax2.bar(x, [r[2] * 100 for r in rows], color=AQUA, width=0.6)
    for i, r in enumerate(rows):
        ax2.text(i, r[2] * 100 + 3, f"{r[2]:.0%}", ha="center", fontsize=9, color=INK2)
    ax2.set_ylim(0, 115)
    ax2.set_ylabel("쓸 만한 비율 %")
    ax2.set_xticks(list(x), gens)
    ax2.set_xlabel("생성기 세대 (gen)")
    ax2.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_gen_progress.png"), dpi=130)
    plt.close(fig)


def fig_terms():
    # 16_rating_breakdown.py 의 항별 분해 (CLAUDE.md 2026-09-27).
    terms = ["낙하", "G", "잔차 (근접/턴/칸)", "주행 시간", "에어타임", "길이"]
    human = [0.69, 0.72, 0.60, 0.32, 0.21, 0.11]
    gap_ = [0.21, 0.16, 0.17, 0.14, 0.13, 0.05]
    ours = [h - g for h, g in zip(human, gap_)]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    y = range(len(terms))
    h = 0.36
    ax.barh([i - h / 2 - 0.01 for i in y], human, height=h, color=INK2, label="사람 (빈 평지 28개)")
    ax.barh([i + h / 2 + 0.01 for i in y], ours, height=h, color=BLUE, label="우리 gen14")
    for i in y:
        ax.text(human[i] + 0.01, i - h / 2, f"{human[i]:.2f}", va="center", fontsize=9, color=INK2)
        ax.text(ours[i] + 0.01, i + h / 2, f"{ours[i]:.2f}  (차이 {gap_[i]:.2f})",
                va="center", fontsize=9, color=INK2)
    ax.set_yticks(list(y), terms)
    ax.invert_yaxis()
    ax.set_xlim(0, 0.95)
    ax.set_xlabel("흥미도에 더해지는 점수 (기본 3.20 위에)")
    ax.set_title("흥미도 항별 분해 -- 남은 격차는 낙하·G·근접에 있다", loc="left",
                 fontsize=13, color=INK)
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_rating_terms.png"), dpi=130)
    plt.close(fig)


def fig_model_size():
    # 2026-09-12 스윕 (gen2+ 107,431개로 학습, 같은 스텝 수).
    names = ["4층x256\n3.2M", "6층x256\n4.8M", "8층x384\n14.3M", "12층x512\n37.9M"]
    val = [0.6000, 0.5870, 0.5691, 0.5531]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    # 막대는 0 에서 시작해야 해서 차이가 안 보인다. 점 + 선으로 그린다.
    ax.plot(range(4), val, color=BLUE, lw=2, marker="o", ms=8)
    for i, v in enumerate(val):
        ax.text(i, v + 0.003, f"{v:.3f}", ha="center", fontsize=10, color=INK2)
    ax.set_xticks(range(4), names)
    ax.set_xlim(-0.4, 3.4)
    ax.set_ylim(0.54, 0.61)
    ax.set_ylabel("val 손실 (낮을수록 좋음)")
    ax.set_title("파라미터 12배 -> val 손실 8% 개선 (gen2+ 107k 개로 학습)",
                 loc="left", fontsize=12, color=INK)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_model_size.png"), dpi=130)
    plt.close(fig)


def fig_profile():
    """세대 대표 트랙 두 개의 높이 프로필. 낙하 몇 번을 눈으로 비교한다."""
    from geom.simulator import Pos, TrackSimulator
    sim = TrackSimulator(os.path.join(REPO, "geometry.json"))
    want = {"gen5": 5.11, "gen14": 5.51}           # 각 세대 흥미 중앙 근처
    pick = {}
    for line in open(os.path.join(REPO, "data", "dataset.jsonl"), encoding="utf-8"):
        r = json.loads(line)
        g = (r.get("meta") or {}).get("gen_label")
        m = r["stats"]
        if g not in want or not gap.meets(m) or m["intensity"] > 10:
            continue
        if g == "gen14" and r.get("hill_kmax") is None:
            continue
        d = abs(m["excitement"] - want[g]) + abs(m["numDrops"] - (3 if g == "gen5" else 6)) * 0.05
        if g not in pick or d < pick[g][0]:
            pick[g] = (d, r)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for g, color in (("gen5", INK2), ("gen14", BLUE)):
        r = pick[g][1]
        path, _ = sim.walk(Pos(0, 0, 0, 0), [t for t, _c in r["sequence"]])
        z = [p.z - path[0].z for p in path]
        m = r["stats"]
        ax.plot(range(len(z)), z, color=color, lw=2, drawstyle="steps-post",
                label=f"{g}: 낙하 {m['numDrops']}회, 에어타임 {m['totalAirTime']:.1f}초, "
                      f"흥미 {m['excitement']:.2f}")
    ax.set_xlabel("조각 번호 (스테이션 출발 -> 복귀)")
    ax.set_ylabel("높이 (스테이션 기준)")
    ax.set_title("gen5 는 한 번 내려가면 끝, gen14 는 낙하 뒤에도 언덕을 여러 번 넘는다",
                 loc="left", fontsize=12, color=INK)
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_height_profile.png"), dpi=130)
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = gen_profile()
    for r in rows:
        print(f"{r[0]:<6} n={r[1]:>6}  usable={r[2]:.0%}  med={r[3]:.2f}  p90={r[4]:.2f}")
    fig_progress(rows)
    fig_terms()
    fig_model_size()
    fig_profile()
    print("->", OUT)


if __name__ == "__main__":
    main()
