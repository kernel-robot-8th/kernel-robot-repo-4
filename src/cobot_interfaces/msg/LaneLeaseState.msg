# LaneLeaseState.msg - 단일 통로(0.8 m) 점유 허가 상태 (SR-05)
# 토픽: /control_center/lane_lease (설정성 QoS, TRANSIENT_LOCAL). 변화 즉시
# 발행: fms_core 하나. 구독: 게이트웨이, 가드(참고용).
# 통신 단절·시간 초과·카메라 판정 없음이면 FREE 가 아니라 UNKNOWN_BLOCKED 다. 자동 해제는 없다.
# 해제 근거는 TAIL_EXIT_CONFIRMED 증거(measured=true) 하나뿐이다.
# state 가 빈 문자열이면 UNKNOWN_BLOCKED 로 다룬다.

string STATE_FREE="FREE"
string STATE_HELD="HELD"
string STATE_RELEASE_PENDING_TAIL_EXIT="RELEASE_PENDING_TAIL_EXIT"
string STATE_UNKNOWN_BLOCKED="UNKNOWN_BLOCKED"

std_msgs/Header header
string lane_id                     # 통로 ID. MVP 는 "CORRIDOR_MAIN" 하나 (초안)
string state                       # 위 STATE_* 중 하나
string holder_robot_id             # 허가를 가진 로봇. 없으면 ""
string lease_id                    # 허가 ID. FleetCommand.lane_lease_id 와 같은 값
uint32 epoch                       # [-] 허가를 받은 로봇의 epoch
builtin_interfaces/Time granted_at   # 허가 시각
builtin_interfaces/Time valid_until  # 만료 시각 (TTL 5000 ms, SR-05)
string[] waiting_robot_ids         # 대기 중인 로봇 (먼저 온 순서)
bool exit_space_ok                 # 진입 전 출구 공간 확인 결과 (데드락 방지)
string tail_exit_evidence_id       # 해제 근거 CompletionEvidence.evidence_id. 없으면 ""
