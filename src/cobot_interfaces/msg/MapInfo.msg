# MapInfo.msg - 지금 쓰는 맵과 웨이포인트 (SR-04, SR-08, D3)
# 토픽: /control_center/map_info (설정성 QoS, TRANSIENT_LOCAL)
# 발행: fms_core. 구독: 게이트웨이, 가드.
# 맵 정본·map_hash 계산법·웨이포인트 값은 맵 계약(D3)이 정본이다. 이 메시지는 그 값을 나른다.

std_msgs/Header header
string map_name                    # 확장자 없는 맵 이름 (예: map_shoe_store_flat)
string map_hash                    # sha256 16진 문자열 64자 (D3)
float64 resolution                 # [m/px] 칸 크기
float64 origin_x                   # [m] 맵 원점 x (맵 YAML origin)
float64 origin_y                   # [m] 맵 원점 y
float64 origin_yaw                 # [rad] 맵 원점 회전
uint32 width                       # [px] 맵 너비
uint32 height                      # [px] 맵 높이
Waypoint[] waypoints               # 이름 붙은 지점
