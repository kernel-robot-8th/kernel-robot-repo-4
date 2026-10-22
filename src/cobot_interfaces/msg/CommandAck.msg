# CommandAck.msg - 명령 수신·판정 결과 (받았다는 뜻일 뿐, 물리 완료가 아니다. SR-21)
# 토픽: /navigation/<robot_id>/command_ack, /manipulation/<arm_id>/command_ack (이벤트 QoS)
# 발행: 핑키 온보드 가드, 팔 노드. 구독: fms_core (원장 기록), 게이트웨이 (표시).
# 물리 완료는 CompletionEvidence 로 따로 온다.
# 주의: 결과 번호는 설계 초안 그대로 ACCEPTED=0 이다. 기본값이 '수락' 이므로 만드는 쪽은 result 를 반드시 채운다.

uint8 ACCEPTED=0
uint8 REJECTED_EPOCH=1             # epoch 가 받아들인 값보다 낮음
uint8 REJECTED_SEQ=2               # seq 가 마지막 수락 seq 이하
uint8 REJECTED_TTL=3               # issued_at + ttl_ms 지남
uint8 REJECTED_MAP_HASH=4          # 이동 계열인데 로드한 맵과 해시가 다름
uint8 REJECTED_STATE=5             # 지금 상태에서 허용하지 않음 (예: DISARMED 에서 RESUME)
uint8 REJECTED_ROBOT_ID=6          # 대상이 자신이 아님
uint8 REJECTED_CLOCK_UNSYNCED=7    # 시계 오프셋을 모르거나 허용치 초과 (구동 명령만)
uint8 REJECTED_SIGNATURE=8         # 서명 불일치

string command_id                  # 원인 명령의 header.command_id
string robot_id                    # 판정한 대상: pinky_1~3 | omx_1~3
uint32 epoch                       # [-] 원인 명령의 header.epoch
uint64 seq                         # [-] 원인 명령의 header.seq
uint8 result                       # [-] 위 ACCEPTED / REJECTED_* 중 하나
bool stop_executed                 # 정지 계열은 판정이 거부여도 정지했으면 true (D4, 초안)
string reason                      # 사람이 읽는 사유. 비밀값·주소를 넣지 않는다
uint32 rx_to_ack_ms                # [ms] 로봇 로컬 단조 시계로 잰 수신~ACK 체류 시간
builtin_interfaces/Time robot_rx_stamp  # 로봇 시계의 수신 시각 (진단용)
