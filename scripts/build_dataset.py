"""흩어진 part 파일들을 학습용 dataset.jsonl 하나로 합친다.

하는 일 세 가지:

1. **세대 태깅.** 레코드의 `meta.gen` 이 이 레코드를 만든 생성기 커밋이다.
   `meta` 가 없는 옛 레코드는 파일 이름으로 세대를 추정해서 채운다 (아래 GENERATIONS).
   생성기를 고치면 같은 설정이라도 분포가 달라지므로, 합쳐놓고 나면 세대를
   구분할 방법이 이것뿐이다.

2. **중복 제거.** 생성기가 같은 시퀀스를 다시 뽑는 일이 4%쯤 있다.
   시드가 겹쳐서가 아니라 무작위 워크가 우연히 같은 걸 만드는 것.

3. **세대별 리포트.** 어느 세대가 몇 개이고 분포가 어떤지 찍어준다.

왜 세대를 구분해야 하나 (2026-09-05 실측):
  gen1 은 `banked` 플래그가 사실상 동작하지 않았다. banked=True 인데도 맨턴이
  중앙 9개 남아서, 그 필드로 조건부 학습을 하면 라벨이 오염된다. gen2 부터는
  banked=True 가 맨턴 중앙 1개로 깨끗하게 갈린다. gen1 은 격렬도가 10을 한 번도
  안 넘어서 "격렬도 10 제한" 경계도 없다.
  --> `--min-gen gen2` 로 걸러 쓰는 게 기본이고, gen1 은 사전학습용 정도로만.

사용법:
    python scripts/build_dataset.py                    # 전부 합침 (세대 태깅 + dedupe)
    python scripts/build_dataset.py --min-gen gen2     # gen2 이상만
    python scripts/build_dataset.py --keep-dupes
"""
import argparse
import collections
import glob
import json
import os
import statistics as st
import sys

