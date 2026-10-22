# FMS 인터페이스 명세 (S1 계약)

- 상태: 초안 (2026-10-22). 팀 리뷰 전이다.
- 결정 상태: 이 문서가 기대는 결정 D1(패키지)·D2(도메인)·D3(맵)·D4(정지 계열 예외)·D5(2단계 승인)는 모두 `proposed`(추천안) 이다. 관제 담당이 팀에 공지하면 `decided` 로 바꾼다. 그 전까지 이 문서의 값은 확정이 아니다.
- 정본: 메시지 정의의 정본은 `src/cobot_interfaces/` 의 `msg/`·`srv/`·`action/` 파일이다. 이 문서는 그 설명과 토픽·서비스·액션 표다. 둘이 다르면 파일을 따르고 이 문서를 고친다.
- 근거: FMS 관제 대시보드 아키텍처 설계서 v0.1 §2.4·§3·§4 (레포 밖 초안), System Requirements v5.0 (SR ID 는 인용만 한다).
- 관련 규칙: [`CLAUDE.md`](../CLAUDE.md) §3-4 (interfaces 패키지), §7 (ROS2 설계 규칙), `docs/fms_dev_rules.md` R3 (인터페이스 먼저).
- 판단이 들어간 값에는 '초안' 이라고 적었다.

## 1. 한눈에 보기

- 패키지: `cobot_interfaces` (ament_cmake, rosidl). 메시지 양식만 있고 동작 코드는 없다.
- 개수: msg 30, srv 5, action 2. (시험이 이 숫자를 본다. 바꾸면 여기도 고친다.)
- 옛 `fleet_msgs`(미병합 브랜치 `feature/setup-fleet-msgs-structure`)의 5종을 옮겨 확장했다 (D1 추천안).
- `FleetCommand` 의 원저작은 team11 pinky_fleet_msgs (Apache-2.0) 다. 표기는 `src/cobot_interfaces/NOTICE` 와 `package.xml` 에 있다. 나머지 4종은 team11 패키지에 없다 (대조 결과는 NOTICE).
- `DatasetSummary` 는 아직 넣지 않았다. D12(PT-23 공식 녹화 도구) 결정 뒤에 넣는다. 시험이 '없음' 을 본다.

```text
브라우저 ──REST/WS──▶ 게이트웨이(cobot_gui) ──서비스──▶ 관제 코어(fms_core)
                                                         │ 명령·하트비트 (도메인 10)
                                                         ▼
                         핑키 온보드 가드 ◀── 도메인 10 ──┘     Station PC 팔 노드
                         (도메인 10 ↔ 12 유일 교차점)            (도메인 10)
                                │ 도메인 12 (로봇 로컬)
                                ▼
                          Nav2 · AMCL · 모터
```

## 2. 처음 보는 사람을 위한 설명

- **메시지 양식**: 노드끼리 주고받는 데이터의 모양이다. 비전이 보낸 것을 주행이 알아들으려면 모양을 먼저 정해야 한다.
- **토픽**: 한쪽이 계속 내보내고 여러 쪽이 받는 길이다 (예: 로봇 상태 10 Hz).
- **서비스**: 묻고 답하는 길이다 (예: 게이트웨이가 관제 코어에 '정지해 달라' 고 요청).
- **액션**: 오래 걸리는 일을 맡기고 중간 경과와 결과를 받는 길이다 (예: 팔 상·하차).
- **세션 펜싱**: 관제가 다시 켜지거나 통신이 끊겼다 이어지면 세션 번호 `epoch` 를 올린다. 로봇은 옛 번호가 붙은 명령을 버린다 (SR-20). 명령마다 순번 `seq`, 유효 기한 `ttl_ms`, 맵 지문 `map_hash` 도 함께 본다.
- **서명 `sig`**: 펜싱 값은 상태 토픽으로 공개된다. 그래서 펜싱만으로는 가짜 명령을 막지 못한다. 명령이 관제 코어에서 왔다는 증거는 서명 하나다 (S3(P2) 필수, 키 관리는 D13).
- **ACK 와 물리 완료는 다르다**: `CommandAck` 는 '받았다' 는 뜻이다. 실제로 멈췄다·빠져나왔다는 `CompletionEvidence` 로 따로 온다 (SR-21).

## 3. ROS 도메인 (D2 추천안, proposed)

| ROS_DOMAIN_ID | 뜻 | 쓰는 쪽 |
|---|---|---|
| 10 | 실물 구동. 관제 명령·상태, 팔 명령·상태, 비전 이벤트 | 중앙 FMS PC 의 모든 노드, Station PC 팔 노드, 핑키 가드의 도메인 10 쪽 |
| 12 | Nav2 (자율주행) | 핑키 온보드 Nav2·AMCL·map_server·라이다, 핑키 가드의 도메인 12 쪽 |
| 100 | 개발·시뮬 전용. 실물 10·12 와 섞지 않는다 | 개발 PC, 가짜 발행기, 시뮬 |

- 근거: SR-19 는 도메인을 10(실물 구동)·12(Nav2)로 나눈다. README 의 `ROS_DOMAIN_ID=100` 은 이 표의 '개발·시뮬 전용' 뜻으로 읽는다. README 문구 정정은 별도 PR 로 한다.
- 두 도메인의 유일한 교차점은 **핑키 온보드 가드 하나**다. 가드는 한 프로세스에서 rclpy Context 를 두 개 연다 (도메인 10 쪽: 명령·하트비트 구독, 상태·ACK 발행 / 도메인 12 쪽: `navigate_to_pose` 액션 클라이언트, Nav2 속도 후보 구독). 이 방식은 PC 한 대 안에서 S1 스파이크로 확인했다 (§17, 2026-10-22). 핑키 실기(arm64)·여러 장비 사이·현장 망에서는 아직 확인하지 않았다. 현장 실측(D18) 뒤에 다시 본다.
- `domain_bridge` 는 쓰지 않는다. 쓰게 되면 그 설정 파일이 교차 토픽 목록의 정본이 되고, 명령 토픽은 넣지 않는다.
- 실물이 도는 망에서 개발 노드를 10·12 로 띄우지 않는다. `ROS_DOMAIN_ID` 는 임의로 바꾸지 않는다 (CLAUDE.md §9).
- 장비마다 자기 도메인을 스스로 보고한다. 다른 도메인의 참가자는 ROS API 로 보이지 않기 때문이다. 모은 값은 `DeviceDiag.ros_domain_id_reported` 에 실린다. 보고하는 노드의 메시지는 아직 정하지 않았다.
- 도메인 번호를 싣는 필드 둘(`DeviceDiag.ros_domain_id_reported`, `DiagSnapshot.ros_domain_id_configured`)은 같은 타입 `int16` 이다. −1 은 '모름' 이다. 화면이 두 값을 그대로 비교할 수 있게 맞췄다.
- 현장 AP 구성·RMW 벤더·핑키 3대의 실제 도메인은 아직 재지 않았다 (D18).

