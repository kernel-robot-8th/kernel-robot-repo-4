# FmsHeartbeat.msg - 관제 코어 -> 대상 1대 생존 신호
# 토픽: /control_center/<id>/heartbeat (하트비트 QoS). 20 Hz 는 제안값이고 아직 재지 않았다 (D11).
# 명령과 번호 공간을 나눈다 (hb_seq 는 명령 seq 와 다르다).
# 하트비트는 대상 상태를 낮추기만 한다. fleet_mode 가 MODE_RUN 으로 돌아와도 자동 재개는 없다.
# 하트비트가 200 ms 넘게 끊기면 로봇 로컬 워치독이 스스로 정지한다 (SR-14).
# 워치독은 '유효한' 하트비트로만 갱신한다: 서명 일치, epoch 일치, hb_seq 증가, map_hash 일치,
# issued_at + ttl_ms 이전 (유효 조건은 설계 초안, 서명은 D13). 높은 epoch 는 통지일 뿐 채택하지 않는다.

uint8 MODE_RUN=0                   # 제한 없음
uint8 MODE_PAUSE=1                 # 일시정지
uint8 MODE_SOFT_LATCH=2            # 소프트 정지 래치 (전원 차단 아님)
uint8 MODE_DISARMED=3              # 안전 대기. HW 전원 상실(HwEstopState ENGAGED 또는 motor_power_present=false)도 이 값

string robot_id                    # 대상: pinky_1~3 | omx_1~3
uint32 epoch                       # [-] 대상별 세션 번호
uint64 hb_seq                      # [-] 하트비트 전용 단조 번호 (명령 seq 와 다른 공간)
builtin_interfaces/Time issued_at  # 발행 시각. 중앙 FMS PC 시계
uint32 ttl_ms                      # [ms] 하트비트 유효 기한. 기본 200 제안 (D11)
string map_hash                    # sha256 16진 문자열 64자 (D3)
uint8 fleet_mode                   # [-] 위 MODE_* 중 하나. 낮추기 전용
string lane_lease_id               # 통로 허가 ID. 없으면 ""
builtin_interfaces/Time lease_valid_until  # 통로 허가 만료 시각 (TTL 5000 ms, SR-05). 하트비트로 갱신하는 것은 설계 초안
uint64 last_cmd_seq_issued         # [-] 진단용. 이 대상에 마지막으로 낸 명령 seq (명령 유실 감지)
string key_id                      # 서명 키 식별자 (D13)
string sig                         # HMAC-SHA256. 서명이 맞지 않으면 워치독을 갱신하지 않는다 (D13)
