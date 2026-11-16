"""환경 변수 -> 설정. 비밀값은 다루지 않는다."""
import os
import re

FRAME_W, FRAME_H = 1080, 1440          # 폭 x 높이. 이 크기가 아니면 추론하지 않는다.
IMGSZ, IOU, PREDICT_CONF, EVIDENCE_CONF = 960, 0.7, 0.25, 0.5
ZONE_MARGIN_PX = 20.0
MODEL_ID, CALIBRATION_ID, CLOCK_ERROR_SEC, STREAM_ID = "pinky-v1", "ceil-20261108", 0.05, "ceiling"
TOPIC_ZONES, TOPIC_BOXES, TOPIC_STATUS = "relay/evidence/zones", "relay/evidence/boxes", "relay/status/vision"
WEIGHTS = {"pinky": "/app/weights/pinky_v2_final.pt", "boxes": "/app/weights/kneg_d_final.pt"}
ZONES_TRAY_JSON = "/app/zone/zones-tray-px-20261108.json"
PACKET_SUMS = "/app/PACKET_SHA256SUMS"
MAX_PAYLOAD = 16000                     # 모니터 수신기는 16384바이트를 넘으면 버린다.


def _bool(name, default):
    v = os.environ.get(name)
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def redact(url):
    """주소에 계정이 들어 있으면 로그에서 가린다."""
    return re.sub(r"//[^/@]*@", "//***@", url)


class Config:
    def __init__(self, env=os.environ):
        self.mqtt_broker = env.get("MQTT_BROKER", "192.168.0.3")
        self.mqtt_port = int(env.get("MQTT_PORT", "1883"))
        self.camera_source = env.get("CAMERA_SOURCE", "http://192.168.0.7:18086/processed")
        self.inference_fps = float(env.get("INFERENCE_FPS", "10"))
        self.publish = _bool("PUBLISH", False)
        self.device = env.get("DEVICE", "auto").strip().lower()
        self.status_log_sec = float(env.get("STATUS_LOG_SEC", "10"))
        self.torch_threads = int(env.get("TORCH_THREADS", "0"))      # 0 = 컨테이너 CPU 한도에 맞춤
        self.queue_max = int(env.get("PUBLISH_QUEUE_MAX", "20"))
        self.net_audit = _bool("NET_AUDIT", False)                   # 파이썬 소켓 연결 시도를 로그에 남김(검증용)
        if not 0 < self.inference_fps <= 60:
            raise ValueError("INFERENCE_FPS must be within 0..60")
        if self.queue_max < 1:
            raise ValueError("PUBLISH_QUEUE_MAX must be at least 1")

    def public(self):
        return {"mqtt_broker": self.mqtt_broker, "mqtt_port": self.mqtt_port, "camera_source": redact(self.camera_source),
                "inference_fps": self.inference_fps, "publish": self.publish, "device_requested": self.device,
                "status_log_sec": self.status_log_sec, "queue_max": self.queue_max, "frame_size": [FRAME_W, FRAME_H],
                "imgsz": IMGSZ, "iou": IOU, "rect": False, "predict_conf": PREDICT_CONF, "evidence_conf": EVIDENCE_CONF,
                "zone_margin_px": ZONE_MARGIN_PX, "model_id": MODEL_ID, "calibration_id": CALIBRATION_ID,
                "clock_error_sec": CLOCK_ERROR_SEC}
