#!/usr/bin/env python3
"""model_slots.py 시험. 모델·네트워크 없이 돈다(이미지 안이든 밖이든).

  python -B verify/test_model_slots.py --app-dir app

보는 것:
  1. 팔 가중치 파일이 없으면 자리는 핑키·상자 두 개뿐이다(기존 동작 그대로)
  2. 팔 가중치 파일이 있으면 셋째 자리가 생긴다
  3. 필수 가중치(핑키·상자)가 없으면 시작하지 않는다
  4. 자리마다 클래스 이름표가 정해져 있고, 다른 이름표의 모델은 거부한다
     (팔 모델이 핑키 자리에 들어가면 모든 검출이 "적재"로 읽히는 사고를 막는다)
  5. 팔 메시지는 관찰용 표시와 모델 해시를 싣고, 문턱 아래 검출은 뺀다
  6. 팔 메시지 주제는 기존 주제와 다르다(기존 수신 쪽 계약을 건드리지 않는다)
끝날 때 실패 수를 종료 코드로 낸다(0 이면 통과).
"""
import argparse
import json
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--app-dir", default="/app")
args = ap.parse_args()
sys.path.insert(0, args.app_dir)

import config  # noqa: E402
import model_slots as ms  # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


PINKY, BOXES, ARM = config.WEIGHTS["pinky"], config.WEIGHTS["boxes"], config.ARM_WEIGHT

# 1~3. 자리 계획
check("no arm file -> two slots, same order as before", list(ms.plan_slots(lambda p: p in (PINKY, BOXES))) == ["pinky", "boxes"])
plan3 = ms.plan_slots(lambda p: p in (PINKY, BOXES, ARM))
check("arm file -> third slot", list(plan3) == ["pinky", "boxes", "arm"] and plan3["arm"] == ARM)
check("two-slot plan keeps the two fixed paths", ms.plan_slots(lambda p: p in (PINKY, BOXES)) == {"pinky": PINKY, "boxes": BOXES})
check("missing pinky weight -> refuse", raises(lambda: ms.plan_slots(lambda p: p in (BOXES, ARM))))
check("missing boxes weight -> refuse", raises(lambda: ms.plan_slots(lambda p: p in (PINKY,))))
check("arm weight path is not one of the two fixed paths", ARM not in (PINKY, BOXES) and ARM.startswith("/app/weights/"))

# 4. 이름표 검사
ARM_NAMES = {0: "arm_over_pinky"}
PINKY_NAMES = {0: "pinky_loaded", 1: "pinky_empty"}
BOX_NAMES = {0: "box_on_floor", 1: "box_perched_on_rim", 2: "box_run_over", 3: "lid_detached", 4: "box_on_tray", 5: "box_stock"}
check("pinky names accepted in pinky slot", ms.names_problem("pinky", PINKY_NAMES) is None)
check("boxes names accepted in boxes slot", ms.names_problem("boxes", BOX_NAMES) is None)
check("arm names accepted in arm slot", ms.names_problem("arm", ARM_NAMES) is None)
check("string keys from model metadata are accepted", ms.names_problem("arm", {"0": "arm_over_pinky"}) is None)
check("arm model in pinky slot -> refused", ms.names_problem("pinky", ARM_NAMES) is not None)
check("arm model in boxes slot -> refused", ms.names_problem("boxes", ARM_NAMES) is not None)
check("pinky model in arm slot -> refused", ms.names_problem("arm", PINKY_NAMES) is not None)
check("swapped pinky class order -> refused", ms.names_problem("pinky", {0: "pinky_empty", 1: "pinky_loaded"}) is not None)
check("unknown slot -> refused", ms.names_problem("other", ARM_NAMES) is not None)

# 5~6. 팔 메시지
dets = [{"cls": 0, "name": "arm_over_pinky", "confidence": 0.81234, "bbox": [800.04, 500.06, 880.0, 590.0]},
        {"cls": 0, "name": "arm_over_pinky", "confidence": 0.30, "bbox": [10.0, 10.0, 50.0, 50.0]}]
msg = ms.arm_message(dets, zone_of=lambda b: ["ZB"], stream_id="ceiling", stream_epoch="e1", frame_seq=7, capture_time=100.5,
                     clock_error_sec=0.05, calibration_id="ceil-20261108", marker_state="OK", device="cpu",
                     frame_size=[1080, 1440], weights_sha256="ab" * 32)
check("arm message keeps only detections at or above evidence conf", len(msg["arm"]) == 1 and msg["arm"][0]["confidence"] == 0.8123)
check("arm detection carries bbox and zones", msg["arm"][0]["bbox"] == [800.0, 500.1, 880.0, 590.0] and msg["arm"][0]["zones"] == ["ZB"])
check("arm message says it is observation only", msg["grade"] == "shadow_synthetic_only" and msg["use_for_judgement"] is False)
check("arm message names the model and its weights", msg["arm_model"] == config.ARM_MODEL and msg["arm_weights_sha256"] == "ab" * 32)
check("arm message carries frame identity", (msg["stream_epoch"], msg["frame_seq"], msg["capture_time"]) == ("e1", 7, 100.5))
check("arm message is json and small", len(json.dumps(msg).encode("utf-8")) < config.MAX_PAYLOAD)
many = [dict(dets[0]) for _ in range(80)]
big = ms.arm_message(many, zone_of=lambda b: [], stream_id="ceiling", stream_epoch="e1", frame_seq=1, capture_time=1.0,
                     clock_error_sec=0.05, calibration_id="c", marker_state="OK", device="cpu", frame_size=[1080, 1440],
                     weights_sha256="ab" * 32)
check("arm message caps the list and counts what it cut", len(big["arm"]) == 50 and big["truncated"] == 30)
check("arm topic is new and under relay/", config.TOPIC_ARM.startswith("relay/")
      and config.TOPIC_ARM not in (config.TOPIC_ZONES, config.TOPIC_BOXES, config.TOPIC_STATUS))

print(f"{len(FAILS)} failed")
sys.exit(len(FAILS))
