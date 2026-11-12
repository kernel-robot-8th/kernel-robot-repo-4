#!/usr/bin/env python3
"""homelab-vision: 천장 카메라 MJPEG -> YOLO 두 모델 -> 구역 근거(MQTT, PUBLISH=true 일 때만).

하지 않는 것: ROS, 관제·작업 결과 토픽, 프레임 저장·전송, 포트 열기. 구역 판정은 /app/zone 모듈을 그대로 불러 쓴다.
"""
import hashlib
import json
import os
import signal
import sys
import threading
import time
import uuid

T0 = time.time()


_LOG_LOCK = threading.Lock()


def log(event, data=None):
    line = json.dumps({"t": round(time.time(), 3), "event": event, **(data or {})}, ensure_ascii=False) + "\n"
    with _LOG_LOCK:                      # 여러 스레드가 쓴다. print 는 글과 줄바꿈을 따로 써서 두 줄이 붙을 수 있다.
        sys.stdout.write(line)
        sys.stdout.flush()


if os.environ.get("NET_AUDIT", "").strip().lower() in ("1", "true", "yes", "on"):
    def _audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
            log("net_audit", {"what": event, "target": str(args[1:] if event != "socket.getaddrinfo" else args[:2])})
    sys.addaudithook(_audit)

# OpenCV/FFmpeg 가 stderr 에 직접 쓰는 줄(영상 접속 실패 때마다 2줄)을 줄인다. 접속 상태는 아래 JSON 로그와 하트비트에 있다.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")

sys.path.insert(0, "/app/zone")

