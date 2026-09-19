"""인스턴스 개수를 늘리면 수집이 실제로 빨라지는지 잰다.

    python scripts/12_throughput.py --counts 8,16,25 --minutes 6

**왜 재는가.** "인스턴스를 늘리면 빨라진다"는 자명해 보이지만 아니다. gen6 부터는
설계(파이썬 A*)가 CPU 를 많이 쓰고, 게임도 속도 8 로 돌아 CPU 를 쓴다. 코어보다
많이 띄우면 서로 CPU 를 뺏어 트랙당 시간이 그만큼 늘어난다. 이 스크립트는
개수별로 정해진 시간 동안 실제로 돌려서 **시간당 수집량**을 잰다.

각 구간마다: 인스턴스 n개 실행 -> 수집기 n개 붙임 -> minutes 분 대기 ->
수집기 종료 -> 그 사이 쌓인 레코드 수를 센다. 측정용 part 파일은
`data/tp_<n>_<port>.jsonl` 로 따로 쓴다 (세대 접두사가 아니라서
`build_dataset.py` 가 안 집어간다 -- 측정 결과를 데이터셋에 섞지 않는다).

시드는 `--seed-base` 부터 쓴다. **CLAUDE.md 의 "이미 쓴 시드"를 볼 것.**
"""
import argparse
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(errors="replace", line_buffering=True)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from rct.client import RCTClient      # noqa: E402


def alive(port, timeout=5):
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
    ap.add_argument("--counts", default="8,16,25")
    ap.add_argument("--minutes", type=float, default=6)
    ap.add_argument("--seed-base", type=int, default=7000)
    ap.add_argument("--speed", type=int, default=8)
    ap.add_argument("--warmup", type=float, default=60, help="측정 전 버리는 시간(초)")
    args = ap.parse_args()

    data = os.path.join(REPO, "data")
    results = []
    for run_i, n in enumerate(int(x) for x in args.counts.split(",")):
        print(f"\n== 인스턴스 {n}개")
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "run_instances.py"),
                        "--n", str(n)], cwd=REPO, timeout=900,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        up = [8080 + i for i in range(n) if alive(8080 + i)]
        print(f"  살아있는 인스턴스 {len(up)}/{n}")
        if not up:
            print("  건너뜀")
            continue

        procs, outs = [], []
        for i, port in enumerate(up):
            out = os.path.join(data, f"tp_{n}_{port}.jsonl")
            outs.append(out)
            log = open(out + ".log", "w", encoding="utf-8", errors="replace")
            procs.append(subprocess.Popen(
                [sys.executable, "-u", os.path.join(REPO, "scripts", "03_collect.py"),
                 "--port", str(port), "--seed", str(args.seed_base + run_i * 100 + i),
                 "--n", "100000", "--speed", str(args.speed), "--out", out],
                cwd=REPO, stdout=log, stderr=log))

        time.sleep(args.warmup)                 # 첫 트랙은 시작 비용이 섞인다
        base = sum(count(o) for o in outs)
        t0 = time.time()
        time.sleep(args.minutes * 60)
        got = sum(count(o) for o in outs) - base
        dt = time.time() - t0
        for p in procs:
            p.terminate()
        rate = got / dt * 3600
        results.append((n, len(up), got, rate))
        print(f"  {dt / 60:.1f}분에 {got}개 -> 시간당 {rate:,.0f}개 "
              f"(인스턴스당 {rate / len(up):,.0f})")

    print("\n== 결과")
    print(f"  {'인스턴스':>6s} {'시간당':>9s} {'인스턴스당':>9s}")
    for n, up, _got, rate in results:
        print(f"  {up:6d} {rate:9,.0f} {rate / up:9,.0f}")


if __name__ == "__main__":
    main()
