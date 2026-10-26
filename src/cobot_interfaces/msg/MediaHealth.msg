# MediaHealth.msg - 시청용 미디어 서버(MediaMTX) 경로 1개의 상태
# 토픽: /control_center/media_health (텔레메트리 QoS), 경로마다 1 Hz
# 발행: fleet_monitor. 구독: 게이트웨이.
# 시청 품질 표시용이다. 안전 증거가 아니다. 경로가 열려 있다는 것만으로 정상이라 하지 않는다.

string FROZEN_STATE_LIVE="LIVE"
string FROZEN_STATE_FROZEN="FROZEN"
string FROZEN_STATE_UNKNOWN="UNKNOWN"   # 프레임 해시를 볼 수 없음

std_msgs/Header header             # stamp = 보고 시각
string path                        # 미디어 서버 경로 이름 (예: cam_desk)
bool publisher_online              # 송출자가 붙어 있는가
float32 bytes_rx_rate              # [B/s] 받은 바이트율
string frozen_state                # 위 FROZEN_STATE_* 중 하나. 빈 문자열은 UNKNOWN
