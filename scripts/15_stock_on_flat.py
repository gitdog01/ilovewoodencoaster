"""스톡 우든 코스터를 우리 빈 평지에 그대로 지어서 평점을 다시 잰다.

    python scripts/15_stock_on_flat.py --port 8080
    python scripts/15_stock_on_flat.py --port 8080 --only "Hardwood"

**왜 필요한가.** 흥미도 천장이 6점대에 막혀 있고 사람은 7.90 이다. 그런데
스톡 TD6 헤더의 평점은 **주경이 깔린 원래 공원에서** 계산된 값이다. OpenRCT2
흥미도에는 트랙 모양 말고도 sheltered / proximity / scenery 항이 있고, 우리는
아무것도 없는 평지에서 잰다. 같은 트랙을 같은 조건에서 재야 비교가 된다.

짓는 법: TD6 조각열은 END_STATION 으로 시작하고 스테이션 나머지가 맨 끝에
있다. 그 스테이션 덩어리가 맨 앞에 오도록 회전시키고, 첫 조각부터 `place()`
가 돌려주는 nextEndpoint 를 따라간다. 기하 표가 필요 없다.

TD6 조각 flags: 0x80 체인리프트, 하위 니블은 좌석 회전(기본 4) 또는 브레이크
속도/2. 헤더 0x4C 열차 수, 0x4D 칸 수 (11_human_gap.py 와 같은 1바이트 어긋남).
"""
import argparse
import glob
import importlib
import json
import os
import statistics as st
import sys
import time

