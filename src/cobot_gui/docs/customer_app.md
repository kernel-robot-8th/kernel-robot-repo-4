# 고객 주문 화면 (보조 A, 관제 PC)

- 상태: 초안 (2026-11-14). 메뉴 트리 밖 화면이다 (D14). 관제 대시보드와 따로 돈다.
- sub PC 는 두지 않는다. 게이트웨이와 order_manager 가 모두 관제 PC 에서 돈다 (2026-11-14 변경).
- 고객은 자기 핸드폰으로 자리의 QR 을 찍어 들어온다. 앱 설치는 없다.
- 주문 처리(DB·단계)는 관제 PC 의 order_manager 가 한다: `src/cobot_control_center/docs/order_flow.md`.

## 1. 구성

| 자리 | 파일 |
|---|---|
| 화면 | `web/customer.html`, `web/src/customer/` (React, 관제 화면과 같은 Vite 빌드의 두 번째 입력) |
| 가짜 결제 QR | `web/public/customer/pay_qr.svg` (고정 이미지, 스캔되지 않는다) |
| 신발 이미지 | `web/public/customer/shoes/` (폴더를 만들어 넣는다. 장당 100 KB 이하, 가로 600 px 정도. 원본 사진은 커밋하지 않는다) |
| 게이트웨이 노드 | `cobot_gui/customer_gateway_node.py` (rclpy), HTTP 처리 `cobot_gui/customer_gateway_utils.py` (파이썬 표준 `http.server`) |
| 설정 | `config/customer_gateway.yaml`, 신발 목록 `config/customer_catalog.yaml`, 자리 목록 `cobot_bringup/config/store_layout.yaml` |
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
- 좌표는 QR 에 넣지 않는다. 위치 ID → 웨이포인트는 매장 배치 파일에 있다. 맵이 바뀌어도 QR 을 다시 인쇄하지 않는다.
- 자리를 늘리려면 `cobot_bringup/config/store_layout.yaml` 의 `locations` 에만 한 줄 더하고 QR 을 인쇄한다.
  게이트웨이(자리 이름)와 order_manager(웨이포인트)가 같은 파일을 읽는다.
  QR 그림은 아무 QR 생성기로 위 주소를 넣어 만든다.

## 3. 화면 흐름

| 화면 | 언제 |
|---|---|
| 신발 선택 → 상세 | 처음. 재고 0 이면 품절 |
| "Cobot이 물건을 준비 중이에요" | `RECEIVED`~`IN_TRANSIT`. 단계 4개(접수·꺼내는 중·가는 중·도착)를 보인다 |
| 도착 → [구매하기] / [구매하지 않을게요] | `UNLOADING` |
| 결제 → [결제하기] 또는 QR 스캔 뒤 [QR 결제를 완료했어요] | 구매하기를 누른 뒤. 핸드폰 하나로도 결제할 수 있게 버튼을 둔다. 둘 다 가짜 결제다 |
| 구매 완료 / 구매 취소 | `CustomerDecision` 응답 뒤 |
| QR 을 찍어 달라는 안내 | 주소에 `loc` 가 없거나 모르는 자리 |

- 진행 중인 주문은 브라우저 `localStorage` 에 남겨서 새로고침해도 이어진다.
- 주문은 만든 화면(세션)만 조회·결정할 수 있다.

## 4. API (`/api/customer`)

| 요청 | 본문 / 쿼리 | 응답 |
|---|---|---|
| `GET /catalog?loc=` | | `{location: {id,name}\|null, items: [{sku,name,brand,size,color,price,image,available}]}` |
| `POST /orders` | `{sku, loc, client_key, session}` | `{order_id, view}` |
| `GET /orders/<id>?session=` | | `{order_id, sku, stage, view, failure_reason}` |
| `POST /orders/<id>/decision` | `{decision: PAID\|CANCEL, session}` | `{order_id, stage, view}` |

- `view`: `preparing`, `arrived`, `paid`, `cancelled`, `failed`, `out_of_stock`
- 오류: 400 (형식), 404 (모르는 주문·다른 세션), 409 (fms_core 거부, 예: `WRONG_STAGE`), 503 (fms_core 응답 없음)
- `client_key` 는 주문 버튼 한 번마다 새로 만든다. 게이트웨이가 `cust-<client_key>` 를 `SubmitOrder.idempotency_key` 로 쓴다.

## 5. 실행

```bash
cd src/cobot_gui/web && npm ci && npm run build && cd -
colcon build --symlink-install --packages-up-to cobot_gui
ros2 launch cobot_gui customer_gateway.launch.xml
```

- 같은 관제 PC 에서 `ros2 launch cobot_control_center order_manager.launch.xml` 이 함께 돌아야 한다. 두 터미널의 `ROS_DOMAIN_ID` 는 같아야 한다 (값은 `docs/fms_interfaces.md`, 임의로 바꾸지 않는다).
- 빌드할 때 `cobot_bringup` 도 함께 고른다 (매장 배치 파일이 그 install 에 있다): `colcon build --symlink-install --packages-up-to cobot_gui cobot_control_center cobot_bringup`
- 화면만 볼 때 (ROS 없이): `cd src/cobot_gui/web && npm run dev` 후 `http://localhost:5173/customer.html?loc=BENCH_1` (모의 서버). 빌드본은 주소에 `&mock=1` 을 붙이면 모의 서버를 쓴다.
