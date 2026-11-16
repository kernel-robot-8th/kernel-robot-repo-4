#!/usr/bin/env python3
"""맵 영역 자르기와 웹 창구 시험. 모델과 장치 없이 돈다. 합성 프레임만 쓴다.

    python test_map_crop.py     # 끝 줄이 [map_test] N/N PASS, exit 0 이어야 한다
"""
import http.client
import json
import os
import sys
import threading

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import edge_view as ev  # noqa: E402
import stream_manager as sm  # noqa: E402
import test_edge_view as te  # noqa: E402
import test_stream_manager as ts  # noqa: E402

results = []
W, H = 1080, 1440
CORNERS = {40: (200, 300), 41: (880, 320), 42: (860, 1100), 43: (220, 1080)}  # 조금 기운 사각형
OUTSIDE_VALUE, INSIDE_VALUE = 200, 90


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))


def scene(ids=(40, 41, 42, 43), shift=(0, 0)):
    """밝은 바탕에 마커를 붙인 프레임. 사각형 안쪽은 어둡게 칠해 안팎을 화소 값으로 가린다."""
    img = np.full((H, W, 3), OUTSIDE_VALUE, np.uint8)
    quad = np.int32([[x + shift[0], y + shift[1]] for x, y in CORNERS.values()])
    cv2.fillConvexPoly(img, quad, (INSIDE_VALUE,) * 3)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for i in ids:
        x, y = CORNERS[i][0] + shift[0], CORNERS[i][1] + shift[1]
        img[y - 40:y + 40, x - 40:x + 40] = 255
        img[y - 30:y + 30, x - 30:x + 30] = cv2.cvtColor(cv2.aruco.generateImageMarker(d, i, 60), cv2.COLOR_GRAY2BGR)
    return img


def viewer(**kw):
    v, _ = te.viewer(map_crop=True, view_width=0, **kw)
    return v


