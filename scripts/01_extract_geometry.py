"""2단계: geometry.json 생성."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geom.extract import extract
from rct.client import RCTClient

with RCTClient.discover() as c:
    extract(c, origin=(67, 66, 14), out="geometry.json")
