# cobot_manipulation PRD — Station PC 팔 노드

- 상태: 뼈대 (2026-11-14). 팔 실행기 백엔드 `worker`, 관제 켜기·끄기(`ArmCommand`·`ArmStatus`·`CommandAck`) 추가 (2026-11-15). 팔 1대(omx1) 실기 시험 전.
- 담당: 로봇팔 팀 (CODEOWNERS). 관제 계약 부분은 로봇 수행 관제 담당이 함께 본다.
- 팀원용 한 장 요약: [`team_guide.md`](team_guide.md)
- 공통 명세와 다르면 공통 명세(`docs/fms_interfaces.md`)를 따른다. 단, 지금 관제가 실제로 쓰는 계약은
  아래 1번이다. 작업 요청까지 정식 메시지(`HandoverTask` 등)로 옮기는 일은 팀이 따로 정한다.
  켜기·끄기와 상태는 이미 정식 메시지(`ArmCommand`·`ArmStatus`·`CommandAck`)를 쓴다 (5절).

## 0. 하는 일

관제를 띄우지 않는 Station PC 에서 팔 3대(omx1~3)를 맡는다.
관제 PC 의 `fleet_control_node` 가 보내는 작업 요청을 팔 1대씩 받아 처리하고 실측 결과를 돌려준다.

```text
[관제 PC] fleet_control_node                         관제 코어 (켜기·끄기 명령을 내는 쪽)
   │ /fleet/work_request (String JSON)                   │ /control_center/omx_1/command (ArmCommand)
   ▼                                                     ▼
[Station PC] omx1_adapter · omx2_adapter · omx3_adapter   (같은 실행 파일, arm_id 만 다름)
   │ ▲ /fleet/work_result (String JSON)                  │ /manipulation/omx_1/command_ack (CommandAck)
   │                                                     │ /manipulation/omx_1/status (ArmStatus, 10 Hz)
   │ 백엔드 (none / fake / worker)
   ▼ stdin/stdout JSON
[Station PC] omx_fleet_worker (tool/omx-dashboard 의 omx_fleet/, lerobot 0.4.4) ──▶ 실제 팔
```

## 1. 관제 계약 (정본: cobot_fleet_control 코드)

### 요청
`fleet_control_node.work()` 와 `scenario_runtime` 이 만든다. 이 노드는 `target` 이 자기 `arm_id` 인 것만 본다.

| 필드 | 뜻 |
|---|---|
| `request_id` | 요청 고유 번호. 같은 번호는 한 번만 실행 |
| `order_id`, `robot_id`, `stage` | 결과에 그대로 돌려준다 |
| `target` | 받을 팔 (`omx1` 등) |
| `action` | `pick`, `load`, `unload`, `warehouse_store`(반품 하차), `hold`, `release_hold` |
| `session_id`, `seq` | 관제 노드 실행마다 새 session. seq 는 target 별 증가 |
| `issued_at`, `ttl_sec` | [s] 관제 PC 시각, 유효 시간 (5 s) |
| `sku`, `quantity`, `attempt`, `route`, `timeout_sec` | 작업 정보 |

| stage | 팔 | action |
|---|---|---|
| `PICK` / `LOAD` | 상차 팔 (`route.pickup_arm`) | `pick` / `load` |
| `PICK_DROPOFF` / `UNLOAD` | 하차 팔 (`route.dropoff_arm`) | `pick` / `unload` 또는 `warehouse_store` |
| `SAFETY` | 경로의 팔 | `hold` / `release_hold` (관제는 결과를 기다리지 않음) |

### 결과
`scenario_runtime.receive()` 가 검사한다. 하나라도 틀리면 결과를 **조용히 버린다**.

```json
{"request_id": "...", "order_id": "...", "robot_id": "...", "stage": "...",
 "source": "omx1", "measured": true, "finished": true,
 "success": true, "detail": "(실패 이유, 선택)", "data": {"arm_safe": true}}
```

- 실패에 `data.retry_safe=true` 가 없으면 관제는 재시도하지 않고 주문을 보류한다.
  이 노드는 **팔을 움직이기 전에 거절한 경우에만** `retry_safe` 를 붙인다 (탐지 안 됨, 만료, 시계 차이, 정지 유지 중, 작업 중, 백엔드 없음).
- 작업 도중 `hold` 나 보드 연결 끊김으로 끝나면 팔 자세를 모르므로 `retry_safe` 없이 실패를 보낸다.

