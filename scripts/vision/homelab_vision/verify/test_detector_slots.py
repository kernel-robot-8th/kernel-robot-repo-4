#!/usr/bin/env python3
"""detector.py 의 자리 검사 시험. 가짜 ultralytics 로 돈다(가중치·GPU·네트워크 없음, numpy 만 필요).

  python -B verify/test_detector_slots.py --app-dir app

보는 것:
  1. 맞는 이름표의 두 모델은 읽힌다. 세 모델도 읽힌다
  2. 팔 모델(1클래스)이 핑키 자리나 상자 자리에 있으면 Detector 가 시작하지 않는다
  3. 핑키 모델이 팔 자리에 있어도 시작하지 않는다
  4. 팔 모델만 읽기에 실패하면(파일 손상 등) 필수 두 모델로 계속 돌고, 사유가 남는다
  5. 필수 모델 읽기에 실패하면 시작하지 않는다
  6. 대기열이 절반 넘게 차 있으면 팔 메시지를 내지 않는다
끝날 때 실패 수를 종료 코드로 낸다(0 이면 통과).
"""
import argparse
import sys
import types

ap = argparse.ArgumentParser()
ap.add_argument("--app-dir", default="/app")
args = ap.parse_args()
sys.path.insert(0, args.app_dir)

NAMES = {"pinky.pt": {0: "pinky_loaded", 1: "pinky_empty"},
         "boxes.pt": {0: "box_on_floor", 1: "box_perched_on_rim", 2: "box_run_over", 3: "lid_detached", 4: "box_on_tray", 5: "box_stock"},
         "arm.pt": {0: "arm_over_pinky"}}


class _Empty:
    def cpu(self):
        return self

    def numpy(self):
        return []


class FakeYOLO:
    def __init__(self, path, task=None):
        if path == "broken.pt":
            raise RuntimeError("cannot read weights")
        self.names = NAMES[path]

    def predict(self, frame, **kw):
        return [types.SimpleNamespace(boxes=types.SimpleNamespace(xyxy=_Empty(), conf=_Empty(), cls=_Empty()))]


sys.modules["ultralytics"] = types.SimpleNamespace(YOLO=FakeYOLO)   # detector.py 가 import 하기 전에 바꿔 둔다
import model_slots  # noqa: E402
from detector import Detector  # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def refused(weights):
    try:
        Detector("cpu", weights)
    except ValueError:
        return True
    return False


def crashed(weights):
    try:
        Detector("cpu", weights)
    except ValueError:
        return False
    except Exception:  # noqa: BLE001
        return True
    return False


d = Detector("cpu", {"pinky": "pinky.pt", "boxes": "boxes.pt"})
check("two fitting models load, no arm", list(d.models) == ["pinky", "boxes"] and d.has_arm is False and d.infer_arm(None) is None)
d = Detector("cpu", {"pinky": "pinky.pt", "boxes": "boxes.pt", "arm": "arm.pt"})
check("three fitting models load", list(d.models) == ["pinky", "boxes", "arm"] and d.has_arm is True and d.arm_error is None)
check("warm-up ran once per loaded model", d.warmup_dets == {"pinky": 0, "boxes": 0, "arm": 0})
check("arm model in the pinky slot -> Detector refuses", refused({"pinky": "arm.pt", "boxes": "boxes.pt"}))
check("arm model in the boxes slot -> Detector refuses", refused({"pinky": "pinky.pt", "boxes": "arm.pt"}))
check("pinky model in the arm slot -> Detector refuses", refused({"pinky": "pinky.pt", "boxes": "boxes.pt", "arm": "pinky.pt"}))
d = Detector("cpu", {"pinky": "pinky.pt", "boxes": "boxes.pt", "arm": "broken.pt"})
check("unreadable arm weights -> two models keep running, reason kept",
      list(d.models) == ["pinky", "boxes"] and d.has_arm is False and "cannot read weights" in (d.arm_error or ""))
check("unreadable required weights -> start fails", crashed({"pinky": "broken.pt", "boxes": "boxes.pt"}))
check("queue empty -> arm may publish", model_slots.arm_may_publish(0, 20) is True)
check("queue just under half -> arm may publish", model_slots.arm_may_publish(9, 20) is True)
check("queue half full -> arm is skipped", model_slots.arm_may_publish(10, 20) is False)

print(f"{len(FAILS)} failed")
sys.exit(len(FAILS))
