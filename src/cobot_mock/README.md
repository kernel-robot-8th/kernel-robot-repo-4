# cobot_mock

로봇 없이 관제를 개발·시연하기 위한 **가짜 핑키**(와 가짜 팔) 패키지입니다.
실제 순찰 노드(`cobot_pinky_patrol`)와 zone_manager 의 규격대로 이벤트를 내고 명령을 받습니다.

- 관제 PC 쪽(브릿지를 지난 뒤) 토픽 이름을 그대로 쓰므로, 관제 코드는 진짜인지 가짜인지 구분하지 못합니다.
- 다른 패키지는 이 패키지에 의존하지 않습니다. **폴더째 빼도 됩니다** (아래 '빼는 법').

담당: 김지혜 · 환경: Ubuntu 24.04 / ROS 2 Jazzy / Python 3.12

## 안전

- **격리 도메인에서만 돕니다.** `ROS_DOMAIN_ID` 가 비었거나 `0`·`10`·`12`·`20`·`30`·`100`(실물)이면 시작을 거부합니다.
  가짜 `/pinkyN/*` 가 진짜 관제에 섞이면 관제가 가짜 로봇을 진짜로 믿기 때문입니다.
- 가짜 팔(아래)은 팔 노드에 도메인 검사가 없어서, `mock_fleet.launch.xml` 이 실물 도메인이면 **팔 노드를 띄우지 않습니다**.
- `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 로 이 PC 안에서만 보이게 씁니다 (아니면 경고).
- 장치·Nav2 를 쓰지 않습니다. 위치는 직선으로 옮기는 흉내입니다.
- 관제 상세 화면 직접 조종을 시험할 수 있게 `/pinkyN/cmd_vel` 을 받아 위치를 적분합니다 (작업 중이 아닐 때만, 0.5초 동안 명령이 없으면 섬, 벽은 무시).

## 실행

`cobot_control_center` 를 `.venv` 에서 빌드한 상태여야 합니다 ([`cobot_control_center/README.md`](../cobot_control_center/README.md#처음-설치)).

```bash
source /opt/ros/jazzy/setup.bash && source .venv/bin/activate
python -m colcon build --symlink-install --packages-up-to cobot_mock
source install/setup.bash

export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_mock mock_fleet.launch.xml
```

가짜 핑키 3대와 관제 노드(`fleet_status_node`, `fleet_api_node`, 작업 노드 `fleet_control_node`)가 함께 뜹니다.
작업 노드는 **실물과 같은 fleet_control** 이고, 가짜 핑키도 실물 순찰 노드처럼 하트비트·세션·순번을 통과한 명령만 받습니다 (시계 비교·TTL 은 실물처럼 하지 않음) (`central_controlled: true`). 작업 명령은 켜진 채로 시작합니다 (격리 도메인이라). 화면은 `http://localhost:8181/` 입니다 (실물 관제 8080 과 겹치지 않게 나눔, `port:=` 로 바꿀 수 있음)
(노트북에서는 `ssh -N -L 8181:127.0.0.1:8181 <사용자>@<관제 PC>` 후 같은 주소).

| 인자 | 기본값 | 뜻 |
|---|---|---|
| `auto_patrol` | `false` | 쉬는 로봇이 스스로 무작위 명령(goto·zone·leave·home)을 냄. 중앙 모드(`central_controlled: true`)라 켜도 꺼짐 (fleet 만 명령) |
| `dropout_robot` | `''` | 주기적으로 끊기는 로봇 ('끊김' 화면 시험 때 `pinky3`) |
| `with_control_center` | `true` | 관제 노드를 함께 띄울지 |
| `allow_raw_cmd` | `true` | 관제 화면의 개발용 수동 명령 칸 (검사 없이 `patrol_cmd` 에 문자열, fleet 이 세션 봉투를 붙임). 실물 관제는 기본 꺼짐 |
| `port` | `8181` | 관제 화면 포트. 실물 관제(8080)와 한 PC 에서 함께 띄울 수 있게 나눔 |
| `points_dir` | `cobot_pinky_patrol/config` (install) | 순찰 설정 폴더 (`common.yaml`·`sites/`·`robots/`, 또는 합친 `pinkyN.yaml`) |
| `site` | `lab` | `sites/` 의 현장 이름 |
| `zone_params` | `cobot_zone_traffic_control/config/zone_params.yaml` (install) | 구역 대기 슬롯 설정 |
| `arms` | `true` | 가짜 팔 3대(omx1~3)를 띄울지 (실물 도메인이면 켜도 안 뜸) |
| `arm_fake_duration_sec` | `6.0` | 가짜 팔 작업 하나가 성공하기까지 [s] |

