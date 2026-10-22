# FleetCommand.msg (v2) - 관제 코어 -> 핑키 1대 명령
# 원저작: team11 pinky_fleet_msgs FleetCommand.msg (Apache-2.0). NOTICE 참고.
# 토픽: /control_center/<robot_id>/command (명령 QoS). 발행자는 fms_core 하나뿐이다.
# 검증: 핑키 온보드 가드가 header 를 판정한다 (SR-20). 판정 순서는 docs/fms_interfaces.md.
# 정지 계열(STOP, CANCEL, SOFT_LATCH)은 판정이 거부여도 정지는 수행한다 (D4 추천안, 초안).
# 주의: 명령 번호는 v1 과 같게 두었다. 그래서 기본값 0 이 CMD_GOTO 다.
#       빈 메시지는 서명(header.sig)이 없어 거부되지만, 만드는 쪽은 command 를 반드시 채운다.

uint8 CMD_GOTO=0              # 이동. fms_core 가 waypoint_id 에서 바꾼 좌표만. 공통 출발 게이트 통과 뒤에만 발행
uint8 CMD_STOP=1              # goal 취소 + PAUSED. last_goal 을 발행 epoch 와 함께 보존 (= PAUSE)
uint8 CMD_RESUME=2            # PAUSED 해제 전용. 현재 epoch 의 last_goal 이 있을 때만 재전송
uint8 CMD_CANCEL=3            # goal 취소 + last_goal 폐기
uint8 CMD_SET_INITIAL_POSE=4  # x, y, yaw 로 initialpose 발행 (AMCL 재초기화)
uint8 CMD_SET_SPEED=5         # 속도 제한 변경. MVP 미사용
uint8 CMD_SET_MAP=6           # map_name 으로 맵 교체. MVP 미사용
uint8 CMD_HEARTBEAT=7         # 번호만 남김. v1 뜻(수신 시각 갱신)은 폐기. v2 가드는 무시하고 워치독을 갱신하지 않는다
uint8 CMD_RESET=8             # 래치 -> DISARMED. 구동 없음. last_goal 폐기
uint8 CMD_START=9             # DISARMED -> 가동. 새 epoch 에서만. last_goal 없이 시작
uint8 CMD_SOFT_LATCH=10       # 로봇 쪽 소프트 정지 래치(전원 차단 아님). RESET 으로만 해제. last_goal 폐기

CommandHeader header          # 세션 펜싱 (SR-20)·서명 (D13, 설계 초안)
uint8 command                 # [-] 위 CMD_* 중 하나

float64 x                     # [m] map 프레임. CMD_GOTO, CMD_SET_INITIAL_POSE
float64 y                     # [m] map 프레임
float64 yaw                   # [rad] map 프레임
float64 max_linear_vel        # [m/s] CMD_SET_SPEED
float64 max_angular_vel       # [rad/s] CMD_SET_SPEED
string waypoint_id            # 맵 YAML 의 웨이포인트 이름 (표시·감사용)
string lane_lease_id          # 통로 진입 허가 ID (SR-05). 없으면 ""
builtin_interfaces/Time lease_valid_until  # 통로 허가 만료 시각
string map_name               # 확장자 없는 맵 이름. CMD_SET_MAP
