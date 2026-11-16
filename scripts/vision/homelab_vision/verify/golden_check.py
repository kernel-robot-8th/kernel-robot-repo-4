#!/usr/bin/env python3
"""컨테이너 안에서 .pt 두 모델을 골든 사진과 대조한다(숫자만 출력, 파일을 쓰지 않는다).

기대값은 OpenVINO 변환본으로 만든 것이라 .pt 결과와 조금 다를 수 있다. 여기서는 차이를 숫자로만 낸다. 아무것도 조정하지 않는다.
    python golden_check.py --pinky-golden /g/golden-pinky-v2-final --boxes-golden /g/golden-kneg-d-final [--device cpu] [--repeat 5]
비교 방식은 패킷의 run_golden.py compare() 와 같다(같은 클래스, IoU 최대 짝, 문턱+0.02 이상만 엄격 판정).
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
import time

CONNECTS = []
sys.addaudithook(lambda e, a: CONNECTS.append((e, str(a[1:]))) if e in ("socket.connect", "socket.getaddrinfo") else None)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from ultralytics import YOLO  # noqa: E402


def iou(a, b):
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def compare(ref, ours, conf, margin=0.02):
    sure = conf + margin
    used, misses, worst = set(), [], {"iou_min": 1.0, "dconf_max": 0.0, "dpx_max": 0.0}
    for r in sorted(ref, key=lambda d: -d["confidence"]):
        cands = [(iou(r["bbox"], o["bbox"]), k) for k, o in enumerate(ours) if k not in used and o["class_id"] == r["class_id"]]
        best = max(cands, default=(0.0, None))
        if best[1] is not None and best[0] >= 0.5:
            o = ours[best[1]]
            used.add(best[1])
            if r["confidence"] >= sure or o["confidence"] >= sure:
                worst["iou_min"] = min(worst["iou_min"], best[0])
                worst["dconf_max"] = max(worst["dconf_max"], abs(r["confidence"] - o["confidence"]))
                worst["dpx_max"] = max(worst["dpx_max"], max(abs(x - y) for x, y in zip(r["bbox"], o["bbox"])))
        elif r["confidence"] >= sure:
            misses.append(("expected_not_found", r["class_id"], round(r["confidence"], 3)))
    for k, o in enumerate(ours):
        if k not in used and o["confidence"] >= sure:
            misses.append(("unexpected", o["class_id"], round(o["confidence"], 3)))
    strict = not misses and worst["iou_min"] >= 0.98 and worst["dconf_max"] <= 0.02 and worst["dpx_max"] <= 2.0
    return strict, misses, worst


def run(tag, weights, golden, device, repeat):
    exp = json.load(open(os.path.join(golden, "expected.json"), encoding="utf-8"))
    model = YOLO(weights, task="detect")
    names_ok = {int(k): v for k, v in model.names.items()} == {int(k): v for k, v in exp["names"].items()}
    print(f"[{tag}] names match expected: {names_ok} {dict(model.names)}")
    kw = dict(imgsz=960, iou=0.7, rect=False, max_det=300, device=device, verbose=False, save=False)
    model.predict(np.full((1440, 1080, 3), 114, np.uint8), conf=0.25, **kw)      # 예열
    all_strict, times, worst_all = names_ok, [], {"iou_min": 1.0, "dconf_max": 0.0, "dpx_max": 0.0}
    n_exp = n_ours = n_miss = 0
    for item in exp["images"]:
        raw = open(os.path.join(golden, item["file"]), "rb").read()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            print(f"[{tag}] FAIL sha256 {item['file']}")
            all_strict = False
            continue
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        for conf, ref in ((float(k), v) for k, v in item["expected"].items()):
            for _ in range(repeat):
                t = time.perf_counter()
                r = model.predict(frame, conf=conf, **kw)[0]
                times.append((time.perf_counter() - t) * 1000.0)
            ours = [{"class_id": int(c), "confidence": float(s), "bbox": [float(v) for v in b]}
                    for b, s, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy())]
            strict, misses, worst = compare(ref, ours, conf)
            all_strict &= strict
            n_exp, n_ours, n_miss = n_exp + len(ref), n_ours + len(ours), n_miss + len(misses)
            worst_all = {"iou_min": min(worst_all["iou_min"], worst["iou_min"]), "dconf_max": max(worst_all["dconf_max"], worst["dconf_max"]),
                         "dpx_max": max(worst_all["dpx_max"], worst["dpx_max"])}
            cls_exp, cls_ours = sorted(d["class_id"] for d in ref), sorted(d["class_id"] for d in ours)
            print(f"[{tag}] {'SAME ' if strict else 'DIFF '}{item['file']} {frame.shape[1]}x{frame.shape[0]} conf>{conf}: expected {len(ref)} ours {len(ours)} "
                  f"classes_equal {cls_exp == cls_ours} iou_min {worst['iou_min']:.4f} dconf_max {worst['dconf_max']:.4f} dpx_max {worst['dpx_max']:.2f}"
                  + (f" misses {misses[:5]}" if misses else ""))
    blank = model.predict(np.full((1440, 1080, 3), 114, np.uint8), conf=0.25, **kw)[0]
    print(f"[{tag}] blank gray frame detections: {len(blank.boxes)} (expected 0)")
    print(f"[{tag}] TOTAL strict(run_golden rule: IoU>=0.98, dconf<=0.02, dpx<=2) = {all_strict and len(blank.boxes) == 0}; boxes expected {n_exp} ours {n_ours} "
          f"misses {n_miss}; worst iou_min {worst_all['iou_min']:.4f} dconf_max {worst_all['dconf_max']:.4f} dpx_max {worst_all['dpx_max']:.2f}")
    print(f"[{tag}] predict time per image on {device}: median {statistics.median(times):.1f} ms, min {min(times):.1f}, max {max(times):.1f}, n {len(times)}")
    return all_strict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinky-golden", required=True)
    ap.add_argument("--boxes-golden", required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    print(f"torch {torch.__version__} threads {torch.get_num_threads()} cuda_available {torch.cuda.is_available()} cv2 {cv2.__version__}")
    ok1 = run("pinky_v2_final", "/app/weights/pinky_v2_final.pt", a.pinky_golden, a.device, a.repeat)
    ok2 = run("kneg_d_final", "/app/weights/kneg_d_final.pt", a.boxes_golden, a.device, a.repeat)
    print(f"python-level network attempts during load+predict: {len(CONNECTS)} {CONNECTS[:5]}")
    print("GOLDEN_STRICT", "SAME" if ok1 and ok2 else "DIFF")


if __name__ == "__main__":
    main()
