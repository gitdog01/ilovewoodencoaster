"""병렬 수집용 OpenRCT2 인스턴스 폴더를 만든다.

왜 이게 필요한가
----------------
플러그인은 8080부터 빈 포트를 찾아 올라가게 돼 있지만, Windows에서는 그게
동작하지 않는다. OpenRCT2가 리슨 소켓에 SO_REUSEADDR를 켜는데 Windows의
SO_REUSEADDR는 **다른 프로세스가 이미 리슨 중인 포트에 대한 bind를 그냥
허용**한다. 그래서 두 번째 인스턴스의 bind가 조용히 성공하고, 예외가 안 나니
포트 탐색 루프는 한 번도 위로 안 올라간다. 실측으로 인스턴스 3개가 전부
8080에 겹쳤다. 게임 안에서 클라이언트 소켓으로 미리 찔러보는 방법도 막혀
있다 (network.createSocket()의 connect 콜백이 이 빌드에서 안 불린다).

그래서 포트를 탐색하지 않고 **인스턴스마다 못 박는다.** OpenRCT2의
--user-data-path 로 인스턴스별 유저 데이터 폴더를 주고, 각 폴더의 플러그인
사본에 DEFAULT_PORT를 다르게 써넣는다. 덤으로 debug_replay.parkrep / autosave
처럼 인스턴스끼리 같은 파일에 겹쳐 쓰던 문제도 같이 사라진다.

무거운 공용 자산(시나리오, 오브젝트 등)은 복사하지 않고 정션으로 걸어서
원본과 계속 같이 간다. 샌드박스 맵을 나중에 고쳐도 인스턴스가 자동으로 따라온다.

사용법:
    python scripts/setup_instances.py --n 4
    python scripts/run_instances.py --n 4
"""
import argparse
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(os.path.expanduser("~"), "Documents", "OpenRCT2")
DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "rct-instances")
PLUGIN_SRC = os.path.join(REPO, "plugin", "ridecreation-api.js")

# 원본과 공유해도 되는(읽기 위주) 디렉터리 — 정션으로 건다.
SHARED_DIRS = ["scenario", "object", "objdata", "track", "assetpack",
               "sequence", "heightmap", "landscape", "themes"]
# 인스턴스마다 따로 가져야 하는 파일 — 복사한다.
COPY_FILES = ["config.ini", "shortcuts.json", "servers.cfg", "highscores.dat",
              "objects.idx", "scenarios.idx", "tracks.idx"]
# 인스턴스마다 비어 있는 채로 시작하는 디렉터리.
FRESH_DIRS = ["plugin", "save", "screenshot", "crash", "desyncs", "replay"]


def junction(link, target):
    """디렉터리 정션을 만든다 (심볼릭 링크와 달리 관리자 권한이 필요 없다)."""
    subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                   check=True, capture_output=True)


def make_instance(root, index, port):
    inst = os.path.join(root, f"inst{index}")
    if os.path.exists(inst):
        shutil.rmtree(inst)
    os.makedirs(inst)

    for name in SHARED_DIRS:
        src = os.path.join(BASE, name)
        if os.path.isdir(src):
            junction(os.path.join(inst, name), src)

    for name in COPY_FILES:
        src = os.path.join(BASE, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(inst, name))

    for name in FRESH_DIRS:
        os.makedirs(os.path.join(inst, name), exist_ok=True)

    # 플러그인 사본에 이 인스턴스의 포트를 박는다.
    with open(PLUGIN_SRC, encoding="utf-8") as fp:
        js = fp.read()
    old = "    const DEFAULT_PORT = 8080;"
    if old not in js:
        sys.exit(f"플러그인에서 DEFAULT_PORT 줄을 못 찾았습니다: {PLUGIN_SRC}")
    js = js.replace(old, f"    const DEFAULT_PORT = {port};", 1)
    dst = os.path.join(inst, "plugin", "ridecreation-api.js")
    with open(dst, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(js)

    return inst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4, help="만들 인스턴스 개수")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="인스턴스 폴더를 둘 위치")
    ap.add_argument("--base-port", type=int, default=8080)
    args = ap.parse_args()

    if not os.path.isfile(PLUGIN_SRC):
        sys.exit(f"플러그인 정본이 없습니다: {PLUGIN_SRC}")
    if not os.path.isdir(BASE):
        sys.exit(f"OpenRCT2 유저 데이터 폴더가 없습니다: {BASE}")

    os.makedirs(args.root, exist_ok=True)
    for i in range(args.n):
        port = args.base_port + i
        inst = make_instance(args.root, i, port)
        print(f"[setup] inst{i}  포트 {port}  {inst}")

    print(f"\n{args.n}개 준비 완료. 다음:  python scripts/run_instances.py --n {args.n}")


if __name__ == "__main__":
    main()
