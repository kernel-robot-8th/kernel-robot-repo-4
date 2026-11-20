"""detector_utils 단위 테스트 (ROS·ultralytics 불필요)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobot_person_detector.detector_utils import RateGate, select_person_boxes  # noqa: E402


def test_select_person_boxes_filters_class_conf_height():
    boxes = [(100, 100, 40, 120), (200, 100, 40, 120), (300, 100, 40, 10), (400, 100, 40, 120)]
    confs = [0.9, 0.3, 0.9, 0.7]
    classes = [0, 0, 0, 2]
    out = select_person_boxes(boxes, confs, classes, 0, 0.5, 20)
    assert out == [(100.0, 100.0, 40.0, 120.0, 0.9)]


def test_select_person_boxes_sorted_by_conf():
    out = select_person_boxes([(1, 1, 5, 50), (2, 2, 5, 50)], [0.6, 0.8], [0, 0], 0, 0.5, 20)
    assert [b[4] for b in out] == [0.8, 0.6]


def test_rate_gate():
    g = RateGate(0.2)
    assert g.ready(0.0)
    assert not g.ready(0.1)
    assert g.ready(0.25)