## 4. 네임스페이스 규칙

| 접두사 | 쓰는 쪽 | 예 |
|---|---|---|
| `/control_center/...` | 관제 코어(fms_core)·진단(fleet_monitor)·HW 판독 | `/control_center/safety_state` |
| `/control_center/<대상>/...` | 관제 코어가 대상 하나에게 보내는 것 | `/control_center/pinky_1/command`, `/control_center/omx_1/heartbeat` |
| `/navigation/<robot_id>/...` | 핑키 가드의 도메인 10 쪽 | `/navigation/pinky_1/status` |
| `/manipulation/<arm_id>/...` | Station PC 팔 노드·요약 노드 | `/manipulation/omx_1/status` |
| `/vision/...` | 비전 노드 | `/vision/camera_health` |
| `/pinky_<n>/...` | 핑키 온보드 스택 (도메인 12, 로봇 로컬) | `/pinky_1/navigate_to_pose`, `/pinky_1/scan` |

- 토픽 이름 안의 `<robot_id>` 는 핑키 이름(`pinky_1`~`pinky_3`), `<arm_id>` 는 팔 이름(`omx_1`~`omx_3`)이다.
- 주의: 메시지 필드 `robot_id` 는 메시지마다 뜻이 다르다.
  - `CommandHeader`·`CommandAck`·`FmsHeartbeat` 의 `robot_id` 는 '받는 대상' 이다. 핑키 이름과 팔 이름이 모두 들어간다.
  - `RobotStatus.robot_id` 는 핑키 이름이다.
  - `HandoverTask` Goal 에는 둘이 함께 있다. `header.robot_id` 는 이 Goal 을 받는 팔, `robot_id` 는 대상 핑키다.
  - 이름을 `target_id` 로 바꿀지는 §20 열린 질문이다 (설계서는 `robot_id`).
- 명령 토픽은 `/control_center/<대상>/command` 에 둔다. 발행자가 관제 코어 하나라는 것을 이름에서 보이려는 것이다 (SR-19 단일 제어권을 명령 토픽에 적용한 것, 설계 초안).
- 이름은 소문자 `snake_case` 이고 `/<namespace>/<name>` 꼴이다 (CLAUDE.md §7). `/emergency_stop` 처럼 역할 접두사가 없는 이름은 쓰지 않는다.
- 핑키 3대가 같은 도메인에서 네임스페이스 없이 `/cmd_vel`·`/scan` 을 쓰면 서로 섞인다. 그래서 온보드 스택은 `/pinky_<n>` 로 띄운다. 두 규칙의 조합은 주행 담당 확인이 필요하다 (초안).

## 5. TF frame 규칙 (초안, 주행 담당 합의 필요)

| frame | 뜻 |
|---|---|
| `map` | 모든 로봇이 함께 쓰는 맵 프레임 |
| `pinky_<n>/odom` | 로봇별 오도메트리 프레임 |
| `pinky_<n>/base_link` | 로봇별 본체 프레임 |
| `pinky_<n>/<센서>` | 로봇별 센서 프레임. 이름은 주행 담당이 정한다 |

- 좌표계는 REP-103(m, rad, 오른손 좌표)·REP-105 를 따른다. TF frame 이름은 이 표에 적은 것만 쓴다 (CLAUDE.md §7).
- 메시지의 위치는 모두 `map` 프레임이다: `RobotStatus.current_pose`, `FleetCommand` 의 `x`·`y`·`yaw`, `Waypoint` 의 작업점·정차점.
- 각도는 rad 다. 맵 YAML 이 deg 로 적었으면 읽을 때 바꾼다.
- 팔·카메라 frame 은 각 담당이 정해 이 표에 더한다.

## 6. QoS 프로필

| 이름 | 설정 | 쓰는 곳 | 이유 |
|---|---|---|---|
| 명령 | RELIABLE, VOLATILE, KEEP_LAST 10 | `FleetCommand`, `ArmCommand` | 늦게 붙은 로봇에게 지난 명령을 다시 보내지 않는다 |
| 하트비트 | BEST_EFFORT, VOLATILE, KEEP_LAST 1 | `FmsHeartbeat` | 재전송을 기다리지 않고 최신 값만 쓴다 |
| 텔레메트리 | BEST_EFFORT, VOLATILE, KEEP_LAST 1 | `RobotStatus`, `ArmStatus`, `CameraHealth`, `MediaHealth` | 링크를 수신 간격으로 판정한다. 재전송 지연이 간격으로 읽히면 안 된다 |
| 이벤트 | RELIABLE, VOLATILE, KEEP_LAST 50 (depth 초안) | `CommandAck`, `CompletionEvidence`, `AlarmEvent`, `VisionEvent`, `DropEvent` | 한 건도 잃지 않는다 |
| 설정성 상태 | RELIABLE, TRANSIENT_LOCAL, KEEP_LAST 1 | `FleetSafetyState`, `LaneLeaseState`, `MapInfo`, `HwEstopState`, `ArmMode`, `InventoryState`, `UnloadQueue`, `OrderStatus`, `Assignment` | 늦게 붙어도 마지막 값을 받는다 |
| 진단 | RELIABLE, VOLATILE, KEEP_LAST 1 (초안) | `DiagSnapshot` | 0.5 Hz 라 한 번 잃으면 공백이 길다 |
| 센서 | SensorDataQoS | 카메라·라이다 원본 | CLAUDE.md §7 |

- 한 토픽에 여러 대가 실리는 것(`CameraHealth`, `MediaHealth`)은 구독 depth 를 대수 이상으로 둔다 (초안).
- `OrderStatus`·`Assignment` 는 주문 1건씩 실린다. depth 1 이면 늦게 붙은 구독자는 마지막 주문만 받는다. 주문 전체를 받는 방법(depth 또는 조회 서비스)은 S2 에서 정한다.

## 7. 토픽 표

