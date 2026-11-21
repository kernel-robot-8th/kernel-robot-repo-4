"""모델 자리 표. 필수 두 자리(핑키 상태, 상자)와 선택 한 자리(팔)를 한곳에서 정한다. 모델·네트워크를 쓰지 않는다.

- 팔 가중치 파일이 이미지에 없으면 자리는 두 개뿐이고 앱은 전과 똑같이 돈다.
- 자리마다 클래스 이름표가 정해져 있다. 이름표가 다른 모델은 시작 때 거부한다. 전에는 거부하지 않아서,
  1클래스 모델이 핑키 자리에 들어가면 모든 검출이 "적재"(클래스 0)로 읽히고 상자 자리에 들어가면 추락 감지가 꺼졌다.
- 팔 모델 결과는 새 주제(TOPIC_ARM)로만 낸다. 기존 주제(zones, boxes, status)의 내용은 바꾸지 않는다.
  팔 모델은 합성 사진만으로 배운 관찰용이다. 판정에 쓰지 않는다.
"""
import os

from config import ARM_MODEL, ARM_WEIGHT, EVIDENCE_CONF, WEIGHTS

EXPECTED_NAMES = {
    "pinky": {0: "pinky_loaded", 1: "pinky_empty"},
    "boxes": {0: "box_on_floor", 1: "box_perched_on_rim", 2: "box_run_over", 3: "lid_detached", 4: "box_on_tray", 5: "box_stock"},
    "arm": {0: "arm_over_pinky"},
}


def plan_slots(exists=os.path.isfile):
    """-> {자리: 가중치 경로}, 순서는 pinky, boxes, (arm). 필수 가중치가 없으면 ValueError."""
    for slot, path in WEIGHTS.items():
        if not exists(path):
            raise ValueError(f"required weights for slot '{slot}' not found: {path}")
    plan = dict(WEIGHTS)
    if exists(ARM_WEIGHT):
        plan["arm"] = ARM_WEIGHT
    return plan


def names_problem(slot, names):
    """모델 이름표가 그 자리의 이름표와 같으면 None, 다르면 사유 문자열."""
    want = EXPECTED_NAMES.get(slot)
    if want is None:
        return f"unknown model slot '{slot}'"
    try:
        got = {int(k): str(v) for k, v in dict(names).items()}
    except (TypeError, ValueError):
        return f"slot '{slot}': class names are not an id->name table: {names!r}"
    if got != want:
        return f"slot '{slot}': class names {got} differ from expected {want}"
    return None


def arm_may_publish(queue_len, queue_max):
    """발행 대기열이 절반 넘게 차 있으면 팔 메시지를 내지 않는다(대기열은 오래된 것부터 버리므로 zones·boxes 가 밀려난다)."""
    return queue_len * 2 < queue_max


def arm_message(dets, *, zone_of, stream_id, stream_epoch, frame_seq, capture_time, clock_error_sec, calibration_id, marker_state,
                device, frame_size, weights_sha256, limit=50):
    """팔 모델 검출 -> TOPIC_ARM 메시지. 문턱(EVIDENCE_CONF) 아래 검출은 뺀다."""
    keep = [d for d in dets if d["confidence"] >= EVIDENCE_CONF]
    items = [{"cls": d["cls"], "name": d["name"], "confidence": round(d["confidence"], 4),
              "bbox": [round(v, 1) for v in d["bbox"]], "zones": zone_of(d["bbox"])} for d in keep[:limit]]
    return {"source_kind": "model_output", "stream_id": stream_id, "stream_epoch": stream_epoch, "frame_seq": frame_seq,
            "capture_time": float(capture_time), "clock_error_sec": clock_error_sec, "calibration_id": calibration_id,
            "marker_state": marker_state, "device": device, "frame_size": list(frame_size), "conf_min": EVIDENCE_CONF,
            "arm_model": ARM_MODEL, "arm_weights_sha256": weights_sha256,
            "grade": "shadow_synthetic_only", "use_for_judgement": False,
            "arm": items, "truncated": max(0, len(keep) - limit)}