### 요청 판정 순서
1. `target` 이 다르면 무시. 필수 필드가 없으면 무시 (결과를 보낼 수 없다).
2. 이미 본 `request_id` 면 무시 (최근 `dedupe_size` 개).
3. `session_id` 가 바뀌면 seq 기록을 비운다. seq 가 줄면 무시.
4. 만료(`now > issued_at + ttl_sec`)나 미래 시각(`issued_at > now + ttl_sec`)이면 거절 (retry_safe).
5. 모르는 action 은 거절 (retry_safe 없음).
- `hold` 는 3·4번에 걸려도 실행한다. 멈춤을 거절하는 쪽이 더 위험하다 (D4 추천안).
- 시계 비교가 있으므로 두 PC 는 chrony 등으로 시계를 맞춘다.

## 2. 팔 탐지

- OpenRB-150 보드는 칩 고유 시리얼을 `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_<시리얼>-if00` 로 드러낸다.
  어느 PC·포트에 꽂아도 같아서 udev 규칙·`sudo` 가 필요 없다. 노드는 **이름만 읽고 장치를 열지 않는다**.
- 등록표 `config/arm_registry.yaml` 은 '팔 자리 이름 ↔ 그 자리에 있어야 할 보드 시리얼' 이다.
  팔 자리 이름은 관제 `scenario.yaml` 의 `pickup_arm`·`dropoff_arm` 과 같다.
- READY 는 등록된 시리얼이 정확히 1개 보일 때뿐이다. 아래는 모두 UNKNOWN 이고 작업을 거절한다.
  시리얼 미등록, 연결 안 됨, 같은 시리얼이 여러 팔에 등록됨, 같은 시리얼이 여러 장치에서 보임.
- `detect_period_sec` 마다 다시 본다. 작업 중 보드가 사라지면 멈추고 실패로 끝낸다.
- 시리얼은 보드의 번호다. 보드를 다른 팔과 바꿔 끼우면 틀리게 판단하므로 보드와 팔에 같은 이름표를 붙인다.

새 팔 등록:
```bash
ls -l /dev/serial/by-id   # 시리얼을 읽어 arm_registry.yaml 의 빈 칸에 넣는다
```

## 3. 백엔드

| 이름 | 동작 | 쓰는 곳 |
|---|---|---|
| `none` (기본) | 모든 작업을 거절 (retry_safe) | 실제 백엔드가 생기기 전 실물 PC |
| `fake` | `fake_duration_sec` 뒤 성공, `data.fake=true` | 격리 도메인 시험만. 실물 도메인 0·10·12·20·30·100 이면 시작 거부 |
| `worker` | 계속 켜 두는 팔 실행기에 stdin/stdout JSON 으로 일을 시킴 | 실제 팔. **팔이 움직인다** |

### 3-1. `worker` 백엔드와 팔 실행기 계약

lerobot·torch·가중치를 이 패키지에 넣지 않으려고 팔 실행기를 별도 프로세스로 둔다.
작업마다 프로그램을 새로 켜지 않는 이유: lerobot 은 연결할 때·끊을 때 토크를 꺼서 **그 사이 팔이 떨어지고 잡은 물건을 놓친다**.
그래서 관제 `CMD_START` 를 받으면 실행기를 한 번 띄우고(5절), 실행기는 연결·토크를 유지한 채 일을 기다린다.

- 명령: `config/arm_adapter.yaml` 의 `worker_command` (셸을 거치지 않고 공백으로 나눠 실행).
- 환경변수: `ARM_ID`, `ROBOT_PORT`(탐지된 `/dev/serial/by-id/...`).
- stdin (어댑터 → 실행기, 한 줄 = JSON 하나):

  | cmd | 뜻 |
  |---|---|
  | `{"cmd":"run","id":<request_id>,"action":"pick"}` | 작업 1건 |
  | `{"cmd":"hold"}` | 지금 단계를 멈추고 토크 유지 |
  | `{"cmd":"state"}` | 대기 중 관절 값 보고 (`state_poll_sec` 마다) |
  | `{"cmd":"release"}` | 쉬는 자세(`rest_pose`)면 연결을 끊고 끝냄, 아니면 거절. **팔을 옮기지 않는다** |
  | `{"cmd":"quit"}` | 무조건 연결을 끊고 끝냄 (노드 종료·고장 정리 때만) |
- stdout (실행기 → 어댑터): `@fleet ` 로 시작하는 줄만 기계용 JSON. 나머지 줄은 노드 로그로 그대로 옮긴다.