'메뉴' 칸은 메뉴 레지스트리(`src/cobot_gui/config/menu_tree.yaml`, S0 PR)의 `data_sources` 에 그 메시지가 적힌 메뉴 ID 다.

### 7.1 도메인 10 (실물 구동)

| 토픽 | 타입 | 발행 | 구독 | QoS | 주기 | 메뉴 |
|---|---|---|---|---|---|---|
| `/control_center/<robot_id>/command` | `FleetCommand` | fms_core (유일) | 핑키 가드 | 명령 | 명령마다 | — |
| `/control_center/<arm_id>/command` | `ArmCommand` | fms_core (유일) | 팔 노드 | 명령 | 명령마다 | — |
| `/control_center/<id>/heartbeat` | `FmsHeartbeat` | fms_core (유일) | 핑키 가드, 팔 노드 | 하트비트 | 20 Hz (제안·미측정, D11) | — |
| `/navigation/<robot_id>/status` | `RobotStatus` | 핑키 가드 | fms_core, 게이트웨이, fleet_monitor | 텔레메트리 | 10 Hz | 1.1, 2.1, 2.2, 5.5 |
| `/navigation/<robot_id>/command_ack` | `CommandAck` | 핑키 가드 | fms_core, 게이트웨이 | 이벤트 | 명령마다 | 2.4, 5.6 |
| `/manipulation/<arm_id>/command_ack` | `CommandAck` | 팔 노드 | fms_core, 게이트웨이 | 이벤트 | 명령마다 | 2.4, 5.6 |
| `/navigation/<robot_id>/completion_evidence` (이름 초안) | `CompletionEvidence` | 핑키 가드 | fms_core, 게이트웨이 | 이벤트 | 사건마다 | 2.4, 5.6 |
| `/manipulation/<arm_id>/completion_evidence` (이름 초안) | `CompletionEvidence` | 팔 노드 | fms_core, 게이트웨이 | 이벤트 | 사건마다 | 2.4, 5.6 |
| `/vision/completion_evidence` (이름 초안) | `CompletionEvidence` | 비전 노드 | fms_core, 게이트웨이 | 이벤트 | 사건마다 | 2.4, 5.6 |
| `/manipulation/<arm_id>/status` | `ArmStatus` | 팔 노드 (ROS 모드만) | fms_core, 게이트웨이 | 텔레메트리 | 10 Hz | 1.1, 3.1, 3.2, 5.5 |
| `/manipulation/<arm_id>/mode` | `ArmMode` | Station 요약 노드 (유일) | fms_core, 게이트웨이 | 설정성 | 변화 즉시 + 1 Hz | 1.1, 3.1, 5.5 |
| `/control_center/safety_state` | `FleetSafetyState` | fms_core | 게이트웨이 | 설정성 | 변화 즉시 + 2 Hz | 5.1, 5.3, 5.4 |
| `/control_center/lane_lease` | `LaneLeaseState` | fms_core | 게이트웨이, 가드(참고) | 설정성 | 변화 즉시 | 2.1, 5.5 |
| `/control_center/orders` | `OrderStatus` | fms_core | 게이트웨이 | 설정성 (§6 주의) | 변화 즉시 | 1.2, 2.4 |
| `/control_center/assignments` (이름 초안) | `Assignment` | fms_core | 게이트웨이 | 설정성 (§6 주의) | 변화 즉시 | 1.3 |
| `/control_center/unload_queue` (이름 초안) | `UnloadQueue` | fms_core | 게이트웨이 | 설정성 | 변화 즉시 | 1.3 |
| `/control_center/alarms` | `AlarmEvent` | fms_core, fleet_monitor | 게이트웨이 | 이벤트 | 사건마다 | 1.4, 2.5, 5.5 |
| `/control_center/hw_estop` | `HwEstopState` | estop_monitor (유일) | fms_core, 게이트웨이 | 설정성 | 변화 즉시 + 주기 (1 s 넘게 없으면 UNKNOWN) | 5.5 |
| `/control_center/map_info` | `MapInfo` | fms_core | 게이트웨이, 가드 | 설정성 | 시작·맵 교체 때 | 2.1, 2.3 |
| `/control_center/inventory` | `InventoryState` | fms_core | 게이트웨이 | 설정성 | 변화 즉시 | 1.2 |
| `/control_center/diag` | `DiagSnapshot` | fleet_monitor | 게이트웨이 | 진단 | 0.5 Hz | 6.1, 6.2, 6.3 |
| `/control_center/media_health` | `MediaHealth` | fleet_monitor | 게이트웨이 | 텔레메트리 | 경로마다 1 Hz | 4.1 |
| `/vision/camera_health` | `CameraHealth` | 비전 노드 (유일) | fms_core, 게이트웨이 | 텔레메트리 | 카메라마다 1 Hz | 4.1 |
| `/vision/events` | `VisionEvent` | 비전 노드 | fms_core, 게이트웨이 | 이벤트 | 사건마다 | 4.3 |
| `/vision/drop_events` (이름 초안) | `DropEvent` | 비전 노드 | — | 이벤트 | SR-17 단계 (MVP 미사용) | — |
| `/rosout` | `rcl_interfaces/msg/Log` (ROS 표준) | 모든 노드 | fleet_monitor | ROS 기본값 | — | 6.4 |

- '유일' 은 발행자가 하나뿐이라는 뜻이다. SR-19 단일 제어권을 토픽에 적용한 것이다 (설계 초안). fleet_monitor 가 명령 토픽 발행자 수를 센다: 0 = NO_PUBLISHER, 1 = 정상, 2 이상 = VIOLATION (`TopicDiag.single_writer_state`).
- 게이트웨이(`cobot_gui`)는 로봇 토픽을 하나도 발행하지 않는다. 구독만 한다.
- `FleetCommand`·`ArmCommand`·`FmsHeartbeat` 는 화면이 직접 읽지 않으므로 메뉴 칸이 비어 있다. 명령을 내는 메뉴는 §8 서비스 표에 있다.

### 7.2 도메인 12 (핑키 로컬, 주행 담당 확인 필요)

