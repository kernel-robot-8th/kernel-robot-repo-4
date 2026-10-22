# RobotStatus.msg (v2) - 핑키 1대의 상태
# 토픽: /navigation/<robot_id>/status (텔레메트리 QoS), 10 Hz
# 발행: 핑키 온보드 가드 하나. 구독: fms_core, 게이트웨이, fleet_monitor.
# v1 에서 바뀐 것: timestamp -> header, robot_boot_id·펜싱 반향·전원 증거·속도 등 추가.
# 링크 판정은 pose 가 아니라 이 메시지의 수신 간격과 하트비트 반향으로 한다.
# state 가 빈 문자열이면 '모름' 으로 다룬다.

string STATE_IDLE="IDLE"
string STATE_NAVIGATING="NAVIGATING"
string STATE_LOADING="LOADING"
string STATE_UNLOADING="UNLOADING"
string STATE_PAUSED="PAUSED"           # 원격 일시정지. 현재 epoch 의 last_goal 보존. 해제는 서명된 RESUME
string STATE_HOLD="HOLD"               # 로컬 안전 사유 정지. 사유는 hold_reason
string STATE_DISARMED="DISARMED"       # 안전 대기. last_goal 없음. 해제는 새 epoch 의 서명된 START
string STATE_SOFT_LATCH="SOFT_LATCH"   # 소프트 정지 래치. RESET -> DISARMED
string STATE_LINK_LOST="LINK_LOST"     # 워치독 만료 래치. 하트비트 재개는 해제가 아니다
string STATE_RECOVERING="RECOVERING"   # v1 값. SR-17 회수용으로 남긴다 (MVP 미사용)
string STATE_ERROR="ERROR"

string HOLD_REASON_WATCHDOG="WATCHDOG"                    # 하트비트 200 ms 넘게 끊김 (SR-14). '유효' 조건은 설계 초안
string HOLD_REASON_EXTERNAL_NAV_GOAL="EXTERNAL_NAV_GOAL"  # 가드가 아닌 Nav2 goal 발견 (SR-19)
string HOLD_REASON_PROXIMITY="PROXIMITY"                  # 근접 정지 (SR-11). 초안, 주행 담당이 더한다

std_msgs/Header header             # stamp = 측정 시각 (로봇 시계). frame_id = "map"
string robot_id                    # pinky_1~3
string robot_boot_id               # 부팅(가드 기동)마다 새 값. 바뀌면 fms_core 가 대상을 UNKNOWN 으로 둔다
string state                       # 위 STATE_* 중 하나
geometry_msgs/Pose current_pose    # [m],[rad] map 프레임
bool localized                     # AMCL 위치 추정이 유효한가
float32 linear_vel                 # [m/s] 엔코더 기준
float32 angular_vel                # [rad/s] 엔코더 기준
uint8 nav_status                   # [-] Nav2 goal 상태. action_msgs/GoalStatus 의 STATUS_* 값을 쓴다 (초안)
float32 battery_percentage         # [%] 0~100. NaN = 미계측 (0 으로 채우지 않는다)
bool is_emergency_stopped          # v1 호환 필드. 새 코드는 state·motor_power_present 를 본다
bool motor_power_present           # 모터 전원 증거. false 또는 복귀 edge 면 가드가 DISARMED 래치. 측정 수단은 D6
bool base_hold_engaged             # 바퀴 잠금 체결 여부 (SR-08). 상태가 아니며 여러 상태에서 true 일 수 있다
string hold_reason                 # 위 HOLD_REASON_* 또는 "". STATE_HOLD·LINK_LOST 때 채운다
string current_task_id             # 진행 중 작업 ID. 없으면 ""
uint32 epoch_accepted              # [-] 가드가 받아들인 epoch. 0 = 아직 없음
uint64 last_seq_accepted           # [-] 마지막으로 수락한 명령 seq
uint64 last_heartbeat_seq          # [-] 마지막 유효 하트비트의 hb_seq 반향 (링크 RTT 상한 계산용)
uint32 last_heartbeat_rx_age_ms    # [ms] 마지막 유효 하트비트 뒤 경과 시간
string map_hash_loaded             # 로드한 맵의 sha256 16진 문자열 (D3)
float32 dock_err_xy                # [m] 1차 정차 오차 (SR-08). NaN = 미측정
float32 dock_err_yaw               # [rad] 1차 정차 각도 오차. NaN = 미측정
float32 dock_err_aruco_mm          # [mm] ArUco 최종 정합 오차. NaN = 미측정
bool clock_offset_known            # false 면 clock_offset_ms 는 의미 없음 (= 시계 모름)
int32 clock_offset_ms              # [ms] chrony 가 보고한 시계 오프셋
uint8 nav2_action_clients          # [개] 도메인 12 의 navigate_to_pose 클라이언트 수. 1(가드) 이 정상