### 가짜 팔

가짜 핑키와 달리 따로 만든 흉내 노드가 아니라, **실제 팔 노드**(`cobot_manipulation` 의 `arm_adapter_node`)를 `backend:=fake` 로 띄운 것입니다.

```text
arm_adapter_node
 ├─ 판단: 켜기·끄기 판정, 정지, epoch·seq, 작업 요청 검사, ArmStatus·CommandAck·작업 결과 발행  ← 진짜 그대로
 └─ 백엔드: fake = 팔을 열지 않고 arm_fake_duration_sec 기다렸다가 성공이라고 답함            ← 여기만 가짜
```

- 보드 탐지는 `config/mock_serial_by_id/` 의 **빈 파일 이름**과 `config/mock_arm_registry.yaml` 의 가짜 시리얼로 통과합니다. 팔 노드는 이름만 읽고 장치를 열지 않습니다.
- 처음에는 꺼짐입니다. 관제 화면 로봇팔 칸에서 **켜기** 뒤 작업 시험을 보낼 수 있습니다.
- 흉내 내지 않는 것: 작업 실패(작업 중 **정지**로만 실패가 남), 관절 값(없음), 퇴피 측정(늘 미측정), 모터 오류.
- 끊김을 보려면 그 팔 노드 프로세스(`omx1_adapter` 등)를 끕니다.

## 흉내 내는 것

| 토픽 | 타입 | 내용 |
|---|---|---|
| `/pinkyN/patrol_status` | `std_msgs/String` | `{"state", "waypoint", "detail", "time", "held_zone", "arrived_zone", "busy", "central_controlled", "central_latched", "boot_id"}`. 바뀔 때 + 1초마다 (실물과 같음) |
| `/pinkyN/amcl_pose` | `PoseWithCovarianceStamped` | 5 Hz, `frame_id=map` |
| `/pinkyN/battery/percent`, `/pinkyN/battery/voltage` | `std_msgs/Float32` | 1 Hz. 이동 중 1 %/분, 대기 0.2 %/분 감소, 15 % 아래면 홈에서 충전 |
| `/zone_manager/status` | `std_msgs/String` | `A:free` / `A:occupied_by:pinky1`. 바뀔 때 + 1초마다 |
| `/zone_manager/queue_slot` | `std_msgs/String` | `A:pinky2:0:<x>,<y>,<yaw>` (대기 로봇마다, k=0 이 맨 앞). 바뀔 때 + 1초마다 (zone_manager 와 같은 형식) |
| 구독 `/pinkyN/patrol_cmd` | `std_msgs/String` | 아래 명령 |
| 구독 `/pinkyN/initialpose` | `PoseWithCovarianceStamped` | 관제 화면 초기위치 버튼. 멈춰 있을 때만 가짜 위치를 그 자리로 옮김 (이동 중이면 무시) |
| 구독 `/pinkyN/fleet_heartbeat` | `std_msgs/String` | 중앙 모드일 때. 움직이던 중 세션이 바뀌거나 3초 끊기면 비상정지·정지 잠금 (놀던 로봇은 잠그지 않음, 끊긴 동안만 명령 거절) |

**규격 v2** (`spec_versions: [v1, v2]` 로 켤 때만, 기본은 v1 만. fleet 은 v1 만 씀): [`cobot_patrol_interfaces`](../cobot_patrol_interfaces/README.md) 메시지도 함께 냅니다.

| 토픽 | 타입 | 내용 |
|---|---|---|
| 구독 `/pinkyN/patrol_command` | `PatrolCommand` | `task_id`·`operation`·`points`. v1 명령으로 바꿔 같은 로봇을 움직임 |
| `/pinkyN/patrol_command_ack` | `PatrolCommandAck` | 명령마다 한 번. 거절 이유 `busy`·`not running`·v1 실패 문구 |
| `/pinkyN/patrol_state` | `PatrolState` | 바뀔 때 + 1초마다. `task_id`·`task_finished`·`held_zone` 포함 |

v1·v2 어느 쪽 명령이든 같은 가짜 로봇이 움직이고, 상태는 두 규격으로 동시에 나갑니다.
v2 로 거절된 명령은 v1 `FAILED` 상태를 내지 않습니다 (ack 가 대신함).