| 이름 | 종류·타입 | 발행·클라이언트 | 받는 쪽·서버 | 비고 |
|---|---|---|---|---|
| `/pinky_<n>/navigate_to_pose` | 액션 `nav2_msgs/action/NavigateToPose` | 핑키 가드 (유일 클라이언트) | Nav2 | 가드 밖의 goal 은 취소하고 BASE_HOLD (hold_reason `EXTERNAL_NAV_GOAL`) |
| `/pinky_<n>/cmd_vel` | 토픽, Twist 계열 (주행 담당이 정한다) | 핑키 가드 (유일) | 모터 드라이버 | 로봇 로컬 전용. 노출 방법은 주행 담당이 정한다 |
| `/pinky_<n>/initialpose` | 토픽 `geometry_msgs/msg/PoseWithCovarianceStamped` | 핑키 가드 (`CMD_SET_INITIAL_POSE`) | AMCL | |
| `/pinky_<n>/scan` | 토픽 `sensor_msgs/msg/LaserScan` | 라이다 드라이버 | Nav2, 가드 | SensorDataQoS |

### 7.3 이 PR 에 없는 것

| 데이터 | 메뉴 | 처리 |
|---|---|---|
| 천장 카메라 로봇 위치 (overhead pose) | 2.1 | 이름·타입은 비전 담당 계약으로 정한다 |
| `DatasetSummary` | 3.3, 3.4 | D12 결정 뒤에 넣는다 |
| 장비별 도메인 자기 보고 | 6.2 | 보고 메시지는 S2 에서 정한다. 모은 값은 `DeviceDiag` 에 있다 |
| 3.5 의 '도착 확정·팔 준비 상태' | 3.5 | `CompletionEvidence`·`ArmStatus` 에서 만든다 (S5) |
| 지도 PNG, `/api/v1/cameras`, `/api/v1/config` | 2.1, 4.2, 6.6 | ROS 메시지가 아니다. 게이트웨이 REST 다 |

## 8. 서비스 표 (도메인 10)

| 서비스 | 타입 | 클라이언트 → 서버 | 메뉴 (명령) |
|---|---|---|---|
| `/control_center/operator_command` | `OperatorCommand` | 게이트웨이 → fms_core | 1.4 ACK_ALARM, 2.4 SEND_MISSION·CANCEL_MISSION, 5.1 SET_MODE, 5.3 PAUSE·RESUME, 5.4 SOFT_LATCH·RESET·RECONCILE·APPROVE·START |
| `/control_center/console_lease` (이름 초안) | `ConsoleLease` | 게이트웨이 → fms_core | 5.1 콘솔 획득·갱신·반납 |
| `/control_center/submit_order` (이름 초안) | `SubmitOrder` | 게이트웨이 → fms_core | 보조 A 주문 호출 (메뉴 트리 밖, D14) |
| `/control_center/query_audit` (이름 초안) | `QueryAudit` | 게이트웨이 → fms_core | 1.5, 2.5, 3.6, 5.6 (읽기) |
| `/control_center/reconcile_report` (이름 초안) | `ReconcileReport` | 게이트웨이 → fms_core | 5.4 (읽기) |

- 브라우저는 ROS 에 닿지 않는다. 브라우저 → REST → 게이트웨이 → 이 서비스 → fms_core 순서다.
- 정지 계열(`PAUSE`, `SOFT_LATCH`)만 서명(`gw_sig`) 없이도 수행한다. 정지를 위조당해도 결과는 정지이기 때문이다. 나머지는 서명이 없으면 `BAD_SIGNATURE` 다 (S3(P2) 필수).
- 2단계 승인 (D5 추천안): `APPROVE` 는 Reconcile 항목마다 관제사가 현장 관측값을 입력한 `attest` 를 싣는다. 보고서와 다르면 `ATTEST_MISMATCH`. `APPROVE` 뒤 최소 체류 시간(제안 5 s) 전의 `START` 는 `APPROVAL_DWELL` 이다. 2인 승인·START 때 재인증은 설정으로 고른다. 이것이 SR-14 를 충족하는지는 팀이 정한다.

## 9. 액션 표 (도메인 10)

| 액션 | 타입 | 클라이언트 → 서버 | 쓰는 때 | 메뉴 |
|---|---|---|---|---|
| `/manipulation/<arm_id>/handover` | `HandoverTask` | fms_core (유일) → 팔 노드 | D7 이 FMS_TRIGGER 일 때만. 기본값 MANUAL_START 에서는 쓰지 않는다 | 3.2 |
| 이름 미정 | `RecoveryTask` | — | SR-17 단계에서 다시 정의한다. MVP 미사용 | — |

## 10. 원소 메시지

ROS 2 는 메시지 안에 이름 없는 구조체 배열을 둘 수 없다. 그래서 배열 원소는 따로 메시지를 둔다.

| 원소 | 실리는 곳 |
|---|---|
| `CommandHeader` | `FleetCommand.header`, `ArmCommand.header`, `HandoverTask` Goal `header` |
| `Waypoint` | `MapInfo.waypoints` |
| `DeviceDiag` | `DiagSnapshot.devices` |
| `TopicDiag` | `DiagSnapshot.topics` |
| `NodeDiag` | `DiagSnapshot.nodes` |
| `ReconcileItem` | `ReconcileReport` 응답 `items` |
| `InventoryItem` | `InventoryState.items` |
| `AuditEvent` | `QueryAudit` 응답 `events` (초안: 설계서에 이름이 없어 더했다) |

## 11. 펜싱 필드: 누가 채우고 누가 검증하나

