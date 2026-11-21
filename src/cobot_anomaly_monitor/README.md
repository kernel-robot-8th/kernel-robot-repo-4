# cobot_anomaly_monitor

중계 장비에서 도는 시나리오 기록·CCTV 이상 판정 패키지입니다. 주문 실행은 `cobot_fleet_control`이 맡고, 이 패키지는 기록하고 판정합니다.

| 모듈 | 하는 일 |
|---|---|
| `judgment.py` | 판정표 정본. ROS와 DB 없는 순수 함수로, 시뮬도 그대로 import합니다 |
| `scenario_view.py` | 관제 단계(일반 경로 주문 단계와 고객 자리 주문 단계, 아래 "관제 기준")를 7단계로 바꾸고 적재 상태를 계산합니다 |
| `monitor_store.py` | 별도 SQLite 파일. 관제 DB에는 쓰지 않습니다 |
| `monitor_core.py` | 스냅샷 기록, 판정, 모드별 조치 |
| `manual_adapter.py` | 사람 승인·자동 응답·비전 판정으로 `/fleet/work_request`에 답합니다 |
| `load_complete.py` | 비전 적재 판정 규칙. ROS 없는 순수 계산 |
| `mqtt_evidence.py` | MQTT로 온 YOLO 근거를 ROS 토픽으로 옮깁니다(`mqtt_zone_evidence`) |
| `console_api.py` | 메뉴 6.5용 HTTP. 표준 라이브러리만 씁니다 |
| `pixel_map.py` | 픽셀 bbox를 map 좌표로 바꿉니다. 확신이 없으면 null입니다 |
| `debug_view.py` | 메뉴 6.5 디버그 표시용 순수 계산 |
| `monitor_node.py`, `pixel_event_node.py` | 위 모듈을 ROS에 연결합니다 |

## 관제 기준

관제 기준은 팀 `origin/sakim` 1b0cb08(김지혜, 11-19)입니다(11-20 맞춤). 구역 역할은 ZB 상차(`omx2`), ZC 매장 신발 정리(`omx3`), ZA 반환 상자 선반 복귀(`omx1`)입니다.

- 일반 경로 주문(`lab_delivery` ZA→ZC `omx1`/`omx3`, `lab_delivery_zb` ZB→ZC `omx2`/`omx3`)은 19단계입니다. 정차 보정 `CORRECT_PICKUP`·`CORRECT_DROPOFF`를 더하면 21개입니다.
- 고객 자리 주문(`col1__P22`, `col2__P22`)은 `MOVE_PICKUP`(ZB)부터 `LEAVE_PICKUP`까지 같고, 그 뒤 `MOVE_CUSTOMER`(P22), `CUSTOMER`로 갑니다. 결제나 시간 초과(300초)면 `RETURN_HOME`, `RETURN_EXIT`로 끝납니다. 회수면 `MOVE_ARRANGE`(ZC), `ARRANGE`(`omx3` `arrange_shoe`), `LEAVE_ARRANGE`, `MOVE_RESTOCK`(ZA), `RESTOCK`(`omx1` `warehouse_store`), `LEAVE_RESTOCK` 뒤 복귀합니다.
- 관제의 재개 가능 단계(`RESUME_STAGES`)는 `MOVE_PICKUP`, `MOVE_DROPOFF`, `RETURN_HOME`, `CUSTOMER`, `MOVE_CUSTOMER`, `MOVE_ARRANGE`, `MOVE_RESTOCK`입니다.
- `ARRANGE`·`RESTOCK` 뒤에는 결과를 확인하는 관제 비전 단계(`VERIFY_*`)가 없습니다. 그래서 자리 주문의 적재 판정은 ZB의 `VERIFY_LOAD`에서만 돕니다.
- 이 변경을 어느 브랜치에 올릴지는 사용자가 정합니다(미정).

## 지키는 규칙

- `patrol_cmd`를 발행하지 않습니다. 관제의 단일 발행자 검사가 주행을 거절합니다.
- `/control_center/task_request`를 구독하지 않습니다. 구독자 수도 같은 검사 대상입니다.
- 로봇 명령은 `/control_center/task_request`로 관제에 요청만 합니다.
- 수동 어댑터와 시뮬 어댑터를 같은 도메인에서 동시에 띄우지 않습니다. `/fleet/work_result`에 모르는 발행자가 있으면 수동 어댑터는 답하지 않습니다. 등록된 팀 팔 노드(`peer_result_nodes`)는 예외이고, 이때 팔 대상만 그쪽에 맡깁니다.

