# cobot_fleet_control

웹 제어 통신은 feature/control-center의 **FastAPI HTTP + WebSocket**을 사용합니다.
이 패키지는 주문별 전체 BT와 개별 주행 BT를 실행하며, 개발용 조회 전용 BT 뷰어를 제공합니다.
뷰어는 기본 8091 포트에서 실행 원장만 읽습니다. 작업 명령은 기존 control-center를 거칩니다.
모델 추론은 별도 PC의 통신 API와 실행 어댑터를 통해 연결해야 합니다.

[전체 구현·통신·검증 HTML](../docs/central_scenario_control.html)

## 웹 계약

| 기존 HTTP 요청 | 내부 ROS 요청 | 결과 |
|---|---|---|
| `POST /api/tasks` | `type=create` | 최초 202, 동일 요청 200, 충돌 409 |
| `POST /api/commands/arm` | `type=arm` | 켜기·끄기 200, 꺼진 상태의 작업 요청 423 |
| `POST /api/robots/{id}/stop` | `type=stop` | 202, 실제 사용한 소프트 정지 동작·작업 ID 반환 |
| `POST /api/tasks/{id}/resolve` | `type=resolve, task_id, result, note` | UNKNOWN만 해제, 최신 정지·취소·구역 상태 확인 |
| `POST /api/orders/{id}/confirm_loaded` | `type=confirm_loaded, order_id, operator, note, evidence` | 수동 상차 확인. 파라미터 `manual_load_confirmation`과 같은 검사 |
| `POST /api/robots/{id}/raw_cmd` | `type=raw` | 중앙 모드에서는 403. 화면에는 비활성으로 보고 |
| `GET /api/tasks`, `WS /ws/tasks` | `tasks`, `task` | 현재 작업 목록·개별 변경 |

웹 백엔드가 쓰는 ROS 토픽은 다음 세 개로 고정합니다.

- `/control_center/task_request`: 요청 JSON (`request_id`, `client_request_id` 포함)
- `/control_center/task_events`: `reply` 응답과 `task` 변경 이벤트
- `/control_center/tasks`: 최근 종료 작업과 **모든 미종료·UNKNOWN 작업**, `armed`, `allow_raw_cmd`, `spec`

`fleet_status_node`는 로봇·구역 상태를 `/control_center/fleet_status`로 집계하고,
`fleet_api_node`가 이를 `/ws/fleet`으로 내보냅니다. fleet이 화면용 상태 수집기를 다시 만들지 않습니다.
웹의 `/api/health` 는 fleet 이 살아 있는지를 `controller_online` 으로 알립니다 (도커 `smoke_check` 가 이 값으로 준비를 확인). 예전 `task_manager_online` 이름은 2026-11-09 에 바꿨으므로, 그 전에 만든 도커 이미지는 다시 빌드합니다.

정지 시에는 팔 작업 영역으로 임의 후퇴하지 않도록 제자리 소프트 정지를 사용합니다.
실제 하드웨어 비상정지와 다릅니다. 웹 해제 버튼은 현장 확인 기록을 남기되,
로봇의 `busy=false`, 최신 상태, 구역 미점유, 정지 래치를 함께 확인합니다.
시나리오의 화물·자원 예약은 기존 단일 작업 해제 버튼으로 풀 수 없습니다.
그 경우 주문별 안전·화물·자원 확인을 담은 시나리오 복구가 필요합니다.

### 현재 제한: 구역 점유 중 정지 래치의 웹 복구

`held_zone`에 구역이 남아 있고 `central_latched=true`인 상태는 현재 웹의
**현장 확인 후 해제**만으로 복구할 수 없습니다. 해제는 구역 미점유를 요구하지만,
구역 이탈 명령도 정지 래치로 차단되기 때문입니다. `busy=false`여도 구역 점유는 유지됩니다.

이 상태에서 현장 확인을 거쳐 이탈하거나 점유를 정리하는 웹 복구 절차는 아직 구현되지 않았습니다.
거절 사유를 구체적으로 표시하는 변경은 진단 개선이며, 이 복구 제한을 해결하지 않습니다.
실제 로봇 위치와 구역 상태를 확인해야 하며, 점유 값이나 DB를 임의로 지워 우회하지 않습니다.

## 기동