| 필드 | 실리는 곳 | 채우는 쪽 | 검증하는 쪽 | 틀리면 |
|---|---|---|---|---|
| `sig`·`key_id` | `CommandHeader`, `FmsHeartbeat` | fms_core (대상별 키) | 핑키 가드, 팔 노드 | 명령: `REJECTED_SIGNATURE` (정지 계열은 정지만 수행). 하트비트: 워치독 미갱신 |
| `epoch` | `CommandHeader`, `FmsHeartbeat`, `RobotStatus`·`ArmStatus` 의 `epoch_accepted` | fms_core (영속) | 핑키 가드, 팔 노드 | 낮으면 `REJECTED_EPOCH`. 높으면 서명된 명령 헤더일 때만 채택하고 DISARMED. 하트비트의 높은 epoch 는 DISARMED 로 내리는 통지일 뿐 채택하지 않는다 |
| `seq` | `CommandHeader` | fms_core | 핑키 가드, 팔 노드 | `REJECTED_SEQ` |
| `hb_seq` | `FmsHeartbeat` | fms_core | 핑키 가드, 팔 노드 (명령과 다른 번호 공간) | 무시. 워치독 미갱신 |
| `issued_at` + `ttl_ms` | `CommandHeader` (5000 ms, SR-20), `FmsHeartbeat` (200 ms 제안) | fms_core | 핑키 가드, 팔 노드 (chrony 시계) | 명령: `REJECTED_TTL`. 시계를 모르면 구동만 `REJECTED_CLOCK_UNSYNCED`. 하트비트: 워치독 미갱신 |
| `map_hash` | `CommandHeader`, `FmsHeartbeat`, `RobotStatus.map_hash_loaded`, `MapInfo` | fms_core 와 로봇이 각자 계산 (§14) | 가드 (이동 계열), fms_core (상태 대조) | 이동은 `REJECTED_MAP_HASH`, 화면은 RED (`MAP_HASH_MISMATCH`) |
| `command_id`·`tx_id`·`order_id`·`task_id` | `CommandHeader` | fms_core | fms_core (원장 대조) | SR-21 역추적 실패 |
| `robot_boot_id` | `RobotStatus`, `ArmStatus` | 로봇·팔 | fms_core | 대상 UNKNOWN, lease UNKNOWN_BLOCKED, epoch +1, Reconcile 대상 |
| `client_request_id` | `OperatorCommand` | 브라우저 (게이트웨이가 전달) | fms_core | 같은 요청이면 같은 응답(`DUPLICATE`). 발행은 1회 |
| `console_token` | `OperatorCommand` | fms_core (`ConsoleLease`) | fms_core | `NO_CONSOLE` |
| `gw_sig`·`gw_nonce` | `OperatorCommand`, `ConsoleLease`, `SubmitOrder` | 게이트웨이 | fms_core | `BAD_SIGNATURE` (정지 계열 제외) |

`CommandAck`·`CompletionEvidence` 는 원인 명령의 `command_id` 를 싣는다 (`CompletionEvidence` 는 `task_id` 도). 나머지 ID(`tx_id`·`order_id`)는 원장의 COMMAND_ISSUED 기록에서 `command_id` 로 잇는다.

### 11.1 가드의 명령 판정 순서 (제안, 주행·매니퓰레이터 담당 구현)

0. 서명이 틀리면 `REJECTED_SIGNATURE`.
1. `robot_id` 가 자신이 아니면 `REJECTED_ROBOT_ID`.
2. `epoch` 가 받아들인 값보다 낮으면 `REJECTED_EPOCH`. 높으면 그 epoch 를 받아들이고 seq 기록을 비우고, last_goal 을 버리고, Nav2 goal 을 취소하고 DISARMED 로 간다.
3. `seq` 가 마지막 수락 값 이하면 `REJECTED_SEQ`.
4. 시계 오프셋을 모르거나 허용치(제안 ±50 ms)를 넘으면 구동 명령만 `REJECTED_CLOCK_UNSYNCED`.
5. 지금 시각이 `issued_at + ttl_ms` 를 넘었으면 `REJECTED_TTL`.
6. 이동 계열인데 `map_hash` 가 로드한 맵과 다르면 `REJECTED_MAP_HASH`.
7. 지금 상태가 허용하지 않으면 `REJECTED_STATE` (예: DISARMED 에서 RESUME).
8. 모두 통과하면 `ACCEPTED`.

- **정지 계열 예외 (D4 추천안, proposed)**: STOP·CANCEL·SOFT_LATCH·HOLD 는 0~7 중 하나에 걸려도 정지는 수행한다. 결과 코드는 그대로 보내고 `stop_executed=true` 를 싣는다. 이때 epoch·seq 는 바꾸지 않고 워치독도 갱신하지 않는다.
- **워치독**은 유효한 하트비트로만 갱신한다 (서명·epoch·hb_seq·map_hash·기한 모두 맞을 때. 이 유효 조건은 설계 초안이고, 서명은 D13). 명령은 워치독을 갱신하지 않는다. 그래서 '거부된 명령은 워치독 미갱신' (SR-20)이 저절로 지켜진다.
- 하트비트가 200 ms 넘게 끊기면 로봇이 로컬 워치독으로 스스로 BASE_HOLD 정지한다 (SR-14). 그 뒤 `LINK_LOST` 로 래치하는 것은 설계 초안이다 (D4).
- **통신 순단 복구 (D4 추천안)**: 통신이 복구되면 epoch +1 이다 (SR-20). 대상을 DISARMED 로 두는 것은 D4 추천안이다. 하트비트가 다시 와도 래치는 풀리지 않는다. 풀려면 Reconcile → 승인 → 새 epoch 의 서명된 START 다.

## 12. 값 규칙

1. 로봇·팔에 가는 명령 번호와 가드 판정 결과는 `uint8` 상수다: `FleetCommand.command`, `ArmCommand.command`, `FmsHeartbeat.fleet_mode`, `CommandAck.result`, `CompletionEvidence.kind`.
2. 그 밖의 상태·종류·사유 값은 `string` 상수다 (v1 `RobotStatus.state` 처럼). 상수 이름은 `UPPER_SNAKE_CASE`, 값은 상수 이름의 뒷부분이다 (예: `STATE_DISARMED="DISARMED"`). **빈 문자열은 '모름' 으로 다룬다.**
3. 필드에 기본값을 두지 않는다. 비어 있는 명령(서명 없음, `ttl_ms` 0)은 검증에서 거부된다. 시험이 본다.
4. 주의: 기본값 0 이 안전하지 않은 곳이 셋 있다. `FleetCommand.CMD_GOTO=0` (v1 번호 유지), `CommandAck.ACCEPTED=0`, `FmsHeartbeat.MODE_RUN=0` (설계 초안 번호). 서명·검증이 막지만, 만드는 쪽은 이 필드를 반드시 채운다. 번호를 바꿀지는 팀이 정한다 (§20). 새로 만든 `ArmCommand` 는 `CMD_HOLD=0` 으로 가장 안전한 값을 0 에 두었다.
5. `ESTOP` 이라는 이름은 HW 릴레이 전용이다 (`hw_estop*` 필드, `HW_ESTOP_*` 상수, `HwEstopState`). 소프트웨어 정지는 `SOFT_LATCH` 계열 이름만 쓴다. 시험이 본다.
6. 숫자 필드에는 같은 줄 주석에 단위를 적는다: `[m]`, `[rad]`, `[ms]`, `[%]` 등. 단위가 없는 정수는 `[-]` 또는 `[개]` 다. 이름이 `_ms`·`_mm`·`_deg`·`_sec`·`_hz`·`_percent` 로 끝나면 그 단위가 있어야 한다. 시험이 본다.
7. 미계측 실수는 `NaN` 이다 (예: `battery_percentage`). 0 으로 채우지 않는다. 시계 오프셋은 `clock_offset_known` 이 false 면 '모름' 이다.
8. `epoch` 는 1 부터 쓴다. `epoch_accepted` 0 은 '아직 받은 적 없음' 이다 (초안).

