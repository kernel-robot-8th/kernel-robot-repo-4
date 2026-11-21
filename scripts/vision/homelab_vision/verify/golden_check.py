#!/usr/bin/env python3
"""컨테이너 안에서 .pt 모델(핑키·상자, 실렸으면 팔까지)을 골든 사진과 대조한다(숫자만 출력, 파일을 쓰지 않는다).

기대값은 OpenVINO 변환본으로 만든 것이라 .pt 결과와 조금 다를 수 있다. 여기서는 차이를 숫자로만 낸다. 아무것도 조정하지 않는다.
    python golden_check.py --pinky-golden /g/golden-pinky-v2-final --boxes-golden /g/golden-kneg-d-final [--device cpu] [--repeat 5]
비교 방식은 패킷의 run_golden.py compare() 와 같다(같은 클래스, IoU 최대 짝, 문턱+0.02 이상만 엄격 판정).

판정(GOLDEN_STRICT)은 세 가지를 모두 만족해야 SAME 이다.
  1) 두 모델의 모든 기준 사진이 엄격 판정 통과  2) 빈 회색 화면 검출 0개  3) 파이썬 수준 네트워크 시도 0번
종료 코드: 0 = SAME, 1 = DIFF, 2 = 실행 오류(골든 폴더·expected.json·가중치 없음, 기준 사진 0개 등).
실행 오류여도 마지막 줄은 항상 "GOLDEN_STRICT DIFF" 다(줄만 보는 쪽이 SAME 으로 오인하지 않게).
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


class SetupError(Exception):
    """판정 전에 멈춰야 하는 입력 문제. 종료 코드 2 로 낸다."""


def load_expected(tag, golden, weights):
    """골든 폴더·expected.json·가중치를 확인한다. 하나라도 없거나 기준 사진이 0개면 SetupError."""
    if not os.path.isdir(golden):
        raise SetupError(f"[{tag}] golden dir not found: {golden}")
    path = os.path.join(golden, "expected.json")
    try:
        with open(path, encoding="utf-8") as f:
            exp = json.load(f)
    except (OSError, ValueError) as e:
        raise SetupError(f"[{tag}] cannot read {path}: {e}") from e
    if not isinstance(exp, dict) or not isinstance(exp.get("names"), dict) or not isinstance(exp.get("images"), list):
        raise SetupError(f"[{tag}] expected.json has no names/images")
    if not exp["images"]:
        raise SetupError(f"[{tag}] expected.json has 0 images")
    if not os.path.isfile(weights):
        raise SetupError(f"[{tag}] weights not found: {weights}")
    return exp


def arm_plan(arm_weights_exist, arm_golden):
    """팔 모델을 대조할지 정한다. 가중치와 골든은 둘 다 있거나 둘 다 없어야 한다.

    가중치만 있으면 골든 없이 팔 모델이 나가는 것이고, 골든만 있으면 대조했다고 착각하게 되므로 둘 다 실행 오류다.
    """
    if arm_weights_exist and not arm_golden:
        raise SetupError("[arm_v1] arm weights are in the image but --arm-golden was not given")
    if arm_golden and not arm_weights_exist:
        raise SetupError("[arm_v1] --arm-golden was given but the image has no arm weights")
    return bool(arm_weights_exist and arm_golden)


def time_summary(times):
    """추론 시간 요약. 한 장도 돌지 않았으면(모두 해시 불일치 등) 중앙값 대신 그 사실을 적는다."""
    if not times:
        return "no predictions (n 0)"
    return f"median {statistics.median(times):.1f} ms, min {min(times):.1f}, max {max(times):.1f}, n {len(times)}"


SLOT_OF = {"pinky_v2_final": "pinky", "kneg_d_final": "boxes", "arm_v1": "arm"}


def slot_names_problem(tag, names, app_dir="/app"):
    """앱의 자리 이름표(app/model_slots.py)와 가중치의 이름표를 대조한다. 앱은 이름표가 다르면 시작하지 않으므로,
    컨테이너를 바꾸기 전에 여기서 먼저 걸러낸다. 앱 모듈을 읽지 못하면 그것도 문제로 돌려준다."""
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        import model_slots
    except Exception as e:  # noqa: BLE001
        return f"cannot import model_slots from {app_dir}: {type(e).__name__}: {e}"
    return model_slots.names_problem(SLOT_OF[tag], names)


def run(tag, weights, golden, device, repeat, app_dir="/app"):
    exp = load_expected(tag, golden, weights)
    model = YOLO(weights, task="detect")
    names_ok = {int(k): v for k, v in model.names.items()} == {int(k): v for k, v in exp["names"].items()}
    print(f"[{tag}] names match expected: {names_ok} {dict(model.names)}")
    slot_problem = slot_names_problem(tag, model.names, app_dir)
    print(f"[{tag}] names fit the app slot '{SLOT_OF[tag]}': {slot_problem is None}" + (f" ({slot_problem})" if slot_problem else ""))
    names_ok = names_ok and slot_problem is None
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
    # 빈 화면 오검출도 판정에 넣는다. 전에는 TOTAL 줄에만 반영되고 반환값(GOLDEN_STRICT)에서는 빠져 있었다.
    # 한 장도 대조하지 못했으면(times 비어 있음) SAME 이 될 수 없다.
    total = bool(all_strict and len(blank.boxes) == 0 and times)
    print(f"[{tag}] TOTAL strict(run_golden rule: IoU>=0.98, dconf<=0.02, dpx<=2) = {total}; boxes expected {n_exp} ours {n_ours} "
          f"misses {n_miss}; worst iou_min {worst_all['iou_min']:.4f} dconf_max {worst_all['dconf_max']:.4f} dpx_max {worst_all['dpx_max']:.2f}")
    print(f"[{tag}] predict time per image on {device}: {time_summary(times)}")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinky-golden", required=True)
    ap.add_argument("--boxes-golden", required=True)
    ap.add_argument("--pinky-weights", default="/app/weights/pinky_v2_final.pt")
    ap.add_argument("--boxes-weights", default="/app/weights/kneg_d_final.pt")
    ap.add_argument("--arm-golden", default=None, help="팔 모델 골든 폴더. 이미지에 팔 가중치가 있으면 반드시 준다")
    ap.add_argument("--arm-weights", default="/app/weights/arm_v1.pt")
    ap.add_argument("--app-dir", default="/app", help="app/ 폴더(model_slots.py 가 있는 곳)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    print(f"torch {torch.__version__} threads {torch.get_num_threads()} cuda_available {torch.cuda.is_available()} cv2 {cv2.__version__}")
    try:
        results = judge_models(a)
    except Exception as e:  # noqa: BLE001 - 어떤 예외든 DIFF(1)와 구분되는 실행 오류(2)로 낸다
        print(f"GOLDEN_ERROR {type(e).__name__}: {e}")
        print("GOLDEN_STRICT DIFF")
        sys.exit(2)
    # 이미지는 YOLO_OFFLINE 등으로 네트워크를 쓰지 않게 만들었다. 시도가 한 번이라도 있으면 그 전제가 깨진 것이라
    # (--network none 이라 실패했을 뿐 현장에서는 나갈 수 있다) 출력만 하지 않고 DIFF 로 친다.
    print(f"python-level network attempts during load+predict: {len(CONNECTS)} {CONNECTS[:5]}")
    is_same = verdict(results, len(CONNECTS))
    print("GOLDEN_STRICT", "SAME" if is_same else "DIFF")
    sys.exit(0 if is_same else 1)


def judge_models(a, run_fn=None, load_fn=None, exists=os.path.isfile):
    """-> {모델 이름: 통과 여부}. 핑키·상자는 항상, 팔은 가중치가 이미지에 있을 때 돌린다. 돌리지 않은 모델은 표에 넣지 않는다."""
    run_fn, load_fn = run_fn or run, load_fn or load_expected
    # 모든 모델의 입력을 먼저 확인한다(첫 모델을 다 돌린 뒤에야 다음 입력이 없다는 걸 알지 않게).
    load_fn("pinky_v2_final", a.pinky_golden, a.pinky_weights)
    load_fn("kneg_d_final", a.boxes_golden, a.boxes_weights)
    with_arm = arm_plan(exists(a.arm_weights), a.arm_golden)
    if with_arm:
        load_fn("arm_v1", a.arm_golden, a.arm_weights)
    results = {"pinky_v2_final": run_fn("pinky_v2_final", a.pinky_weights, a.pinky_golden, a.device, a.repeat, a.app_dir),
               "kneg_d_final": run_fn("kneg_d_final", a.boxes_weights, a.boxes_golden, a.device, a.repeat, a.app_dir)}
    if with_arm:
        results["arm_v1"] = run_fn("arm_v1", a.arm_weights, a.arm_golden, a.device, a.repeat, a.app_dir)
    print("[arm_v1] " + (f"checked, strict = {results['arm_v1']}" if with_arm
                         else "not shipped in this image (no arm weights, no arm golden)"))
    return results


def verdict(results, n_connects):
    """돌린 모델이 모두 통과하고(핑키·상자는 반드시 들어 있어야 한다) 네트워크 시도가 0번일 때만 SAME."""
    required = ("pinky_v2_final", "kneg_d_final")
    return bool(all(k in results for k in required) and all(v is True for v in results.values()) and n_connects == 0)


if __name__ == "__main__":
    main()
