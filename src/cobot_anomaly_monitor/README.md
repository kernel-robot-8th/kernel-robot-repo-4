# cobot_anomaly_monitor

중계 장비에서 도는 시나리오 기록·CCTV 이상 판정 패키지입니다. 주문 실행은 `cobot_fleet_control`이 맡고, 이 패키지는 기록하고 판정합니다.

| 모듈 | 하는 일 |
|---|---|
| `judgment.py` | 판정표 정본. ROS와 DB 없는 순수 함수로, 시뮬도 그대로 import합니다 |
| `scenario_view.py` | 21단계를 7단계로 바꾸고 적재 상태를 계산합니다 |
| `monitor_store.py` | 별도 SQLite 파일. 관제 DB에는 쓰지 않습니다 |
| `monitor_core.py` | 스냅샷 기록, 판정, 모드별 조치 |
| `manual_adapter.py` | 사람 승인으로 `/fleet/work_request`에 답합니다 |
| `console_api.py` | 메뉴 6.5용 HTTP. 표준 라이브러리만 씁니다 |
| `pixel_map.py` | 픽셀 bbox를 map 좌표로 바꿉니다. 확신이 없으면 null입니다 |
| `debug_view.py` | 메뉴 6.5 디버그 표시용 순수 계산 |
| `monitor_node.py`, `pixel_event_node.py` | 위 모듈을 ROS에 연결합니다 |

## 지키는 규칙

- `patrol_cmd`를 발행하지 않습니다. 관제의 단일 발행자 검사가 주행을 거절합니다.
- `/control_center/task_request`를 구독하지 않습니다. 구독자 수도 같은 검사 대상입니다.
- 로봇 명령은 `/control_center/task_request`로 관제에 요청만 합니다.
- 수동 어댑터와 시뮬 어댑터를 같은 도메인에서 동시에 띄우지 않습니다. `/fleet/work_result` 발행자가 둘이면 수동 어댑터는 답하지 않습니다.

## 실행

관제와 같은 ROS 도메인에서 실행합니다. `fleet_control`에는 `scenario_config`로 `config/scenario_relay_dev.yaml`을 넘깁니다.

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
- `dock_xy_m` 0.05는 개발용 임시값입니다. 팀 기본은 0.01입니다.
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
