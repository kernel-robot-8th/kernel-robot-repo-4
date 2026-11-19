"""환경 변수 -> 설정. 비밀값은 다루지 않는다."""
import os
import re

FRAME_W, FRAME_H = 1080, 1440          # 폭 x 높이. 이 크기가 아니면 추론하지 않는다.


def _imgsz(default=960):
    """INFER_IMGSZ: 모델 입력 크기(정사각, 32의 배수, 160..1280). 비어 있으면 960(천장 카메라 학습 조건).

    근접 카메라는 로봇이 커서 960 이면 못 잡는다(11-15 홈랩 시험: 실사 천장 프레임 확대와 합성 수직 렌더에서, 로봇이 입력에서
    약 70 px 를 넘으면 검출이 무너졌다. 실물 근접 카메라로는 아직 확인 안 함).
    로봇이 입력에서 40~60 px 가 되게 줄인다. 예: 노트3 640x480 은 약 416, 웹캠 1280x720 은 약 480~576.
    ultralytics 는 긴 변을 이 값에 맞추므로, 프레임을 미리 줄여도 효과가 없고 이 값을 바꿔야 한다.
    근접 카메라는 이 값만으로는 돌지 않는다(프레임 크기·검출 전용 설정은 이 트리에 아직 없다). 프레임 크기가 1080x1440 이 아니면
    추론 전에 건너뛰고, 운영 모드의 구역 윤곽·보정 이름은 천장 카메라 것이기 때문이다.
    """
    v = os.environ.get("INFER_IMGSZ", "").strip()
    if not v:
        return default
    if not re.fullmatch(r"[0-9]{3,4}", v):
        raise ValueError("INFER_IMGSZ must be an integer such as 416")
    n = int(v)
    if not 160 <= n <= 1280 or n % 32:
        raise ValueError("INFER_IMGSZ must be a multiple of 32 within 160..1280")
    return n


IMGSZ = _imgsz()
IOU, PREDICT_CONF, EVIDENCE_CONF = 0.7, 0.25, 0.5
ZONE_MARGIN_PX = 20.0
MODEL_ID, CALIBRATION_ID, CLOCK_ERROR_SEC, STREAM_ID = "pinky-v1", "ceil-20261108", 0.05, "ceiling"
TOPIC_ZONES, TOPIC_BOXES, TOPIC_STATUS = "relay/evidence/zones", "relay/evidence/boxes", "relay/status/vision"
WEIGHTS = {"pinky": "/app/weights/pinky_v2_final.pt", "boxes": "/app/weights/kneg_d_final.pt"}
# 선택 자리: 팔 모델(1클래스 arm_over_pinky, 합성 전용·관찰용). 이 파일이 이미지에 없으면 앱은 전과 같이 두 모델만 돈다.
# 결과는 새 주제로만 낸다. 기존 주제(zones, boxes, status)의 내용은 바뀌지 않는다.
ARM_WEIGHT, ARM_MODEL, TOPIC_ARM = "/app/weights/arm_v1.pt", "arm-v1", "relay/evidence/arm"
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
        self.mqtt_broker = env.get("MQTT_BROKER", "192.168.0.8")    # 중계 유선. 192.168.0.3 은 11-14 부터 노트3 주소
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