feature/control-center의 cobot_control_center를 빌드·source한 환경이 필요합니다.
현재 브랜치의 예전 cobot_control_center만 있으면 웹 실행 파일이 없어 기동 전 거절됩니다.

```bash
# Linux 관제 PC, ROS·control-center 설치 환경을 먼저 source
colcon build --packages-up-to cobot_fleet_control cobot_domain_bridge cobot_zone_traffic_control
source install/setup.bash
export ROS_DOMAIN_ID=100

# 기본 미리보기
ros2 launch cobot_fleet_control control_center_web.launch.xml \
  navigation_root:=/ws/kernel-robot-repo-4/src/cobot_navigation

# 웹 + 상태 집계 + 중앙 실행기. 기본 작업 명령 꺼짐
ros2 launch cobot_fleet_control control_center_web.launch.xml \
  navigation_root:=/ws/kernel-robot-repo-4/src/cobot_navigation mode:=execute
```

`--packages-up-to`는 `cobot_fleet_control`의 의존 패키지인 `cobot_control_center`도 함께 빌드합니다.
`--packages-select`는 지정한 패키지만 빌드하므로, 의존 패키지가 아직 설치되지 않았다면
`cobot_control_center/share/cobot_control_center/package.sh`를 찾지 못해 실패합니다.
이 빌드는 현재 체크아웃의 `cobot_control_center`를 설치하므로, 웹 기동에는 위에서 설명한
feature/control-center의 웹 실행 파일이 있는 소스가 필요합니다.

개발 설정 두 개는 `fleet_control.launch.xml` 인자로 줍니다. 실물은 둘 다 `false`(기본)입니다.

| 인자 | 기본 | 뜻 |
|---|---|---|
| `allow_raw_cmd` | `false` | 개발용 수동 명령(`type=raw`). 켜면 작업 명령 켜짐·로봇 보류 없음·연결 확인 뒤 세션 봉투를 붙여 `patrol_cmd` 로 보냄. 결과는 추적하지 않음 |
| `start_armed` | `false` | 작업 명령 켜진 채로 시작. 격리 도메인 시뮬 전용 |
| `db_path` | `~/.cobot/fleet_control.sqlite3` | 실행 원장. 가짜 핑키·가제보는 다른 파일 |

가짜 핑키(`cobot_mock` `mock_fleet.launch.xml`)·가제보(`cobot_gazebo` `sim_fleet.launch.xml`)·`cobot_bringup` 은 이 노드를 작업 노드로 띄웁니다.

이미 fleet이 실행 중이면 `fleet:=existing`을 추가합니다. 브릿지·zone_manager·로봇은 이 기동기가 중복 실행하지 않습니다.
`host`·`port` 인자로 화면 접속 주소를 바꿀 수 있고 기본은 `127.0.0.1:8080`입니다.

새 기동기는 **fleet_status_node + fleet_api_node + 선택적 fleet_control_node**만 시작합니다.
정상 종료·실패 시 자신이 시작한 프로세스만 정리합니다.

웹 지도용 프로필은 현재 주행 설정을 사용자 캐시 `~/.cache/cobot/control_center_profiles`에 자동 내보냅니다.
내보내기를 마친 뒤에 웹 서버를 시작합니다. 원본 waypoint는 `cobot_pinky_patrol/config/sites/lab.yaml` 한 곳에서 관리합니다.

중앙 실행기만 직접 실행할 경우 지점 설정을 함께 지정하면 웹 요청을 로봇 전달 전에 검증합니다.

```bash
ros2 launch cobot_fleet_control fleet_control.launch.xml \
  patrol_config_dir:=/ws/kernel-robot-repo-4/src/cobot_navigation/cobot_pinky_patrol/config site:=lab
```

## 관제에서 로봇까지 SSH 순차 기동

`config/fleet_startup.yaml`의 주소·계정·vendor underlay를 현장에 맞춥니다.
기본 명령은 미리보기이고 SSH 연결이나 로봇 프로세스를 시작하지 않습니다.

```bash
ros2 launch cobot_fleet_control fleet_startup.launch.xml
# 실제 기동은 준비 확인 후 execute:=true
```

