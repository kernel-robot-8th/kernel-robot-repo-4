#!/usr/bin/env python3
"""Work zone outlines at robot-tray height for the Pinky state model (2026-11-09). Pure Python, no OpenCV.

zones-tray-px-20261108.json holds, per zone, the hull of the user's floor zone joined with the same zone raised to tray height
(0.20 and 0.25 m), in pixels of the 11-08 ceiling camera pose (Note10, 1080x1440 portrait). A robot box belongs to a zone when its
centre lies inside the hull or within margin_px of it (homelab scoring used 20 px). Pixel outlines hold only while the camera stays
where it was on 11-08: between 11-07 11:24 and 11-08 it had moved about 25 px. Check the four markers before trusting them.
Use: zone_of = make_zone_of(load_hulls(path)); zone_of([x0, y0, x1, y1]) -> ["ZC"] or []
"""
import json
import math


def load_hulls(path, rec="rec-20261108-203844-3"):
    d = json.load(open(path, encoding="utf-8"))
    return {z: [tuple(p) for p in v] for z, v in d["recs"][rec]["hulls"].items()}


def _inside(poly, x, y):
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _dist(poly, x, y):
    best = math.inf
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = x2 - x1, y2 - y1
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def make_zone_of(hulls, margin_px=20.0):
    def zone_of(box):
        x, y = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        return [z for z, poly in hulls.items() if _inside(poly, x, y) or _dist(poly, x, y) <= margin_px]
    return zone_of
