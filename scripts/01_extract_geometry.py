"""2단계: geometry.json 생성."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geom.extract import extract
from rct.client import RCTClient

with RCTClient.discover() as c:
    # z=14+16: 내리막류 조각(FlatToDown25 등)이 땅에 파고들지 않을 만큼만 살짝 띄운다.
    # 너무 높이 띄우면 지지대 최대 높이 제한에 걸리므로 과하게 올리지 않는다.
    extract(c, origin=(67, 66, 30), out="geometry.json")