- 지점 좌표는 실제 순찰 설정(`sites/<site>.yaml`, `robots/pinkyN.yaml`)의 `points`·`zone_points`·`home_name` 을 읽습니다. 대기 슬롯은 `zone_params.yaml` 의 앵커·간격으로 계산합니다.
- 상태 순서는 실제 순찰 노드와 같습니다.
  - goto: `STARTING` → (구역 보유 시 `LEAVING_ZONE`) → 지점마다 `MOVING`·`ARRIVED` → `DONE` → `IDLE_WAIT`
  - zone: `STARTING` → (점유 중이면 슬롯으로 `MOVING`(`slot`) → `QUEUEING`(`slot{k}`)) → `MOVING` → `ARRIVED` → `DONE` → `HOLDING_ZONE` → `IDLE_WAIT`
  - leave: `STARTING` → `LEAVING_ZONE` → `DONE`(`left zone`)
  - home·유휴 복귀: `STARTING` → `RETURNING` → `DONE`(`returned home`)
  - stop: `STOPPED` (구역 안이면 `RETREATING` → `STOPPED`(`retreated`)), emergency_stop: `STOPPED` 후 토큰 유지
  - 검증 실패는 실물과 같은 detail 로 `FAILED` (`unknown point: ['P99']`, `use zone: ['ZA']`, `no zone held` 등). 작업 중 들어온 명령은 무시.
- JSON 봉투 `{"command_id": "...", "command": "goto:P1"}` 를 받으면 그 작업의 상태에 `command_id` 를 붙이고, 마지막 `DONE`/`FAILED`/`STOPPED` 에 `task_finished: true` 를 붙입니다.
- 중앙 모드(`central_controlled: true`, 기본)는 실물 `central_guard.py` 와 같은 규칙입니다: 하트비트가 살아 있을 때 현재 세션·늘어나는 순번의 봉투 명령만 받고, 정지는 늘 받으며(잠금은 비상정지와, 움직이던 중의 하트비트 단절·관제 재시작 때만), 잠긴 동안은 `control_reset` 만 받습니다.
- 구역 목표에 실제로 도착하면 `arrived_zone` 이 생기고 다음 이동을 시작하면 비웁니다 (`held_zone` 은 예약 토큰).
- `dropout_robot`(기본 없음)을 주면 60초마다 12초씩 아무것도 보내지 않습니다. 화면의 '끊김' 표시 시험용입니다.
- 구역 장부는 실물 zone_manager 처럼 시간이 지나도 점유를 풀지 않고, `/zone_manager/notify_exit` (점유자 이름이 맞을 때만)로 풉니다 (2026-11-18, 그 전에는 `max_hold_sec` 뒤 저절로 풀었음).
- **전원 끔 흉내** `power_off` (쉼표로 여러 대, 실행 중에 바꿈): 꺼진 동안 아무것도 내지 않고 명령도 받지 않습니다. 목록에서 빼면 다시 켜진 것처럼 작업과 `held_zone` 을 잊습니다 (구역 장부는 그대로). 관제 '구역 강제 해제' 시험용입니다.
  ```bash
  ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ros2 param set /mock_pinky_node power_off pinky1
  ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ros2 param set /mock_pinky_node power_off ''
  ```

## 명령 보내 보기

가짜 핑키는 실물처럼 중앙 모드라, `patrol_cmd` 에 봉투 없는 글자 명령을 바로 내면 거절합니다. 명령은 화면(8181)이나 관제 API 로 보냅니다 (작업 명령은 켜진 채로 시작):

```bash
curl -s -X POST localhost:8181/api/tasks -H 'Content-Type: application/json' \
  -d '{"client_request_id": "t1", "robot_id": "pinky1", "operation": "zone", "points": ["ZA"]}'
curl -s -X POST localhost:8181/api/tasks -H 'Content-Type: application/json' \
  -d '{"client_request_id": "t2", "robot_id": "pinky1", "operation": "leave"}'
ros2 topic echo /pinky1/patrol_status
```

개발용 수동 명령 칸(화면 아래, `allow_raw_cmd:=true` 기본)은 fleet 이 세션 봉투를 붙여 그대로 보냅니다.

## 파라미터

`config/mock_pinky_node.yaml` 에 설명이 있습니다. 주요 값: `speed_mps`(0.15), `idle_return_sec`(40, 실물 120), `auto_interval_sec`(8), `dropout_robot`/`dropout_period_sec`/`dropout_sec`, `seed`.

## 시험

```bash
python -m colcon test --packages-select cobot_mock && python -m colcon test-result --verbose
```

실제 순찰 설정·`zone_params.yaml` 을 읽어 시험하므로, 그 파일 형식이 바뀌면 여기서 먼저 깨집니다.

## 빼는 법

- 빌드에서만 빼기: `touch src/cobot_mock/COLCON_IGNORE`
- 완전히 빼기: `src/cobot_mock/` 폴더 삭제, `CLAUDE.md` §2 구조도·담당표의 `cobot_mock` 줄 삭제