## 실행

관제와 같은 ROS 도메인에서 실행합니다.

`config/scenario_relay_dev.yaml`은 격리 시뮬·시험 전용입니다. 격리 도메인에서 `fleet_control`을 같이 띄울 때만 `scenario_config`로 넘깁니다. 현장 관제 `fleet_control`은 자기 패키지의 `config/scenario.yaml`을 씁니다.

- 값은 sakim 1b0cb08 `scenario.yaml`과 같게 맞췄습니다(11-20). 팀 파일이 바뀌면 다시 맞춥니다. 개발 전용 경로 `wh_a_to_store`·`wh_b_to_store`만 더 있습니다.
- `customer_return`이 들어 있어 sakim 87b9bee 이후 `fleet_control`에서만 뜹니다. main a0d0bf0·feature/control-center 판은 `customer_return` 인자 오류로 시작하지 못합니다.
- 감시 노드도 기본값(`scenario_config` 인자)으로 이 파일을 읽지만 `routes`만 씁니다. 기록의 팔 이름(`load_arm_id`·`unload_arm_id`), 7단계의 구역 진입 계산과 작업 주체, 주문 추적의 대상 대체값에 씁니다. 비전 적재 판정에는 쓰지 않습니다(판정은 요청에 실린 route를 씁니다).
- 자리 주문 경로 `col1__P22`·`col2__P22`는 `fleet_control`이 `shelf`·`destinations`로 만드는 경로라 감시 노드 `routes`에 없습니다. 그래서 자리 주문 기록의 팔 이름은 빈 값입니다.

```bash
ros2 launch cobot_anomaly_monitor anomaly_monitor.launch.xml
```

| 인자 | 기본값 | 설명 |
|---|---|---|
| `console_host` | `127.0.0.1` | `fms-web-server` 컨테이너에서 부르면 `172.17.0.1` |
| `mode` | `OBSERVE_ONLY` | `AUTO_HOLD`는 판정 뒤 `pause` 또는 `estop`을 요청합니다 |
| `manual_adapter` | `true` | 시뮬 어댑터를 쓸 때는 `false` |
| `console_commands` | `false` | 콘솔 명령. 시뮬에서만 `true` |
| `camera_policy` | `field` | `field`는 `sim_` 카메라를 거절하고, `sim`은 `sim_`만 받습니다 |
| `db_path` | `~/.cobot/anomaly_monitor.sqlite3` | 기록 파일 |

## 메뉴 6.5 디버그

메뉴 6.5의 3D 장면과 그 옆 버튼은 브라우저 안의 모의입니다. 실제 값과 관제 요청은 시나리오 콘솔만 다룹니다.

콘솔은 기본이 읽기 전용입니다. 메뉴 등록부가 6.5에 실물 명령 경로를 두지 않기 때문입니다. 시뮬에서만 켭니다.

```bash
ros2 launch cobot_anomaly_monitor anomaly_monitor.launch.xml console_commands:=true manual_adapter:=false camera_policy:=sim
```

| 패널 | 보는 것 |
|---|---|
| 이동 명령 | `zone`, `goto`, `leave`, `home`을 관제 `create` 요청으로 보냅니다 |
| 전체 비상 정지 | 로봇 지정 없는 관제 `estop` 요청입니다. 복구는 아래 "전체 정지 복구 순서"를 따릅니다 |
| 구역 점유 | 구역 관리자와 로봇이 말하는 점유자를 나란히 놓습니다. 다르면 불일치입니다 |
| 연결 진단 | 도메인, 순찰 상태, 토픽 발행자와 수신 나이, `ready()`가 이동을 거절할 이유 |
| 경유 기록 | `amcl_pose`가 지점 0.15 m 안을 지난 순서입니다. 믿는 위치라서 실제 경로와 다를 수 있습니다 |
| 요청과 응답 | 관제 요청의 상태 코드와 왕복 시간, 관제 작업 상태 |

웹과 이 패키지는 로봇 토픽을 발행하지 않습니다(`fms_dev_rules` R7). 그래서 `cmd_vel`, `initialpose`는 콘솔에 없습니다.

## 입력

`/anomaly_monitor/vision_event`(String JSON, RELIABLE, depth 50)로 이벤트를 받습니다.

```json
{"event_id": "e1", "camera_id": "ceil_cam", "vision_class": "box_on_floor",
 "confidence": 0.9, "detected_at": 1793790000.0, "zone_id": "",
 "map_x": 0.6, "map_y": 0.5}
```

