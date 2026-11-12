#!/usr/bin/env python3
"""marker_zone.py tests on synthetic frames with generated ArUco markers. No real frame, no device, no file.

    python test_marker_zone.py     # last line [marker_test] N/N PASS, exit 0
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import marker_zone as mz  # noqa: E402

results = []
BASE = {40: (150, 200), 41: (930, 180), 42: (960, 1250), 43: (120, 1270)}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))


def scene(rot=0.0, shift=(0, 0), hide=(), side=48):
    """White frame with four markers, turned about the centre and shifted, as the camera would see it."""
    img = np.full((1440, 1080, 3), 200, np.uint8)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for i, (x, y) in BASE.items():
        if i in hide:
            continue
        m = cv2.aruco.generateImageMarker(d, i, side)
        img[y - side // 2 - 8:y + side // 2 + 8, x - side // 2 - 8:x + side // 2 + 8] = 255
        img[y - side // 2:y - side // 2 + side, x - side // 2:x - side // 2 + side] = m[:, :, None]
    M = cv2.getRotationMatrix2D((540, 720), rot, 1.0)
    M[:, 2] += shift
    return cv2.warpAffine(img, M, (1080, 1440), flags=cv2.INTER_LINEAR, borderValue=(200, 200, 200)), M


def move(M, p):
    return (M @ np.array([p[0], p[1], 1.0])).tolist()


def test_square():
    s = mz.MarkerSquare()
    f, M = scene()
    check("four markers give OK", s.update(f, now=100.0, force=True) == "OK" and s.seen == 4)
    u, v = s.pixel_to_unit(*BASE[40])
    check("marker 40 is the unit origin", abs(u) < .01 and abs(v) < .01, f"{u} {v}")
    u, v = s.pixel_to_unit(*BASE[42])
    check("marker 42 is unit (1,1)", abs(u - 1) < .01 and abs(v - 1) < .01, f"{u} {v}")
    x, y = s.unit_to_pixel(1, 0)
    check("unit back to pixel", abs(x - BASE[41][0]) < 2 and abs(y - BASE[41][1]) < 2)
    check("second call inside the period reads nothing", s.update(f, now=100.2) == "OK" and s.checked == 100.0)


def test_follows_camera():
    p = (500, 600)
    s0 = mz.MarkerSquare()
    f, M = scene()
    s0.update(f, now=1.0, force=True)
    want = s0.pixel_to_unit(*p)
    s1 = mz.MarkerSquare()
    f, M = scene(rot=-3.8, shift=(-20, 15))
    s1.update(f, now=1.0, force=True)
    got = s1.pixel_to_unit(*move(M, p))
    check("a place keeps its unit coordinates when the camera turns", max(abs(want[0] - got[0]), abs(want[1] - got[1])) < .005, f"{want} {got}")


def test_partial():
    s = mz.MarkerSquare()
    f, _ = scene()
    s.update(f, now=1.0, force=True)
    f, M = scene(rot=-1.2, shift=(-10, 8), hide=(43,))
    check("three markers correct the square", s.update(f, now=2.0, force=True) == "FIXED" and s.seen == 3)
    want = move(M, BASE[43])
    check("hidden corner is estimated", float(np.abs(s.quad[3] - want).max()) < 4, f"{s.quad[3]} {want}")
    f, M = scene(rot=-1.2, shift=(-10, 8), hide=(41, 43))
    check("two markers correct the square", s.update(f, now=3.0, force=True) == "FIXED" and s.seen == 2)
    f, M = scene(hide=(40, 41, 42))
    check("one marker holds the last square", s.update(f, now=4.0, force=True) == "HOLD")
    f, _ = scene(hide=(40, 41, 42, 43))
    check("no marker holds", s.update(f, now=5.0, force=True) == "HOLD")
    check("hold ends in LOST", s.update(f, now=40.0, force=True) == "LOST")
    check("lost gives no coordinates", s.pixel_to_unit(500, 500) is None)
    check("lost gives no crop", s.crop(f)[0] is None)


def test_never_seen():
    s = mz.MarkerSquare()
    f, _ = scene(hide=(42, 43))
    check("two markers with no earlier square stay LOST", s.update(f, now=1.0, force=True) == "LOST")


def test_camera_jump():
    s = mz.MarkerSquare(max_step_px=60)
    f, _ = scene()
    s.update(f, now=1.0, force=True)
    f, M = scene(rot=-6, shift=(40, -30))
    check("a large step with all four markers is believed", s.update(f, now=2.0, force=True) == "OK" and s.seen == 4)
    check("square moved with it", float(np.abs(s.quad[0] - move(M, BASE[40])).max()) < 3)
    f, M2 = scene(rot=-6, shift=(40, -30), hide=(43,))
    bad = mz.MarkerSquare(max_step_px=60)
    bad.full_quad = np.float32([BASE[i] for i in (40, 41, 42, 43)]) + 200
    bad.quad = bad.full_quad.copy()
    bad.to_unit = cv2.getPerspectiveTransform(bad.quad, mz.UNIT)
    bad.updated, bad.state = 0.5, "OK"
    bad.update(f, now=1.0, force=True)
    check("a large step from a corrected square is refused", bad.rejected == 1)
    check("a refused correction is a conflict", bad.state == "CONFLICT", bad.state)
    check("a conflict gives no coordinates", bad.pixel_to_unit(500, 500) is None and bad.unit_to_pixel(.5, .5) is None)
    check("the same reading again is believed", bad.update(f, now=2.0, force=True) == "FIXED", bad.state)
    s2 = mz.MarkerSquare()
    s2.update(scene()[0], now=1.0, force=True)
    s2.update(scene(hide=(40, 41, 42, 43))[0], now=500.0, force=True)
    check("LOST gives no outline", s2.state == "LOST" and s2.unit_to_pixel(.5, .5) is None)
    s3 = mz.MarkerSquare()
    s3.update(scene()[0], now=1.0, force=True)
    check("status ages a stopped stream", s3.status(now=900.0)["state"] == "LOST")


def test_crop_offset():
    s = mz.MarkerSquare()
    f, _ = scene(rot=-3)
    s.update(f, now=1.0, force=True)
    c, (x0, y0) = s.crop(f)
    check("crop keeps pixels: same value at the offset", c is not None and (c[10, 10] == f[y0 + 10, x0 + 10]).all())
    check("crop holds the square", s.quad[:, 0].min() >= x0 and s.quad[:, 1].min() >= y0 and s.quad[:, 0].max() <= x0 + c.shape[1] and s.quad[:, 1].max() <= y0 + c.shape[0])


def test_zones():
    z = mz.Zones([{"name": "ZA", "poly": [[.1, .1], [.4, .1], [.4, .4], [.1, .4]], "purpose": "load"},
                  {"name": "AISLE", "poly": [[.3, .3], [.9, .3], [.9, .9], [.3, .9]], "purpose": "floor"}])
    check("point in a zone", z.at(.2, .2) == ["ZA"])
    check("point in two zones", sorted(z.at(.35, .35)) == ["AISLE", "ZA"])
    check("point outside", z.at(.05, .95) == [])
    s = mz.MarkerSquare()
    f, M = scene(rot=-3.8, shift=(-20, 15))
    s.update(f, now=1.0, force=True)
    x, y = s.unit_to_pixel(.2, .2)
    check("box centre finds its zone after a turn", z.of_box(s, [x - 15, y - 15, x + 15, y + 15]) == ["ZA"])
    b = z.crop_box(s, "ZA", f.shape)
    check("zone crop is inside the frame", b is not None and b[0] >= 0 and b[3] <= 1440 and b[2] > b[0] and b[3] > b[1])
    lost = mz.MarkerSquare()
    check("lost square means unknown, not outside", z.of_box(lost, [0, 0, 10, 10]) is None)
    check("zone crop needs a square", z.crop_box(lost, "ZA", f.shape) is None)
    far = mz.Zones([{"name": "OUT", "poly": [[-5, -5], [-4, -5], [-4, -4], [-5, -4]]}])
    check("a zone outside the frame gives no crop", far.crop_box(s, "OUT", f.shape) is None)
    try:
        mz.Zones([{"name": "A", "poly": [[0, 0], [1, 1]]}])
        check("two points refused", False)
    except ValueError:
        check("two points refused", True)
    try:
        mz.Zones([{"name": "A", "poly": [[0, 0], [1, 0], [1, 1]]}, {"name": "A", "poly": [[0, 0], [1, 0], [1, 1]]}])
        check("repeated name refused", False)
    except ValueError:
        check("repeated name refused", True)


def test_misread():
    s = mz.MarkerSquare()
    f, _ = scene()
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    f[700:748, 500:548] = cv2.aruco.generateImageMarker(d, 41, 48)[:, :, None]
    f[692:700, 492:556] = 255
    f[748:756, 492:556] = 255
    f[692:756, 492:500] = 255
    f[692:756, 548:556] = 255
    found = s.read(f)
    check("a repeated id is dropped", 41 not in found and len(found) == 3, str(sorted(found)))


def main():
    test_square()
    test_follows_camera()
    test_partial()
    test_never_seen()
    test_camera_jump()
    test_crop_offset()
    test_zones()
    test_misread()
    print(f"[marker_test] {sum(results)}/{len(results)} {'PASS' if all(results) else 'FAIL'}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