| event | 뜻 | 어댑터 처리 |
|---|---|---|
| `ready` | 팔 연결·모델 준비 끝 | 이때부터 일을 받는다. 그 전 요청은 거절 (retry_safe) |
| `started` | 작업 시작 | 없음 |
| `done` | 작업 끝 | **`success` 와 `arm_safe` 가 둘 다 true 일 때만 성공**. 그 밖은 retry_safe 없는 실패. `data` 에 `arm_safe`·`end_reason`·`success_basis`·`pose_error`·`joints` 를 담는다 |
| `rejected` | 움직이기 전 거절 (예: 그 action 모델 없음) | retry_safe 실패 |
| `fatal` | 실행기 오류로 끝남 | 전원 FAULT. 이후 모든 작업 거절 |
| `state` | 대기 중 관절 값 | `ArmStatus` 관절 값 갱신 |
| `released` | 쉬는 자세 확인, 연결 끊음 | 실행기가 끝나면 전원 DISARMED, RESET 에 ACCEPTED |
| `release_refused` | 쉬는 자세가 아님 | 전원 그대로, RESET 에 REJECTED_STATE (이유 포함) |

`ready`·`state`·`done`·`release_refused` 에는 `joints`(lerobot 단위, `<관절>.pos`) 가 실린다.

- `hold`·시간 초과: 실행기에 `hold` 를 보내 **토크를 유지한 채 멈춘다** (SIGINT 를 쓰지 않는다. SIGINT 로 끝내면 토크가 꺼진다).
  그 작업은 바로 retry_safe 없는 실패로 돌려주고, 실행기가 멈춤을 알릴 때까지 새 작업은 '팔 작업 중' 으로 거절한다.
- 시간 제한은 요청 `timeout_sec` 과 `worker_timeout_sec` 중 짧은 쪽.
- 실행기가 죽으면 저절로 다시 띄우지 않는다 (전원 FAULT). 사람이 팔을 확인한 뒤 관제가 `CMD_RESET` → `CMD_START` 로 다시 켠다.
- 노드를 끄면 실행기에 `quit` 을 보낸다. 실행기가 연결을 끊으면서 토크가 꺼지므로 **팔이 내려앉을 수 있다**. 평소에는 노드를 켜 두고 관제로 끈다.
- 실행기가 팔에 연결할 때 lerobot `configure()` 가 토크를 잠깐 껐다 켠다. 켤 때 팔은 쉬는 자세에 둔다.

### 3-2. 팔 실행기 `omx_fleet` (2026-11-15)

팔 실행기는 이 패키지 밖, **`tool/omx-dashboard` 브랜치의 `omx_fleet/`** 에 있다 (lerobot 0.4.4, `~/venv/il`).
팔 팀 `omx_chain.py`(대시보드 v2 연속 실행기)의 함수를 그대로 쓴다. 자세한 사용법은 그 폴더의 `README.md`.

- 팔별 설정: `omx_fleet/fleet_arms.yaml` (git 제외, `fleet_arms.example.yaml` 을 복사). 카메라 by-id·MJPG·`robot_id`·action → 모델.

  | action | 모델 | 시간 |
  |---|---|---|
  | `pick` | `omx_shoebox_d/models/act_shoebox_d_5000step` | 90 s |
  | `load` | `omx_move_in_success/models/act_move_in_5000step` | 90 s |

- 작업 순서: 그 모델의 `init_pose.json` 으로 이동 → 정책 실행 → 안전 자세로 이동 → 관절을 다시 읽어 판정.
- `success`: 번들 `success.json` 의 YOLO 판단이 성공을 낸 경우만 true. **지금은 판단 모델이 비어 있어 항상 false (`success_basis=none`)** →
  관제는 주문을 보류한다. 가짜 성공을 보내지 않으려는 결정이다 (2026-11-15).
- `arm_safe`: 안전 자세(기본은 그 번들의 `init_pose.json`)로 **그리퍼를 뺀 관절만** 옮긴 뒤(잡은 물건을 놓지 않게)
  모든 관절 오차가 3 단위(약 5°) 이하일 때만 true. `hold` 로 끝나면 움직이지 않으므로 false.
- 확인한 것: 가짜 로봇으로 대화 방식·hold·오차 판정, 실제 모델 2개 GPU 로드 (팔 연결 없음).
- **알려진 위험**
  - 안전 자세 이동은 학습된 동작이 아니라 보간이다. 팔이 상자 안에 있을 때 걸릴 수 있다.
  - 초기 자세·안전 자세로 이동하는 동안(수 초)에는 `hold` 가 이동이 끝날 때까지 기다린다. 정책 실행 중에는 바로 멈춘다.
  - 지금 꽂힌 보드(`6D96...`)의 캘리브레이션 파일이 `omx_follower.json` 이 맞는지 확인하지 않았다.

