#!/usr/bin/env python3
"""pinky_evidence.py tests with fake zones. No frame, no device, no file.

    python test_pinky_evidence.py     # last line [pinky_test] N/N PASS, exit 0
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pinky_evidence as pe  # noqa: E402
import vision_answer as va  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))


def zone_of(b):
    """ZA = x < 100, ZB = 100..200, ZC = 200..300 by box centre; elsewhere no zone."""
    cx = (b[0] + b[2]) / 2
    return ["ZA"] if cx < 100 else ["ZB"] if cx < 200 else ["ZC"] if cx < 300 else []


def det(cls, x, conf=0.9):
    return {"cls": cls, "confidence": conf, "bbox": [x - 10, 0, x + 10, 20]}


def run(frames, ev=None, **kw):
    ev = ev or pe.PinkyEvidence(window=5, need=4, **kw)
    r = None
    for t, dets in enumerate(frames):
        r = ev.update(dets, zone_of, now=float(t), frame_time=float(t))
    return r, ev


r, _ = run([[det(0, 50)]] * 5)
check("loaded robot steady -> BOX", r["zones"]["ZA"]["state"] == "BOX")
check("other zones without robot -> NO_ROBOT", r["zones"]["ZB"]["state"] == "NO_ROBOT" and r["zones"]["ZC"]["state"] == "NO_ROBOT")
r, _ = run([[det(1, 250)]] * 5)
check("empty robot steady -> EMPTY", r["zones"]["ZC"]["state"] == "EMPTY")
r, _ = run([[det(0, 50)]] * 4)
check("short history -> FILLING", r["zones"]["ZA"]["state"] == "FILLING")
r, _ = run([[det(0, 50)]] * 4 + [[det(1, 50)]])
check("one empty frame among loaded -> not BOX", r["zones"]["ZA"]["state"] == "MIXED", r["zones"]["ZA"])
r, _ = run([[det(1, 50)]] * 4 + [[det(0, 50)]])
check("one loaded frame among empty -> not EMPTY", r["zones"]["ZA"]["state"] == "MIXED")
r, _ = run([[det(0, 40), det(1, 60)]] * 5)
check("two robots in one zone -> MULTI, never BOX", r["zones"]["ZA"]["state"] == "MULTI")
r, _ = run([[det(0, 50, conf=0.3)]] * 5)
check("low confidence ignored -> NO_ROBOT", r["zones"]["ZA"]["state"] == "NO_ROBOT")
r, _ = run([[det(0, 350)]] * 5)
check("robot outside every zone counts nowhere", all(v["state"] == "NO_ROBOT" for v in r["zones"].values()))
r, _ = run([[det(0, 50), {"cls": 5, "confidence": 0.9, "bbox": [0, 0, 1, 1]}, {"cls": 0, "bbox": [0, 0, 1]}]] * 5)
check("bad detections skipped, counted", r["zones"]["ZA"]["state"] == "BOX" and r["skipped_detections"] == 2)
ev = pe.PinkyEvidence(window=5, need=4)
for t in range(5):
    ev.update([det(0, 50)], zone_of, now=float(t), frame_time=float(t))
r = ev.update([det(0, 50)], zone_of, now=10.0, frame_time=5.0)
check("stale frame -> UNKNOWN and history cleared", r["zones"]["ZA"]["state"] == "UNKNOWN" and r["zones"]["ZA"]["frames"] == 0)
r = ev.update([det(0, 50)], None, now=11.0, frame_time=11.0)
check("geometry lost -> UNKNOWN", r["zones"]["ZA"]["state"] == "UNKNOWN" and r["geometry"] is False)
r = ev.update([det(0, 50)], lambda b: None, now=12.0, frame_time=12.0)
check("zone_of returns None -> UNKNOWN", r["zones"]["ZA"]["state"] == "UNKNOWN")
try:
    pe.PinkyEvidence(window=3, need=4)
    check("need > window refused", False)
except ValueError:
    check("need > window refused", True)

# with vision_answer.py: NO_ROBOT / MULTI must never become an answer
req = {"action": "verify_load", "stage": "VERIFY_LOAD", "target": "vision", "request_id": "r1", "order_id": "o1", "robot_id": "pinky1",
       "route": {"pickup": "ZA", "dropoff": "ZC"}, "issued_at": 0.0, "ttl_sec": 5.0, "timeout_sec": 60.0}
for st in ("NO_ROBOT", "MULTI", "MIXED"):
    rep = {"at": 1.0, "stale": False, "zones": {"ZA": {"state": st}}}
    res, why = va.build_answer(req, rep, True, now=1.0, negative="report")
    check(f"vision_answer gives no answer for {st}", res is None, why)
r, _ = run([[det(0, 50)]] * 5)
r["at"] = 1.0
res, why = va.build_answer(req, r, True, now=1.0)
check("BOX from the Pinky model answers VERIFY_LOAD load_present True", res is not None and res["data"]["load_present"] is True, why)
# 11-09: window times and request start
r, _ = run([[det(0, 50)]] * 5)
check("window first/last frame time reported", r["zones"]["ZA"]["first_frame_time"] == 0.0 and r["zones"]["ZA"]["last_frame_time"] == 4.0)
late = dict(req, issued_at=2.0, ttl_sec=5.0)
r["at"] = 4.0
res, why = va.build_answer(late, r, True, now=4.0)
check("evidence that began before the request gets no answer", res is None and why == "evidence predates request", why)
ev = pe.PinkyEvidence(window=5, need=4)
for t in range(5):
    r = ev.update([det(0, 50)], zone_of, now=float(t), frame_time=float(t), marker_state="LOST")
check("marker not OK -> UNKNOWN", r["zones"]["ZA"]["state"] == "UNKNOWN" and r["marker_state"] == "LOST")
print(f"[pinky_test] {sum(results)}/{len(results)} {'PASS' if all(results) else 'FAIL'}")
sys.exit(0 if all(results) else 1)
