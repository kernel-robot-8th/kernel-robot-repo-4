# FleetSafetyState.msg - 플릿 전체의 안전·제어권 상태
# 토픽: /control_center/safety_state (설정성 QoS, TRANSIENT_LOCAL). 변화 즉시 + 2 Hz
# 발행: fms_core 하나. 구독: 게이트웨이.
# 'ESTOP' 이름은 HW 릴레이 전용이다. 소프트웨어 정지는 SOFT_LATCH 계열 이름만 쓴다.
# run_state(소프트웨어 축)와 hw_estop(HW 축)은 따로 본다. 빈 문자열은 '모름' 이다.

string SYSTEM_MODE_AUTO="AUTO"
string SYSTEM_MODE_MANUAL="MANUAL"

string RUN_STATE_DISARMED="DISARMED"
string RUN_STATE_RECONCILING="RECONCILING"
string RUN_STATE_APPROVED="APPROVED"
string RUN_STATE_RUNNING="RUNNING"
string RUN_STATE_PAUSED="PAUSED"
string RUN_STATE_SOFT_LATCH="SOFT_LATCH"

string HW_ESTOP_ENGAGED="ENGAGED"
string HW_ESTOP_RELEASED="RELEASED"
string HW_ESTOP_UNKNOWN="UNKNOWN"
string HW_ESTOP_SOURCE_NOT_INSTALLED="not_installed"

std_msgs/Header header
string system_mode                 # 위 SYSTEM_MODE_* 중 하나
string run_state                   # 위 RUN_STATE_* 중 하나 (소프트웨어 축)
string hw_estop                    # 위 HW_ESTOP_* 중 하나 (HW 축, run_state 와 별도)
string hw_estop_source             # 판독 장치 ID 또는 "not_installed"
builtin_interfaces/Time hw_estop_stamp  # HW 축 값의 판독 시각
string[] power_lost_targets        # motor_power_present=false 또는 전원 복귀 edge 를 보고한 대상
string[] latched_targets           # 소프트 정지 래치가 걸린 대상
string[] epoch_targets             # epochs 와 같은 순서의 대상 ID
uint32[] epochs                    # [-] 대상별 현재 epoch. epoch_targets 와 같은 순서
string console_holder_id           # 콘솔 보유 계정 ID (사람 이름 아님). 없으면 ""
string console_holder_role         # customer | staff | operator
builtin_interfaces/Time console_expires_at  # 콘솔 만료 시각
string pending_approval_ref        # 승인 대기 참조: report_hash 또는 challenge_id
string[] allowed_actions           # 지금 상태에서 허용되는 동작. 게이트웨이가 세션 역할로 한 번 더 거른다
