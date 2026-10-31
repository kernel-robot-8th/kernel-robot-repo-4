"""로봇 전용 LED 타입 없이도 순수 로직과 ROS 어댑터를 검증한다."""

from pathlib import Path
import sys
import types

for package in ('cobot_pinky_patrol', 'cobot_zone_traffic_control'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / package))
try:
    import pinky_interfaces.srv  # noqa: F401
except ImportError:
    stub = types.ModuleType('pinky_interfaces')
    stub.srv = types.ModuleType('pinky_interfaces.srv')
    stub.srv.SetLed = type('SetLed', (), {})
    sys.modules['pinky_interfaces'] = stub
    sys.modules['pinky_interfaces.srv'] = stub.srv
