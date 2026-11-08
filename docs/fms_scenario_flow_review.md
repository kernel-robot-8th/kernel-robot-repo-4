# 중앙 관제 시나리오·플로우와 구현 점검

- 기준: `feature/control-center` 병합 커밋 `24a3947` (2026-11-08). `refactor/control-server-bt-mqtt-db`의 `c9374ec`까지 포함한다.
- 범위: `cobot_fleet_control`(중앙 관제), `cobot_control_center`(웹·API), `cobot_pinky_patrol`(로봇 순찰 노드), `cobot_zone_traffic_control`(구역 통제).
- 근거: 코드 읽기와 단위 테스트(541개 통과) 결과다. 실물 검증은 2026-11-07 ZA 도착 → 수동 상차 → ZC 이동까지만 했다.
- 상태: 점검 기록이다. 결정 사항이 아니며, 빈 항목의 담당·순서는 팀 논의가 필요하다.

## 1. 시나리오: 주문 1건이 하는 일

경로 설정은 `cobot_fleet_control/config/scenario.yaml`, 좌표는 `cobot_pinky_patrol/config/sites/lab.yaml`에 있다.

| 경로(route) | 상차 지점 | 상차 팔 | 하차 지점 | 하차 팔 |
|---|---|---|---|---|
| `lab_delivery` | ZA | omx1 | ZC | omx2 |
| `lab_delivery_zb` | ZB | omx1 | ZC | omx2 |

행동 트리(`scenario_tree.py`)의 정상 순서:

```
[상차]  상차장 이동 → 통로 비었는지 확인 → 정차 위치 측정(틀리면 보정)
        → 마커·상품 확인 → 팔 피킹 → 로봇에 상차 → 적재·팔 퇴피 확인
[이동]  상차 구역 이탈 → 하차장 이동 → 통로 확인
[하차]  정차 위치 측정(보정) → QR·상품 확인 → 팔 피킹 → 하차 → 배치·빈 적재함·팔 퇴피 확인
[수령]  고객 수령 대기 (customer_timeout_sec=120, 넘으면 기록 후 진행)
[복귀]  하차 구역 이탈 → HOME 복귀 → 통로 확인 → 주문 종결
```

- 피킹 전에 정차가 실패하면 나머지 단계를 건너뛰고 HOME으로 안전 복귀한다.
- 장치 단계는 장치가 `retry_safe=true`라고 알린 경우에만 재시도하며, 최대 `max_retries=3`번이다.
- 단계마다 제한 시간이 있다(`step_timeout_sec=300`).

## 2. 플로우: 명령이 흐르는 길

```
웹 화면 ──HTTP/WS──▶ fleet_api_node (cobot_control_center)
                          │ /control_center/task_request
                          ▼
                  fleet_control_node (주문 BT + 주행 BT, SQLite 기록)
          │                       │                         │
 /pinkyN/patrol_cmd       /fleet/work_request      /control_center/tasks · task_events
          ▼                       ▼                         ▼
 pinky_patrol_node (Nav2)   팔·비전 (어댑터 없음)        웹 화면 상태 표시
   │ /pinkyN/patrol_status        │ /fleet/work_result
   └────────▶ fleet_control ◀─────┘

 구역 진입: zone_manager_node가 토큰으로 한 대씩 허가
 생존 신호: fleet → /pinkyN/fleet_heartbeat (0.5초 주기)
```

## 3. 주문 진행 조건

- **접수**: 경로와 수량을 확인한 뒤 `WAITING`으로 받는다. 로봇이 모두 바빠도 접수한다.
- **배정**: 접수 순서대로, 아래 조건을 모두 만족하는 로봇에 배정한다. 출발 간격은 `departure_gap_sec=3`이다.
  - 작업 명령 켜짐(arm)
  - 배터리 `battery_min=20`% 이상
  - 상태 수신 3초 이내, 배터리 수신 10초 이내
  - `IDLE`/`DONE` 상태
  - `central_controlled=true`, 정지 잠금 없음, 구역 점유 없음
- **진행 중 감시** (`SafetyGate`, 매 tick):
  - 작업 명령 꺼짐 → 그 자리에서 멈춘 채 대기
  - 상태·배터리 수신 만료 → 주문 `UNKNOWN`, 사람 확인 대기
  - 로봇 정지 잠금 → 주문 중단
- **재시작**: 끝나지 않은 주문은 `UNKNOWN`으로 보류한다. 운영자가 확인하면 이동·수령 체크포인트에서만 다시 시작하고, 팔 작업은 임의로 다시 하지 않는다.
- **수동 상차 확인**: 상차장에서 멈춘 주문은 `/fleet_control`의 `manual_load_confirmation` 파라미터로 처리한다. 내부 요청은 `type=confirm_loaded`다. 확인되면 잠금을 풀고 상차 구역 이탈부터 재개한다.

## 4. 점검표

