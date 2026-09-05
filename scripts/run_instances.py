"""병렬 수집용 OpenRCT2 인스턴스를 띄우고, 포트가 실제로 갈렸는지 확인한다.

setup_instances.py 로 만든 인스턴스 폴더를 --user-data-path 로 물려서 띄운다.
각 인스턴스는 자기 폴더의 플러그인 사본을 로드하고, 거기 박힌 DEFAULT_PORT를
그대로 잡는다 (탐색 안 함 — 이유는 setup_instances.py 의 설명 참고).

띄운 뒤 netstat 으로 포트 -> PID 를 실제로 읽어서 표로 보여준다. 여기서
포트가 인스턴스 수만큼 서로 다르게 나와야 병렬 수집이 성립한다.

사용법:
    python scripts/run_instances.py --n 4
    python scripts/run_instances.py --n 4 --no-park   # 공원은 직접 로드
"""
import argparse
import os
import re
import subprocess
import sys
import time

EXE = r"C:\Program Files\OpenRCT2\openrct2.com"
BASE = os.path.join(os.path.expanduser("~"), "Documents", "OpenRCT2")
DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "rct-instances")
DEFAULT_PARK = os.path.join(BASE, "scenario", "내 새 시나리오.park")

CREATE_NEW_CONSOLE = 0x00000010


def listening_ports(base_port, n):
    """netstat 으로 base_port..base_port+n-1 의 리슨 상태를 읽는다.

    포트 하나에 PID가 여러 개 나오면 그게 바로 중복 bind 사고다 (Windows의
    SO_REUSEADDR 때문에 예외 없이 성공해버린다). 그래서 딕셔너리가 아니라
    포트별 PID 목록으로 모은다.
    """
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    found = {}
    wanted = set(range(base_port, base_port + n))
    for line in out.splitlines():
        m = re.search(r"\s127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING\s+(\d+)", line)
        if m and int(m.group(1)) in wanted:
            found.setdefault(int(m.group(1)), []).append(int(m.group(2)))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--base-port", type=int, default=8080)
    ap.add_argument("--park", default=DEFAULT_PARK)
    ap.add_argument("--no-park", action="store_true",
                    help="공원을 자동으로 열지 않는다 (직접 로드할 때).")
    ap.add_argument("--timeout", type=int, default=120,
                    help="포트가 다 뜰 때까지 기다리는 최대 초.")
    ap.add_argument("--check", action="store_true",
                    help="띄우지 않고 지금 떠 있는 포트 상태만 확인한다.")
    args = ap.parse_args()

    if not os.path.isfile(EXE):
        sys.exit(f"openrct2.com 을 못 찾았습니다: {EXE}")
    if not args.check and not args.no_park and not os.path.isfile(args.park):
        sys.exit(f"공원 파일이 없습니다: {args.park}")

    for i in range(0 if args.check else args.n):
        inst = os.path.join(args.root, f"inst{i}")
        if not os.path.isdir(inst):
            sys.exit(f"인스턴스 폴더가 없습니다: {inst}\n"
                     f"먼저: python scripts/setup_instances.py --n {args.n}")
        cmd = [EXE]
        if not args.no_park:
            # -n: 시나리오를 인스턴스 폴더에 새로 설치하지 말고 그대로 연다.
            cmd += [args.park, "-n"]
        cmd += [f"--user-data-path={inst}"]
        subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE)
        print(f"[run] inst{i} 실행 (포트 {args.base_port + i} 예정)")

    if not args.check:
        print(f"\n포트가 올라오길 기다리는 중 (최대 {args.timeout}초)...")
    deadline = time.time() + (0 if args.check else args.timeout)
    while True:
        found = listening_ports(args.base_port, args.n)
        if len(found) == args.n or time.time() >= deadline:
            break
        time.sleep(2)

    print("\n" + "=" * 46)
    ok = True
    for i in range(args.n):
        port = args.base_port + i
        pids = found.get(port, [])
        if len(pids) == 1:
            print(f"  {port}  PID {pids[0]}")
        elif not pids:
            print(f"  {port}  (없음 - 공원이 아직 로드 안 됐을 수 있음)")
            ok = False
        else:
            print(f"  {port}  PID {pids} <- 중복 bind!")
            ok = False
    print("=" * 46)

    all_pids = [p for pids in found.values() for p in pids]
    if ok and len(set(all_pids)) == args.n:
        print(f"\n[OK] 포트 {args.n}개가 서로 다른 프로세스에 갈렸습니다. 병렬 수집 가능.")
        print("\n터미널을 여러 개 열어서:")
        for i in range(args.n):
            print(f"  python scripts/03_collect.py --port {args.base_port + i} "
                  f"--seed {i} --n 250 --out data/part_{args.base_port + i}.jsonl")
    else:
        print("\n[!] 아직 다 안 떴습니다. 각 창에서 공원이 로드됐는지 확인하고 다시 이 스크립트의")
        print("    확인 부분만 돌리려면: python scripts/run_instances.py --n {} --check".format(args.n))
        sys.exit(1)


if __name__ == "__main__":
    main()
