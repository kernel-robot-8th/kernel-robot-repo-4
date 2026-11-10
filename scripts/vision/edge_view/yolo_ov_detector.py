#!/usr/bin/env python3
"""evt960 OpenVINO YOLO 검출기 — ultralytics 8.4.193 predict 의 전처리·후처리를 numpy 로 옮긴 참조 구현.

홈랩(DEV)에서 ultralytics predict 결과와 대조해 만든 파일이다. 필요한 것은 numpy, opencv-python, openvino 뿐이다
(PyYAML·torch·ultralytics 불필요). 프레임 사진을 디스크에 쓰지 않는다(FD-16).

- 전처리: 레터박스(비율 유지, 회색 114, 가운데 정렬) -> BGR->RGB -> /255 -> NCHW float32.
  cv2.resize 로 늘려 맞추면 안 된다. 학습·검증이 모두 레터박스였다.
- 모델 출력: (1, 4+nc, A). 0~3행은 레터박스 좌표계의 cx, cy, w, h 픽셀, 나머지 행은 시그모이드가 적용된 클래스 점수.
- 후처리: 앵커마다 최고 점수 클래스 하나 -> 점수 > conf -> 클래스별 NMS(iou) -> max_det -> 원본 프레임 좌표로 복원·클립.

사용:
    det = OVYoloDetector("/home/kgh1005/yolo_edge/models/best_openvino_model")  # 폴더 또는 best.xml
    for d in det.detect(frame_bgr, conf=0.5):
        d["class_id"], d["event_type"], d["confidence"], d["bbox"]  # bbox = 원본 프레임 [x1, y1, x2, y2]
"""
import os
import re

import cv2
import numpy as np

PAD_VALUE = 114  # ultralytics LetterBox padding_value
MAX_WH = 7680  # ultralytics nms: 클래스별 NMS 를 위한 좌표 오프셋
MAX_NMS = 30000  # ultralytics nms: NMS 에 넣는 상자 상한


def read_metadata(model_dir):
    """ultralytics 가 내보낸 metadata.yaml 에서 names 와 imgsz 만 읽는다(PyYAML 없이)."""
    names, imgsz, block = {}, [], None
    with open(os.path.join(model_dir, "metadata.yaml"), encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith((" ", "-")):
                block = line.split(":", 1)[0].strip()
                continue
            if block == "names":
                m = re.match(r"^\s+(\d+):\s*(.+?)\s*$", line)
                if m:
                    names[int(m.group(1))] = m.group(2).strip("'\"")
            elif block == "imgsz":
                m = re.match(r"^-\s*(\d+)\s*$", line)
                if m:
                    imgsz.append(int(m.group(1)))
    return names, imgsz


def letterbox(img, new_shape):
    """ultralytics LetterBox(auto=False, center=True) 와 같은 결과. new_shape = (h, w). 파이썬 round 를 그대로 쓴다."""
    h, w = img.shape[:2]
    nh, nw = new_shape
    r = min(nh / h, nw / w)
    unpad_w, unpad_h = max(round(w * r), 1), max(round(h * r), 1)
    dw, dh = (nw - unpad_w) / 2, (nh - unpad_h) / 2
    if (w, h) != (unpad_w, unpad_h):
        img = cv2.resize(img, (unpad_w, unpad_h), interpolation=cv2.INTER_LINEAR)
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    return cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(PAD_VALUE,) * 3)


def as_bgr_uint8(frame):
    """회색(H, W)·(H, W, 1)·BGRA 프레임을 BGR 로 맞춘다. uint8 이 아니면 거부한다(0~255 가정이 깨지므로)."""
    if frame.dtype != np.uint8:
        raise ValueError(f"uint8 프레임만 받습니다: {frame.dtype}")
    if frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1):
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim == 3 and frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"프레임 모양을 알 수 없습니다: {frame.shape}")
    return frame


def to_blob(img_lb):
    """레터박스된 BGR uint8 (H, W, 3) -> RGB NCHW float32 0~1."""
    return np.ascontiguousarray(img_lb[..., ::-1].transpose(2, 0, 1))[None].astype(np.float32) / 255.0


def nms(boxes, scores, iou_thres, max_keep=None):
    """탐욕 NMS. 점수 내림차순으로 고르고 IoU 가 iou_thres 보다 큰 상자를 지운다(torchvision.ops.nms 와 같은 규칙).

    max_keep 개를 고르면 멈춘다. 고른 순서가 점수 내림차순이라 결과는 [:max_keep] 과 같고, 이상한 프레임에서 시간이 폭주하지 않는다.
    """
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = np.argsort(-scores, kind="stable")
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if max_keep is not None and len(keep) >= max_keep:
            break
        rest = order[1:]
        w = np.maximum(0.0, np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]))
        h = np.maximum(0.0, np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]))
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter)
        order = rest[~(iou > iou_thres)]
    return np.asarray(keep, dtype=np.int64)