## 4. 실행

```bash
colcon build --symlink-install --packages-up-to cobot_manipulation   # cobot_interfaces 포함
source install/setup.bash
# 관제 PC 와 같은 ROS_DOMAIN_ID. 시험은 격리 도메인 + fake
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_manipulation arm_station.launch.xml backend:=fake
```

`backend:=worker` 는 `CMD_START` 를 받으면 실제 팔에 연결하고 움직인다. 사람이 팔 옆에 있을 때만, 팀 확인 없이 실물 도메인에서 띄우지 않는다.
노드는 켜 두어도 된다. 꺼짐(DISARMED) 동안은 팔에 연결하지 않고 토크도 없다.

launch 인자: `backend`, `registry_file`, `enable_omx1`·`enable_omx2`·`enable_omx3`.
파라미터: `config/arm_adapter.yaml`.

## 5. 관제 켜기·끄기 (`ArmCommand` → `CommandAck`·`ArmStatus`)

관제가 Station PC 에 가지 않고 팔을 켜고 끈다. 메시지는 `cobot_interfaces` 에 이미 있는 것만 쓴다 (인터페이스 변경 없음).
토픽 이름의 팔 이름은 명세(`docs/fms_interfaces.md`)대로 `omx_1` 이다. 관제 시나리오의 `omx1` 에서 자동으로 만든다 (`interface_arm_id`).

| 토픽 | 타입 | 방향 | QoS |
|---|---|---|---|
| `/control_center/omx_1/command` | `ArmCommand` | 관제 → 팔 노드 | RELIABLE, VOLATILE, depth 10 |
| `/manipulation/omx_1/command_ack` | `CommandAck` | 팔 노드 → 관제 | RELIABLE, VOLATILE, depth 50 |
| `/manipulation/omx_1/status` | `ArmStatus` | 팔 노드 → 관제, 10 Hz | BEST_EFFORT, VOLATILE, depth 1 |

### 전원 상태 흐름

```text
           CMD_START (새 epoch)            실행기 ready
DISARMED ───────────────────▶ CONNECTING ───────────────▶ ARMED ◀──┐
   ▲                                                         │      │ 작업 (/fleet/work_request)
   │ released (쉬는 자세)        CMD_RESET (작업 중 아님)     │      │
   └──────────── RELEASING ◀──────────────────────────────────┤──────┘
                    │ release_refused → 이전 상태로             │ CMD_SOFT_LATCH
                    ▼                                          ▼
                                                LATCHED ── CMD_RESET ──▶ RELEASING
   실행기 죽음 (CONNECTING·ARMED·LATCHED) ──▶ FAULT ── CMD_RESET ──▶ DISARMED
```

| 명령 | 되는 상태 | 하는 일 | ACK |
|---|---|---|---|
| `CMD_START` | DISARMED, 팔 탐지 READY, backend ≠ none | 실행기를 띄워 팔에 연결 (토크 켜짐) | 바로 |
| `CMD_RESET` | ARMED·LATCHED (작업 중 아님) | 실행기에 `release`. 쉬는 자세면 끄고, 아니면 거절 | 실행기 답을 받은 뒤 (`release_timeout_sec`) |
| `CMD_RESET` | FAULT, 또는 실행기 없는 LATCHED | 정리하고 DISARMED | 바로 |
| `CMD_SOFT_LATCH` | 아무 때나 | 작업을 멈추고 LATCHED (토크 유지) | 바로, `stop_executed=true` |
| `CMD_HOLD` / `CMD_RELEASE_HOLD` | 아무 때나 | `/fleet/work_request` 의 hold/release_hold 와 같다 | 바로 |

- 작업 요청은 **ARMED 일 때만** 받는다. 그 밖은 `retry_safe` 거절 (`팔 전원 DISARMED (관제 CMD_START 필요)` 등).
- **끄기는 팔을 옮기지 않는다.** `ArmCommand.msg` 의 "팔 모션은 FMS 가 시작하지 않는다" 에 따라, 지금 자세가 `rest_pose` 에서
  그리퍼를 뺀 모든 관절 3 단위(약 5°) 안일 때만 토크를 끈다. 아니면 `REJECTED_STATE` "현장에서 팔을 내려 주세요".
  작업이 끝나면 안전 자세로 물러나므로, 안전 자세를 쉬는 자세와 같게 두면 작업 뒤 바로 끌 수 있다.
