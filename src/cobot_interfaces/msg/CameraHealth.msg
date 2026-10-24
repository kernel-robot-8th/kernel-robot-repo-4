# CameraHealth.msg - 카메라 1대의 신선도·동결 상태 (SR-07)
# 토픽: /vision/camera_health (텔레메트리 QoS), 카메라마다 1 Hz
# 발행: 비전 노드 하나. 구독: fms_core, 게이트웨이.
# age_basis 가 RECEIVE(또는 빈 문자열)인 카메라의 증거는 lease 해제·도착 판정에서 measured=false 로 다룬다.
# 한 토픽에 여러 카메라가 실리므로 구독 depth 는 카메라 수 이상으로 둔다 (초안).

string ROLE_OVERHEAD="OVERHEAD"
string ROLE_GATE="GATE"
string ROLE_DESK="DESK"
string ROLE_TTOP="TTOP"
string ROLE_TWRIST="TWRIST"
string ROLE_PINKY_FRONT="PINKY_FRONT"

string SOURCE_KIND_REAL="REAL"
string SOURCE_KIND_SIM="SIM"

string AGE_BASIS_CAPTURE="CAPTURE"   # 카메라 쪽 캡처 시각을 검증했다
string AGE_BASIS_RECEIVE="RECEIVE"   # 수신 시각 기준 (검증 안 됨)

std_msgs/Header header             # stamp = 보고 시각
string camera_id                   # 카메라 ID (예: cam_gate)
string role                        # 위 ROLE_* 중 하나
string source_kind                 # 위 SOURCE_KIND_* 중 하나. SIM 은 제어 경로에 섞지 않는다 (SR-07)
builtin_interfaces/Time last_capture_stamp  # 마지막 프레임의 캡처(또는 수신) 시각
float32 frame_age_ms               # [ms] 마지막 프레임 나이. NaN = 프레임 없음
string age_basis                   # 위 AGE_BASIS_* 중 하나
float32 fps_measured               # [Hz] 실측 프레임률
bool frozen                        # 같은 프레임 해시가 N 회 반복됨
uint32 width                       # [px] 프레임 너비
uint32 height                      # [px] 프레임 높이
