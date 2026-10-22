# ArmStatus.msg - OMX 팔 1대의 상태
# 토픽: /manipulation/<arm_id>/status (텔레메트리 QoS), 10 Hz
# 발행: Station PC 의 팔 노드(ROS 모드) 하나뿐이다. LeRobot 단독 모드에서는 그 노드가 종료돼
# 발행이 없다. 그러면 화면은 STALE, 출발 게이트는 retract_safe 미계측으로 막힌다.
# 문자열 열거가 빈 문자열이면 '모름' 으로 다룬다.

string JOINT_UNIT_RAD="RAD"
string JOINT_UNIT_NORMALIZED_0_4095="NORMALIZED_0_4095"

string WORK_STEP_IDLE="IDLE"
string WORK_STEP_APPROACHING="APPROACHING"
string WORK_STEP_VISION_ALIGNING="VISION_ALIGNING"
string WORK_STEP_GRASPING="GRASPING"
string WORK_STEP_PLACING="PLACING"
string WORK_STEP_RETRACTING="RETRACTING"
string WORK_STEP_VERIFYING="VERIFYING"
string WORK_STEP_DONE="DONE"       # 초안. 'VERIFYING 이후' 를 나타내려고 더했다

std_msgs/Header header             # stamp = 측정 시각 (Station PC 시계)
string arm_id                      # omx_1~3
string robot_boot_id               # 팔 노드 기동마다 새 값
string joint_unit                  # 위 JOINT_UNIT_* 중 하나. 보정 파일이 없으면 3D 자세를 계산하지 않는다
string[] joint_names               # joint_positions 와 같은 순서
float64[] joint_positions          # [joint_unit] 관절 위치
float64 gripper_position           # [joint_unit] 그리퍼 위치
float32[] present_current_ma       # [mA] 관절별 전류. 미지원 축은 NaN
bool torque_enabled                # 토크 켜짐
bool retract_safe                  # 퇴피 완료 Z >= 280 mm (SR-10)
bool retract_safe_measured         # retract_safe 를 실제로 쟀는가. false 는 PASS 가 아니다 (초안)
bool hold_active                   # 사람 진입 HOLD 중 (SR-12)
string hold_reason                 # HOLD 사유. 없으면 ""
bool power_present                 # 팔 전원(12 V) 증거. 측정 수단은 D6
uint32 epoch_accepted              # [-] 팔 노드가 받아들인 epoch. 0 = 아직 없음
uint64 last_seq_accepted           # [-] 마지막으로 수락한 ArmCommand seq (초안)
string work_step                   # 위 WORK_STEP_* 중 하나. MANUAL_START 때 로컬 작업 단계 (D7)