## 13. 물리 증거(`CompletionEvidence`) 단위 표 (초안)

| kind | value 단위 | threshold 뜻 | 원천 |
|---|---|---|---|
| `ENCODER_VEL_ZERO` | [m/s] | 이 속도 이하가 지속 | 핑키 가드 (엔코더) |
| `BASE_HOLD_ENGAGED` | [-] 1 = 체결 | — | 핑키 가드 |
| `ARM_RETRACT_SAFE` | [mm] 팔 끝 높이 Z | 280 (SR-10) | 팔 노드 |
| `LOAD_SENSOR_PRESENT` | 센서별 (D6) | 센서별 | 미정 (D6) |
| `GRIPPER_HOLD_OK` | 센서별 (D6) | 센서별 | 팔 노드 |
| `TAIL_EXIT_CONFIRMED` | [-] 1 = 퇴장 확인 | — | 비전 (게이트 카메라). 캡처 시각 검증(`age_basis=CAPTURE`)과 프레임 나이 200 ms 이하일 때만 `measured=true` (SR-05, SR-07) |
| `ZONE_PRESENT` | [-] 1 = 구역 안 | — | 비전 (천장 카메라, 보조 증거) |

- `measured=false` 는 PASS 가 아니다. 센서가 없으면 '미계측' 이고 출발은 보류된다 (SR-10, SR-21).

## 14. map_hash

- 형식: sha256 16진 문자열 64자.
- 계산법과 입력 파일은 맵 계약 문서 `docs/fms_map_contract.md` (D3, S1 맵 PR `feature/common-map-contract`)가 정본이다. 이 문서는 계산법을 따로 적지 않는다. 두 곳에 적으면 언젠가 어긋나기 때문이다. 두 PR 의 머지 순서에 따라 그 파일이 잠시 없을 수 있다.
- 맵 정본은 Floor Map 1021 도면 + 아래 벽에 붙은 67 cm 게이트(`map_shoe_store_1021_gate67`)이고, 공통 패키지 `cobot_bringup` 의 `config/maps/` 에 둔다 (D3 추천안, S1 맵 PR).
- `LaneLeaseState` 의 '단일 통로' 는 맵 정본의 게이트(폭 0.67 m, 창고 쪽 실제 통행 0.45 m)다. SR v5.0 SR-05 의 0.8 m 와 다르다 (SR_v2 대조 전, `docs/fms_map_contract.md` 8절).
- 쓰는 곳: `CommandHeader.map_hash`, `FmsHeartbeat.map_hash`, `RobotStatus.map_hash_loaded`, `MapInfo.map_hash`.
- 작업점(`Waypoint.work_*`)과 Nav2 정차점(`Waypoint.approach_*`)을 나눈다 (D3 추천안). 정차점 값은 초안이고 주행 담당 확인이 필요하다.

## 15. v1(fleet_msgs) 에서 바뀐 것

| v1 | v2 (`cobot_interfaces`) |
|---|---|
| 패키지 `fleet_msgs` | `cobot_interfaces` (접두사 `cobot_`, D1) |
| `FleetCommand` | `CommandHeader header` 추가 (펜싱·서명). `CMD_RESET=8`·`CMD_START=9`·`CMD_SOFT_LATCH=10` 추가. `CMD_HEARTBEAT=7` 은 번호만 남기고 뜻을 폐기 (v2 가드는 무시하고 워치독을 갱신하지 않는다). `waypoint_id`·`lane_lease_id`·`lease_valid_until` 추가. 단위 주석 |
| `RobotStatus` | `timestamp` → `header`. `robot_boot_id`, 상태 값 PAUSED·DISARMED·SOFT_LATCH·LINK_LOST 추가 (RECOVERING 은 SR-17 용으로 유지), 속도, `motor_power_present`, `base_hold_engaged`, 펜싱 반향, `map_hash_loaded`, 도킹 오차, 시계 오프셋, Nav2 클라이언트 수 |
| `HandoverTask` | `CommandHeader` 추가. `station_id`(STATION_S1/S2/HOME) → `waypoint_id`(PRD_3 이름), `item_type` → `sku`. RETRACTING 단계, `retract_safe`·`load_confirmed`·`evidence_ids`·`error_code` 추가 |
| `DropEvent`, `RecoveryTask` | 그대로 옮겼다 (단위 주석만 더함). PRD_v2 어휘가 남아 있다. SR-17 단계에서 다시 정의한다 |

- `CMD_HEARTBEAT` 의 뜻 바꿈은 호환이 아니다. v1 가드와 v2 관제를 섞어 쓰지 않는다.
- 옛 정의의 사본은 `src/cobot_interfaces/test/fixtures/fleet_msgs_9e51d4d/` 에 있다. 스키마 시험이 그 사본에서는 실패하는 것을 본다 (음성 대조). 사본이 스냅샷과 같은지도 sha256 으로 본다.
- v1 필드는 v2 에 남아 있거나, 기록된 이름 바꿈(`timestamp`→`header`, `station_id`→`waypoint_id`, `item_type`→`sku`)이어야 한다. 시험이 본다.

## 16. 설계서와 다르게 한 것 (초안 판단)

