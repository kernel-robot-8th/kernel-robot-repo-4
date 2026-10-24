# ArmCommand.msg - 관제 코어 -> 팔 1대 명령
# 토픽: /control_center/<arm_id>/command (명령 QoS). 발행자는 fms_core 하나뿐이다.
# 팔 모션은 FMS 가 시작하지 않는다. 모션은 D7 이 FMS_TRIGGER 일 때만 HandoverTask 로 한다.
# 검증: 팔 노드가 header 를 판정한다 (SR-20). 정지 계열(HOLD, SOFT_LATCH)은 거부여도 정지한다.
# 기본값 0 은 CMD_HOLD(멈춤)다. 일부러 가장 안전한 값을 0 에 두었다 (초안).

uint8 CMD_HOLD=0                   # 팔 정지 유지
uint8 CMD_RELEASE_HOLD=1           # HOLD 해제 (모션 시작은 아님)
uint8 CMD_RESET=2                  # 래치 -> DISARMED. 구동 없음
uint8 CMD_START=3                  # DISARMED -> 가동. 새 epoch 에서만
uint8 CMD_SOFT_LATCH=4             # 소프트 정지 래치 (전원 차단 아님). RESET 으로만 해제

CommandHeader header               # 세션 펜싱 (SR-20)·서명 (D13, 설계 초안). header.robot_id = arm_id
uint8 command                      # [-] 위 CMD_* 중 하나
