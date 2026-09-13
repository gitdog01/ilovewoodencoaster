"""RCT2 스톡 우든 코스터를 뜯어 생성기 어휘의 커버리지를 잰다.

    python scripts/10_vocab_coverage.py
    python scripts/10_vocab_coverage.py --refresh-names --port 8080   # 이름표 갱신

**왜 필요한가.** "행동 공간에 없는 수는 아무리 탐색해도 안 나온다." 생성기가
쓰는 조각이 21종뿐인데, 사람이 만든 진짜 우든 코스터가 어떤 조각을 쓰는지
모르면 무엇이 빠졌는지도 모른다. 어휘 확장(5단계)의 우선순위 근거가 여기서 나온다.

예전에 이 분석을 한 번 했지만 **스크립트가 커밋된 적이 없어서** 숫자만 문서에
남고 재현이 안 됐다 (2026-09-13 문서 검증에서 걸렸다). 그래서 다시 만들었다.

TD6 형식 메모 (실측으로 확인한 것):
  - 파일 전체가 RCT2 sawyer RLE 로 눌려 있다. 마지막 4바이트는 체크섬이라 뺀다.
  - 헤더: 0x00 ride_type, 0x5C/0x5D/0x5E 흥미/격렬/멀미 (x10), 0x81/0x82 필요 공간.
    우든 코스터는 ride_type 52.
  - **조각열은 0xA5 부터** 시작한다 (0xA4 로 적어둔 자료가 많은데 실측하면 아니다).
    조각 하나가 2바이트 `(type, flags)` 이고 type 0xFF 가 종료자, flags 의 0x80 이
    체인리프트다. 검증: 0xA5 로 잡으면 종료자가 항상 짝수 위치에 떨어지고 첫
    조각이 스테이션/평지류로 나온다. 0xA4 로 잡으면 전부 Flat 으로 읽힌다.

조각 이름은 **추측하지 않는다.** `rct/constants.py` 의 NAMES(플러그인이 노출하는
것)와 `track_names.json`(게임의 `getAllTrackSegments` 설명)만 쓴다. 둘 다 없으면
번호로 표시한다.
"""
import argparse
import collections
import glob
import json
import os
import sys

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gen.random_walk import WEIGHTS, WEIGHTS_PLAIN     # noqa: E402
from rct import constants as C                         # noqa: E402

DEFAULT_TRACKS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Rollercoaster Tycoon 2\Tracks",
    r"C:\Program Files\Steam\steamapps\common\Rollercoaster Tycoon 2\Tracks",
    r"C:\GOG Games\RollerCoaster Tycoon 2\Tracks",
]
NAMES_FILE = os.path.join(REPO, "track_names.json")
ELEMENTS_OFFSET = 0xA5