`VisionEvent.msg`에는 클래스와 맵 좌표가 없습니다. 현장 픽셀 검출은 아래 `pixel_event_node`가 이 형식으로 바꿉니다.

## 정지 범위

판정 결과의 `stop_scope`가 정지 범위입니다. `AUTO_HOLD`에서만 요청이 나갑니다.

| 판정 | 범위 | 요청 |
|---|---|---|
| `LOAD_FAIL_PERCHED`, `TRANSIT_PERCHED`, `LOAD_FAIL_DROP`, `UNLOAD_FAIL` | `ROBOT` | `pause`, 그 로봇 |
| `TRANSIT_DROP`, `LANE_OBSTACLE`, `AMBIGUOUS`(바닥) | `ALL` | `pause`, 로봇 지정 없음 |
| `RUN_OVER_COLLISION` | `ALL` | `estop`, 로봇 지정 없음 |
| `LID_OPEN_ANOMALY`, `AMBIGUOUS`(걸침), `NO_POSITION`, `IGNORED` | `ROBOT` | 없음 |

- `ROBOT`은 `stop_targets`의 로봇마다 `robot_id`를 넣어 요청합니다. 관제는 그 로봇만 보류하고 `armed`는 켜 둡니다.
- `ALL`은 `robot_id` 키가 없는 요청 한 건입니다. 관제는 전 로봇을 보류하고 `armed`를 끕니다. 이때 `stop_targets`는 기록용입니다.
- 전체 정지 응답은 2xx이고 본문의 `armed`가 `false`일 때만 `*_ACCEPTED`로 적습니다. 아니면 `*_FAILED`입니다. 응답은 `control_detail`의 `ALL` 키에 남습니다.
- 보류 사유는 전체 정지일 때 로봇에 배정된 진행 중 주문 전부에 적습니다. 이미 사유가 적힌 주문은 덮어쓰지 않습니다.
- 이미 전체 정지 중(`armed` 꺼짐, 전 로봇 보류)이면 전체 `pause`는 보내지 않고 `PAUSE_ACCEPTED`와 `control_detail`의 `skipped`로 적습니다. `estop`은 언제나 보냅니다.
- 정지가 스냅샷에 보이지 않은 사건(`hold_seen` 0, 응답 없음·거절 포함)은 같은 물체가 다시 감지될 때 정지를 다시 요청합니다. 간격은 5초에서 두 배씩 늘고 60초에서 멈춥니다. 대상이 이미 보류 중이면 보내지 않습니다. 감지가 끊기면 재요청도 없습니다.
- `OBSERVE_ONLY`에서 기록만 한 사건은 `AUTO_HOLD`로 바꾼 뒤 같은 물체가 다시 감지되면 기록된 범위대로 정지를 요청합니다. 모드만 바꿔서는 요청이 나가지 않습니다.

### 전체 정지 복구 순서

1. 관제 웹에서 `arm`으로 `armed`를 켭니다. 켜기 전의 `resolve`는 400입니다. 이 콘솔과 중계 웹은 켜기를 받지 않습니다(`armed`가 `false`가 아닌 `arm`은 403, 관제로 보내지 않음). 끄기는 전달합니다. 시뮬에서도 같습니다.
2. 주문이 걸린 로봇은 주문 `resolve`(`resume` 또는 `fail`)로 풉니다. 이 로봇에 `release_control`을 보내면 409입니다.
3. 주문 없는 로봇은 한 대씩 `release_control`로 풉니다. 풀기 전의 명령은 409입니다.

로봇 지정 정지는 그 주문의 `resolve` 한 번으로 끝납니다.

### 사건 닫기

- 이 콘솔의 `resolve`는 `operator`가 있어야 합니다. 없으면 관제로 보내지 않고 400입니다.
- 콘솔 `resolve`가 200이면 그 주문에 연결된 `ROBOT` 사건은 바로 닫습니다. 정지가 걸린 `ALL` 사건은 `ACKNOWLEDGED`(확인한 사람·메모 기록)로만 두고, 아래 조건이 스냅샷에 보일 때 닫습니다.
- 관제에서 직접 복구해도 스냅샷으로 사건을 닫습니다. 정지가 스냅샷에 한 번 보인 뒤(`hold_seen`)에만 닫습니다. 닫은 사람은 `fleet`으로 적되, 운영자가 먼저 남긴 이름은 그대로 두고 메모는 뒤에 덧붙입니다.
  - `ROBOT` 사건: 연결 주문이 보류 상태를 벗어나면 닫습니다. 연결 주문이 스냅샷에서 사라졌으면 대상 로봇의 보류가 풀릴 때 닫습니다. 이 경우 정지를 확인하기 전(`hold_seen` 0)이었다면 자동으로 닫지 않으니 운영자가 닫습니다.
  - `ALL` 사건: `armed`가 켜지고, 보류 로봇이 없고, 보류 주문이 없을 때 닫습니다. 정지 확인은 `armed`가 꺼져 있고 관제 응답이 수락이거나 전 로봇이 보류일 때만 합니다.