✅ 있음 · ⚠️ 일부 · ❌ 없음

### 4-1. 안전

| 항목 | 상태 | 현재 구현 |
|---|---|---|
| 정지 버튼 | ⚠️ | 소프트웨어 제자리 정지만 있다. 하드웨어 비상정지와는 연결되어 있지 않다. |
| 통신이 끊기면 로봇이 스스로 정지 | ✅ | 관제 생존 신호가 3초 동안 없으면 로봇이 비상정지한다(`pinky_patrol_node._heartbeat`). |
| 오래되거나 엉뚱한 명령 거부 | ✅ | 명령 유효시간(5초), 세션, 순번으로 거른다(`central_guard.py`). |
| 사람·장애물 회피 | ⚠️ | Nav2 기본 기능에만 의존한다. 관제 쪽 감시는 없다. |

### 4-2. 다중 로봇

| 항목 | 상태 | 현재 구현 |
|---|---|---|
| 구역 동시 진입 방지 | ✅ | zone_manager 토큰. `held_zone`(예약)과 `arrived_zone`(실제 도착)을 구분한다. |
| 팔·작업장·통로 충돌 방지 | ✅ | 주문마다 `station_*`, `arm_*`, `lane_*`을 예약한다. |
| 같은 주문·요청 중복 방지 | ✅ | 같은 `order_id`·`request_id`로 다시 오면 처음 결과를 돌려준다. |
| 교착 상황 | ⚠️ | 예약 순서로 일부 막지만, 따로 시험한 기록은 없다. |

### 4-3. 장애·복구

| 항목 | 상태 | 현재 구현 |
|---|---|---|
| 단계별 제한 시간 | ✅ | 단계 300초, 고객 수령 120초 |
| 재시작 후 주문 유지 | ✅ | SQLite 실행 원장에 저장하고, 끝나지 않은 주문은 `UNKNOWN`으로 보류한다. |
| 감사 기록 | ✅ | 운영자 확인, 해제, 수동 상차 확인 이벤트를 남긴다. |
| 정지 잠금 복구 | ⚠️ | 웹 `release_control`이 있다. 상차장 잠금은 파라미터로만 풀 수 있다. 다른 구역 안에서 잠기면 복구 절차가 없다. |

### 4-4. 로봇 상태

| 항목 | 상태 | 현재 구현 |
|---|---|---|
| 배터리 부족 시 배정 제외 | ✅ | 20% 미만이면 배정하지 않는다. |
| 충전 이동 | ❌ | 없다. |
| 기동 시 센서·Nav2 준비 확인 | ✅ | `robot_startup.py`가 scan·odom·tf와 amcl·bt_navigator를 확인한다. |
| 주행 중 위치 신뢰도 감시 | ❌ | 기동 때만 확인한다. |

### 4-5. 연동

| 항목 | 상태 | 현재 구현 |
|---|---|---|
| 팔·비전 연동 | ❌ | `/fleet/work_request`를 받는 노드가 저장소에 없다. 그래서 장치 단계에서 결과를 계속 기다린다. |
| 웹 주문 입력 | ❌ | 웹 이동 버튼(`type=create`)은 주행만 한다. 전체 주문(`type=order`) 화면과 API가 없다. |
| 웹 수동 상차 확인 | ❌ | ROS 파라미터로만 할 수 있다. |
| 웹 접속 권한 | ⚠️ | 인증이 없다. 지금은 `127.0.0.1`에만 열려 있다. |
| 시계 동기화 | ⚠️ | 명령 유효시간을 각 PC 시계로 비교한다. PC 간 시계가 1초 넘게 어긋나면 명령이 거부될 수 있다. NTP 확인 기록은 없다. |

### 4-6. 시험

| 항목 | 상태 | 현재 구현 |
|---|---|---|
| 단위 테스트 | ✅ | control_center 183, fleet_control 160, pinky_patrol 167, zone_traffic_control 31 |
| 시뮬레이션 | ✅ | `cobot_mock`, `cobot_gazebo` |
| 실물 전체 시나리오 | ⚠️ | ZA 도착 → 수동 상차 → ZC 이동까지 했다. 하차·수령·복귀는 아직 하지 않았다. |
| 린트 | ⚠️ | control_center는 통과한다. navigation 3개 패키지는 flake8·pep257 오류가 원래부터 있다. |

## 5. 남은 일 (중요한 순서)

1. 팔·비전 연동: `/fleet/work_request` → `/fleet/work_result` 어댑터. 이것이 없으면 처음부터 끝까지 자동으로 돌릴 수 없다.
2. 웹 주문 입력과 수동 상차 확인 화면 (`cobot_control_center`)
3. 구역 안 정지 잠금의 복구 절차
4. 하드웨어 비상정지 연결
5. 충전 이동
6. 관제 PC·로봇 간 시계 동기화(NTP) 확인
7. 실물 전체 시나리오 시험 (하차·수령·복귀 포함)
