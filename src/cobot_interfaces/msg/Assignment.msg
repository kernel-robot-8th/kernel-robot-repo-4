# Assignment.msg - 주문 1건의 로봇 배정 결과 (SR-03)
# 토픽: /control_center/assignments (설정성 QoS, TRANSIENT_LOCAL, 이름은 초안)
# 발행: fms_core. 구독: 게이트웨이.

string EXCLUSION_NONE="NONE"
string EXCLUSION_BATTERY_LE_20="BATTERY_LE_20"   # 배터리 20 % 이하 (SR-03)
string EXCLUSION_LINK_STALE="LINK_STALE"         # 통신 장애
string EXCLUSION_ERROR="ERROR"                   # 오류 상태

std_msgs/Header header
string order_id                    # 주문 ID
string task_id                     # 배정으로 생긴 작업 ID
string robot_id                    # 배정된 로봇. 아직 없으면 ""
builtin_interfaces/Time assigned_at  # 배정 시각
string[] excluded_robot_ids        # 배정에서 뺀 로봇
string[] exclusion_reasons         # 뺀 이유. excluded_robot_ids 와 같은 순서, 위 EXCLUSION_* 값