- 거절된 정지(`*_FAILED`), 관찰 모드 기록, 조치 없는 판정은 자동으로 닫지 않습니다.
- 열린 사건과 같은 자리(30초, 0.25 m)의 재감지는 묶여서 요청이 늘지 않습니다. 전체 정지가 걸린 채 열린 사건은 30초가 지나도 묶습니다. 닫힌 뒤의 재감지는 새 사건이고 정지가 다시 나갑니다.
- 로봇 지정 정지 사건이 `RESOLVED`로 닫힌 뒤 300초 안에 같은 자리에서 다시 감지되면, 새 판정이 `LANE_OBSTACLE`이어도 닫힌 사건의 판정·범위·대상을 이어받습니다(그 로봇만 정지, 경보 문구에 `재감지`와 앞 사건 ID). 주문이 `fail`로 끝난 뒤 남은 상자가 전체 정지를 부르지 않게 하기 위해서입니다. 300초가 지나면 새로 판정합니다.

### 기록 DB 열 추가

`cctv_anomaly_events`에 `stop_scope`(기본 `ROBOT`)와 `hold_seen`(기본 0)이 추가됐습니다. 이미 있는 DB에는 시작할 때 열 유무를 보고 `ALTER TABLE ADD COLUMN`으로 더합니다. 다른 프로세스가 먼저 더한 경우(`duplicate column name`)는 넘어갑니다. 따로 할 일은 없습니다.

## 시험

```bash
python3 -m pytest test -q
```

`test_scenario_cctv.py`는 실제 `ScenarioService`와 `ControlAPI`를 돌립니다. `py_trees`와 `cobot_fleet_control`이 필요합니다.

`test_ros_roundtrip.py`는 격리 도메인에서만 돕니다.

```bash
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest test/test_ros_roundtrip.py -q
```

## 주의

- 로봇을 지정한 정지는 그 로봇만 보류하고 관제의 `armed`는 켜 둡니다. 로봇 지정 없는 정지는 전 로봇을 보류하고 `armed`를 끕니다. 판정별 범위는 위 "정지 범위"에 있습니다.
- `AUTO_HOLD`에서는 콘솔 모의 이벤트의 `box_on_floor`도 전체 정지를 부릅니다. 주문과 로봇이 없어도 `LANE_OBSTACLE`이 나옵니다.
- `armed`가 꺼진 채 300초를 넘겨 장치 결과가 오면 그 주문은 `UNKNOWN`과 비상 정지로 갑니다.
- `dock_xy_m`은 0.03 m입니다(sakim 1b0cb08 값, 팀이 1 cm에서 3 cm로 넓힘). 11-19 실물 ZB 정차 오차가 약 5 cm였고 정밀 보정은 아직 없습니다. 수동 어댑터는 `CORRECT_*`에 `no_motion`으로만 답해 로봇을 움직이지 않습니다. 그래서 상차 정차(`DOCK_PICKUP`) 오차가 3 cm를 계속 넘으면 보정 3회 뒤 안전 복귀로 주문이 `FAILED`가 됩니다(논리 탐침 확인, 실물 미확인). 하차 정차(`DOCK_DROPOFF`)에서 같은 일이 나면 `RETRIES_EXHAUSTED` 경보 뒤 `UNKNOWN` 보류입니다(관제 `scenario_runtime.retry` 코드 확인).
- 개발 경로 둘은 `ZC`와 주행 통로를 함께 써서 두 로봇이 동시에 달리지 않습니다.

## 픽셀→map 좌표 변환

`pixel_event_node`가 `/anomaly_monitor/pixel_event`(String JSON)의 검출을 받아 `/anomaly_monitor/vision_event`로 냅니다. 변환 규칙은 `pixel_map.py`의 순수 함수에 있습니다.

