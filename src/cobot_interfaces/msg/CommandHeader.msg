# CommandHeader.msg - 로봇·팔에 가는 모든 명령의 공통 머리 (세션 펜싱·서명)
# 실리는 곳: FleetCommand, ArmCommand, HandoverTask Goal.
# 만드는 쪽: 관제 코어(fms_core) 하나뿐이다. 검증: 핑키 온보드 가드, 팔 노드.
# 펜싱 값(epoch, seq, map_hash)은 상태 토픽으로 공개된다. 그래서 펜싱은 인증이 아니다.
# 명령의 출처를 증명하는 것은 sig 하나다 (설계 초안, D13). SR-20 이 요구하는 검증은 epoch·seq·TTL·map_hash 다.
# 기본값을 두지 않는다. 비어 있는 헤더(ttl_ms 0, sig "")는 검증에서 거부된다.

string command_id                  # UUIDv4. 명령마다 새 값
string tx_id                       # 트랜잭션 ID. 원장 역추적용 (SR-21)
string order_id                    # 주문 ID. 없으면 ""
string task_id                     # 작업 ID (SR-21)
string robot_id                    # 명령을 받는 대상: pinky_1~3 | omx_1~3
uint32 epoch                       # [-] 대상별 세션 번호. fms_core 가 영속한다. 1 부터 쓴다 (초안)
uint64 seq                         # [-] 대상별·epoch 안에서 단조 증가. 명령 전용 번호 공간
builtin_interfaces/Time issued_at  # 발행 시각. 중앙 FMS PC 시계 (chrony 기준)
uint32 ttl_ms                      # [ms] 유효 기한. 5000 고정 (SR-20). 0 이면 바로 만료
string map_hash                    # sha256 16진 문자열 64자. 계산법은 맵 계약(D3)을 따른다
string issued_by                   # 발행자 이름. "control_center"
string key_id                      # 서명 키 식별자 (대상별 키, D13)
string sig                         # HMAC-SHA256(대상별 키, 헤더 + 본문 정규화). S3(P2) 필수 (D13)
