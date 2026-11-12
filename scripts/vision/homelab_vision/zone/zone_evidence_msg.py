#!/usr/bin/env python3
"""Pinky state model detections -> the monitor's zone evidence frame (2026-11-09). Builds dicts only: no MQTT, no ROS, no file.

Contract: cobot_anomaly_monitor/load_evidence.py LoadEvidence.observe() at repo65 sim-verify-load 34623b4 (relay 8485221 + 11-09 fixes).
The monitor takes one frame at a time (MQTT relay/evidence/zones -> ROS /anomaly_monitor/zone_evidence) and keeps the last three unique
LOADED frames of the pickup zone. Any other value for that zone, or marker_state other than "OK", clears its window.

Frame fields: source_kind "model_output", stream_id, stream_epoch (non-empty, new per detector start), frame_seq (int, strictly rising
within an epoch), capture_time (Unix s, strictly rising), clock_error_sec (0..0.25), model_id and calibration_id (must equal the
monitor's load_model / calibration_id), marker_state, zones {zone: "LOADED" | "EMPTY" | "NO_ROBOT" | "MULTI"} (flat strings).
Time rule after the 11-09 fix: the monitor drops a frame when capture_time - clock_error_sec > now (future) or now - capture_time +
clock_error_sec > 3 (old). emit() refuses the same cases here, so nothing that the monitor would drop is sent.

Per zone and frame (single-robot rule): one Pinky box centre in the zone -> its class (LOADED / EMPTY); none -> NO_ROBOT; two or more ->
MULTI. Mode "2of3" (optional): LOADED when at least 2 of the last 3 raw readings are LOADED and none of them is EMPTY or MULTI, so a
single missed frame does not reset the monitor's 3-frame window; EMPTY and MULTI are never smoothed into LOADED.
"""
from collections import deque

LOADED_CLS, EMPTY_CLS = 0, 1
STATES = ("LOADED", "EMPTY", "NO_ROBOT", "MULTI")


def frame_states(dets, zone_of, zones=("ZA", "ZB", "ZC"), conf=0.5):
    """dets: [cls, confidence, x0, y0, x1, y1] lists or dicts with cls/confidence/bbox. zone_of(bbox) -> zone names."""
    found = {z: [] for z in zones}
    for d in dets:
        if isinstance(d, dict):
            cls, c, box = d.get("cls"), d.get("confidence"), d.get("bbox")
        else:
            cls, c, box = d[0], d[1], list(d[2:6])
        if cls not in (LOADED_CLS, EMPTY_CLS) or not isinstance(c, (int, float)) or c < conf:
            continue
        for z in zone_of(box) or []:
            if z in found:
                found[z].append(cls)
    return {z: "NO_ROBOT" if not c else "MULTI" if len(c) > 1 else ("LOADED" if c[0] == LOADED_CLS else "EMPTY")
            for z, c in found.items()}


class ZoneEvidenceEmitter:
    def __init__(self, stream_epoch, model_id="pinky-v1", calibration_id="replay-v1", stream_id="ceiling", clock_error_sec=0.05,
                 mode="raw", zones=("ZA", "ZB", "ZC"), conf=0.5, source_kind="model_output"):
        if not isinstance(stream_epoch, str) or not stream_epoch:
            raise ValueError("stream_epoch must be a non-empty string")
        if not isinstance(clock_error_sec, (int, float)) or not 0 <= clock_error_sec <= 0.25:
            raise ValueError("clock_error_sec must be within 0..0.25")
        if mode not in ("raw", "2of3"):
            raise ValueError("mode is raw or 2of3")
        if source_kind not in ("model_output", "sim_fixture"):
            raise ValueError("source_kind")
        self.epoch, self.model_id, self.calibration_id, self.stream_id = stream_epoch, model_id, calibration_id, stream_id
        self.error, self.mode, self.zones, self.conf, self.source_kind = float(clock_error_sec), mode, tuple(zones), conf, source_kind
        self.seq, self.last_ts = -1, None
        self.hist = {z: deque(maxlen=3) for z in self.zones}

    def emit(self, dets, zone_of, capture_time, marker_state, now):
        """-> (frame dict or None, reason). zone_of None or marker_state != "OK" sends marker_state as is and clears smoothing."""
        if not isinstance(capture_time, (int, float)):
            return None, "capture_time missing"
        if self.last_ts is not None and capture_time <= self.last_ts:
            return None, "capture_time not rising"
        if capture_time - self.error > now:
            return None, "capture_time in the future"
        if now - capture_time + self.error > 3:
            return None, "frame older than 3 s"
        usable = marker_state == "OK" and zone_of is not None
        if usable:
            raw = frame_states(dets, zone_of, self.zones, self.conf)
            for z in self.zones:
                self.hist[z].append(raw[z])
            out = {z: self._smooth(z) if self.mode == "2of3" else raw[z] for z in self.zones}
        else:
            for h in self.hist.values():
                h.clear()
            raw = out = {z: "NO_ROBOT" for z in self.zones}
        self.seq += 1
        self.last_ts = capture_time
        frame = {"source_kind": self.source_kind, "stream_id": self.stream_id, "stream_epoch": self.epoch, "frame_seq": self.seq,
                 "capture_time": float(capture_time), "clock_error_sec": self.error, "model_id": self.model_id,
                 "calibration_id": self.calibration_id, "marker_state": marker_state if usable else (marker_state if marker_state != "OK" else "LOST"),
                 "zones": out}
        return frame, "ok" if usable else "marker not usable"

    def _smooth(self, z):
        h = list(self.hist[z])
        if h[-1] in ("EMPTY", "MULTI"):
            return h[-1]
        if h.count("LOADED") >= 2 and not any(s in ("EMPTY", "MULTI") for s in h):
            return "LOADED"
        return h[-1]
