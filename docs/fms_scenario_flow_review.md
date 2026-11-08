# 중앙 관제 시나리오·플로우와 구현 점검

- 기준: `feature/control-center` 병합 커밋 `24a3947` (2026-11-08). `refactor/control-server-bt-mqtt-db`의 `c9374ec`까지 포함한다.
- 범위: `cobot_fleet_control`(중앙 관제), `cobot_control_center`(웹·API), `cobot_pinky_patrol`(로봇 순찰 노드), `cobot_zone_traffic_control`(구역 통제).
- 근거: 코드 읽기와 단위 테스트(541개 통과) 결과다. 실물 검증은 2026-11-07 ZA 도착 → 수동 상차 → ZC 이동까지만 했다.
- 상태: 현재 코드가 어떻게 되어 있는지 적은 사실 기록이다. 개선 과제와 목표 구조 제안은 [`fms_architecture_proposal.md`](fms_architecture_proposal.md)에 따로 둔다.

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

## 5. 현재 구현의 특징

동작은 하지만 일반적인 ROS2·관제 구현과 다르게 되어 있는 부분이다. 바꿀지는 [제안 문서](fms_architecture_proposal.md)에서 다룬다.

| # | 항목 | 현재 구현 | 일반적인 방식 | 영향 |
|---|---|---|---|---|
| 1 | 메시지 형식 | `/pinkyN/patrol_cmd`, `/pinkyN/patrol_status`, `/control_center/task_request`, `/zone_manager/*` 등이 `std_msgs/String`에 JSON이나 글자를 담는다. | `cobot_interfaces`의 `msg/srv/action` (CLAUDE.md 3-4) | 필드가 틀리거나 빠져도 빌드 때 안 잡히고 실행 중에 실패한다. 형식을 알려면 코드를 읽어야 한다. |
| 2 | 웹 ↔ fleet 요청·응답 | `task_request` 토픽으로 요청하고 `task_events` 토픽으로 응답한다. `request_id`로 직접 맞춘다. | 같은 도메인 안에서는 서비스 | ROS 기본 기능(응답 대기·타임아웃·취소)을 직접 다시 만들어 코드와 버그 지점이 늘어난다. |
| 3 | 수동 상차 확인 | `/fleet_control`의 `manual_load_confirmation` 파라미터에 JSON을 넣어 실행한다(`fleet_control_node.py`). | 서비스 호출 | 한 번만 실행할 명령이 설정값으로 남는다. 누가 보냈는지, 결과가 무엇인지 알기 어렵다. |
| 4 | 웹의 모드 판단 | 작업 목록에 `holds` 키가 있으면 fleet 모드로 판단한다(`fleet_api_utils.py:449`). | 모드를 알려 주는 명시 필드 | 나중에 task_manager도 `holds`를 내면 화면이 모드를 잘못 판단한다. |
| 5 | 명령 유효시간 | 보내는 PC의 `issued_at`을 받는 PC의 시계와 비교한다(`central_guard.py`). | 받는 쪽 자기 시계로 마지막 수신 후 경과 시간만 셈 | PC 간 시계가 1초 넘게 어긋나면 정상 명령도 거부된다. |
| 6 | 로봇 기동 | `fleet_startup.py`가 SSH로 접속해 프로세스를 직접 띄우고 감시한다. | systemd 서비스, 도커 compose 등 | 재부팅이나 프로세스가 죽었을 때 자동으로 다시 살리지 않는다. |
| 7 | 코드 위치·담당 | 중앙 관제 서버 `cobot_fleet_control`이 `cobot_navigation/` 아래에 있다. CLAUDE.md 표에 없는 패키지(`cobot_fleet_control`, `cobot_pinky_patrol`, `cobot_zone_traffic_control` 등)와 새 의존성 `py_trees`가 있다. | CLAUDE.md 2번 구조도·담당 표 | 관제 담당(`cobot_control_center`)과 코드 위치가 어긋난다. 새 의존성은 팀 허락 대상이다(CLAUDE.md 9번). |

일반적인 방식과 같아서 문제없는 것: 구역 토큰 방식, SQLite 실행 원장, py_trees 행동 트리, 관제 ↔ 로봇 구간의 "명령 + 상태" 토픽 구조.

### 5-1. 도메인 브릿지와 토픽 방식

로봇은 도메인 10/20/30, 관제 PC는 도메인 100을 쓰고 `cobot_domain_bridge`(ros2/domain_bridge 0.5.0 사본)가 그 사이를 잇는다.

- YAML 설정(`config/pinky_bridge_pinkyN.yaml`)은 `topics:`만 읽는다(`parse_domain_bridge_yaml_config.cpp`). 서비스는 C++ 코드에서 형식별로 직접 등록해야 하고, 액션은 지원하지 않는다.
- 그래서 로봇과 주고받는 명령·상태·구역 토큰·생존 신호가 모두 토픽이다. 이 구간은 토픽을 쓴 이유가 있다.
- 다만 토픽 브릿지는 메시지 형식을 가리지 않는다. 양쪽에 형식이 설치되어 있으면 `cobot_interfaces`에 정의한 msg도 넘길 수 있다. `String`+JSON은 브릿지 때문에 꼭 필요한 선택은 아니다.
- 웹(`fleet_api_node`)과 `fleet_control_node`는 같은 관제 PC·같은 도메인 100에 있어 브릿지를 거치지 않는다.

### 5-2. `String` 메시지 방식의 이력

메시지 형식을 정식으로 정한 적은 없고, 처음 만든 방식을 이어서 썼다.

| 날짜 | 커밋 | 대상 | 형식 |
|---|---|---|---|
| 2026-10-25 | `75a87da` (`cobot_pinky_patrol` 추가) | 로봇 상태 `patrol_status` | String + JSON (`state`, `waypoint` 등) |
| 2026-10-25 | `75a87da` | 로봇 명령 `patrol_cmd` | String + 글자 (`start`, `stop`, `goto:P2,P3`) |
| 2026-10-26 | `408db10` (`cobot_zone_traffic_control` 추가) | 구역 토큰 `/zone_manager/*` | String + 글자 (`robot_id:k:x,y,yaw` 등) |
| 2026-11-02 | `ddadba3` (control_center task_manager) | 웹 ↔ 작업 노드 `task_request` | String + JSON |
| 2026-11-05 | `97be6c7` (중앙 시나리오 제어) | 로봇 명령 `patrol_cmd` | String + JSON 봉투 (`session_id`, `seq`, `issued_at`, `ttl_sec`) |

### 5-3. 화면 구성

| 화면 | 상태 | 용도 |
|---|---|---|
| 컨트롤센터 웹 (8080, `cobot_control_center/web/`) | 있음 | 개발·시험: 로봇 이동, 정지·해제, 수동 명령 |
| BT 뷰어 (8091, `fleet_bt_viewer`) | 있음 | 개발: 주문 BT 내부를 읽기 전용으로 확인 |
| 주문 운영 화면 | 없음 | 서비스: 주문 접수·진행·확인·복구 |

- 개발 기능 차단은 서버에서 한다: `allow_raw_cmd: false` 기본, fleet 모드 `raw_cmd` 403, 작업 명령 꺼짐 423, `read_only` 백엔드.
- 현장 컨테이너에는 `cobot_mock`, `cobot_gazebo`가 들어 있지 않다.
- 로그인·역할 구분은 없다. 웹은 `127.0.0.1`에서만 열려 있다.