기동 순서는 bridge → zone_manager → pinky1 준비 → pinky2 준비 → pinky3 준비 → fleet입니다.
각 로봇은 bringup 센서 수신 → Nav2 lifecycle/action → patrol ID 확인을 거칩니다.
현재 주소는 192.168.45.21 / .22 / .23, 도메인은 10 / 20 / 30,
로봇 workspace는 `/ws/kernel-robot-repo-4`, 지도는 각 로봇의 `~/cobot_map_v9.yaml`입니다.
키 인증·호스트 키·SSH 계정·지도 이미지가 필요합니다. 계정 공란은 실제 기동 전에 거절됩니다.
이미 관제 서비스를 실행 중이면 `fleet_startup --robots-only`를 사용합니다.

## 전체 시나리오 BT와 코드 역할

주문마다 실제 `py_trees.BehaviourTree`를 구성합니다. 상차·작업장 간 이동·하차·수령·복귀가
메모리 순차 노드로 실행되며, 정차 측정·재보정은 선택 노드와 안전 재시도 노드로 분기합니다.
`scenario.py`는 접수·배정·트리 수명만 관리합니다. 단계 전이표 `NEXT`는 제거했습니다.

| 파일 | 역할 |
|---|---|
| `fleet_control_node.py` | ROS 입출력과 타이머. 전체 주문 BT 실행 후 하위 주행 BT 실행 |
| `control_api.py` | 기존 웹 요청·응답 호환, 작업 생성·정지·해제 |
| `scenario.py` | 주문 검증·접수, 재고 예약, 로봇 배정, 주문별 BT 수명 |
| `scenario_tree.py` | 전체 업무의 순서·선택·재시도·실패 복귀 트리 조립 |
| `scenario_nodes.py` | 안전 감시, 주행·장치·실측 검증·정차 보정·수령·종결 BT 노드 |
| `scenario_runtime.py` | 주문별 실행 문맥, 예약·요청 전달·결과 대응·관측 기록 |
| `scenario_safety.py` | 트리 무효화·소프트 정지·현장 확인 복구 |
| `scenario_contracts.py` | 단계별 장치 요청 계약, 상태 집합, 입력 검증 |
| `scenario_repository.py` | 주문·재고·작업 구역·팔·통로·로봇 보류 영속화 |
| `service.py`, `behaviours.py` | 개별 주행의 명령 전달 → 실제 종료 확인 BT |
| `repository.py`, `contracts.py` | 단일 프로세스 SQLite 실행 원장과 주행 명령 검증 |
| `bt_visualization.py` | 실제 트리 상태·방문 기록 수집, 오프라인 JSON 내보내기 |
| `bt_viewer.py`, `docs/bt_viewer.html` | 원장 읽기 전용 실시간 조회 서버와 화면 |
| `web_profiles.py`, `control_center_web.py` | 기존 웹용 지점 내보내기와 웹 프로세스 기동 |
| `fleet_startup.py` | 관제에서 로봇까지 SSH 순차 기동 |

정상 경로: 상차 이동 → 후미 이탈 → 정차 실측·보정 → 마커 → 피킹 → 상차·적재 검증 →
상차 구역 이탈 → 하차 이동 → 후미 이탈 → 정차 실측·보정 → QR → 피킹 → 하차·배치 검증 →
고객 수령 → 하차 구역 이탈 → HOME → 후미 이탈 → 주문 종결.

개별 이동 버튼의 `type=create`는 주행 BT만 실행합니다. 전체 업무는 `type=order`를 접수해야 합니다.
웹 주문 엔드포인트·화면 연결은 기존 control-center에서 추가해야 합니다.
장치 결과 콜백은 현재 BT의 상태만 진행시키며 다음 장치 명령은 타이머에서 전달합니다.
정지·통신 단절 시 트리를 무효화하고, 재시작한 미종료 주문은 UNKNOWN으로 보류합니다.
운영자 복구는 이동·수령 체크포인트에서만 새 트리를 만들며 물리 작업을 임의 재실행하지 않습니다.

## 실시간 BT 뷰어

중앙 제어기와 별도 터미널에서 **같은 실행 원장 경로**를 지정합니다.

```bash
ros2 run cobot_fleet_control fleet_bt_viewer --db ~/.cobot/fleet_control.sqlite3
# 브라우저: http://127.0.0.1:8091
```

