#!/usr/bin/env python3
"""Marker square tracking, whole-map crop and zone lookup for the ceiling camera (2026-11-07).

The camera has turned by several degrees within one morning, so nothing may be stored in pixels. Places are stored in marker-square coordinates:
(u, v) = (0, 0) at marker 40, (1, 0) at 41, (1, 1) at 42, (0, 1) at 43. The square is found again from the image, so zones follow the camera.

This needs no tape measure and no lens values. It is pixel to pixel. Metres on the map still need the measured calibration of pixel_map.py.
Numbers only: nothing here writes an image. Detection boxes stay in original frame pixels. crop() returns the offset to add back.

MarkerSquare states
  OK     all four markers were read at the last check
  FIXED  2 or 3 markers read. The last four-marker square is corrected by a similarity (2) or affine (3) transform. Solving directly from fewer markers is much worse.
  HOLD   0 or 1 marker read, last square kept, younger than max_age_sec. A one-marker shift is worse than no correction, so it is not used.
  CONFLICT  2 to 4 markers read but they disagree with the square and the reading was refused. The square is not trusted: zone lookup returns None.
  LOST   no square, or not updated for max_age_sec. Zone lookup returns None.
"""
import json
import time

import cv2
import numpy as np

CORNERS = {40: 0, 41: 1, 42: 2, 43: 3}   # tl, tr, br, bl: tablet/vision/config/markers.yaml
UNIT = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])


def _clamp(x0, y0, x1, y1, w, h):
    box = max(int(x0), 0), max(int(y0), 0), min(int(x1), w), min(int(y1), h)
    return box if box[2] > box[0] and box[3] > box[1] else None


def _detector():
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    return cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())


