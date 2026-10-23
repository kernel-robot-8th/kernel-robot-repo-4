# ArmMode.msg - 팔 버스를 지금 누가 쓰는가 (모드 표지)
# 토픽: /manipulation/<arm_id>/mode (설정성 QoS, TRANSIENT_LOCAL). 변화 즉시 + 1 Hz
# 발행: Station PC 의 요약 노드 하나. 모드는 잠금 파일로만 판정한다. 읽을 수 없으면 MODE_UNKNOWN.
# LEROBOT_EXCLUSIVE 동안에는 FMS 정지가 팔에 닿지 않는다 (SR-12 미이행, 12 V 차단만 유효).

string MODE_ROS_MANAGED="ROS_MANAGED"
string MODE_LEROBOT_EXCLUSIVE="LEROBOT_EXCLUSIVE"
string MODE_OFFLINE="OFFLINE"
string MODE_UNKNOWN="UNKNOWN"

std_msgs/Header header             # stamp = 판정 시각
string arm_id                      # omx_1~3
string mode                        # 위 MODE_* 중 하나. 빈 문자열은 MODE_UNKNOWN 으로 다룬다
string source                      # 판정 근거 (잠금 파일 경로와 sha256). 장치 경로·홈 경로는 넣지 않는다