sys.stdout.reconfigure(errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
cov = importlib.import_module("10_vocab_coverage")
gap = importlib.import_module("11_human_gap")

from rct import constants as C                 # noqa: E402
from rct.client import RCTClient               # noqa: E402

SPEED_PIECES = {99, 100, 216}      # 브레이크 / 부스터 / 블록 브레이크


def load_design(path):
    d = cov.rle_decode(open(path, "rb").read()[:-4])
    if d[0] != C.RIDE_TYPE_WOODEN:
        return None
    seq, i = [], cov.ELEMENTS_OFFSET
    while d[i] != 0xFF:
        seq.append((d[i], d[i + 1]))
        i += 2
    # 스테이션 덩어리(끝의 연속 스테이션 + 맨 앞 END_STATION)를 앞으로.
    k = len(seq)
    while k > 0 and seq[k - 1][0] in C.STATION_PIECES:
        k -= 1
    seq = seq[k:] + seq[:k]
    vehicle = d[0x74:0x7C].decode("ascii", "replace").strip()
    return {"seq": seq, "trains": d[0x4C], "cars": d[0x4D], "vehicle": vehicle}


def build(c, obj, design, origin, brake_default):
    rid = c.create_ride(C.RIDE_TYPE_WOODEN, obj)
    x, y, z = origin
    pos = {"x": x, "y": y, "z": z, "direction": 0}
    complete = False
    low = z
    for n, (t, fl) in enumerate(design["seq"]):
        speed = 0
        if t in SPEED_PIECES:
            speed = (fl & 0x0F) * 2 or brake_default
        p = c.place(rid, C.RIDE_TYPE_WOODEN, pos["x"], pos["y"], pos["z"],
                    pos["direction"], t, chain=bool(fl & 0x80),
                    brake_speed=speed)
        if p is None:
            err = c.place_full(rid, C.RIDE_TYPE_WOODEN, pos["x"], pos["y"],
                               pos["z"] - c._z_offset(t), pos["direction"], t,
                               bool(fl & 0x80), speed).get("error")
            return rid, n, f"piece {n} type {t} @ {pos}: {err}"
        low = min(low, pos["z"] - c._z_offset(t))
        pos = p["nextEndpoint"]
        complete = bool(p.get("isCircuitComplete"))
    design["low"] = low - z          # 스테이션 대비 최저 base z
    return rid, len(design["seq"]), None if complete else "not closed"


def rate(c, rid, timeout):
    c.start_test(rid)
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = c.measurements(rid)
        if m and m.get("excitement", 0) > 0:
            return m
        time.sleep(0.5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--tracks", default=None)
    ap.add_argument("--only", default=None, help="파일 이름 부분 문자열")
    ap.add_argument("--ground", type=int, default=14, help="지면 높이")
    ap.add_argument("--probe-z", type=int, default=44,
                    help="최저점을 재려고 먼저 지어보는 스테이션 높이")
    ap.add_argument("--clearance", type=int, default=2,
                    help="최저점을 지면보다 이만큼 띄운다 (땅에 안 박히게)")
    ap.add_argument("--brake-default", type=int, default=25)
    ap.add_argument("--default-train", action="store_true",
                    help="TD6 편성 대신 게임 기본 편성으로 잰다")
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--out", default=os.path.join(REPO, "data", "stock_on_flat.jsonl"))
    args = ap.parse_args()

    folder = args.tracks or next(p for p in cov.DEFAULT_TRACKS if os.path.isdir(p))
    files = sorted({os.path.normcase(os.path.realpath(p))
                    for pat in ("*.TD6", "*.td6")
                    for p in glob.glob(os.path.join(folder, pat))})
    stock = {os.path.basename(f): s for f, s in
             zip([f for f in files if load_design(f)],
                 gap.stock_stats(folder, C.RIDE_TYPE_WOODEN))}

    c = RCTClient(port=args.port, timeout=120)
    c.set_game_speed(8)
    obj = next(o["index"] for o in c.list_ride_objects()
               if C.RIDE_TYPE_WOODEN in o.get("rideType", []))
    plot = c.find_free_plot(60, 60)
    cx = (plot["plot"]["x0"] + plot["plot"]["x1"]) // 2
    cy = (plot["plot"]["y0"] + plot["plot"]["y1"]) // 2
    print(f"스테이션 origin ({cx},{cy})  부지 {plot['plot']}")

    rows = []
    out = open(args.out, "w", encoding="utf-8")
    for f in files:
        name = os.path.basename(f)
        if args.only and args.only.lower() not in name.lower():
            continue
        design = load_design(f)
        if design is None:
            continue
        ref = stock[name]
        # 1) 높이 지어서 최저점을 잰다. 2) 최저점이 지면+clearance 에 오게
        # 스테이션을 내려 다시 짓는다. 지면에 바로 지으면 스톡 디자인의 지하
        # 구간(원래 공원의 터널)이 땅에 박혀 NoClearance 가 난다.
        c.delete_all_rides()
        rid, placed, err = build(c, obj, design, (cx, cy, args.probe_z),
                                 args.brake_default)
        z = args.probe_z
        if err is None:
            z0 = args.ground + args.clearance - design["low"]
            for z in range(z0, z0 + 12, 2):
                c.delete_all_rides()
                rid, placed, err = build(c, obj, design, (cx, cy, z),
                                         args.brake_default)
                if err is None:
                    break
        rec = {"name": name, "vehicle": design["vehicle"], "stock": ref,
               "pieces": len(design["seq"]), "z": z, "low": design.get("low")}
        if err:
            rec["error"] = err
            print(f"{name[:26]:<26} 배치 실패: {err}")
        else:
            c.place_entrance_exit(rid)
            if not args.default_train:
                rec["vehicles"] = c.set_vehicles(rid, cars=design["cars"],
                                                 trains=design["trains"])
            try:
                m = rate(c, rid, args.timeout)
            except Exception as e:           # noqa: BLE001
                m, rec["error"] = None, str(e)
            rec["flat"] = m
            if m:
                rows.append(rec)
                print(f"{name[:26]:<26} z{z:<3} 흥미 {ref['excitement']:.2f} -> "
                      f"{m['excitement']:.2f}  격렬 {ref['intensity']:.2f} -> "
                      f"{m['intensity']:.2f}  길이 {ref['rideLength']} -> "
                      f"{m.get('rideLength')}  낙하 {ref['numDrops']} -> "
                      f"{m.get('numDrops')}  [{design['vehicle']}]")
            else:
                print(f"{name[:26]:<26} 평점 안 나옴 {rec.get('error', '(timeout)')}")
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
    c.delete_all_rides()

    if rows:
        se = [r["stock"]["excitement"] for r in rows]
        fe = [r["flat"]["excitement"] for r in rows]
        si = [r["stock"]["intensity"] for r in rows]
        fi = [r["flat"]["intensity"] for r in rows]
        print(f"\n평점 나온 것 {len(rows)}개")
        print(f"  흥미 중앙: 스톡 {st.median(se):.2f} -> 빈 평지 {st.median(fe):.2f}"
              f"  (차이 중앙 {st.median(b - a for a, b in zip(se, fe)):+.2f})")
        print(f"  흥미 최대: 스톡 {max(se):.2f} -> 빈 평지 {max(fe):.2f}")
        print(f"  격렬 중앙: 스톡 {st.median(si):.2f} -> 빈 평지 {st.median(fi):.2f}")


if __name__ == "__main__":
    main()