```json
{"stream_id": "CAM_CEILING_01", "event_type": "box_on_floor", "confidence": 0.9,
 "timestamp": 1793790000.0, "bbox": [100, 200, 140, 260], "image_size": [1280, 720],
 "reference_markers": {"40": [10.0, 20.0], "42": [1200.0, 700.0]}}
```

`bbox`와 `reference_markers`는 `image_size` 원본 프레임의 픽셀입니다. 값은 예시입니다.

- 출력 좌표는 로봇 AMCL과 같은 `cobot_map_v9`의 map 좌표입니다. `canonical`로 잰 값은 보정 파일을 만들 때 v9로 바꿉니다.
- 아래 경우에는 `map_x`, `map_y`가 null이고 판정은 `NO_POSITION`입니다. 이유는 노드 로그에 남습니다.
  - 보정값이 없거나 지문이 맞지 않을 때
  - 카메라나 프레임 크기가 보정값과 다를 때
  - bbox가 프레임을 벗어날 때
  - 클래스 기준이 없을 때
  - 기준 마커가 부족하거나 움직였을 때
  - 상자가 렌즈 모델의 유효 범위 밖일 때
- 호모그래피는 측정으로 한 번 만들어 고정합니다. 실행 중에 다시 계산하지 않습니다.
- 렌즈 왜곡을 먼저 뺍니다. 호모그래피는 직선을 직선으로만 보내므로 이 단계가 없으면 화면 가장자리에서 오차가 커집니다. 내부값은 체커보드로 잰 값을 씁니다.
- bbox는 중심을 쓰고 `height_m`은 그 중심의 실제 높이입니다. bbox 아래 변은 카메라 직하점을 지나면 상자 윗면 쪽이 됩니다.

`config/camera_calibration.yaml`은 측정 전이라 `PENDING`입니다. 값을 손으로 넣지 말고 `config/camera_measurement_template.yaml`을 채워 만듭니다. 아래 경우에는 파일을 만들지 않습니다.

- 검증점 오차가 상한을 넘을 때
- 검증점이 화면 네 사분면에 없을 때
- `required_zones`의 구역 0.45 m 안에 검증점이 없을 때

왜곡 오차는 화면 중앙과 마커 옆에서는 드러나지 않아서 검증점을 넓게 요구합니다.

```bash
ros2 run cobot_anomaly_monitor build_camera_calibration measured.yaml camera_calibration.yaml
```

현장 감지기는 아직 이 입력을 내지 않습니다. 지금 `inference_worker.py`의 `infer()`는 빈 목록만 돌려주고 결과도 로그로만 남깁니다. `image_size`와 `reference_markers`를 내는 코드와 이 토픽의 발행자도 없습니다. 원본 프레임 bbox를 내는 검출기는 `~/yolo_edge/inbox/homelab-20261102/`에 전달돼 있고 미적용입니다.

홈랩 7번 적재 검증과 메뉴 6.5 재생은 [실행 안내](docs/homelab_verify_load.md)를 참고하세요.

## 비전 적재 판정 (천장 카메라 → `/fleet/work_result`)

천장 카메라 YOLO 근거와 팔 결과를 묶어 "상자가 핑키에 실렸는가"를 한 번 답합니다.
`/fleet` 계약의 토픽·메시지·노드 이름은 새로 만들지 않았습니다. 관제가 이미 내는 `/fleet/work_request`의
`VERIFY_LOAD` 단계(target `vision`)에 `/fleet/work_result`로 답하는 기존 자리를 그대로 씁니다.
근거 입력용 ROS 토픽 `/anomaly_monitor/box_evidence`(MQTT `relay/evidence/boxes`) 하나만 추가했습니다.
기본값은 꺼짐(`judge_mode=off`)이라 인자를 주지 않으면 이전과 똑같이 돕니다.
단, `auto_targets`는 이제 launch 인자가 yaml 값을 덮어씁니다. yaml에서 켜 두었다면 launch 인자로 옮겨야 합니다.

### 흐름

```text
천장 카메라 → YOLO 발행 앱 ─MQTT→ mqtt_zone_evidence ─┬→ /anomaly_monitor/zone_evidence
              (relay/evidence/zones, boxes)           └→ /anomaly_monitor/box_evidence
팔 노드 ──────────────────────────────→ /fleet/work_result (PICK, LOAD 결과)
관제 ─────────────────────────────────→ /fleet/work_request (VERIFY_LOAD, target vision)
                         monitor_node (판정) ─→ /fleet/work_result (VERIFY_LOAD 답)
```

