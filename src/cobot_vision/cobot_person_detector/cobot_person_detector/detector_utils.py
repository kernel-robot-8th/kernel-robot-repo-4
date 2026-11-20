"""YOLO 결과에서 사람 bbox 를 고르는 순수 로직 (ROS·ultralytics 의존 없음)."""


def select_person_boxes(boxes_xywh, confs, classes, person_class, min_conf, min_height_px):
    """
    사람 클래스이고 신뢰도·높이 기준을 넘는 bbox 만 남긴다.

    boxes_xywh: [(cx, cy, w, h), ...] 픽셀 단위 (YOLO xywh 형식)
    반환: [(cx, cy, w, h, conf), ...] 신뢰도 높은 순
    """
    out = []
    for (cx, cy, w, h), conf, cls in zip(boxes_xywh, confs, classes):
        if int(cls) != person_class or conf < min_conf or h < min_height_px:
            continue
        out.append((float(cx), float(cy), float(w), float(h), float(conf)))
    out.sort(key=lambda b: -b[4])
    return out


class RateGate:
    """마지막 처리 이후 period[s] 가 지났을 때만 True. 최신 프레임만 처리하기 위해 쓴다."""

    def __init__(self, period):
        """period: 최소 처리 간격 [s]. 0 이하면 매번 처리."""
        self.period = period
        self.last = None

    def ready(self, now):
        """이번에 처리해도 되면 True 를 돌려주고 시각을 기록한다."""
        if self.last is not None and now - self.last < self.period:
            return False
        self.last = now
        return True
