# Waypoint.msg - 이름 붙은 지점 1개 (MapInfo.waypoints 의 원소)
# 작업점(work_pose)과 Nav2 정차점(approach_pose)을 나눈다 (D3 추천안).
# 작업점은 팔이 일하는 자리, 정차점은 Nav2 가 실제로 멈추는 자리다.
# 각도는 rad 다. 맵 YAML 이 deg 로 적었으면 읽을 때 바꾼다 (REP-103).

string waypoint_id                 # 이름 (예: WP_LOAD_1)
float64 work_x                     # [m] 작업점 x, map 프레임
float64 work_y                     # [m] 작업점 y
float64 work_yaw                   # [rad] 작업점 방향
float64 approach_x                 # [m] Nav2 정차점 x, map 프레임
float64 approach_y                 # [m] Nav2 정차점 y
float64 approach_yaw               # [rad] Nav2 정차점 방향
string arm_id                      # 이 지점에 연계된 팔 (출발 게이트용). 없으면 "" (초안)
