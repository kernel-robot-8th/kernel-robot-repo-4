#!/usr/bin/env python3
"""What the Pinky state model sees in each work zone (2026-11-09). It decides nothing and sends nothing: no /fleet/work_result, no MQTT, no ROS.

Model: 0 pinky_loaded (robot with a box on its saucer; a box on the rim counts as loaded, user decision 11-07), 1 pinky_empty.
The box model D keeps watching store, warehouse and aisle; this module only reads ZA, ZB and ZC.

Rule (review 11-08): a zone has a state only from ONE robot. Per frame a zone reads
  L  exactly one robot box in the zone, class loaded        E  exactly one robot box, class empty
  0  no robot box in the zone                              M  two or more robot boxes in the zone
States over the last `window` usable frames:
  UNKNOWN   frame stale or zone geometry unavailable (caller passes zone_of=None). Nothing is claimed.
  FILLING   fewer frames than the window.
  BOX       L in at least `need` frames and no E frame        -> load_present evidence
  EMPTY     E in at least `need` frames and no L frame        -> load_absent evidence: a robot is SEEN without a box
  NO_ROBOT  0 in at least `need` frames. For VERIFY this is unknown, never "absent" (a missed robot reads the same).
  MULTI     M in at least `need` frames.
  MIXED     anything else.
vision_answer.py must treat NO_ROBOT, MULTI and MIXED as undecided, like UNKNOWN and FILLING.
window, need and conf are not measured values: today's recordings never show an empty robot standing in a zone (user labels 11-08),
so EMPTY in a zone is untested on real frames.
Zone membership is the caller's: zone_of(bbox) -> list of zone names, or None when the geometry is lost. A robot box centre sits at tray
height, so the zone outline must include the tray-height shift (roi_tray.json hull on the 11-08 frames).
"""
from collections import Counter, deque

LOADED, EMPTY = 0, 1


class PinkyEvidence:
    def __init__(self, watch=("ZA", "ZB", "ZC"), window=10, need=7, conf=0.5, stale_sec=3.0):
        if not 0 < need <= window:
            raise ValueError("need must be within the window")
        self.watch, self.window, self.need, self.conf, self.stale_sec = tuple(watch), window, need, conf, stale_sec
        self.hist = {z: deque(maxlen=window) for z in watch}
        self.since = {z: None for z in watch}
        self.last = {z: None for z in watch}

    def update(self, dets, zone_of, now, frame_time, marker_state="OK"):
        """dets: dicts with cls (0 loaded, 1 empty), confidence, bbox [x0, y0, x1, y1] in frame pixels. Call once per processed frame.
        Each zone reports first_frame_time / last_frame_time of the frames in its window, so an answer can refuse evidence that
        started before the request (vision_answer.py). marker_state other than "OK" counts as lost geometry."""
        stale = now - frame_time > self.stale_sec
        per_zone = {z: [] for z in self.watch}
        usable = not stale and zone_of is not None and marker_state == "OK"
        skipped = 0
        if usable:
            for d in dets:
                box = d.get("bbox")
                if not isinstance(box, (list, tuple)) or len(box) != 4 or d.get("cls") not in (LOADED, EMPTY) or "confidence" not in d:
                    skipped += 1
                    continue
                if d["confidence"] < self.conf:
                    continue
                zs = zone_of(box)
                if zs is None:
                    usable = False
                    break
                for z in zs:
                    if z in per_zone:
                        per_zone[z].append(d["cls"])
        out = {}
        for z in self.watch:
            if usable:
                c = per_zone[z]
                self.hist[z].append(("0" if not c else "M" if len(c) > 1 else ("L" if c[0] == LOADED else "E"), frame_time))
            else:
                self.hist[z].clear()
            state = self._state(z, usable)
            if state != self.last[z]:
                self.last[z], self.since[z] = state, now
            h = self.hist[z]
            out[z] = {"state": state, "since_sec": round(now - self.since[z], 1), "frames": len(h), "seen": dict(Counter(s for s, _ in h)),
                      "first_frame_time": h[0][1] if h else None, "last_frame_time": h[-1][1] if h else None}
        return {"at": now, "stale": stale, "geometry": zone_of is not None, "marker_state": marker_state, "skipped_detections": skipped, "observe_only": True,
                "not_measured_thresholds": True, "source": "pinky_state_model", "zones": out}

    def _state(self, z, usable):
        h = self.hist[z]
        if not usable:
            return "UNKNOWN"
        if len(h) < self.window:
            return "FILLING"
        n = Counter(s for s, _ in h)
        if n["L"] >= self.need and n["E"] == 0:
            return "BOX"
        if n["E"] >= self.need and n["L"] == 0:
            return "EMPTY"
        if n["0"] >= self.need:
            return "NO_ROBOT"
        if n["M"] >= self.need:
            return "MULTI"
        return "MIXED"
