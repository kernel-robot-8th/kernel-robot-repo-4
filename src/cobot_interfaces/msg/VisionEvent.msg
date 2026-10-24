# VisionEvent.msg - 비전 인식 이벤트 1건 (SR-07)
# 토픽: /vision/events (이벤트 QoS)
# 발행: 비전 노드. 구독: fms_core, 게이트웨이.
# capture_stamp 는 수신 시각이 아니라 캡처 시각이다. 검증하지 못했으면 age_basis 를 RECEIVE 로 둔다.

string KIND_PERSON_IN_ZONE="PERSON_IN_ZONE"
string KIND_QR_MATCH="QR_MATCH"
string KIND_QR_MISMATCH="QR_MISMATCH"
string KIND_TAIL_EXIT="TAIL_EXIT"
string KIND_DROP="DROP"

string AGE_BASIS_CAPTURE="CAPTURE"
string AGE_BASIS_RECEIVE="RECEIVE"

string event_id                    # UUIDv4 (초안: 증거로 가리키려고 더했다)
string kind                        # 위 KIND_* 중 하나
string camera_id                   # 카메라 ID
builtin_interfaces/Time capture_stamp  # 캡처 시각 (수신 시각 아님)
string age_basis                   # 위 AGE_BASIS_* 중 하나. 빈 문자열은 RECEIVE 로 다룬다 (초안)
string zone_id                     # 구역 ID. 없으면 ""
string robot_id                    # 관련 로봇. 없으면 ""
float32 confidence                 # [0~1] 인식 신뢰도
