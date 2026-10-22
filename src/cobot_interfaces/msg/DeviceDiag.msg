# DeviceDiag.msg - 장비 1대의 링크 진단 (DiagSnapshot.devices 의 원소)

int16 DOMAIN_ID_NOT_REPORTED=-1    # 자기 보고 없음 = 다른 도메인이거나 미기동

string device_id                   # 장비 ID (예: pinky_1, station_1)
string ip                          # 장비 주소 문자열. 레포의 예시·설정에는 실주소를 쓰지 않는다
float32 link_rtt_ms                # [ms] 링크 왕복 시간 (단일 시계). NaN = 미측정
uint32 last_seen_age_ms            # [ms] 마지막으로 본 뒤 경과 시간
int16 ros_domain_id_reported       # [-] 장비가 스스로 보고한 ROS_DOMAIN_ID. 없으면 DOMAIN_ID_NOT_REPORTED