### 보내는 답 세 가지

| 판정 | 조건 | `/fleet/work_result` |
|---|---|---|
| 적재 성공 `LOAD_COMPLETE` | 아래 세 조건이 모두 참 | `success: true`, `data.load_present: true`, `data.arm_safe: true`, `data.box_dropped: false` |
| 상자 추락 `BOX_DROPPED` | 상차 구역 핑키 근처에서 `box_on_floor`·`box_run_over`가 연속 `judge_drop_frames`장 | `success: false`, `data.box_dropped: true`, `detail`에 사유 |
| 보류 | 위 둘이 아님 | 답을 보내지 않음. `judge_max_wait_sec` 뒤 콘솔에 `operator_attention` 표시 |

세 조건:

1. **팔**: 같은 주문의 PICK·LOAD 결과가 모두 `success: true`이고 LOAD의 `data.arm_safe`가 참.
   두 결과의 `source`가 서로 같고 주문 경로의 `pickup_arm`과 같아야 합니다. `fake`·수동 결과는 근거로 쓰지 않습니다.
   `session_id`·`attempt`는 결과에 들어 있을 때만 비교합니다(지금 팔 노드는 넣지 않습니다).
2. **핑키 적재**: 상차 구역 상태가 `judge_hold_sec` 이상, `judge_min_frames`장 이상 연속 `LOADED`이고 그 사이 핑키가 서 있음.
3. **추락 아님**: 판정 시점의 가장 최근 상자 프레임에 상차 구역 핑키 근처 바닥 상자가 없음.
   상자 프레임이 `judge_fresh_sec` 넘게 끊기면 모르는 것으로 보고 보류합니다.
   유지 구간 중간에 잡혔다 사라진 바닥 상자는 막지 않습니다(`judge_latch_drop:=true`면 연속으로 확정된 추락만 유지).

세 조건이 참이어도 주문·호기 귀속 검사(관제 스냅샷의 주문 단계, 대상 호기 정지·구역 도착, 다른 호기가 구역 밖)와
턱 걸림 검사를 통과해야 답합니다. 통과하지 못하면 보류입니다.
귀속 검사(`load_evidence.py`)는 상차 구역 ZA·ZB만 받습니다. 상차 구역이 ZC인 주문은 보류됩니다.

답의 공통 필드는 기존 계약 그대로입니다(`request_id`, `order_id`, `robot_id`, `stage`, `source: vision`,
`measured`, `finished`). `data`에는 `decision: vision_judged`, `rule_version`, 근거 프레임 번호(`evidence`)가 붙습니다.
추락은 결과만 전합니다. 주문을 어떻게 처리할지는 관제가 정합니다.
지금 관제 코드는 `retry_safe` 없는 실패를 주문 `UNKNOWN` + 정지(로봇 비상 정지, 경로 팔 SAFETY hold)로 처리하고
관제 알람에는 `재시도 안전성 미확인`만 남깁니다. 추락 사유(`detail`)는 중계 웹의 작업 이력에서 봅니다.

### 모드

| `judge_mode` | 동작 |
|---|---|
| `off` (기본) | 판정하지 않음. 이전 동작 그대로 |
| `shadow` | 판정을 계산해 기록만 함. 답은 기존 자동 응답이 성공으로 보내고(판정이 안 서면 약 5초 기다림) `data.judge`에 판정을 붙임. 추락 판정이어도 성공으로 답합니다. **관측 전용이 아닙니다** |
| `enforce` | 판정대로 답함. 성공 근거면 성공, 추락이면 실패, 모르면 보류 |

`auto_targets`에 `vision`이 있어야 판정이 쓰입니다. 없으면 기동 때 경고를 냅니다.
`verify_load_join`과는 같이 켤 수 없습니다. `VERIFY_UNLOAD`는 판정하지 않습니다(`placed` 기준 미정).

### 켜는 법

```bash
# 1) MQTT 근거를 ROS 토픽으로 (현장 도메인에 붙일 때만 --field-domain)
ros2 run cobot_anomaly_monitor mqtt_zone_evidence --broker <브로커 주소> --field-domain 100

# 2) 감시 노드 (shadow 예)
ros2 launch cobot_anomaly_monitor anomaly_monitor.launch.xml \
  judge_mode:=shadow auto_targets:='[vision, navigation]' calibration_id:=ceil-20261108
```