화면은 0.5초마다 원장을 읽어 주문 전체 BT와 개별 주행 BT를 선택해 표시합니다.
실행 중인 노드로 이동, 표시 일시정지·재개, 수신 이력 탐색이 가능하며 트리당 최근 200개를 보관합니다.
접속 시에는 트리별 최신 기록부터 받습니다. 과거 전체 기록이 필요하면 JSON 내보내기를 사용합니다.
밝은 테두리는 해당 갱신에서 방문한 노드이고, 노드의 SUCCESS가 유지되는 것은 재실행을 뜻하지 않습니다.
원장이 없으면 대기하고 DB를 만들지 않습니다. 쓰기·제어 API와 ROS 연결은 없습니다.
서버 종료·재시작 후 과거 기록도 읽을 수 있으므로 기록 시각과 현재 주문 상태를 함께 확인하세요.

```bash
# 주문별 전체 BT 기록을 나중에 분석할 때
ros2 run cobot_fleet_control fleet_bt_trace \
  --db ~/.cobot/fleet_control.sqlite3 --order-id order1 --output /tmp/order1.json
```

`bt_visualization.py`는 기록·내보내기, `bt_viewer.py`는 실시간 화면 제공을 담당합니다.
기존 단일 명령의 DB 직접 해제 CLI는 제거했고, 웹 작업 해제와 증거 기반 시나리오 복구를 사용합니다.
실행 경로가 없는 로봇 상태 중복 저장 함수·신규 테이블 생성과 시험 전용 재고 조회 함수도 제거했습니다.
웹 상태 수집은 기존 control-center가 담당합니다. 이전 DB에 남은 상태 이력은 삭제하지 않습니다.
ROS publish는 원격 수신 확인이 아니며, 배터리 만료는 상태 만료와 별도로 10초입니다.

## 시나리오와 외부 추론 PC

`config/scenario.yaml`의 배송 경로는 다음과 같습니다. 두 경로 모두 상차는 omx1, 하차는 omx2를 사용합니다.

| 주문의 route | 상차 지점 | 하차 지점 |
|---|---|---|
| `lab_delivery` | ZA | ZC |
| `lab_delivery_zb` | ZB | ZC |

두 주문은 각각 접수할 수 있으며, 같은 팔·ZC·통로 예약을 사용하는 단계는 자원을 기다립니다.
좌표는 `cobot_pinky_patrol/config/sites/lab.yaml`에서 관리합니다.
주문·수령·시나리오 복구는 내부 요청 타입이 준비돼 있고, 해당 HTTP 엔드포인트·화면은 기존 웹에 추가해야 합니다.
운영자가 실물 상차를 끝낸 경우 `/fleet_control`의 `manual_load_confirmation` 문자열 파라미터에
주문 ID·operator·note·evidence JSON을 넣어 기존 주문에 확인값만 반영합니다.
내부 `type=confirm_loaded` ROS 요청도 같은 경로를 사용합니다. 주문 ID·operator·note와
`evidence.sku`, `load_present=true`, `arm_safe=true`, `pickup_path_clear=true`를 전달합니다.
상차장 도착·정지·최신 통신·구역과 예약을 검증한 뒤 실제 구역 이탈부터 재개하며,
센서 결과와 구분한 `operator_load_confirmation`·`operator_completed` 및 감사 이벤트를 보존합니다.
수동 확인 명령·응답·감사 이력 조회 예시는 HTML의 [수동 상차 확인](../docs/central_scenario_control.html#manual-load)에 있습니다.
별도 추론 PC에는 아직 ROS·통신 API가 없으며 원격 HTTP 추론 제어는 별도 연동 작업입니다.
추론 코드·가중치·LeRobot·GPU 라이브러리를 이 패키지에 넣지 않습니다.

## 검증

```bash
python3 -m pytest src/cobot_navigation/cobot_fleet_control/test -q
```

control-center 패키지가 Python 경로에 있고 FastAPI/httpx가 설치돼 있으면
`test_control_center_integration.py`에서 **그 브랜치의 실제 HTTP·WebSocket 코드**로 시험합니다.
GitHub Actions에서도 b847b8e를 테스트 참조로 체크아웃하고 같은 검사를 수행합니다.
ROS 실물·DDS 시험은 별도이며 격리 도메인 77·localhost 조건에서만 실행합니다.

Docker 사용법은 [config/docker/README.md](config/docker/README.md)를 참고하세요.