| 설계서 | 이 PR | 이유 |
|---|---|---|
| `RobotStatus.clock_offset_ms`, INT32_MIN = 모름 | `clock_offset_known` (bool) + `clock_offset_ms` | 기본값(false)이 '모름' 이 되게 했다. 최솟값 상수는 생성 코드에서 다루기 까다롭다 |
| §3.4 의 열거 값 (타입 미정) | `string` 상수 | §12 규칙 2. v1 `RobotStatus.state` 와 같은 방식 |
| `ArmCommand` 명령 번호 (미정) | `CMD_HOLD=0` | 기본값을 가장 안전한 값으로 |
| `CompletionEvidence` 에 ID 없음 | `evidence_id` 추가 | `LaneLeaseState.tail_exit_evidence_id`·`HandoverTask` 결과 `evidence_ids` 가 가리킬 값이 필요하다 |
| `VisionEvent` | `event_id`·`age_basis` 추가 | 증거로 가리키고, 캡처 시각 검증 여부를 실으려고 |
| `ArmStatus` | `retract_safe_measured`·`last_seq_accepted` 추가, `WORK_STEP_DONE` 추가 | 출발 게이트가 '미계측' 을 구분해야 한다. 'VERIFYING 이후' 를 나타낼 값이 필요하다 |
| `Waypoint` (id, work_pose, approach_pose) | `x`·`y`·`yaw` 실수 필드로 풀고 `arm_id` 추가 | 단위 주석을 달 수 있게. `arm_id` 는 출발 게이트 조건 1 (연계된 팔) 에 쓴다 |
| `MapInfo` | `width`·`height` 추가 | 지도 그리기용 |
| `QueryAudit` events[] 원소 타입 없음 | `AuditEvent` 추가 | 원소 메시지가 필요하다 |
| `ConsoleLease`·`SubmitOrder` 에 nonce 없음 | `gw_nonce` 추가, `SubmitOrder.requester_id` 추가 | 서명 재전송 방지, 원장 actor_id |
| `HandoverTask` Goal 에 `order_id` | 빼고 `header.order_id` 를 쓴다 | 같은 값이 두 곳에 있지 않게 |
| `ReconcileItem.match` | `matched` | 일부 언어의 예약어를 피하려고 |
| OrderStatus 행의 `exclusion_reason` | `Assignment.excluded_robot_ids`·`exclusion_reasons` 로 옮김 | 배정에서 뺀 이유는 로봇마다 붙는 값이다 |
| `OrderStatus` | `order_id`·`sku`·`qty`·`table_id` 추가, 단계 이력은 `stage_history`·`stage_entered_at` 두 배열 | 주문 1건을 혼자 읽을 수 있게 |
| `AlarmEvent` | `active`·`detail` 추가 | 풀렸는지와 사람이 읽는 설명 |
| `MediaHealth.frozen` (해시를 못 보면 UNKNOWN) | `frozen_state` 문자열 (LIVE·FROZEN·UNKNOWN) | bool 로는 '모름' 을 나타낼 수 없다 |
| `ConsoleLease` 응답 `holder` | `holder_id`·`holder_role` | 화면이 역할도 보여야 한다 |
| `SubmitOrder` 응답 | `reject_code` 추가 | 거부·예외 사유 |
| `QueryAudit` 의 '기간' | `from_time`·`to_time` | `from` 은 예약어다 |
| `HwEstopState`·`AlarmEvent` 등 | `std_msgs/Header` 로 시각을 싣는다 | 측정 시각을 한 방식으로 |
| 맵 YAML 위치 `cobot_navigation/config/` 권고 | 공통 패키지 `cobot_bringup/config/maps/` (맵 PR) | 주행 담당 패키지를 요청 없이 고치지 않으려고 |

## 17. 두 도메인 스파이크 (S1 검증 로그로 갱신)

- 스크립트: `scripts/spikes/two_domain_context_check.py` (CLAUDE.md §2 의 `scripts/` 보조 스크립트 자리. 구조도에 `scripts/spikes/` 를 적을지는 §20)
- 하는 일: 한 프로세스에서 rclpy Context 를 도메인 A 에 둘, 도메인 B 에 둘 연다. 같은 토픽 이름으로 서로 주고받는다. 같은 도메인 상대의 메시지는 받아야 하고, 다른 도메인 메시지는 0건이어야 통과다.
- 로봇 없이, 몇 초 안에 끝난다. 기본으로 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 로 돌아서 현장 망에 패킷을 내보내지 않는다.
- 기본 도메인은 개발 전용 번호 100·101 이다 (초안). 실물 번호 10·12 는 인자로 적을 때만 쓴다. 실물 번호와 `--allow-network` 를 함께 주면 돌지 않는다.
- 종료 코드: 0 = 통과, 1 = 실패, 2 = 환경 오류.
- 실행:

  ```bash
  source /opt/ros/jazzy/setup.bash
  python3 scripts/spikes/two_domain_context_check.py                          # 개발 번호 100·101
  python3 scripts/spikes/two_domain_context_check.py --domain-a 10 --domain-b 12   # D2 실물 번호, 한 PC 안
  echo $?
  ```

| 날짜 | 환경 (OS · ROS · RMW) | 명령 | 종료 코드 | 요약 |
|---|---|---|---|---|
| 2026-10-22 | Ubuntu 22.04 호스트 위 `ros:jazzy-ros-base` 컨테이너 · Jazzy · `rmw_fastrtps_cpp` (기본값) · LOCALHOST · 한 프로세스, PC 한 대 | 당시 기본값(10·12)으로 실행. 지금의 `--domain-a 10 --domain-b 12` 와 같다 | 0 | 통과. 1.67 s. Context 4개(10 가드·10 상대·12 가드·12 상대)가 같은 도메인 상대 메시지를 각각 14~15건(보낸 16건 중) 받았고, 다른 도메인 메시지는 0건이었다. 컨테이너 망을 끊고(`--network none`) 5번 돌려도 같았다 |

- 이 검사는 실패할 수 있다: 도메인 12 Context 를 몰래 10 으로 여는 복사본은 종료 코드 1 로 실패했다 (음성 대조). 두 도메인 번호를 같게 주거나 ROS 를 source 하지 않으면 종료 코드 2 다.
- 확인하지 못한 것: 여러 장비 사이, CycloneDDS, 실제 Nav2, 핑키 실기(arm64). 그래서 D2 공지에는 '(PC 한 대 스파이크 통과, 핑키 실기 재확인 예정)' 을 붙인다.
- 스크립트 린트: 이 파일은 어느 패키지에도 속하지 않아 `colcon test` 가 린트를 돌리지 않는다. 같은 날 Jazzy 컨테이너에서 `ament_flake8`·`ament_pep257`·`ament_copyright` 를 직접 돌려 모두 통과했다. 위 기본 도메인 변경 뒤에는 다시 돌려야 한다.
- 이 스파이크는 가드 노드의 실현성만 본다. 실물 망(서로 다른 장비)에서의 발견은 현장 실측(D18) 뒤에 따로 본다.

## 18. 검사 방법

ROS 가 없는 PC 에서 (글자 시험만):

