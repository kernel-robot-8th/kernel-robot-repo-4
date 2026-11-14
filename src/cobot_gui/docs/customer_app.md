# 고객 주문 화면 (보조 A, 관제 PC)

- 상태: 초안 (2026-11-14). 메뉴 트리 밖 화면이다 (D14). 관제 대시보드와 따로 돈다.
- sub PC 는 두지 않는다. 게이트웨이와 fleet_control 이 모두 관제 PC 에서 돈다 (2026-11-14 변경).
- 고객은 자기 핸드폰으로 자리의 QR 을 찍어 들어온다. 앱 설치는 없다.
- **주문·재고 원장은 `cobot_fleet_control` 하나다** (`~/.cobot/fleet_control.sqlite3`). 게이트웨이는 주문을 저장하지 않고 fleet_control 에 요청만 한다.
  요청 설명: `src/cobot_navigation/cobot_fleet_control/README.md` 의 '고객 주문 화면용 요청'.

```
고객 핸드폰 ──Wi-Fi/HTTP──▶ customer_gateway ──/control_center/task_request (JSON)──▶ fleet_control ──▶ 로봇·팔
       ◀──── 1초 polling ───┘      ◀── /control_center/task_events (응답), /control_center/tasks (스냅숏) ──┘
```

## 1. 구성

| 자리 | 파일 |
|---|---|
| 화면 | `web/customer.html`, `web/src/customer/` (React, 관제 화면과 같은 Vite 빌드의 두 번째 입력) |
| 가짜 결제 QR | `web/public/customer/pay_qr.svg` (고정 이미지, 스캔되지 않는다) |
| 신발 이미지 | `web/public/customer/shoes/` (폴더를 만들어 넣는다. 장당 100 KB 이하, 가로 600 px 정도. 원본 사진은 커밋하지 않는다) |
| 게이트웨이 노드 | `cobot_gui/customer_gateway_node.py` (rclpy), HTTP 처리 `cobot_gui/customer_gateway_utils.py` (파이썬 표준 `http.server`) |
| 설정 | `config/customer_gateway.yaml`, 신발 이름·가격 `config/customer_catalog.yaml` |
| 자리·선반·재고 | fleet_control 이 가진다. 자리와 선반 열은 `cobot_fleet_control/config/scenario.yaml` 의 `destinations`, `shelf`. 재고와 선반 칸은 `type=inventory` 요청 |
| launch | `launch/customer_gateway.launch.xml` |

- 게이트웨이는 `customer.html` 과 `assets/`, `customer/` 만 내보낸다. 관제 화면(`index.html`)은 이 포트(8080)로 열리지 않는다. 같은 PC 라도 고객 핸드폰이 관제 화면에 닿지 않게 하기 위해서다.
- 새 의존성은 없다 (React·lucide 는 이미 있는 것, 서버는 표준 라이브러리).

## 2. 자리 QR

QR 내용은 주소 하나다.

```
http://<관제 PC IP>:8080/?loc=BENCH_1
```

- 핸드폰과 관제 PC 는 같은 Wi-Fi 에 있어야 한다. `localhost` 는 핸드폰 자신이라 쓸 수 없다.
- IP 가 QR 에 인쇄되므로 공유기에서 관제 PC IP 를 고정한다 (DHCP 예약).
- 포트 6000 은 크롬이 막는다. 8080 을 쓴다.
- 좌표는 QR 에 넣지 않는다. 위치 ID → 하차 구역은 fleet_control 의 `scenario.yaml` `destinations` 에 있다. 맵이 바뀌어도 QR 을 다시 인쇄하지 않는다.
- 자리를 늘리려면 `destinations` 에만 한 줄 더하고 QR 을 인쇄한다. 게이트웨이는 자리 목록을 `/control_center/tasks` 스냅숏에서 받는다.
  지금은 하차 구역이 ZC 하나라 `BENCH_1` 만 있다.
  QR 그림은 아무 QR 생성기로 위 주소를 넣어 만든다.

## 3. 화면 흐름

| 화면 | 화면 단계 (`stage`) | fleet_control 주문 상태 |
|---|---|---|
| 신발 선택 → 상세 | | 재고 0 이면 품절 |
| "Cobot이 물건을 준비 중이에요" (접수) | `RECEIVED` | `WAITING` (로봇 배정 전) |
| 〃 (꺼내는 중) | `ASSIGNED`, `LOADING` | `MOVE_PICKUP`, 상차 구역 안 단계(`PICKUP_EXIT`~`VERIFY_LOAD`) |
| 〃 (가는 중) | `IN_TRANSIT` | `LEAVE_PICKUP`~`VERIFY_UNLOAD` (하차 팔이 자리에 내려놓을 때까지) |
| 도착 → [구매하기] / [구매하지 않을게요] | `UNLOADING` | `CUSTOMER` 이고 `RUNNING` |
| 결제 → [결제하기] 또는 QR 스캔 뒤 [QR 결제를 완료했어요] | | 구매하기를 누른 뒤. 핸드폰 하나로도 결제할 수 있게 버튼을 둔다. 둘 다 가짜 결제다 |
| 구매 완료 | `HANDOVER_CONFIRMED` | `customer_received` |
| 구매 취소 | `CANCELLED` | `customer_declined`, 수령 시간 초과(`customer_timed_out`), 수령 확인 없이 종결 |
| 실패 | `FAILED` | `FAILED` |
| QR 을 찍어 달라는 안내 | | 주소에 `loc` 가 없거나 모르는 자리 |