sys.stdout.reconfigure(errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 파일 이름 접두사 -> (세대, 생성기 커밋, 설명)
# meta 가 없는 옛 레코드를 소급 태깅하는 표. 새 수집물은 레코드에 gen 이
# 직접 박히므로 여기 손댈 필요가 없다.
GENERATIONS = {
    "part_":  ("gen1", "07784aa", "strict_banked 이전. banked 플래그가 사실상 무효, 격렬도 <=9.67"),
    "part2_": ("gen2", "b7d0a1e", "banked 분리 + 격렬도 상단 개방. 설계 시간상한 없음"),
    "part3_": ("gen2", "b7d0a1e", "위와 동일"),
    "part4_": ("gen2", "b7d0a1e", "위와 동일"),
    "part5_": ("gen2", "b7d0a1e", "위와 동일"),
    "part6_": ("gen3", "66939a4", "설계 시간상한 추가"),
    "run2_":  ("gen3", "66939a4", "설계 시간상한 추가"),
    "run3_":  ("gen3", "346330f", "meta.gen 기록 시작. 분포는 gen3 와 동일"),
    "run4_":  ("gen4", "", "스테이션 플랫폼 타일을 점유로 반영 (배치 성공률 개선)"),
    # gen5 (2026-09-13): 배치 거부 17% -> 4% (실측 footprint + 입구/출구 예약 +
    # plan_safe) 하고 **브레이크를 어휘에 넣었다.** 레코드에 brake_speed 와
    # n_brake 가 새로 들어간다. 격렬도 구멍(4.0~5.0, 10.5~13.5)이 메워지는지가
    # 이 세대의 목적이다.
    "run5_":  ("gen5", "", "실측 footprint + plan_safe + 브레이크 어휘 추가"),
    # gen6 (2026-09-19): 우든 코스터 요건을 설계 단계에서 보장. 리프트 6 이상,
    # 첫 낙하 뒤 낙타등 언덕 1~3개, 요건 예측(gen/requirements.py) 미달은 폐기.
    # 그전 세대는 75% 가 요건 미달이라 평점이 반토막이었다.
    "run6_":  ("gen6", "", "우든 요건 보장 + 낙타등 언덕"),
    # gen7 (2026-09-20): 언덕을 4~9개로 늘리고 본체 전체에 흩었다 (hill_spread).
    # 낙하 수 중앙 3 -> 6 (사람은 9).
    "run7_":  ("gen7", "", "언덕을 본체까지 흩뿌림"),
    # gen8 (2026-09-20): 워크가 한 수 앞을 봐서 막다른 길을 피한다 + 워크 길이 2배.
    # 워크가 중앙 2스텝에서 10스텝으로 늘었다.
    "run8_":  ("gen8", "", "막다른 길 회피 + 긴 워크"),
    # gen9 (2026-09-20): 층 쌓기. 같은 x,y 를 다른 z 로 다시 쓰고(_ramp),
    # 첫 언덕 말고는 높이 제한을 풀었다. 설계 길이 중앙 476 -> 594m.
    "run9_":  ("gen9", "", "층 쌓기 (_ramp) + 언덕 높이 제한 완화"),
    # gen10 (2026-09-20): ztol 2 -> 4. 긴 트랙이 게임에 실제로 놓인다.
    # 램프는 효과가 없어 껐다.
    "run10_": ("gen10", "", "ztol 4 (긴 트랙 배치) + 램프 제거"),
    # gen11 (2026-09-20): ztol 2 로 복귀. gen8 + 언덕 높이 제한 완화만 남겼다.
    "run11_": ("gen11", "", "gen8 + 언덕 높이 제한 완화"),
}
# 커밋 -> 세대. 레코드에 meta.gen 이 있을 때 세대를 붙이는 데 쓴다.
COMMIT_TO_GEN = {c: g for g, c, _ in GENERATIONS.values() if c}
GEN_ORDER = ["gen1", "gen2", "gen3", "gen4", "gen5", "gen6", "gen7", "gen8", "gen9", "gen10", "gen11"]


def generation_of(record, filename):
    """레코드의 세대. meta.gen 이 있으면 그걸 쓰고, 없으면 파일 이름으로 추정."""
    gen = (record.get("meta") or {}).get("gen")
    if gen and gen.replace("+dirty", "") in COMMIT_TO_GEN:
        return COMMIT_TO_GEN[gen.replace("+dirty", "")]
    # meta.gen 이 없거나 표에 없는 커밋이면 파일 이름으로 떨어진다. 새 세대를
    # 만들 때 커밋 해시를 미리 알 수 없으므로(태깅 커밋 자체가 해시를 바꾼다)
    # 접두사 쪽이 실제로 쓰이는 경로다. meta.gen 은 정확한 커밋 기록용.
    base = os.path.basename(filename)
    for prefix, (g, _commit, _desc) in GENERATIONS.items():
        if base.startswith(prefix):
            return g
    return gen or "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(REPO, "data"))
    ap.add_argument("--out", default=os.path.join(REPO, "data", "dataset.jsonl"))
    ap.add_argument("--min-gen", default=None,
                    help="이 세대 이상만 쓴다 (예: gen2). 생략하면 전부.")
    ap.add_argument("--keep-dupes", action="store_true")
    args = ap.parse_args()

    files = sorted(f for f in glob.glob(os.path.join(args.data, "*.jsonl"))
                   if os.path.basename(f) != os.path.basename(args.out))
    if not files:
        sys.exit(f"합칠 파일이 없습니다: {args.data}/*.jsonl")

    min_i = GEN_ORDER.index(args.min_gen) if args.min_gen else -1
    rows, seen = [], set()
    per_gen = collections.Counter()
    dropped_gen = dropped_dup = bad = 0

    for path in files:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                bad += 1          # 수집기를 죽인 순간의 반쪽짜리 마지막 줄
                continue
            gen = generation_of(r, path)
            r.setdefault("meta", {})["gen_label"] = gen
            if min_i >= 0 and (gen not in GEN_ORDER or GEN_ORDER.index(gen) < min_i):
                dropped_gen += 1
                continue
            if not args.keep_dupes:
                key = json.dumps(r["sequence"], separators=(",", ":"))
                if key in seen:
                    dropped_dup += 1
                    continue
                seen.add(key)
            per_gen[gen] += 1
            rows.append(r)

    with open(args.out, "w", encoding="utf-8") as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"파일 {len(files)}개 -> {args.out}")
    print(f"  기록 {len(rows)}개")
    if dropped_dup:
        print(f"  중복 제외 {dropped_dup}개")
    if dropped_gen:
        print(f"  세대 미달 제외 {dropped_gen}개 (--min-gen {args.min_gen})")
    if bad:
        print(f"  깨진 줄 {bad}개 (수집기를 중간에 끊으면 마지막 줄이 반쪽일 수 있음)")

    print("\n세대   개수    흥미(중앙)  격렬(중앙)  격렬>10   맨턴중앙(banked=True)")
    from gen.random_walk import PLAIN_TURNS
    for g in GEN_ORDER + [x for x in per_gen if x not in GEN_ORDER]:
        sub = [r for r in rows if r["meta"]["gen_label"] == g]
        if not sub:
            continue
        e = st.median(r["stats"]["excitement"] for r in sub)
        i = st.median(r["stats"]["intensity"] for r in sub)
        over = sum(1 for r in sub if r["stats"]["intensity"] > 10)
        bk = [r for r in sub if r.get("banked")]
        pl = st.median(sum(p[0] in PLAIN_TURNS for p in r["sequence"])
                       for r in bk) if bk else float("nan")
        print(f"  {g:<6} {len(sub):<7} {e:9.2f} {i:11.2f} {over:8d}   {pl:.1f}")

    print("\n학습에는 --min-gen gen2 를 쓸 것. gen1 은 banked 라벨이 오염돼 있다"
          " (스크립트 상단 설명 참고).")


if __name__ == "__main__":
    sys.path.insert(0, REPO)
    main()
