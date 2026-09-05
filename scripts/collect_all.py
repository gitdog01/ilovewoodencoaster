"""여러 인스턴스에 수집기를 한꺼번에 붙인다.

run_instances.py 로 띄운 인스턴스마다 03_collect.py 를 하나씩 물려서 병렬로
수집한다. 인스턴스가 4개면 터미널 4개를 여는 게 낫지만 12개쯤 되면 손으로는
못 한다.

각 수집기는 트랙 하나 끝날 때마다 자기 part 파일에 append 하므로, 중간에
Ctrl+C 로 끊어도 그때까지 모은 건 그대로 남는다. 그래서 --each 는 넉넉히
잡아두고 원하는 만큼 모이면 끊는 쪽이 편하다.

사용법:
    python scripts/collect_all.py --start 4 --n 8 --each 1500 --seed-base 20
    python scripts/collect_all.py --n 12 --each 2000 --tag part3
"""
import argparse
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECT = os.path.join(REPO, "scripts", "03_collect.py")


def count(path):
    if not os.path.isfile(path):
        return 0
    with open(path, "rb") as fp:
        return sum(1 for _ in fp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4, help="수집기 개수")
    ap.add_argument("--start", type=int, default=0, help="인스턴스 시작 번호")
    ap.add_argument("--base-port", type=int, default=8080)
    ap.add_argument("--each", type=int, default=250, help="수집기 하나당 시도 횟수")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="시드 시작값. 이미 쓴 시드와 겹치면 같은 트랙이 또 나온다.")
    ap.add_argument("--tag", default="part", help="출력 파일 접두사")
    ap.add_argument("--speed", type=int, default=8)
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)
    procs = []
    for i in range(args.n):
        port = args.base_port + args.start + i
        out = os.path.join(REPO, "data", f"{args.tag}_{port}.jsonl")
        cmd = [sys.executable, COLLECT, "--port", str(port),
               "--seed", str(args.seed_base + i), "--n", str(args.each),
               "--speed", str(args.speed), "--out", out]
        # 출력은 각자 로그 파일로. 12개가 한 콘솔에 섞이면 못 읽는다.
        log = open(os.path.join(REPO, "data", f"{args.tag}_{port}.log"), "w",
                   encoding="utf-8", errors="replace")
        procs.append((port, out, subprocess.Popen(cmd, stdout=log, stderr=log), log))
        print(f"[collect] 포트 {port} 시작 -> {os.path.basename(out)}")

    print(f"\n{args.n}개 수집기 실행 중. Ctrl+C 로 끊어도 모은 건 남는다.\n")
    t0 = time.time()
    try:
        while any(p.poll() is None for _, _, p, _ in procs):
            time.sleep(30)
            total = sum(count(out) for _, out, _, _ in procs)
            el = time.time() - t0
            rate = total / el if el else 0
            alive = sum(1 for _, _, p, _ in procs if p.poll() is None)
            print(f"[{el/60:5.1f}분] {total}개  "
                  f"({rate:.2f}개/초, 트랙당 {1/rate if rate else 0:.1f}초)  "
                  f"수집기 {alive}/{args.n} 살아있음")
    except KeyboardInterrupt:
        print("\n중단 요청 -- 수집기를 정리합니다.")
        for _, _, p, _ in procs:
            p.terminate()

    for _, _, p, log in procs:
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
        log.close()

    total = sum(count(out) for _, out, _, _ in procs)
    el = time.time() - t0
    print(f"\n끝. {total}개 / {el/60:.1f}분 (트랙당 {el/total if total else 0:.1f}초)")
    for port, out, _, _ in procs:
        print(f"  {port}: {count(out)}개  {os.path.basename(out)}")


if __name__ == "__main__":
    main()
