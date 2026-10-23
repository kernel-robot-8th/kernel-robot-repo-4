# InventoryState.msg - 재고 원장 투영 (SR-02 초안, 원천은 D19)
# 토픽: /control_center/inventory (설정성 QoS, TRANSIENT_LOCAL). 변화 즉시
# 발행: fms_core. 구독: 게이트웨이.

string SOURCE_MANUAL_YAML="MANUAL_YAML"

std_msgs/Header header
InventoryItem[] items              # 재고 항목
string source                      # 재고 원천. 위 SOURCE_* 중 하나 (D19 에서 더한다)