- 화면 단계 이름은 고객 화면의 진행 표시에 맞춘 것이다. 바꾸는 규칙은 `customer_gateway_utils.order_progress` 에 있다.
- 고객 결정: [구매하기] → `type=received`, [구매하지 않을게요] → `type=declined`. fleet_control 은 `CUSTOMER` 단계에서만 받는다.
- **도착 뒤 120초 안에 고르지 않으면** fleet_control 이 시간 초과로 기록하고 로봇을 복귀시킨다. 화면은 구매 취소로 바뀐다.
- 구매하지 않으면 로봇은 그대로 복귀한다. 자리에 내려놓은 신발의 회수는 fleet_control 의 `allow_returns` 설정을 따른다 (그 패키지 README).
- 정지·현장 확인 중(`UNKNOWN`, `PAUSED`, `ESTOP`, `MANUAL`)에는 준비 중 화면을 유지한다.
- 진행 중인 주문은 브라우저 `localStorage` 에 남겨서 새로고침해도 이어진다.
- 주문은 만든 화면(세션)만 조회·결정할 수 있다. 세션 소유는 게이트웨이 메모리에만 있어서 게이트웨이를 다시 켜면 진행 중이던 화면은 처음으로 돌아간다 (주문 자체는 fleet_control 에 남는다).

## 4. API (`/api/customer`)

| 요청 | 본문 / 쿼리 | 응답 |
|---|---|---|
| `GET /catalog?loc=` | | `{location: {id,name}\|null, items: [{sku,name,brand,size,color,price,image,available}]}` |
| `POST /orders` | `{sku, loc, client_key, session}` | `{order_id, view}` |
| `GET /orders/<id>?session=` | | `{order_id, sku, stage, view, failure_reason}` |
| `POST /orders/<id>/decision` | `{decision: PAID\|CANCEL, session}` | `{order_id, sku, stage, view, failure_reason}` |

- `view`: `preparing`, `arrived`, `paid`, `cancelled`, `failed`, `out_of_stock`
- 오류: 400 (형식), 404 (모르는 주문·다른 세션), 409 (fleet_control 거절: `ORDER_REJECTED`, `WRONG_STAGE`. `detail` 에 거절 이유), 503 (fleet_control 응답 없음 또는 스냅숏을 아직 못 받음)
- `client_key` 는 주문 버튼 한 번마다 새로 만든다 (영문·숫자·밑줄·하이픈). 게이트웨이가 `cust-<client_key>` 를 fleet_control 의 `order_id` 로 쓴다. 같은 `order_id` 를 다시 보내면 fleet_control 이 같은 주문을 돌려준다.
- `available` 은 스냅숏의 `stock` 에서 온다. 스냅숏이 5초 넘게 없으면 `null` (모름), fleet_control 재고에 없는 SKU 는 0 이다.
- 재고가 없으면 주문을 만들지 않고 `view: out_of_stock` 을 돌려준다.

## 5. 실행

```bash
cd src/cobot_gui/web && npm ci && npm run build && cd -
colcon build --symlink-install --packages-up-to cobot_gui cobot_fleet_control
ros2 launch cobot_fleet_control fleet_control.launch.xml   # 주문·재고 원장, 로봇 실행기
ros2 launch cobot_gui customer_gateway.launch.xml          # 고객 화면
```

- 두 노드는 같은 관제 PC, 같은 `ROS_DOMAIN_ID` 에서 돈다 (값은 `docs/fms_interfaces.md`, 임의로 바꾸지 않는다).
- 주문하려면 fleet_control 에 재고와 선반 칸이 있어야 한다. 예 (1행 1열에 3켤레):
  ```bash
  ros2 topic pub --once /control_center/task_request std_msgs/msg/String \
    '{data: "{\"type\": \"inventory\", \"request_id\": \"stock-1\", \"sku\": \"SHOE_RUN_WHITE_260\", \"available\": 3, \"shelf_row\": 1, \"shelf_col\": 1}"}'
  ```
  `customer_catalog.yaml` 의 SKU 와 같아야 화면에 재고가 보인다. 지금 상차 구역은 1열(ZA)·2열(ZB)뿐이라 3열 신발은 주문이 거절된다.
- 로봇이 움직이려면 관제에서 작업 명령을 켜야 한다 (`type=arm`). 꺼져 있으면 주문은 접수되고 `WAITING` 에 머문다.
- 화면만 볼 때 (ROS 없이): `cd src/cobot_gui/web && npm run dev` 후 `http://localhost:5173/customer.html?loc=BENCH_1` (모의 서버). 빌드본은 주소에 `&mock=1` 을 붙이면 모의 서버를 쓴다.
