# 고객 주문 관리 (fms_core 주문 부분)

- 상태: 초안 (2026-11-14). 주문 단계 의미는 D14, 재고 규칙은 D19 가 정해지면 고친다.
- 노드: `order_manager_node` (관제 PC). 코드: `cobot_control_center/order_manager_node.py`, 규칙 `order_flow.py`, DB `order_db.py`.
- 고객 화면·게이트웨이(sub PC)는 `src/cobot_gui/docs/customer_app.md`.

## 1. 전체 흐름

```
고객 핸드폰 ──Wi-Fi/HTTP──▶ sub PC: customer_gateway ──ROS 서비스──▶ 관제 PC: order_manager ──▶ SQLite
       ◀──────── 1초 polling ────────┘           ◀── /control_center/orders (OrderStatus) ──┘
```

| 이름 | 종류 | 방향 |
|---|---|---|
| `/control_center/submit_order` | `SubmitOrder` 서비스 | 게이트웨이 → order_manager |
| `/control_center/customer_decision` | `CustomerDecision` 서비스 | 게이트웨이 → order_manager |
| `/control_center/orders` | `OrderStatus` 토픽 (RELIABLE, TRANSIENT_LOCAL, KEEP_LAST 50) | order_manager → 게이트웨이 |
| `/control_center/inventory` | `InventoryState` 토픽 (RELIABLE, TRANSIENT_LOCAL, KEEP_LAST 1) | order_manager → 게이트웨이 |

## 2. 주문 단계

| 단계 (`OrderStatus.stage`) | 로봇 | 고객 화면 |
|---|---|---|
| `RECEIVED` → `ASSIGNED` → `LOADING` | 창고(WP_LOAD_x)에서 상차 | 준비 중 |
| `IN_TRANSIT` | 자리 웨이포인트로 주행 | 준비 중 |
| `UNLOADING` | 고객 앞 정차, 결정 대기 (초안: 이 단계를 '도착' 으로 쓴다) | 구매 / 구매 안 함 |
| `HANDOVER_CONFIRMED` → `RETURNING` → `COMPLETED` | 결제 뒤 복귀 | 구매 완료 |
| `CANCELLED` | 아래 '취소 뒤 로봇 단계' | 구매 취소 |
| `FAILED` | 모르는 자리(`UNKNOWN_TABLE`) | 실패 |

- 재고가 없으면 `RECEIVED` 에 머물고 `failure_reason = INVENTORY_UNAVAILABLE` 이다 (SR-02: 접수하되 배정하지 않는다).
- 취소 뒤 로봇 단계 (`orders.robot_step`, 이력 `order_events.kind = 'robot'`):
  `TO_REPACK`(WP_UNLOAD 로 이동) → `REPACKING`(OMX_3 이 `HandoverTask` REPACK 으로 정돈·재상차) → `TO_WAREHOUSE`(창고로 복귀) → `DONE`.
  신발은 핑키 위에 그대로 둔다. 선반에 되돌리는 동작은 아직 없다.

### 지금은 시뮬레이션이다

팔·주행이 관제와 연결되지 않아서, 로봇이 하는 단계는 `sim_step_sec` 마다 저절로 넘어간다 (`OrderService.tick`).
실제 연동 때는 시간 진행 대신 `CompletionEvidence`·`HandoverTask` 결과로 같은 전이를 부른다.
`robot_ids` 를 돌아가며 배정할 뿐 SR-03 배정 규칙(배터리·통신)은 없다.

## 3. 재고

| 때 | `qty_on_hand` | `qty_reserved` |
|---|---|---|
| 주문 접수 (가점유 성공) | 그대로 | +수량 |
| 결제 완료 | −수량 | −수량 |
| 취소 뒤 창고 도착 (`DONE`) | 그대로 | −수량 |

초기 재고는 `config/order_manager.yaml` 의 `initial_inventory` 이다. DB 의 재고가 비어 있을 때만 넣는다.

## 4. DB (SQLite)

파일: `db_path` 파라미터 (기본 `~/.ros/cobot_orders.sqlite3`). 지우면 주문이 사라지고 재고를 다시 채운다.

| 표 | 내용 |
|---|---|
| `inventory` | sku, location_id, qty_on_hand, qty_reserved |
| `orders` | order_id, idempotency_key(UNIQUE), sku, qty, table_id, waypoint_id, robot_id, stage, stage_history(JSON), failure_reason, reserved, robot_step, next_step_at, 시각 |
| `payments` | order_id, status(`PAID`·`CANCELLED`, 가짜 결제), decided_at |
| `order_events` | 단계·결제·로봇 이력. 추가만 한다 (고치거나 지우는 함수가 없다) |
| `meta` | schema_version |

같은 `idempotency_key` 로 다시 오면 같은 `order_id` 를 돌려준다 (`duplicate = true`).

## 5. 자리 (위치 ID)

`config/order_manager.yaml` 의 `locations` 에 `"위치ID=웨이포인트"` 로 적는다. 고객 화면 카탈로그(`cobot_gui/config/customer_catalog.yaml`)의 `locations` 와 ID 를 맞춘다.
지금은 `BENCH_1=WP_BENCH_DELIVERY` 하나다. `WP_BENCH_DELIVERY` 는 맵 YAML 에만 있고 `approach_poses.yaml` 에 정차점이 없다. 실제 주행 전에 주행 담당이 맵 계약 절차(`docs/fms_map_contract.md`)로 정차점을 넣어야 한다.

## 6. 서명

`gateway_key_file` 이 있으면 게이트웨이 요청의 `gw_sig` 를 검사하고, 같은 `gw_nonce` 를 두 번 받지 않는다. 비어 있으면 검사하지 않는다 (개발 모드, 시작할 때 경고).

```
gw_sig = HMAC-SHA256(key, "\n".join(fields + [gw_nonce]))   # 16진수
SubmitOrder      fields = idempotency_key, sku, qty, table_id, requester_role, requester_id
CustomerDecision fields = order_id, decision, requester_id
```

키 파일은 커밋하지 않는다. 관제 PC 와 sub PC 에 같은 키를 둔다.

## 7. 실행과 시험

```bash
colcon build --symlink-install --packages-up-to cobot_control_center
ros2 launch cobot_control_center order_manager.launch.xml
colcon test --packages-select cobot_control_center && colcon test-result --verbose
```

ROS 없이 규칙만 볼 때: `cd src/cobot_control_center && python3 -m pytest test/test_order_flow.py`