def rle_decode(data):
    """RCT2 sawyer RLE. 최상위 비트가 서면 반복, 아니면 그만큼 그대로 복사."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b & 0x80:
            count = 257 - b
            i += 1
            if i >= n:
                break
            out += bytes([data[i]]) * count
            i += 1
        else:
            count = b + 1
            i += 1
            out += data[i:i + count]
            i += count
    return bytes(out)


def parse_td6(path):
    """(ride_type, [(조각, 체인), ...], 평점). 종료자를 못 찾으면 None."""
    raw = open(path, "rb").read()
    dec = rle_decode(raw[:-4])
    if len(dec) < ELEMENTS_OFFSET + 2:
        return None
    seq = []
    i = ELEMENTS_OFFSET
    while i + 1 < len(dec):
        if dec[i] == 0xFF:
            break
        seq.append((dec[i], bool(dec[i + 1] & 0x80)))
        i += 2
    else:
        return None
    return dec[0], seq, {"exc": dec[0x5C] / 10, "int": dec[0x5D] / 10,
                         "nau": dec[0x5E] / 10}


def load_segments():
    """type -> {description, trackGroup, length}. 게임이 알려준 값이다."""
    if not os.path.isfile(NAMES_FILE):
        return {}
    with open(NAMES_FILE, encoding="utf-8") as fp:
        return {int(k): v for k, v in json.load(fp).items()}


def refresh_names(port):
    from rct.client import RCTClient
    segs = RCTClient(port=port).all_track_segments()
    out = {str(s["type"]): {"description": s.get("description") or "",
                            "trackGroup": s.get("trackGroup"),
                            "length": s.get("length")}
           for s in segs}
    with open(NAMES_FILE, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1, sort_keys=True)
    named = sum(1 for v in out.values() if v["description"])
    print(f"{NAMES_FILE}: 세그먼트 {len(out)}개 (이름 있는 것 {named}개)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", default=None, help="TD6 폴더")
    ap.add_argument("--ride-type", type=int, default=C.RIDE_TYPE_WOODEN)
    ap.add_argument("--top", type=int, default=15, help="빠진 조각을 몇 개 보일지")
    ap.add_argument("--refresh-names", action="store_true",
                    help="게임에서 조각 이름표를 다시 받아온다 (게임이 떠 있어야 함)")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    if args.refresh_names:
        refresh_names(args.port)

    folder = args.tracks or next((p for p in DEFAULT_TRACKS if os.path.isdir(p)), None)
    if not folder or not os.path.isdir(folder):
        sys.exit("TD6 폴더를 못 찾았습니다. --tracks 로 지정하세요.\n찾아본 곳:\n  "
                 + "\n  ".join(DEFAULT_TRACKS))

    # Windows 는 파일 이름 대소문자를 안 가려서 *.TD6 과 *.td6 이 같은 파일을
    # 두 번 잡는다. 실제 경로로 중복을 없앤다 (예전에 디자인 수가 2배로 나왔다).
    files = sorted({os.path.normcase(os.path.realpath(p))
                    for pat in ("*.TD6", "*.td6")
                    for p in glob.glob(os.path.join(folder, pat))})
    print(f"{folder}\n  TD6 파일 {len(files)}개")

    segs = load_segments()

    def name_of(t):
        return (C.NAMES.get(t) or (segs.get(t) or {}).get("description")
                or f"(조각 {t})")

    def is_diagonal(t):
        """대각선 계열인가. 게임이 알려준 **길이**로 판별한다.

        이 조각들은 이름이 비어 있어서 (게임이 UI 용 설명을 안 준다) 번호로만
        보인다. 다만 길이가 45(=32*sqrt2, 대각 직선)나 87(직교<->대각 전환)이라
        기하학적으로 특정된다. 번호를 손으로 적는 것보다 이쪽이 안전하다.
        """
        return (segs.get(t) or {}).get("length") in (45, 87)

    designs, bad = [], 0
    for f in files:
        got = parse_td6(f)
        if got is None:
            bad += 1
            continue
        if got[0] == args.ride_type:
            designs.append((os.path.basename(f), got[1], got[2]))
    print(f"  라이드 타입 {args.ride_type}: {len(designs)}개"
          + (f" (파싱 실패 {bad}개)" if bad else ""))
    if not designs:
        sys.exit("해당 타입의 디자인이 없습니다.")

    counts = collections.Counter()
    for _n, seq, _s in designs:
        counts.update(t for t, _c in seq)
    total = sum(counts.values())

    gen_only = set(WEIGHTS) | set(WEIGHTS_PLAIN)
    gen_vocab = gen_only | set(C.STATION_PIECES)
    geo_vocab = set(C.NAMES)
    print()
    # 스테이션 조각을 어휘에 넣느냐 빼느냐로 3 포인트 갈린다. 둘 다 보인다 --
    # 예전 분석(53.1%)은 뺀 쪽이었고, 그걸 몰라서 재현이 안 맞는 줄 알았다.
    for label, vocab in [("생성기 어휘 (스테이션 제외)", gen_only),
                         ("생성기 어휘 (스테이션 포함)", gen_vocab),
                         ("geometry.json 어휘", geo_vocab)]:
        hit = sum(n for t, n in counts.items() if t in vocab)
        print(f"{label:<24} ({len(vocab):2d}종): {hit}/{total} 조각 커버 "
              f"({100 * hit / total:.1f}%)")

    lens = [len(s) for _n, s, _x in designs]
    print(f"\n디자인 {len(designs)}개, 조각 {total}개, 종류 {len(counts)}가지")
    print(f"조각 수 {min(lens)}~{max(lens)}, 평균 {total / len(designs):.0f}")

    missing = sorted(((n, t) for t, n in counts.items() if t not in gen_vocab),
                     reverse=True)
    miss_total = sum(n for n, _t in missing)
    print(f"\n생성기가 못 만드는 조각 {len(missing)}종 / {miss_total}개 "
          f"({100 * miss_total / total:.1f}%). 많이 쓰는 순:")
    print(f"  {'조각':<32} {'횟수':>5} {'전체 중':>7}  geometry.json")
    for n, t in missing[:args.top]:
        print(f"  {name_of(t):<32} {n:5d} {100 * n / total:6.1f}%  "
              f"{'있음' if t in geo_vocab else '없음'}")

    # 묶음은 **게임이 준 정보로만** 만든다. 조각 번호를 손으로 적으면 틀린다 --
    # 실제로 62 를 브레이크로 잘못 적었었고, 게임 이름표를 보니 99 가 브레이크였다.
    groups = {
        "60도 경사 계열": lambda t: "60" in name_of(t),
        "대각선 계열": is_diagonal,
        "브레이크류": lambda t: any(k in name_of(t) for k in ("브레이크", "부스터")),
        "나선(헬릭스)류": lambda t: "나선" in name_of(t),
        "S자 트랙": lambda t: "S자" in name_of(t),
        "루프/트위스트/롤": lambda t: any(k in name_of(t)
                                   for k in ("루프", "트위스트", "롤")),
    }
    # 배타적으로 나눈다 (먼저 맞는 묶음이 가져간다). 겹치게 두면 합계를 잘못
    # 읽는다 -- 예를 들어 대각선 브레이크는 두 묶음에 다 걸린다.
    print("\n묶음별 (배타적. 합이 전체와 맞는다):")
    assigned, rows = set(), []
    for g, pred in groups.items():
        ids = [t for t in counts if t not in assigned and pred(t)]
        assigned |= set(ids)
        n = sum(counts[t] for t in ids)
        if n:
            rows.append((g, n, sum(counts[t] for t in ids if t not in gen_vocab)))
    rest = [t for t in counts if t not in assigned]
    rows.append(("그 밖 (기본 조각)", sum(counts[t] for t in rest),
                 sum(counts[t] for t in rest if t not in gen_vocab)))
    for g, n, miss in rows:
        print(f"  {g:<18} {n:5d}개 ({100 * n / total:4.1f}%)  "
              f"그중 생성기가 못 만드는 것 {miss:4d}개")
    print(f"  {'합계':<18} {sum(r[1] for r in rows):5d}개  "
          f"(전체 {total}개와 일치: {sum(r[1] for r in rows) == total})")


if __name__ == "__main__":
    main()
