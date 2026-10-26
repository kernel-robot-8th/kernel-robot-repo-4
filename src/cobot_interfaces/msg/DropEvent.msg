# DropEvent.msg - 경로상 물품 낙하 감지 이벤트 메시지
# fleet_msgs 에서 그대로 옮겼다 (단위 주석만 더함). PRD_v2 어휘(밀대·포켓)가 남아 있다.
# SR-17 단계에서 PRD_3 어휘로 재정의 예정. MVP 에서는 쓰지 않는다.
builtin_interfaces/Time timestamp
string detected_by               # "overhead_cam" or "pinky_cam"
uint32 incident_id               # [-] 고유 사고 식별자
geometry_msgs/Point location     # [m] 글로벌 맵 기준 x, y 좌표
string item_type                 # "disc_puffed_rice", "sphere", "vinyl_box"
float32 confidence               # [0~1] 비전 인식 신뢰도 (0.0 ~ 1.0)
string lane_segment_id           # 사고가 발생한 차선 구역 ID (예: "LANE_SOUTH_1")