sakim 관제에서 target `vision`·`navigation` 요청에 답하는 노드는 이 패키지의 수동 어댑터뿐입니다.
주문을 끝까지 돌리려면 `auto_targets`에 둘 다 넣습니다. `vision`이 빠지면 첫 비전 단계 `PICKUP_EXIT`에서,
`navigation`이 빠지면 정차가 공차를 벗어나 `CORRECT_PICKUP`이 나갈 때 답이 없어 300초 뒤 `UNKNOWN`이 됩니다.
`console_commands`가 `false`(기본)이면 콘솔 승인도 403이라 사람이 대신 답할 수 없습니다.

`mqtt_zone_evidence`는 paho-mqtt 2.x가 필요합니다(`pip install paho-mqtt==2.1.0`). apt의 `python3-paho-mqtt` 1.6.1로는 뜨지 않습니다.
프레임의 `stream_id`·`model_id`·`calibration_id`가 감시 노드 값(`ceiling`, `pinky-v1`, `calibration_id` 인자)과 같아야 받습니다.
`--field-domain`은 도메인 100 참여를 명시적으로 허용하는 옵션일 뿐, 현장 승인을 뜻하지 않습니다.
`/fleet/work_result` 발행자를 늘리지 않습니다. 팔 노드(`<arm>_adapter`)와는 함께 돌 수 있습니다.

| launch 인자 | 기본값 |
|---|---|
| `auto_targets` | `['']` (꺼짐), sakim 관제와 돌릴 때 `'[vision, navigation]'` |
| `judge_hold_sec`, `judge_still_ratio` | 1.0, 0.15 |
| `judge_drop_frames`, `judge_min_frames` | 3, 3 |
| `judge_fresh_sec`, `judge_gap_sec`, `judge_drop_reach` | 2.0, 1.0, 1.0 |
| `judge_drop_tray_iou_max` | `-1.0` (`> 0`이면 핑키 안 tray와 겹치는 floor를 추락에서 제외, 예: `0.5`) |
| `judge_require_tray_marker_absent` | `false` (`true`면 트레이 마커가 안 보여야 적재로 인정. 상자 메시지에 `tray_markers` 또는 핑키 항목의 `tray_marker_seen`이 없으면 보류) |
| `judge_min_tray_box_frames` | `0` (`> 0`이면 유지 구간 안 `box_on_tray` 최소 장수 요구) |
| `judge_latch_drop` | `false` (`true`면 확정된 추락을 이후 단발 미검출에도 유지) |
| `judge_max_wait_sec` | `30.0` (보류가 이어지면 `operator_attention` 표시, `judge_hold_timeout` 기록) |

이 값들은 실물 성능으로 확정한 임계값이 아닙니다. `judge_mode`가 `shadow`·`enforce`일 때 판정 수치가 유효하지 않으면 기동을 거절합니다.
`judge_max_wait_sec`는 검사하지 않으며 0 이하면 `operator_attention` 표시가 꺼집니다.
트레이 마커는 구역이 아니라 핑키 트레이에 붙어 있는 것으로 보입니다(추정. 11-18 ZC에 선 pinky1 위에서 31이 보였습니다). 핑키별 번호 대응은 미확인이고 현장 확인이 필요합니다.
`load_complete.py`의 `TRAY_MARKERS`(ZA 31, ZB 30, ZC 32)는 구역별 표입니다. 상자 메시지의 핑키 항목에 `tray_marker_seen`(bool)이 없을 때 쓰는 대체값입니다(있으면 표는 사실상 쓰이지 않습니다). 이 검사는 `judge_require_tray_marker_absent`를 켰을 때만 돌고, 기본은 꺼짐입니다.
`scripts/vision/homelab_vision` 발행 앱(404d7ab 판)은 프레임별 `tray_markers`와 핑키별 `tray_marker_seen`을 `relay/evidence/boxes`에 담아 보냅니다.
스트림·모델·보정·시각이 맞지 않는 프레임이 오면 그때까지 쌓은 이력도 함께 비우고, 불일치가 이어지는 동안 종류별 30초 간격으로 경고합니다.
추락을 주문에 귀속하지 못해 보류하면 `judge_suppressed` 이력에 원래 판정과 프레임 번호를 남기고 실패 답은 보내지 않습니다.

### 11-18 현장 시험에서 확인한 것

pinky1을 ZC에 세우고 omx3로 `load`, `arrange_shoe`를 수동 시험(`MANUAL_TEST`)으로 한 번씩 돌렸습니다.