def postprocess(pred, conf, iou, max_det, lb_shape, orig_shape):
    """모델 출력 (1, 4+nc, A) -> (N, 6) [x1, y1, x2, y2, score, class] 원본 프레임 좌표."""
    p = pred[0]
    cls_scores = p[4:]
    best = cls_scores.max(0)
    cand = best > conf
    if not cand.any():
        return np.zeros((0, 6), np.float32)
    score = best[cand]
    cls = cls_scores[:, cand].argmax(0).astype(np.float32)
    cx, cy, bw, bh = p[0, cand], p[1, cand], p[2, cand], p[3, cand]
    boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1)
    if score.size > MAX_NMS:
        top = np.argsort(-score, kind="stable")[:MAX_NMS]
        boxes, score, cls = boxes[top], score[top], cls[top]
    keep = nms(boxes + cls[:, None] * MAX_WH, score, iou, max_keep=max_det)
    boxes, score, cls = boxes[keep], score[keep], cls[keep]
    # ultralytics ops.scale_boxes: 레터박스 크기를 변마다 반올림하므로 x, y 배율을 따로 구한다.
    h0, w0 = orig_shape[:2]
    gain = min(lb_shape[0] / h0, lb_shape[1] / w0)
    new_h, new_w = max(round(h0 * gain), 1), max(round(w0 * gain), 1)
    pad_x, pad_y = round((lb_shape[1] - new_w) / 2 - 0.1), round((lb_shape[0] - new_h) / 2 - 0.1)
    boxes[:, [0, 2]] = ((boxes[:, [0, 2]] - pad_x) / (new_w / w0)).clip(0, w0)
    boxes[:, [1, 3]] = ((boxes[:, [1, 3]] - pad_y) / (new_h / h0)).clip(0, h0)
    return np.concatenate([boxes, score[:, None], cls[:, None]], 1)


class OVYoloDetector:
    """evt960 OpenVINO 모델(정적 960x960, NMS 없음)을 CPU 에서 돌린다. 입력 크기는 설정이 아니라 모델에서 읽는다."""

    def __init__(self, model_path, device="CPU", threads=None):
        import openvino as ov

        xml = model_path if model_path.endswith(".xml") else os.path.join(model_path, "best.xml")
        if not os.path.isfile(xml):
            raise FileNotFoundError(f"OpenVINO 모델이 없습니다: {xml}")
        self.names, meta_imgsz = read_metadata(os.path.dirname(xml))
        if not self.names:
            raise ValueError(f"metadata.yaml 에서 클래스 이름을 읽지 못했습니다: {os.path.dirname(xml)}")
        # threads: CPU 추론 스레드 수 상한(None 이면 OpenVINO 기본 = 물리 코어 전부). 중계 다른 서비스와 CPU 를 나눠 쓰려면 2.
        config = {"INFERENCE_NUM_THREADS": int(threads)} if threads else {}
        self.compiled = ov.Core().compile_model(xml, device, config)
        shape = self.compiled.input(0).get_partial_shape()
        if shape.is_dynamic:
            raise ValueError(f"정적 입력 모델만 지원합니다: {shape}")
        n, c, h, w = (int(d.get_length()) for d in shape)
        if (n, c) != (1, 3):
            raise ValueError(f"입력은 [1, 3, H, W] 여야 합니다: {shape}")
        self.imgsz = (h, w)
        if meta_imgsz and tuple(meta_imgsz) != self.imgsz:
            raise ValueError(f"metadata imgsz {meta_imgsz} 와 모델 입력 {self.imgsz} 가 다릅니다")
        out = self.compiled.output(0).get_partial_shape()
        if out.is_dynamic or int(out[1].get_length()) != 4 + len(self.names):
            raise ValueError(f"출력 {out} 이 4+{len(self.names)} 클래스와 맞지 않습니다")
        self.output = self.compiled.output(0)

    def raw(self, frame_bgr):
        """전처리와 순전파만. (모델 출력, 레터박스 크기)를 돌려준다."""
        lb = letterbox(frame_bgr, self.imgsz)
        return self.compiled(to_blob(lb))[self.output], lb.shape[:2]

    def detect(self, frame_bgr, conf=0.25, iou=0.7, max_det=300):
        """프레임 하나(BGR uint8, OpenCV 가 읽은 그대로) -> 검출 목록. bbox 는 원본 프레임 [x1, y1, x2, y2] 픽셀."""
        frame_bgr = as_bgr_uint8(frame_bgr)
        pred, lb_shape = self.raw(frame_bgr)
        out = postprocess(pred, conf, iou, max_det, lb_shape, frame_bgr.shape)
        return [
            {"class_id": int(r[5]), "event_type": self.names[int(r[5])], "confidence": float(r[4]),
             "bbox": [float(r[0]), float(r[1]), float(r[2]), float(r[3])]}
            for r in out
        ]