```bash
python3 -m pytest src/cobot_interfaces/test/test_interface_schema.py
```

ROS 2 Jazzy 에서 (빌드 + 전체 시험 + 린트):

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_interfaces
source install/setup.bash
colcon test --packages-select cobot_interfaces
colcon test-result --verbose
```

- ROS 를 설치하지 않은 PC 는 도커 개발 환경 안내 `docs/dev_docker_guide.md` (S1 도커 PR `feature/common-docker-dev-guide`)를 따라 Jazzy 컨테이너에서 위 명령을 돌린다. 두 PR 의 머지 순서에 따라 그 파일이 잠시 없을 수 있다.
- 시험이 보는 것:
  - (a) `test_interface_schema.py`: 필수 펜싱·상태 필드와 상수, 원소 메시지, 이름·단위 주석 규칙, `CMakeLists.txt`·`package.xml` 목록과 의존성, 린트 등록 이름, 원저작 표기, v1 필드 승계, 이 문서에 모든 인터페이스가 있는지. 옛 fleet_msgs 사본과 일부러 고친 정의에서는 실패하는 것도 본다.
  - (b) `test_generated_types.py`: 빌드로 생긴 Python 타입을 import 해서 필드 이름·상수 값이 정의와 같은지, 직렬화가 되는지 본다.
  - 린트: `copyright`·`flake8`·`pep257` 세 시험이 `test/` 의 Python 파일을 본다 (C++ 소스 없음). `package.xml` 에 `ament_cmake_copyright`·`ament_cmake_flake8`·`ament_cmake_pep257` 으로 적어야 `colcon test` 에 등록된다. `ament_flake8` 처럼 적으면 경고 없이 빠진다. (a) 가 이 이름을 본다.
- 린트가 정말 등록됐는지는 `colcon test-result --verbose` 목록에 `copyright`, `flake8`, `pep257` 이 보이는지로 확인한다. 셋이 안 보이면 린트는 돈 것이 아니다.
- skip 은 통과가 아니다. (b) 는 import 가 안 되면 실패한다.

검사 기록:

| 날짜 | 환경 | 결과 |
|---|---|---|
| 2026-10-22 | Jazzy 컨테이너, 고치기 전 `package.xml` (`ament_flake8` 등) | 등록된 시험 2개뿐 (`test_interface_schema`, `test_generated_types`). 린트가 돌지 않았다 |
| 2026-10-22 | 같은 환경, `test_depend` 만 `ament_cmake_*` 로 바꾼 복사본 | 등록된 시험 5개 (위 2개 + `copyright`·`flake8`·`pep257`). 111건 통과, 실패·오류·skip 0 |
| 2026-10-22 | 노트북 (ROS 없음) | (a) 만 돌 수 있다. (b)·린트·빌드는 돌지 않는다 |

- 위 두 번째 줄은 지금 파일과 `test_depend` 가 같은 복사본으로 잰 것이다. 이 PR 의 최종 파일로 Jazzy 에서 한 번 더 돌려 이 표를 갱신한 뒤 머지한다.

## 19. 바꾸는 법

1. `src/cobot_interfaces/` 의 파일을 고친다. 필드는 `snake_case`, 상수는 `UPPER_SNAKE_CASE`, 숫자 필드에는 단위 주석.
2. 파일을 더하거나 지웠으면 `CMakeLists.txt` 목록, 이 문서(§1 개수, 표), `test_interface_schema.py` 의 개수를 같이 고친다.
3. 펜싱·안전 필드를 바꾸면 `test/interface_schema.py` 의 계약 표도 고친다.
4. 위 §18 의 시험을 돌린다.
5. PR 에 바뀐 점을 적고, 팀에 알린 뒤, 1명 이상 리뷰를 받아 머지한다 (CLAUDE.md §3-4, §9).
6. 이 패키지를 쓰는 패키지를 다시 빌드한다.

## 20. 열린 질문 (팀 확인 필요)

- `test/` 폴더 (예외 승인 요청): CLAUDE.md §3-4 는 interfaces 패키지에 `msg/`·`srv/`·`action/`·`docs/` 만 둔다고 한다. 이 PR 은 `test/` 에 Python 검사 코드(약 1,200줄)와 옛 정의 사본(`test/fixtures/`)을 둔다. PR 본문에 예외로 적어 리뷰에서 승인받는다.
  - 둔 이유: 시험은 동작 코드가 아니다. `test/` 는 §3-1 의 표준 폴더다. ament_cmake 패키지가 `ament_cmake_pytest` 로 Python 시험을 두는 것은 ROS 의 보통 방식이고, 패키지 빌드 방식(ament_cmake)은 하나다.
  - 다른 패키지(예: `cobot_control_center/test/`)로 옮기지 않은 이유: 검사는 이 패키지의 `.msg` 원본과 `CMakeLists.txt`·`package.xml` 을 읽는다. 다른 패키지가 남의 소스 폴더를 읽게 되면 §3-6 의 취지(패키지끼리 코드를 직접 가져다 쓰지 않는다)와 어긋난다.
  - 승인되면 CLAUDE.md §3-4 에 '`test/` 는 둘 수 있다' 한 줄을 규칙 PR 로 더한다.
- `scripts/spikes/` 자리: 두 도메인 스파이크(§17)는 레포 루트 `scripts/` 아래에 있다. CLAUDE.md §2 는 `scripts/` 를 '보조 스크립트' 자리로 두지만, `docs/fms_dev_rules.md` R4 는 새 자리를 구조도에 먼저 적으라고 한다. S1 규칙 PR 의 구조도에 `scripts/spikes/` 한 줄을 더할지, 스크립트를 별도 브랜치로 나눌지 정한다.
- 필드 이름 `robot_id` → `target_id`: `CommandHeader`·`CommandAck`·`FmsHeartbeat` 의 `robot_id` 에는 팔 이름도 들어간다 (§4). 쓰는 코드가 없는 S2 전에 바꾸는 것이 가장 싸다. 설계서는 `robot_id` 다.
- 기본값 0 이 안전하지 않은 번호 셋(§12-4)을 바꿀지.
- `OrderStatus`·`Assignment` 의 늦게 붙은 구독자 처리 (§6).
- '이름 초안' 이라고 적은 토픽·서비스 이름, TF frame 이름 (§5), `/pinky_<n>/cmd_vel` 노출 방법 (§7.2).
- 장비별 도메인 자기 보고 메시지 (§3).
