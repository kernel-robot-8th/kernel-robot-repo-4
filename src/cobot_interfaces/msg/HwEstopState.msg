# HwEstopState.msg - HW E-STOP 릴레이 판독값 (SR-13)
# 토픽: /control_center/hw_estop (설정성 QoS, TRANSIENT_LOCAL)
# 발행: HW 판독 노드(estop_monitor) 하나. 구독: fms_core, 게이트웨이.
# 발행자가 없거나 1 s 넘게 갱신이 없으면 받는 쪽이 UNKNOWN 으로 본다. 절대 '정상' 으로 두지 않는다.
# 화면의 HW 배지는 이 메시지만으로 그린다. 소프트웨어 상태로 HW 상태를 추정하지 않는다.

string STATE_ENGAGED="ENGAGED"     # 릴레이가 모터 전원을 끊었다
string STATE_RELEASED="RELEASED"   # 릴레이 풀림
string STATE_UNKNOWN="UNKNOWN"     # 판독 불가

string SOURCE_NOT_INSTALLED="not_installed"

std_msgs/Header header             # stamp = 판독 시각
string state                       # 위 STATE_* 중 하나. 빈 문자열은 UNKNOWN
string source_device               # 판독 장치 ID 또는 "not_installed" (D6)
