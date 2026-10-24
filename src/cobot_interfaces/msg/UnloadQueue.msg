# UnloadQueue.msg - 매장 하차 대기열 (SR-16)
# 토픽: /control_center/unload_queue (설정성 QoS, TRANSIENT_LOCAL, 이름은 초안)
# 발행: fms_core. 구독: 게이트웨이.

std_msgs/Header header
string waypoint_id                 # 하차 지점 (예: WP_UNLOAD)
string[] robot_ids                 # 도착 순서 (FIFO). 맨 앞이 지금 하차하는 로봇
