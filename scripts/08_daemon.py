"""5단계: 게임 UI 의 생성 요청을 받아 처리하는 데몬.

    python scripts/08_daemon.py --port 8080

게임 안에서 지도 메뉴 -> "우든 코스터 생성기" 창을 열고 목표값을 넣은 뒤
"트랙 생성"을 누르면, 이 데몬이 그 요청을 가져다 07_bestof.py 와 같은 흐름
(LM 후보 -> A* 마무리 -> 게임 채점 -> 최고 선택)을 돌리고 트랙을 남긴다.

**왜 데몬이 게임을 폴링하는가.** 모델은 파이썬(PyTorch)에 있고 플러그인은
게임 안 quickjs 라 직접 호출을 못 한다. 자연스러운 방향은 "플러그인 -> 파이썬"
인데, 이 빌드에서는 network.createSocket() 의 connect 콜백이 안 와서 플러그인이
바깥으로 거는 연결을 못 믿는다 (포트 자동 탐색이 깨진 것과 같은 원인).
그래서 검증된 방향(파이썬 -> 게임)만 쓰고 방향을 뒤집었다.
"""
import argparse
import os
import sys
import time

# 오래 도는 데몬이라 줄 단위로 흘려보낸다. 파일이나 파이프로 리다이렉트하면
# 기본이 블록 버퍼링이라, 정작 멈췄을 때 로그가 텅 빈 채로 남는다.
sys.stdout.reconfigure(errors="replace", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch

from geom.simulator import Bounds, TrackSimulator
from model.bestof import pick_best
from model.gpt import GPT, GPTConfig
from model.hybrid import generate_closed, station_states
from model.tokenizer import TrackTokenizer
from rct.client import RCTClient
from rct.env import WoodenCoasterEnv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGIN = (67, 66, 14)
DIRECTION = 0


def handle(req, model, tok, sim, env, client, device, cap, idle_speed=1,
           keep=False):
    """요청 하나를 처리한다. 진행 상황은 게임 UI 에 되돌려 보여준다."""
    def status(msg):
        print(f"  {msg}")
        client.call("setGenerationStatus", {"status": msg}, strict=False)

    # 채점(테스트 주행)은 시뮬 시간 ~35초가 필요해서 속도를 올려야 하지만,
    # 유저 공원을 계속 8배속으로 돌려놓으면 안 된다. 처리하는 동안만 올린다.
    client.set_game_speed(8)
    delivered = False
    try:
        delivered = _handle(req, model, tok, sim, env, client, device, cap,
                            status, keep)
    finally:
        client.set_game_speed(idle_speed)
        # 실패하거나 예외로 끝나면 채점하던 후보가 공원에 그대로 남는다.
        # 성공했으면 그건 유저에게 보여줄 완성품이니 놔둔다.
        if not delivered and env.ride_id is not None:
            client.delete_ride(env.release())


def _handle(req, model, tok, sim, env, client, device, cap, status, keep):
    """트랙을 하나 넘겼으면 True. False 면 공원에 남은 건 치워야 할 찌꺼기다."""
    width = int(req.get("width", 28))
    depth = int(req.get("depth", 24))
    n = int(req.get("n", 16))
    target = {"exc": float(req.get("exc", 5)), "int": float(req.get("int", 8)),
              "nau": float(req.get("nau", 3)), "latg": float(req.get("latg", 2.5))}

    bounds = Bounds.plot(ORIGIN, DIRECTION, width, depth, 60)
    start, goal, tiles = station_states(sim, ORIGIN, DIRECTION, 3)
    cond = dict(target, width=width, depth=depth, height=60, station=3)

    status(f"후보 {n}개 생성 중...")
    seqs = generate_closed(model, tok, cond, sim, bounds, start, goal, n,
                           device, station_tiles=tiles)
    if not seqs:
        status("실패: 폐곡선 후보 없음. 부지를 키우거나 후보 수를 늘려보세요.")
        return False

    status(f"폐곡선 {len(seqs)}개 -- 게임에서 채점 중...")
    # clear="own": 후보를 갈아끼울 때 이 env 가 만든 라이드만 지운다.
    # 기본값("all")이면 유저 공원의 다른 라이드까지 전부 날아간다.
    seq, stats, tried = pick_best(env, seqs, target, intensity_cap=cap,
                                  verbose=False, clear="own")
    built = sum(1 for t in tried if t["ok"])
    if seq is None:
        status(f"실패: {built}개 지었지만 조건을 만족하는 게 없음")
        return False

    env.reset(station_length=3, clear="own")
    env.build(seq)
    if keep:
        # 완성품을 유저 것으로 넘긴다. 단, ORIGIN 이 고정이라 그 자리가 계속
        # 막히므로 **다음 요청은 스테이션을 못 깐다.** 유저가 직접 치우거나
        # 자리를 옮기기 전까지는 한 번만 되는 모드다 (좌표 선택은 TODO).
        env.release()
    status(f"완료: E {stats['excitement']:.2f} / I {stats['intensity']:.2f} "
           f"/ latg {stats['maxLateralGs']:.2f} ({built}개 중 선택)")
    print(f"  -> 조각 {len(seq)}개, 최고속도 {stats['maxSpeed']}")
    if keep:
        print("  (--keep: 이 트랙을 남겨둡니다. 다음 요청은 같은 자리에 못 지으니 "
              "먼저 치우세요.)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=os.path.join(REPO, "model", "ckpt.pt"))
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--poll", type=float, default=1.0, help="폴링 간격(초)")
    ap.add_argument("--cap", type=float, default=10.0, help="격렬도 상한")
    ap.add_argument("--once", action="store_true", help="요청 하나만 처리하고 종료")
    ap.add_argument("--idle-speed", type=int, default=1,
                    help="요청 처리가 끝난 뒤 되돌릴 게임 속도")
    ap.add_argument("--keep", action="store_true",
                    help="완성된 트랙을 남긴다. 기본은 다음 요청 때 자기 트랙을 "
                         "갈아끼우는 것 -- ORIGIN 이 고정이라 남기면 그 자리가 "
                         "막혀서 다음 요청이 실패한다. 유저가 지은 다른 라이드는 "
                         "어느 쪽이든 건드리지 않는다.")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = TrackTokenizer()
    ck = torch.load(args.ckpt, map_location=device, weights_only=False)
    model = GPT(GPTConfig(**ck["cfg"])).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    sim = TrackSimulator("geometry.json")

    ports = [args.port] if args.port else range(8080, 8110)
    client = RCTClient.discover(ports=ports)
    env = WoodenCoasterEnv(client, origin=ORIGIN)
    client.call("setGenerationStatus", {"status": "데몬 연결됨 -- 대기 중"},
                strict=False)

    print(f"데몬 시작 (device={device}). 게임에서 지도 메뉴 -> "
          f"'우든 코스터 생성기' 를 열어 사용하세요. Ctrl+C 로 종료.")

    def reconnect():
        """게임을 껐다 켜도 데몬은 살아있게 한다.

        실제로 채점 도중 게임 창을 닫았더니 ConnectionAbortedError 로 데몬이
        통째로 죽었다. 유저가 게임을 다시 켜면 알아서 다시 붙어야 한다.
        """
        nonlocal client, env
        while True:
            try:
                client = RCTClient.discover(ports=ports, verbose=False)
                env = WoodenCoasterEnv(client, origin=ORIGIN)
                print("  게임에 다시 연결됨")
                return
            except Exception:
                time.sleep(3)

    try:
        while True:
            try:
                resp = client.call("getGenerationRequest", strict=False)
            except (OSError, Exception) as e:
                print(f"  연결 끊김 ({type(e).__name__}) -- 재접속 대기")
                reconnect()
                continue
            req = (resp or {}).get("request")
            if req:
                print(f"\n요청 받음: {req}")
                client.call("clearGenerationRequest", strict=False)
                try:
                    handle(req, model, tok, sim, env, client, device,
                           args.cap, args.idle_speed, args.keep)
                except Exception as e:
                    # 요청 하나가 죽어도 데몬은 살아있어야 한다.
                    msg = f"오류: {type(e).__name__}: {e}"
                    print(f"  {msg}")
                    try:
                        client.call("setGenerationStatus",
                                    {"status": msg[:80]}, strict=False)
                    except Exception:
                        reconnect()      # 게임이 내려간 경우
                if args.once:
                    break
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\n데몬 종료")


if __name__ == "__main__":
    main()