- `arrange_shoe`에서 팔이 상자를 떨어뜨렸는데 팔 결과는 `SUCCEEDED`(`success_basis: judge`)였습니다.
  카메라 상자 토픽에는 같은 구간에 `box_on_floor`가 약 40초 동안 여러 번 잡혔습니다. 팔 결과만으로는 적재를 확정할 수 없습니다.
- 그래도 판정 답은 나가지 않았습니다. 이유:
  - 수동 시험은 `VERIFY_LOAD` 단계가 아니라 판정 대상이 아닙니다.
  - 당시 모서리 마커가 3개만 잡혀 `marker_state`가 `FIXED`였고, 이때 발행 앱은 세 구역을 모두 `NO_ROBOT`으로 보내므로 판정은 보류합니다(현재 모서리 마커 4개 정상 검출로 `OK`).
  - (11-20 정정: 위 괄호의 "현재 4개 정상 검출로 `OK`"는 지금 사실이 아닙니다. 천장 모서리 마커 42가 실제로 없습니다(11-20 사용자 현장 확인).
    그래서 `marker_state`가 `OK`가 될 수 없고, 발행 앱은 세 구역을 모두 `NO_ROBOT`으로 보내며, 판정은 늘 보류입니다.
    이 동안 `enforce`는 쓸 수 없습니다. `enforce`면 답이 없어 관제가 300초 뒤 `UNKNOWN`과 비상 정지로 처리합니다.
    `shadow`는 약 5초 뒤 판정 없이 성공으로 답합니다. 42를 다시 붙일지, 마커 조건을 바꿀지는 미정이고 사용자가 정합니다.)
- 빈 핑키가 처음부터 `pinky_loaded`로 분류됐고 트레이 마커는 계속 보였습니다.
  빈 차가 적재로 읽히지 않게 하려면 `judge_require_tray_marker_absent`를 켜야 합니다.
- 배포된 `scenario.yaml`은 상차 구역이 ZA·ZB, 상차 팔이 `omx1`, 하차 팔이 `omx2`입니다. 조건 1은 팔 결과의 `source`가
  경로의 `pickup_arm`과 같아야 통과하므로 경로의 팔 지정이 실제 팔과 맞아야 합니다. ZC를 상차 구역으로 쓰는 주문은
  귀속 검사에서 보류됩니다(위 "세 조건" 참고).
  - (11-20 정정: 위는 11-18 당시 배포판 기준입니다. 관제 기준 sakim 1b0cb08 `scenario.yaml`에서는 ZB 상차 `omx2`,
    ZC 매장 신발 정리 `omx3`, ZA 반환 상자 선반 복귀 `omx1`입니다. 경로는 `lab_delivery` ZA→ZC `omx1`/`omx3`,
    `lab_delivery_zb` ZB→ZC `omx2`/`omx3`이고, 자리 주문 `col1__P22`·`col2__P22`는 ZB `omx2` 상차 → P22이며
    회수 때 ZC `omx3` 정리 → ZA `omx1` 반환을 거칩니다. sakim 경로에는 ZC 상차가 없습니다.
    판정은 요청에 실린 route의 `pickup`·`pickup_arm`을 쓰므로 자리 주문은 ZB·`omx2`로 판정합니다.
    현장 관제가 sakim 판으로 배포됐는지는 확인하지 않았습니다.
    ZA가 반환 구역이 된 뒤에도 `lab_delivery`(ZA 상차)를 쓰는지는 미정이고 김지혜 님이 정합니다.)

아직 실물에서 확인하지 못한 것: 주문 단계에서의 성공·추락 답, `enforce` 모드, 실제 적재 때의 구역 `LOADED` 전환.

### 로컬 시험

가짜 로봇과 주문은 격리 도메인에만 둡니다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset CYCLONEDDS_URI ROS_DISCOVERY_SERVER
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
# 워크스페이스 루트, py_trees와 ROS가 있는 가상환경에서 실행
export PYTHONPATH="$PWD/src/cobot_anomaly_monitor:$PWD/src/cobot_navigation/cobot_fleet_control:$PWD/src/cobot_navigation/cobot_amcl_corrector:$PYTHONPATH"
python -m pytest src/cobot_anomaly_monitor/test -q -p no:cacheprovider
```

판정만 볼 때는 `test/test_load_complete.py`(규칙), `test/test_vision_judge.py`(응답), `test/test_judge_node.py`(ROS 입력)를 돌립니다.
