# AuditEvent.msg - 감사 원장 행 1개 (QueryAudit 응답의 원소, SR-21)
# 원장은 fms_core 하나가 쓴다. 이 메시지는 읽기용 사본이다.
# 초안: 설계서의 QueryAudit events[] 를 담으려고 더한 원소 메시지다.

uint64 seq                         # [-] 원장 행 번호 (64-bit 단조 증가)
string event_id                    # UUIDv4
string event_type                  # 이벤트 유형 (예: COMMAND_ISSUED)
uint32 schema_version              # [-] 원장 스키마 버전
builtin_interfaces/Time ts_fms     # 기록 시각 (중앙 FMS PC 시계)
bool has_ts_source                 # false 면 ts_source 는 의미 없음
builtin_interfaces/Time ts_source  # 원천 측정 시각
string source_host                 # 기록을 낸 장비 ID
string source_node                 # 기록을 낸 노드
string target_id                   # 대상. 없으면 ""
uint32 epoch                       # [-] 관련 epoch. 0 = 없음
uint64 cmd_seq                     # [-] 관련 명령 seq. 0 = 없음
string order_id                    # 없으면 ""
string task_id                     # 없으면 ""
string command_id                  # 없으면 ""
string tx_id                       # 없으면 ""
string actor_role                  # customer | staff | operator | system
string actor_id                    # 계정 ID (사람 이름 아님)
string payload_json                # 이벤트 본문 JSON
bool simulated                     # true 면 실물이 아니다
string prev_hash                   # 앞 행의 row_hash
string row_hash                    # sha256(prev_hash 와 정규화한 행)
