# AlarmEvent.msg - 알림 1건 (SR-15)
# 토픽: /control_center/alarms (이벤트 QoS). 생길 때·풀릴 때마다 낸다.
# 발행: fms_core, fleet_monitor. 구독: 게이트웨이.
# severity 가 빈 문자열이면 화면은 RED 로 그린다 (모르는 경보를 가볍게 보이지 않게).
# code 목록은 설계 초안이다. 새 코드는 이 파일 PR 로 더한다.

string SEVERITY_INFO="INFO"
string SEVERITY_AMBER="AMBER"
string SEVERITY_RED="RED"

string CODE_LINK_LOSS="LINK_LOSS"
string CODE_CAMERA_STALE="CAMERA_STALE"
string CODE_CAMERA_FROZEN="CAMERA_FROZEN"
string CODE_UNKNOWN_BLOCKED="UNKNOWN_BLOCKED"
string CODE_RETRY_EXCEEDED="RETRY_EXCEEDED"
string CODE_QR_MISMATCH="QR_MISMATCH"
string CODE_HUMAN_IN_ZONE="HUMAN_IN_ZONE"
string CODE_CLOCK_OFFSET="CLOCK_OFFSET"
string CODE_SINGLE_WRITER_VIOLATION="SINGLE_WRITER_VIOLATION"
string CODE_NO_COMMAND_PUBLISHER="NO_COMMAND_PUBLISHER"
string CODE_ACK_WITHOUT_PHYSICAL="ACK_WITHOUT_PHYSICAL"
string CODE_MAP_HASH_MISMATCH="MAP_HASH_MISMATCH"
string CODE_LEDGER_UNAVAILABLE="LEDGER_UNAVAILABLE"
string CODE_POWER_LOST="POWER_LOST"
string CODE_ARM_INTERLOCK="ARM_INTERLOCK"
string CODE_INVENTORY_SHORTAGE="INVENTORY_SHORTAGE"

std_msgs/Header header
string alarm_id                    # 알림 ID (UUIDv4)
string severity                    # 위 SEVERITY_* 중 하나
string code                        # 위 CODE_* 중 하나
string target_id                   # 대상: pinky_1, omx_2, cam_gate, CORRIDOR_MAIN ...
builtin_interfaces/Time raised_at  # 생긴 시각
builtin_interfaces/Time cleared_at # 풀린 시각. active 가 true 면 의미 없음
bool active                        # 아직 풀리지 않았는가
bool requires_reconcile            # 풀려면 Reconcile 이 필요한가 (SR-14)
string detail                      # 사람이 읽는 설명. 비밀값·주소·사람 이름을 넣지 않는다
