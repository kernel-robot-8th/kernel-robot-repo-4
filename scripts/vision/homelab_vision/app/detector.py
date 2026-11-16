"""두 모델(핑키 상태, 상자 D)을 ultralytics 로 추론한다. 홈랩 평가 조건: imgsz=960, iou=0.7, rect=False."""
import numpy as np
from ultralytics import YOLO

from config import FRAME_H, FRAME_W, IMGSZ, IOU, PREDICT_CONF, WEIGHTS


class Detector:
    def __init__(self, device):
        self.device = device
        self.models = {k: YOLO(p, task="detect") for k, p in WEIGHTS.items()}
        self.names = {k: {int(i): n for i, n in m.names.items()} for k, m in self.models.items()}
        # 예열: 첫 추론의 초기화 시간을 시작 때 치른다. 회색 빈 프레임이라 검출은 없어야 한다.
        self.warmup_dets = {k: len(v) for k, v in zip(("pinky", "boxes"), self.infer(np.full((FRAME_H, FRAME_W, 3), 114, np.uint8)))}

    def _one(self, key, frame):
        r = self.models[key].predict(frame, imgsz=IMGSZ, iou=IOU, rect=False, conf=PREDICT_CONF, max_det=300, device=self.device,
                                     verbose=False, save=False, stream=False)[0]
        b = r.boxes
        xyxy, conf, cls = b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), b.cls.cpu().numpy()
        names = self.names[key]
        return [{"cls": int(c), "name": names.get(int(c), str(int(c))), "confidence": float(s), "bbox": [float(v) for v in box]}
                for box, s, c in zip(xyxy, conf, cls)]

    def infer(self, frame):
        """-> (핑키 검출, 상자 검출). 각 항목은 cls, name, confidence, bbox[x0, y0, x1, y1] (원본 프레임 픽셀)."""
        return self._one("pinky", frame), self._one("boxes", frame)