def test_four_markers():
    v = viewer()
    inside, outside = te.det("box_on_floor", bbox=(500, 600, 560, 660)), te.det("box_on_floor", bbox=(20, 20, 80, 80))
    frame = scene()
    for i in range(3):
        v.process(frame, [dict(inside), dict(outside)], 0.01, 1000.0 + i * 0.2)
    snap = v.snapshot()
    check("four markers give OK", snap["map"]["state"] == "OK" and snap["map"]["visible"], snap["map"])
    x0, y0, x1, y1 = snap["map"]["box"]
    # 마커 한 변은 60 화소다. 영역은 마커 중심이 아니라 바깥 귀(중심에서 30 화소 밖)까지다.
    check("box reaches the outer marker corners", abs(x0 - 170) <= 4 and abs(y0 - 270) <= 4 and abs(x1 - 910) <= 4 and abs(y1 - 1130) <= 4, snap["map"]["box"])
    check("outside detection dropped", len(snap["current"]) == 1 and snap["map"]["dropped_outside"] == 3, snap["current"])
    check("inside detection keeps frame pixels", snap["current"][0]["bbox"] == [500.0, 600.0, 560.0, 660.0])
    check("only the inside one alarms", len(v.events) == 1)
    view = v.render(frame, [])
    check("view is the crop, not the frame", view.shape[:2] == (y1 - y0, x1 - x0), view.shape)
    whole = all(np.array_equal(view[y - 30 - y0:y + 30 - y0, x - 30 - x0:x + 30 - x0], frame[y - 30:y + 30, x - 30:x + 30])
                for x, y in CORNERS.values())
    check("every marker is shown whole", whole)
    # 마커 바깥 귀를 이은 선에서 6 화소 넘게 벗어난 곳은 모두 지워져 있어야 한다.
    outer = np.float32([[x + dx, y + dy] for x, y in CORNERS.values() for dx in (-30, 30) for dy in (-30, 30)])
    allowed = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(allowed, cv2.convexHull(outer).reshape(-1, 2).astype(np.int32), 255)
    allowed = cv2.dilate(allowed, np.ones((13, 13), np.uint8))[y0:y1, x0:x1]
    leaked = int((view.max(axis=2)[allowed == 0] > 0).sum())
    check("nothing past the marker outline is sent", leaked == 0, leaked)
    check("corner outside the tilted outline is black", view[2, view.shape[1] // 2].max() == 0)
    drawn = v.render(frame, [dict(inside, alarm_class=True, in_roi=False)])
    px = drawn[600 - y0 + 30, 500 - x0]
    check("box drawn at crop offset", tuple(int(c) for c in px) == ev.COLOR["box_on_floor"], str(px))


def test_fewer_markers():
    v = viewer()
    v.process(scene(), [], 0.01, 1000.0)
    v.process(scene(ids=(40, 41, 42), shift=(6, 4)), [], 0.01, 1001.0)
    snap = v.snapshot()["map"]
    check("three markers correct the square", snap["state"] == "FIXED" and snap["visible"] and abs(snap["box"][0] - 176) <= 5, snap)
    v.process(scene(ids=()), [], 0.01, 1002.0)
    held = v.render(scene(ids=(), shift=(6, 4)), [])
    check("hidden markers keep their place in the crop", held.shape[:2] == (v.map_box[3] - v.map_box[1], v.map_box[2] - v.map_box[0]))
    check("no marker holds the last square", v.snapshot()["map"]["state"] == "HOLD" and v.snapshot()["map"]["visible"])
    hidden = te.det("box_on_floor", bbox=(500, 600, 560, 660))
    for i in range(4):
        v.process(scene(ids=()), [dict(hidden)], 0.01, 1012.5 + i * 0.6)
    snap = v.snapshot()
    check("hold ends after 10 s", snap["map"]["state"] == "LOST" and not snap["map"]["visible"], snap["map"])
    view = v.render(scene(ids=()), [])
    check("lost shows the notice, not the frame", view.shape[:2] == (360, 480)
          and np.array_equal(view, v.render(np.zeros((H, W, 3), np.uint8), [])))
    check("nothing is judged while hidden", snap["current"] == [] and len(v.events) == 0)
    v.process(scene(), [], 0.01, 1020.0)
    check("markers back, view back", v.snapshot()["map"]["state"] == "OK" and v.snapshot()["map"]["visible"])


def test_never_seen_and_jitter():
    v = viewer()
    v.process(scene(ids=(40, 41)), [], 0.01, 1000.0)
    check("two markers without a first square stay hidden", not v.snapshot()["map"]["visible"])
    check("never seen shows the notice", v.render(scene(ids=()), []).shape[:2] == (360, 480))
    v.process(scene(), [], 0.01, 1001.0)
    v.process(scene(shift=(3, -2)), [], 0.01, 1002.0)
    box = v.snapshot()["map"]["box"]
    check("small shake follows", v.snapshot()["map"]["state"] == "OK" and abs(box[0] - 173) <= 4 and abs(box[1] - 268) <= 4, box)
    plain, _ = te.viewer()
    plain.process(scene(), [], 0.01, 1000.0)
    check("off by default: full frame, no map state", plain.snapshot()["map"] is None and plain.render(scene(), []).shape[:2] == (960, 720))
    m = viewer(map_margin_px=20)
    m.process(scene(), [], 0.01, 1000.0)
    check("margin widens the box", m.snapshot()["map"]["box"][0] <= 151)


def test_config_and_bridge():
    check("map_crop must be bool", ts.refuses({"cameras": [ts.entry("a", map_crop="yes")]}))
    check("margin must be a small integer", ts.refuses({"cameras": [ts.entry("a", map_margin_px=500)]}))
    check("bridge bind is the docker gateway only", ts.refuses({"cameras": [], "bridge_bind": "0.0.0.0"})
          and ts.refuses({"cameras": [], "bridge_bind": "192.168.0.8"}))
    check("docker gateway passes", not ts.refuses({"cameras": [], "bridge_bind": "172.17.0.1"}))
    m = ts.manager([ts.entry("map", map_crop=True), ts.entry("raw")])
    server = ev.Server(("127.0.0.1", 0), sm.make_handler(m, bridge=True))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    web = {"Host": "192.168.0.8:5173", "Sec-Fetch-Site": "same-origin"}
    js = {"Content-Type": "application/json"}
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/api/state", headers=web)
        reply = conn.getresponse()
        status, data = reply.status, reply.read()
        conn.close()
        state = json.loads(data) if status == 200 else {}
        check("bridge state lists only cropped cameras", status == 200 and [c["id"] for c in state["cameras"]] == ["map"], data[:200])
        check("bridge state hides host details", "resources" not in state and "scheduler" not in state)
        check("uncropped stream is not served", ts.request(port, "GET", "/cameras/raw/stream.mjpg", headers=web)[0] == 404)
        check("bridge has no page", ts.request(port, "GET", "/", headers=web)[0] == 404)
        for path in ("/api/cameras/map/stop", "/api/cameras/map/start", "/api/reload"):
            check(f"bridge refuses post {path}", ts.request(port, "POST", path, "{}", dict(js, **web))[0] == 403)
        check("bridge refuses cross site", ts.request(port, "GET", "/api/state", headers=dict(web, **{"Sec-Fetch-Site": "cross-site"}))[0] == 403)
        check("camera still running", m.cameras["map"].state == "running")
        raw = ts.raw(port, b"GET /cameras/map/stream.mjpg HTTP/1.0\r\nHost: 192.168.0.8:5173\r\n\r\n")
        check("cropped stream is served", raw.startswith(b"HTTP/1.0 200"), raw[:40])
    finally:
        server.shutdown()
        server.server_close()
        m.shutdown()


def main():
    test_four_markers()
    test_fewer_markers()
    test_never_seen_and_jitter()
    test_config_and_bridge()
    print(f"[map_test] {sum(results)}/{len(results)} {'PASS' if all(results) else 'FAIL'}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
