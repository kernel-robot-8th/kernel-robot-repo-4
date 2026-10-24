# InventoryItem.msg - 재고 항목 1개 (InventoryState.items 의 원소)

string sku                         # 신발 종류
string location_id                 # 보관 위치
uint32 qty_on_hand                 # [개] 보유 수량
uint32 qty_reserved                # [개] 가점유 수량
string lock_holder_order_id        # 락을 가진 주문. 없으면 ""
