"""수집이 무인으로 오래 돌 때 죽은 인스턴스를 되살린다.

    python scripts/collect_watchdog.py --n 25 --tag run5 --seed-base 500

**왜 필요한가.** OpenRCT2 인스턴스가 가끔 죽는다 (2026-09-13 에 한 번 봤다).
그러면 그 포트에 붙은 수집기도 같이 멈추는데, `collect_all.py` 는 되살리지
않는다. 무인으로 몇 시간 돌리면 25개 중 몇 개가 조용히 놀고 있게 된다.

하는 일은 두 가지뿐이다:
  1. 포트마다 살아있는지 찔러본다 (`listAllRides`).
  2. 죽었으면 그 인스턴스를 다시 띄우고 수집기도 다시 붙인다.

수집기는 트랙 하나 끝날 때마다 자기 part 파일에 append 하므로, 중간에 죽어도
모은 건 남는다. 되살릴 때 **시드를 바꿔서** 같은 트랙을 다시 뽑지 않게 한다.
"""
import argparse
import datetime
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(errors="replace", line_buffering=True)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from rct.client import RCTClient      # noqa: E402


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")


def alive(port, timeout=8):
    try:
        c = RCTClient(port=port, timeout=timeout)
        c.list_rides()
        c.close()
        return True
    except Exception:
        return False


def count(path):
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8", errors="replace") as fp:
        return sum(1 for line in fp if line.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--base-port", type=int, default=8080)
    ap.add_argument("--tag", default="run5")
    ap.add_argument("--seed-base", type=int, default=500)
    ap.add_argument("--each", type=int, default=20000)
    ap.add_argument("--speed", type=int, default=8)
    ap.add_argument("--interval", type=float, default=300, help="점검 간격(초)")
    args = ap.parse_args()

    data = os.path.join(REPO, "data")
    # 되살릴 때 쓸 시드. 원래 시드와 안 겹치게 멀찍이 떨어뜨린다.
    revive_seed = args.seed_base + 10000
    restarts = {}
    last = {}

    log(f"감시 시작: 포트 {args.base_port}~{args.base_port + args.n - 1}, "
        f"{args.interval:.0f}초마다 점검")
    while True:
        time.sleep(args.interval)
        total = 0
        dead = []
        for i in range(args.n):
            port = args.base_port + i
            out = os.path.join(data, f"{args.tag}_{port}.jsonl")
            n = count(out)
            total += n
            grew = n > last.get(port, -1)
            last[port] = n
            if not alive(port):
                dead.append((i, port, out))
            elif not grew and port in last:
                pass          # 살아있는데 안 늘었으면 그냥 느린 것일 수 있다
        log(f"합계 {total}개" + (f"  죽은 포트 {[p for _i, p, _o in dead]}" if dead else "  전부 정상"))

        for i, port, out in dead:
            nth = restarts.get(port, 0) + 1
            restarts[port] = nth
            log(f"  포트 {port} 되살리는 중 ({nth}번째)")
            try:
                subprocess.run(
                    [sys.executable, os.path.join(REPO, "scripts", "run_instances.py"),
                     "--start", str(i), "--n", "1"],
                    cwd=REPO, timeout=240,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                log(f"    인스턴스 재실행 실패: {type(e).__name__}")
                continue
            if not alive(port):
                log("    포트가 아직 안 올라옴 -- 다음 점검에 다시 시도")
                continue
            seed = revive_seed + i * 100 + nth
            logf = open(os.path.join(data, f"{args.tag}_{port}.revive{nth}.log"),
                        "w", encoding="utf-8", errors="replace")
            subprocess.Popen(
                [sys.executable, "-u", os.path.join(REPO, "scripts", "03_collect.py"),
                 "--port", str(port), "--seed", str(seed), "--n", str(args.each),
                 "--speed", str(args.speed), "--out", out],
                cwd=REPO, stdout=logf, stderr=logf)
            log(f"    수집기 재시작 (seed {seed})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n감시 종료 (수집기는 그대로 돕니다)")
