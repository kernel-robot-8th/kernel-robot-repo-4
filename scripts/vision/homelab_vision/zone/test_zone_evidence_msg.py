#!/usr/bin/env python3
"""zone_evidence_msg.py tests. No frame, no device, no file.

    python test_zone_evidence_msg.py     # last line [zmsg_test] N/N PASS, exit 0
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zone_evidence_msg as zm  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))


def zone_of(b):
    cx = (b[0] + b[2]) / 2
    return ["ZA"] if cx < 100 else ["ZB"] if cx < 200 else ["ZC"] if cx < 300 else []


def d(cls, x, conf=0.9):
    return [cls, conf, x - 10, 0, x + 10, 20]


s = zm.frame_states([d(0, 50), d(1, 150), d(0, 240), d(1, 260), d(0, 400)], zone_of)
check("single loaded -> LOADED, single empty -> EMPTY, two -> MULTI", s == {"ZA": "LOADED", "ZB": "EMPTY", "ZC": "MULTI"}, s)
check("low confidence ignored", zm.frame_states([d(0, 50, .3)], zone_of)["ZA"] == "NO_ROBOT")
check("dict detections accepted", zm.frame_states([{"cls": 0, "confidence": .9, "bbox": [40, 0, 60, 20]}], zone_of)["ZA"] == "LOADED")

e = zm.ZoneEvidenceEmitter("epoch-1", clock_error_sec=0.05)
f, why = e.emit([d(0, 50)], zone_of, 100.0, "OK", now=100.2)
keys = {"source_kind", "stream_id", "stream_epoch", "frame_seq", "capture_time", "clock_error_sec", "model_id", "calibration_id", "marker_state", "zones"}
check("frame has exactly the monitor's keys", f is not None and set(f) == keys, f)
check("zones are flat strings", all(isinstance(v, str) for v in f["zones"].values()))
check("first seq 0, source model_output", f["frame_seq"] == 0 and f["source_kind"] == "model_output")
f2, _ = e.emit([d(0, 50)], zone_of, 100.5, "OK", now=100.6)
check("seq rises", f2["frame_seq"] == 1)
f3, why = e.emit([d(0, 50)], zone_of, 100.5, "OK", now=100.7)
check("same capture_time refused", f3 is None and "rising" in why)
f4, why = e.emit([d(0, 50)], zone_of, 101.13, "OK", now=101.1)
check("frame ahead of now by less than the clock error is sent (11-09 rule ts - error > now)", f4 is not None, why)
f5, why = e.emit([d(0, 50)], zone_of, 102.0, "OK", now=101.9)
check("frame ahead of now by more than the clock error is refused", f5 is None and "future" in why)
f6, why = e.emit([d(0, 50)], zone_of, 103.0, "OK", now=106.0)
check("frame older than 3 s (with error) refused", f6 is None and "older" in why)
f7, why = e.emit([d(0, 50)], zone_of, 104.0, "LOST", now=104.1)
check("marker lost -> marker_state LOST and no LOADED", f7["marker_state"] == "LOST" and "LOADED" not in f7["zones"].values())
f8, why = e.emit([d(0, 50)], None, 104.5, "OK", now=104.6)
check("geometry missing -> not OK", f8["marker_state"] != "OK")
for bad in (dict(stream_epoch=""), dict(stream_epoch="x", clock_error_sec=0.3), dict(stream_epoch="x", mode="vote")):
    try:
        zm.ZoneEvidenceEmitter(**bad)
        check(f"bad config refused {bad}", False)
    except ValueError:
        check(f"bad config refused {bad}", True)

# 2of3 smoothing
s2 = zm.ZoneEvidenceEmitter("e2", mode="2of3")
seqz = []
for t, dets in enumerate([[d(0, 50)], [d(0, 50)], [], [d(0, 50)]]):
    f, _ = s2.emit(dets, zone_of, 200.0 + t * 0.5, "OK", now=200.1 + t * 0.5)
    seqz.append(f["zones"]["ZA"])
check("2of3: one missed frame stays LOADED", seqz == ["LOADED", "LOADED", "LOADED", "LOADED"], seqz)
s3 = zm.ZoneEvidenceEmitter("e3", mode="2of3")
out = [s3.emit(x, zone_of, 300.0 + t * 0.5, "OK", now=300.1 + t * 0.5)[0]["zones"]["ZA"] for t, x in enumerate([[d(0, 50)], [d(0, 50)], [d(1, 50)]])]
check("2of3: an EMPTY frame is never smoothed into LOADED", out[-1] == "EMPTY", out)
s4 = zm.ZoneEvidenceEmitter("e4", mode="2of3")
out = [s4.emit(x, zone_of, 400.0 + t * 0.5, "OK", now=400.1 + t * 0.5)[0]["zones"]["ZA"] for t, x in enumerate([[d(0, 50)], [], []])]
check("2of3: one LOADED among misses is not LOADED", out[-1] == "NO_ROBOT", out)
s5 = zm.ZoneEvidenceEmitter("e5", mode="2of3")
out = [s5.emit(x, zone_of, 500.0 + t * 0.5, "OK", now=500.1 + t * 0.5)[0]["zones"]["ZA"] for t, x in enumerate([[d(0, 50)], [d(0, 50), d(0, 60)], [d(0, 50)]])]
check("2of3: a MULTI frame in the window blocks LOADED", out[-1] == "LOADED" and out[1] == "MULTI" and out == ["LOADED", "MULTI", "LOADED"], out)
s6 = zm.ZoneEvidenceEmitter("e6", mode="2of3")
s6.emit([d(0, 50)], zone_of, 600.0, "OK", now=600.1)
s6.emit([d(0, 50)], zone_of, 600.5, "OK", now=600.6)
s6.emit([d(0, 50)], zone_of, 601.0, "LOST", now=601.1)
f, _ = s6.emit([], zone_of, 601.5, "OK", now=601.6)
check("2of3: marker loss clears the smoothing history", f["zones"]["ZA"] == "NO_ROBOT")
print(f"[zmsg_test] {sum(results)}/{len(results)} {'PASS' if all(results) else 'FAIL'}")
sys.exit(0 if all(results) else 1)