- `auto_start: true` 면 관제 없이 팔이 탐지되자마자 켠다 (예전 동작). 기본은 false.

### 헤더 판정 (`CommandHeader`, SR-20)

| 검사 | 거부 |
|---|---|
| `robot_id` 가 `omx_1` 이 아님 | `REJECTED_ROBOT_ID` |
| `ttl_ms` 0, 만료(`now > issued_at + ttl`), 미래(`issued_at > now + ttl`) | `REJECTED_TTL` |
| `CMD_START` 의 `epoch` 가 받아들인 epoch 이하 | `REJECTED_EPOCH` (START 는 새 epoch 에서만) |
| 그 밖 명령의 `epoch` 가 받아들인 epoch 와 다름 | `REJECTED_EPOCH` |
| `seq` 가 마지막 수락 seq 이하 | `REJECTED_SEQ` |
| 지금 상태에서 안 되는 명령 | `REJECTED_STATE` |

- 정지 계열(`CMD_HOLD`·`CMD_SOFT_LATCH`)은 **판정이 거부여도 정지**하고 `stop_executed=true` 를 보낸다.
- 보지 않는 것: `map_hash`(팔은 맵을 쓰지 않음), `sig`(D13 미정, **아직 서명 검사 없음**), 시계 오프셋(`REJECTED_CLOCK_UNSYNCED`).
- epoch·seq 는 노드 메모리에만 있다. 노드를 다시 켜면 0 부터 다시 받는다 (`robot_boot_id` 가 바뀐다).

### `ArmStatus` 채우는 법

| 필드 | 값 |
|---|---|
| `header.stamp` | 관절을 마지막으로 잰 시각 (작업 중에는 읽지 못해 오래된다 → 화면은 STALE 로 판단) |
| `joint_names`·`joint_positions`·`gripper_position` | 실행기 `joints` (lerobot -100..100, 그리퍼 0..100). 모르면 빈 값·NaN |
| `joint_unit` | `""` (모름). lerobot 단위가 명세 열거(RAD, 0..4095)에 없다 |
| `torque_enabled` | 실행기가 떠 있고 CONNECTING·ARMED·LATCHED·RELEASING |
| `retract_safe` / `retract_safe_measured` | 마지막 작업의 `arm_safe` / 그것을 실제로 쟀는가. 새 작업·새 연결이면 둘 다 false |
| `hold_active`·`hold_reason` | HOLD 또는 LATCHED (`HOLD`·`SOFT_LATCH`) |
| `work_step` | ARMED 대기 중이면 `IDLE`, 그 밖은 `""` (세부 단계 모름) |
| `epoch_accepted`·`last_seq_accepted` | 헤더 판정 기록 |
| `power_present` | false (측정 수단 없음, D6) |
| `present_current_ma` | 빈 값 |

- 명세의 `retract_safe` 는 "Z ≥ 280 mm" 이지만 여기서는 관절 오차로 판정한다. 이 값은 정본 고정값이 아니다 (CLAUDE.md).
- `ArmStatus` 에는 전원 상태(DISARMED·FAULT 등) 칸이 없다. `torque_enabled` 와 ACK 사유로만 알 수 있다.
- `/manipulation/<arm_id>/mode` (`ArmMode`) 는 Station 요약 노드의 몫이라 이 노드가 내지 않는다.

## 6. 아직 안 된 것

- 팔 1대 실기 시험 (3-2절). 보드 `6D96...` 가 omx1 자리 팔인지, 캘리브레이션이 맞는지 확인 필요.
- 성공 판단 YOLO 모델 (`success.json` 의 `model`). 그 전까지 성공 결과는 나오지 않는다.
- omx2·omx3 실행기 설정과 보드 시리얼.
- 관제 `scenario.yaml` 에 omx3 경로가 없다 (omx3 역할 미정). 지금은 관제가 omx3 에 요청을 보내지 않는다.
- 관제 PC cyclonedds Peers 에 Station PC IP 추가.
- 관제 쪽 켜기·끄기 버튼·HTTP 중계 (`cobot_control_center`·`cobot_gui`). 지금은 `ArmCommand` 를 내는 관제 코드가 없다.
- `ArmCommand` 서명 검사 (D13), 시계 오프셋 검사.
- 쉬는 자세(`rest_pose`)를 실제 팔로 재기. 지금은 shoebox_d 시작 자세.
- 팔 이름 통일: 명세 `omx_1`, 관제 시나리오 `omx1`. 지금은 `interface_arm_id` 로 이어 붙인다.
- Station PC 부팅 때 노드 자동 시작 (D18 뒤).