import config as cfgmod  # noqa: E402
from config import (CALIBRATION_ID, CLOCK_ERROR_SEC, EVIDENCE_CONF, FRAME_H, FRAME_W, MAX_PAYLOAD, MODEL_ID, PACKET_SUMS,  # noqa: E402
                    STREAM_ID, TOPIC_BOXES, TOPIC_ZONES, WEIGHTS, ZONE_MARGIN_PX, ZONES_TRAY_JSON)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_sums():
    out = {}
    with open(PACKET_SUMS, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                out[os.path.basename(parts[1])] = parts[0]
    return out


def cpu_limit():
    """컨테이너 CPU 한도(cgroup v2)와 실제 쓸 수 있는 코어 수 중 작은 값."""
    n = len(os.sched_getaffinity(0))
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
        if quota != "max":
            n = min(n, max(1, int(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return n


def dets_payload(dets, zone_of=None, limit=50):
    keep = [d for d in dets if d["confidence"] >= EVIDENCE_CONF]
    out = []
    for d in keep[:limit]:
        item = {"cls": d["cls"], "name": d["name"], "confidence": round(d["confidence"], 4), "bbox": [round(v, 1) for v in d["bbox"]]}
        if zone_of is not None:
            item["zones"] = zone_of(d["bbox"])
        out.append(item)
    return out, max(0, len(keep) - limit)


def main():
    cfg = cfgmod.Config()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    sums = {os.path.basename(p): sha256_file(p) for p in WEIGHTS.values()}
    want = expected_sums()
    bad = [n for n, s in sums.items() if want.get(n) != s]
    if bad:
        log("fatal", {"reason": "weights sha256 differs from packet", "files": bad})
        return 2

    import cv2
    import numpy
    import torch
    import torchvision
    import ultralytics
    from ultralytics.utils import ONLINE, SETTINGS

    if cfg.device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    elif cfg.device.startswith("cuda") and not torch.cuda.is_available():
        log("fatal", {"reason": "DEVICE asks for cuda but torch.cuda.is_available() is False"})
        return 2
    else:
        device = "cuda:0" if cfg.device == "cuda" else cfg.device
    threads = cfg.torch_threads or cpu_limit()
    torch.set_num_threads(threads)
    cv2.setNumThreads(threads)

    stream_epoch = f"{int(T0)}-{uuid.uuid4().hex[:8]}"
    log("startup", {"weights_sha256": sums, "stream_epoch": stream_epoch, "device": device,
                    "gpu": torch.cuda.get_device_name(0) if device.startswith("cuda") else None,
                    "versions": {"python": sys.version.split()[0], "torch": torch.__version__, "torchvision": torchvision.__version__,
                                 "ultralytics": ultralytics.__version__, "cv2": cv2.__version__, "numpy": numpy.__version__,
                                 "torch_cuda_build": torch.version.cuda},
                    "ultralytics_online": bool(ONLINE), "ultralytics_sync": bool(SETTINGS.get("sync")), "threads": threads,
                    "config": cfg.public()})

    import marker_zone
    import tray_zones
    import zone_evidence_msg
    from detector import Detector
    from source import FrameSource

    zone_of = tray_zones.make_zone_of(tray_zones.load_hulls(ZONES_TRAY_JSON), ZONE_MARGIN_PX)
    emitter = zone_evidence_msg.ZoneEvidenceEmitter(stream_epoch, model_id=MODEL_ID, calibration_id=CALIBRATION_ID, stream_id=STREAM_ID,
                                                    clock_error_sec=CLOCK_ERROR_SEC, mode="raw", conf=EVIDENCE_CONF)
    marker = marker_zone.MarkerSquare(period_sec=1.0)

    t = time.time()
    det = Detector(device)
    log("models_ready", {"load_and_warmup_sec": round(time.time() - t, 2), "names": det.names, "warmup_detections": det.warmup_dets})

    pub = None
    if cfg.publish:
        from publisher import Publisher          # paho 는 여기서만 import 된다
        pub = Publisher(cfg.mqtt_broker, cfg.mqtt_port, client_id=f"homelab-vision-{stream_epoch}", queue_max=cfg.queue_max, log=log)

    src = FrameSource(cfg.camera_source, stop, log=log)
    src.start()

    st = {"inferred": 0, "skipped_wrong_size": 0, "zones_emitted": 0, "zones_refused": 0, "oversize_payload": 0, "infer_ms": 0.0,
          "infer_ms_sum": 0.0, "first_infer": None, "last_infer": None, "marker_state": marker.state, "markers_seen": 0,
          "last_zones": None, "last_refusal": None}

    def status(prev):
        now = time.time()
        span = (st["last_infer"] - st["first_infer"]) if st["inferred"] > 1 else 0.0
        d = {"status": "online", "ts": round(now, 3), "stream_id": STREAM_ID, "stream_epoch": stream_epoch, "model_id": MODEL_ID,
             "calibration_id": CALIBRATION_ID, "clock_error_sec": CLOCK_ERROR_SEC, "weights_sha256": sums, "device": device,
             "publish": cfg.publish, "source_connected": src.is_live(now), "source_connect_attempts": src.connect_attempts,
             "source_connect_failures": src.connect_failures, "frames_received": src.frames_received,
             "frames_inferred": st["inferred"], "frames_skipped_wrong_size": st["skipped_wrong_size"],
             "last_frame_size": list(src.last_size) if src.last_size else None,
             "infer_fps_1s": round((st["inferred"] - prev["inferred"]) / max(now - prev["ts"], 1e-6), 2),
             "infer_fps_avg": round((st["inferred"] - 1) / span, 2) if span > 0 else 0.0,
             "infer_ms_last": round(st["infer_ms"], 1),
             "infer_ms_avg": round(st["infer_ms_sum"] / st["inferred"], 1) if st["inferred"] else 0.0,
             "zones_frames_emitted": st["zones_emitted"], "zones_frames_refused": st["zones_refused"],
             "last_refusal": st["last_refusal"], "marker_state": st["marker_state"], "markers_seen": st["markers_seen"],
             "last_zones": st["last_zones"],
             "publish_queue_drops": pub.drops if pub else 0,
             "publish_drops_detail": {"overflow": pub.drops_overflow, "stale": pub.drops_stale, "rc": pub.drops_rc} if pub else None,
             "publish_queue_len": pub.queue_len() if pub else 0, "published": pub.published if pub else 0,
             "published_acked": pub.published_acked if pub else 0, "publish_unacked_lost": pub.unacked_lost if pub else 0,
             "publish_inflight": pub.inflight() if pub else 0, "mqtt_renewals": pub.renewals if pub else 0,
             "mqtt_connected": bool(pub and pub.connected), "oversize_payload": st["oversize_payload"],
             "uptime_sec": round(now - T0, 1)}
        prev["inferred"], prev["ts"] = st["inferred"], now
        return d

    def heartbeat_loop():
        prev, last_log = {"inferred": 0, "ts": time.time()}, 0.0
        while not stop.wait(1.0):
            d = status(prev)
            if pub:
                pub.heartbeat(json.dumps(d, ensure_ascii=False))
            if cfg.status_log_sec > 0 and time.time() - last_log >= cfg.status_log_sec - 0.05:
                last_log = time.time()
                log("status", {k: v for k, v in d.items() if k != "weights_sha256"})

    threading.Thread(target=heartbeat_loop, name="heartbeat", daemon=True).start()

    def offer(topic, obj):
        if not pub:
            return
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > MAX_PAYLOAD:
            st["oversize_payload"] += 1
            return
        pub.offer(topic, payload, age_sec=time.time() - obj["capture_time"])

    period = 1.0 / cfg.inference_fps
    next_t, last_seq = time.monotonic(), 0
    while not stop.is_set():
        item = src.latest()
        if item is None or item[2] == last_seq:
            stop.wait(0.005)
            continue
        wait = next_t - time.monotonic()
        if wait > 0:
            stop.wait(wait)
            item = src.latest() or item           # 기다리는 동안 온 더 새 프레임을 쓴다
        next_t = max(next_t + period, time.monotonic())
        frame, capture_time, last_seq = item
        h, w = frame.shape[:2]
        if (w, h) != (FRAME_W, FRAME_H):
            st["skipped_wrong_size"] += 1
            continue
        t_inf = time.monotonic()
        marker_state = marker.update(frame, now=time.time())
        pinky, boxes = det.infer(frame)
        now = time.time()
        st["infer_ms"] = (time.monotonic() - t_inf) * 1000.0
        st["infer_ms_sum"] += st["infer_ms"]
        st["inferred"] += 1
        st["last_infer"] = now
        if st["first_infer"] is None:
            st["first_infer"] = now
        st["marker_state"], st["markers_seen"] = marker_state, marker.seen

        zframe, reason = emitter.emit(pinky, zone_of, capture_time, marker_state, now)
        if zframe is None:
            st["zones_refused"] += 1
            st["last_refusal"] = reason
        else:
            st["zones_emitted"] += 1
            st["last_zones"] = zframe["zones"]
            offer(TOPIC_ZONES, zframe)             # 모니터 계약: 키를 더하지 않고 그대로 보낸다
        p_list, p_cut = dets_payload(pinky, zone_of)
        b_list, b_cut = dets_payload(boxes)
        offer(TOPIC_BOXES, {"source_kind": "model_output", "stream_id": STREAM_ID, "stream_epoch": stream_epoch,
                            "frame_seq": st["inferred"] - 1, "zones_frame_seq": zframe["frame_seq"] if zframe else None,
                            "capture_time": float(capture_time), "clock_error_sec": CLOCK_ERROR_SEC, "model_id": MODEL_ID,
                            "calibration_id": CALIBRATION_ID, "marker_state": marker_state, "device": device,
                            "weights_sha256": sums, "frame_size": [w, h], "conf_min": EVIDENCE_CONF, "box_model": "kneg-d-final",
                            "pinky_model": "pinky-v2-final", "boxes": b_list, "pinky": p_list, "truncated": b_cut + p_cut})

    log("stopping", {"frames_inferred": st["inferred"], "frames_received": src.frames_received,
                     "frames_skipped_wrong_size": st["skipped_wrong_size"], "publish_queue_drops": pub.drops if pub else 0})
    if pub:
        pub.close()
    # 영상 읽기 스레드가 FFmpeg 안에 있는 채로 인터프리터가 끝나면 glibc 가 "FATAL: exception not rethrown" 으로 중단시킨다.
    # 그래서 스레드가 끝나기를 기다리고(읽기·열기 제한 5초), 그래도 남아 있으면 정리 단계를 건너뛰고 끝낸다.
    src.join(timeout=6.0)
    if src.is_alive():
        log("source_thread_still_running_at_exit")
        sys.stdout.flush()
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