class MarkerSquare:
    def __init__(self, period_sec=1.0, max_age_sec=30.0, max_step_px=120.0, ids=None):
        self.ids = dict(ids or CORNERS)
        self.period_sec, self.max_age_sec, self.max_step_px = period_sec, max_age_sec, max_step_px
        self.detector = _detector()
        self.quad = None          # 4x2 float32, frame pixels
        self.full_quad = None     # last square read from all four markers
        self.state, self.seen, self.checked, self.updated = "LOST", 0, 0.0, 0.0
        self.to_unit = None
        self.rejected = 0
        self.pending = None       # a refused correction, kept to see if the next reading agrees with it

    def read(self, frame):
        """Marker centres in frame pixels. A repeated id is a misread: both are dropped."""
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        found, twice = {}, set()
        if ids is not None:
            for c, i in zip(corners, ids.ravel().tolist()):
                if i in self.ids:
                    if i in found:
                        twice.add(i)
                    found[i] = c.reshape(4, 2).mean(axis=0)
        for i in twice:
            del found[i]
        return found

    def _set(self, quad, state, now):
        area = cv2.contourArea(quad.astype(np.float32))
        if area < 1000 or not cv2.isContourConvex(quad.astype(np.float32)):
            self.rejected += 1
            return False
        if self.quad is not None and float(np.abs(quad - self.quad).max()) > self.max_step_px:
            # A real camera move looks the same as a bad reading, so a second reading in the same place is believed.
            if self.pending is None or float(np.abs(quad - self.pending).max()) > self.max_step_px / 4:
                self.pending = quad.copy()
                self.rejected += 1
                return False
        self.pending = None
        self.quad = quad.astype(np.float32)
        self.to_unit = cv2.getPerspectiveTransform(self.quad, UNIT)
        self.state, self.updated = state, now
        return True

    def update(self, frame, now=None, force=False):
        """Call for every frame. Reads markers at most once per period. Returns the state."""
        now = time.time() if now is None else now
        if not force and now - self.checked < self.period_sec:
            return self._aged(now)
        self.checked = now
        found = self.read(frame)
        self.seen = len(found)
        idx = {self.ids[i]: p for i, p in found.items()}
        if len(idx) == 4:
            quad = np.float32([idx[k] for k in range(4)])
            prev, self.quad = self.quad, None   # four matching ids are believed even after a large step: the camera does move.
            if self._set(quad, "OK", now):
                self.full_quad = self.quad.copy()
                return self.state
            self.quad = prev
            self.state = "CONFLICT"
            return self._aged(now)
        if len(idx) >= 2 and self.full_quad is not None:
            src = np.float32([self.full_quad[k] for k in sorted(idx)])
            dst = np.float32([idx[k] for k in sorted(idx)])
            if len(idx) == 3:
                m = cv2.getAffineTransform(src, dst)
            else:
                m = self._similarity(src, dst)
            quad = (np.c_[self.full_quad, np.ones(4)] @ m.T).astype(np.float32)
            if self._set(quad, "FIXED", now):
                return self._aged(now)
            self.state = "CONFLICT"
            return self._aged(now)
        return self._aged(now, hold=True)

    @staticmethod
    def _similarity(src, dst):
        a, b = src[1] - src[0], dst[1] - dst[0]
        s = float(np.linalg.norm(b) / max(np.linalg.norm(a), 1e-6))
        t = float(np.arctan2(b[1], b[0]) - np.arctan2(a[1], a[0]))
        r = s * np.float32([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        return np.c_[r, dst[0] - r @ src[0]]

    def _aged(self, now, hold=False):
        if self.quad is None or now - self.updated > self.max_age_sec:
            self.state = "LOST"
        elif hold:
            self.state = "HOLD"
        return self.state

    def usable(self):
        return self.to_unit is not None and self.state in ("OK", "FIXED", "HOLD")

    def pixel_to_unit(self, x, y):
        if not self.usable():
            return None
        p = cv2.perspectiveTransform(np.float32([[[x, y]]]), self.to_unit)[0, 0]
        return float(p[0]), float(p[1])

    def unit_to_pixel(self, u, v):
        if not self.usable():
            return None
        p = cv2.perspectiveTransform(np.float32([[[u, v]]]), np.linalg.inv(self.to_unit))[0, 0]
        return float(p[0]), float(p[1])

    def crop_box(self, frame_shape, margin_px=24):
        """Axis-aligned box around the square. No perspective warp and no mask, so a box found in the crop returns to frame pixels by adding the offset."""
        if self.quad is None or not self.usable():
            return None
        h, w = frame_shape[:2]
        x0, y0 = np.floor(self.quad.min(axis=0)).astype(int) - margin_px
        x1, y1 = np.ceil(self.quad.max(axis=0)).astype(int) + margin_px
        return _clamp(x0, y0, x1, y1, w, h)

    def crop(self, frame, margin_px=24):
        box = self.crop_box(frame.shape, margin_px)
        if box is None:
            return None, (0, 0)
        x0, y0, x1, y1 = box
        return frame[y0:y1, x0:x1], (x0, y0)

    def status(self, now=None):
        now = time.time() if now is None else now
        self._aged(now)
        return {"state": self.state, "markers_seen": self.seen, "age_sec": round(now - self.updated, 1) if self.updated else None,
                "quad": None if self.quad is None else [[round(float(a), 1) for a in p] for p in self.quad], "rejected": self.rejected}


class Zones:
    """Named polygons in marker-square coordinates. File: {"space": "marker_unit", "zones": [{"name": "ZA", "poly": [[u, v], ...], "purpose": "load"}]}"""

    def __init__(self, zones):
        names = [z["name"] for z in zones]
        if len(names) != len(set(names)):
            raise ValueError("zone names repeat")
        for z in zones:
            if len(z["poly"]) < 3:
                raise ValueError(f"zone {z['name']} needs three points")
        self.zones = zones
        self.polys = {z["name"]: np.float32(z["poly"]).reshape(-1, 1, 2) for z in zones}

    @classmethod
    def load(cls, path):
        d = json.load(open(path, encoding="utf-8"))
        if d.get("space") != "marker_unit":
            raise ValueError("zones file must use marker_unit coordinates")
        return cls(d["zones"])

    def at(self, u, v):
        """Names of the zones holding this point. Empty when the point is outside all of them."""
        return [n for n, p in self.polys.items() if cv2.pointPolygonTest(p, (float(u), float(v)), False) >= 0]

    def of_box(self, square, bbox):
        """Zones of a detection box in frame pixels, judged at its centre. None means the square is lost: unknown, not 'outside'."""
        p = square.pixel_to_unit((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        return None if p is None else self.at(*p)

    def crop_box(self, square, name, frame_shape, margin_px=12):
        """Frame pixel box of one zone, for a zone crop. Returns None when the square is lost."""
        if not square.usable():
            return None
        pts = np.float32([square.unit_to_pixel(float(u), float(v)) for u, v in self.polys[name].reshape(-1, 2)])
        h, w = frame_shape[:2]
        x0, y0 = np.floor(pts.min(axis=0)).astype(int) - margin_px
        x1, y1 = np.ceil(pts.max(axis=0)).astype(int) + margin_px
        return _clamp(x0, y0, x1, y1, w, h)
