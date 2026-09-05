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


def handle(req, model, tok, sim, env, client, device, cap):
    """요청 하나를 처리한다. 진행 상황은 게임 UI 에 되돌려 보여준다."""
    def status(msg):
        print(f"  {msg}")
        client.call("setGenerationStatus", {"status": msg}, strict=False)

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
        return

    status(f"폐곡선 {len(seqs)}개 -- 게임에서 채점 중...")
    seq, stats, tried = pick_best(env, seqs, target, intensity_cap=cap,
                                 verbose=False)
    built = sum(1 for t in tried if t["ok"])
    if seq is None:
        status(f"실패: {built}개 지었지만 조건을 만족하는 게 없음")
        return

    env.reset(station_length=3)
    env.build(seq)
    status(f"완료: E {stats['excitement']:.2f} / I {stats['intensity']:.2f} "
           f"/ latg {stats['maxLateralGs']:.2f} ({built}개 중 선택)")
    print(f"  -> 조각 {len(seq)}개, 최고속도 {stats['maxSpeed']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=os.path.join(REPO, "model", "ckpt.pt"))
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--poll", type=float, default=1.0, help="폴링 간격(초)")
    ap.add_argument("--cap", type=float, default=10.0, help="격렬도 상한")
    ap.add_argument("--once", action="store_true", help="요청 하나만 처리하고 종료")
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
    client.set_game_speed(8)
    env = WoodenCoasterEnv(client, origin=ORIGIN)
    client.call("setGenerationStatus", {"status": "데몬 연결됨 -- 대기 중"},
                strict=False)

    print(f"데몬 시작 (device={device}). 게임에서 지도 메뉴 -> "
          f"'우든 코스터 생성기' 를 열어 사용하세요. Ctrl+C 로 종료.")
    try:
        while True:
            resp = client.call("getGenerationRequest", strict=False)
            req = (resp or {}).get("request")
            if req:
                print(f"\n요청 받음: {req}")
                client.call("clearGenerationRequest", strict=False)
                try:
                    handle(req, model, tok, sim, env, client, device, args.cap)
                except Exception as e:
                    # 요청 하나가 죽어도 데몬은 살아있어야 한다.
                    msg = f"오류: {type(e).__name__}: {e}"
                    print(f"  {msg}")
                    client.call("setGenerationStatus", {"status": msg[:80]},
                                strict=False)
                if args.once:
                    break
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\n데몬 종료")


if __name__ == "__main__":
    main()
