"""0단계: 게임과 파이썬이 대화되는지 확인."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rct import constants as C
from rct.client import RCTClient

with RCTClient.discover() as c:
    objs = c.list_ride_objects()
    wooden = [o for o in objs if C.RIDE_TYPE_WOODEN in o.get("rideType", [])]
    print(f"라이드 오브젝트 {len(objs)}개, 그 중 우든 {len(wooden)}개")
    for o in wooden:
        print(f"  index={o['index']}  {o['identifier']}  {o['name']}")
    if not wooden:
        sys.exit("우든 코스터 오브젝트를 시나리오에 추가하세요.")

    segs = c.all_track_segments()
    print(f"트랙 조각 {len(segs)}종")
    c.delete_all_rides()
    print("\n[OK] 0단계 통과")
