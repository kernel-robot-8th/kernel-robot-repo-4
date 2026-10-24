# OrderStatus.msg - 주문 1건의 진행 상태 (SR-01, SR-18)
# 토픽: /control_center/orders (설정성 QoS, TRANSIENT_LOCAL). 바뀔 때마다 그 주문 1건을 낸다.
# 늦게 붙은 구독자가 주문 전체를 받는 방법(depth 또는 조회 서비스)은 S2 에서 정한다 (초안).
# SR 이 정한 단계 이름은 ASSIGNED·COMPLETED 뿐이다. 나머지 이름은 제안이다 (D14).
# stage 가 빈 문자열이면 '모름' 이다.

string STAGE_RECEIVED="RECEIVED"
string STAGE_ASSIGNED="ASSIGNED"
string STAGE_LOADING="LOADING"
string STAGE_IN_TRANSIT="IN_TRANSIT"
string STAGE_UNLOADING="UNLOADING"
string STAGE_HANDOVER_CONFIRMED="HANDOVER_CONFIRMED"
string STAGE_RETURNING="RETURNING"
string STAGE_COMPLETED="COMPLETED"
string STAGE_FAILED="FAILED"
string STAGE_CANCELLED="CANCELLED"

std_msgs/Header header
string order_id                    # 주문 ID
string sku                         # 신발 종류
uint32 qty                         # [개] 주문 수량
string table_id                    # 배송할 매장 테이블 위치
string stage                       # 위 STAGE_* 중 하나 (지금 단계)
string[] stage_history             # 지나온 단계. stage_entered_at 과 같은 순서
builtin_interfaces/Time[] stage_entered_at  # 각 단계에 들어간 시각
string failure_reason              # 실패 원인. 없으면 ""
uint32 retry_count                 # [회] 재시도 횟수 (SR-14 는 3회)
