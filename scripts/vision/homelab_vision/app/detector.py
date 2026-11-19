"""모델을 ultralytics 로 추론한다. 필수 두 모델(핑키 상태, 상자 D)과 선택 한 모델(팔).

홈랩 평가 조건: imgsz=960(INFER_IMGSZ 로 바꿈), iou=0.7, rect=False.
"""
import numpy as np
from ultralytics import YOLO

import model_slots
from config import FRAME_H, FRAME_W, IMGSZ, IOU, PREDICT_CONF


class Detector:
    def __init__(self, device, weights=None):
        """weights: {자리: 가중치 경로}. 없으면 model_slots.plan_slots() (팔 가중치가 있으면 세 자리, 없으면 두 자리)."""
        self.device = device
        weights = dict(weights) if weights is not None else model_slots.plan_slots()
        self.models, self.names, self.warmup_dets, self.arm_error = {}, {}, {}, None
        # 예열: 첫 추론의 초기화 시간을 시작 때 치른다. 회색 빈 프레임이라 검출은 없어야 한다.
        blank = np.full((FRAME_H, FRAME_W, 3), 114, np.uint8)
        for k, p in weights.items():
            try:
                self._load(k, p, blank)
            except ValueError:
                raise                        # 자리에 맞지 않는 모델: 어느 자리든 시작하지 않는다
            except Exception as e:           # noqa: BLE001
                if k != "arm":
                    raise
                # 팔 모델은 관찰용이다. 읽기·예열이 실패해도 필수 두 모델은 그대로 돈다.
                self.models.pop(k, None), self.names.pop(k, None), self.warmup_dets.pop(k, None)
                self.arm_error = f"{type(e).__name__}: {e}"
        self.has_arm = "arm" in self.models

    def _load(self, key, path, blank):
        model = YOLO(path, task="detect")
        names = {int(i): n for i, n in model.names.items()}
        # 자리에 맞지 않는 모델(예: 1클래스 팔 모델이 핑키 자리)은 조용히 틀린 판정을 내므로 시작하지 않는다.
        problem = model_slots.names_problem(key, names)
        if problem:
            raise ValueError(problem)
        self.models[key], self.names[key] = model, names
        self.warmup_dets[key] = len(self._one(key, blank))

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

    def infer_arm(self, frame):
        """-> 팔 검출 목록. 팔 모델이 없으면 None."""
        return self._one("arm", frame) if self.has_arm else None
