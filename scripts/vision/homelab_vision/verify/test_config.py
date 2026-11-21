#!/usr/bin/env python3
"""config.py 시험. 모델·네트워크 없이 돈다(이미지 안이든 밖이든).

  python -B verify/test_config.py --app-dir app

보는 것:
  1. INFER_IMGSZ 가 없으면 960(기존 동작 그대로)
  2. 근접 카메라용 값(예 416, 480, 576)을 받는다
  3. 32의 배수가 아니거나 160..1280 밖이거나 숫자가 아니면 시작하지 않는다
  4. 브로커 기본값은 중계 유선 주소 192.168.0.8 (192.168.0.3 은 11-14 부터 노트3 주소)
  5. 시작 로그(public)에 실제 imgsz 가 찍힌다
끝날 때 실패 수를 종료 코드로 낸다(0 이면 통과).
"""
import argparse
import importlib
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--app-dir", default="/app")
args = ap.parse_args()
sys.path.insert(0, args.app_dir)

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def load(env):
    for k in ("INFER_IMGSZ", "MQTT_BROKER", "FRAME_SIZE", "DETECT_ONLY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import config
    return importlib.reload(config)


c = load({})
check("default imgsz 960", c.IMGSZ == 960)
check("default broker 192.168.0.8", c.Config(env={}).mqtt_broker == "192.168.0.8")
check("public shows imgsz", c.Config(env={}).public()["imgsz"] == 960)

for v in ("416", "480", "576", "160", "1280", " 448 "):
    try:
        c = load({"INFER_IMGSZ": v})
        check(f"accepts INFER_IMGSZ={v.strip()}", c.IMGSZ == int(v) and c.Config(env={}).public()["imgsz"] == int(v))
    except ValueError as e:
        check(f"accepts INFER_IMGSZ={v.strip()} ({e})", False)

for v in ("400", "100", "2000", "abc", "960.0", "-32", "+416", "1312", "128", "\u0664\u0661\u0666", "\uff14\uff11\uff16", "4_16"):
    try:
        load({"INFER_IMGSZ": v})
        check(f"refuses INFER_IMGSZ={v!a}", False)
    except ValueError:
        check(f"refuses INFER_IMGSZ={v!a}", True)

c = load({"INFER_IMGSZ": ""})
check("empty INFER_IMGSZ = default 960", c.IMGSZ == 960)
c = load({"INFER_IMGSZ": "   "})
check("whitespace INFER_IMGSZ = default 960", c.IMGSZ == 960)
c = load({"INFER_IMGSZ": "0416"})
check("0416 reads as 416", c.IMGSZ == 416)

load({})
import main as main_mod  # noqa: E402
dets = [{"cls": 0, "name": "pinky_loaded", "confidence": 0.95, "bbox": [100.0, 100.0, 200.0, 200.0]}]
out_in, _ = main_mod.dets_payload(dets, zone_of=lambda _: ["ZB"], tray_centers={30: [150.0, 150.0], 31: [300.0, 300.0]})
check("tray marker inside pinky bbox sets seen=True", out_in[0]["tray_markers"] == [30] and out_in[0]["tray_marker_seen"] is True)
out_out, _ = main_mod.dets_payload(dets, zone_of=lambda _: ["ZB"], tray_centers={30: [350.0, 350.0]})
check("stray tray marker outside pinky bbox sets seen=False", out_out[0]["tray_markers"] == [] and out_out[0]["tray_marker_seen"] is False)

print(f"{len(FAILS)} failed")
sys.exit(len(FAILS))
