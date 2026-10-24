# DiagSnapshot.msg - 통신·노드 진단 묶음 (SR-06, SR-19)
# 토픽: /control_center/diag (진단 QoS: RELIABLE, VOLATILE, KEEP_LAST 1, 초안), 0.5 Hz
# 발행: fleet_monitor. 구독: 게이트웨이.
# 다른 도메인의 참가자는 ROS API 로 보이지 않는다. 그래서 도메인은 장비별 자기 보고만 싣는다.

std_msgs/Header header
DeviceDiag[] devices               # 장비별 링크 상태
TopicDiag[] topics                 # 토픽별 발행자 수·유량
NodeDiag[] nodes                   # 노드·서비스 왕복
int16 ros_domain_id_configured     # [-] fleet_monitor 자신의 ROS_DOMAIN_ID. DeviceDiag.ros_domain_id_reported 와 같은 타입 (-1 = 모름)
float32 chrony_offset_ms           # [ms] 중앙 PC 의 chrony 오프셋. NaN = 모름
