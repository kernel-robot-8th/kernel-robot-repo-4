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
| `camera_policy` | `field` | `field`는 `sim_` 카메라를 거절하고, `sim`은 `sim_`만 받습니다 |
| `db_path` | `~/.cobot/anomaly_monitor.sqlite3` | 기록 파일 |

## 입력

`/anomaly_monitor/vision_event`(String JSON, RELIABLE, depth 50)로 이벤트를 받습니다.

```json
{"event_id": "e1", "camera_id": "ceil_cam", "vision_class": "box_on_floor",
 "confidence": 0.9, "detected_at": 1793790000.0, "zone_id": "",
 "map_x": 0.6, "map_y": 0.5}
```

`VisionEvent.msg`에는 클래스와 맵 좌표가 없습니다. 현장 픽셀 검출은 아래 `pixel_event_node`가 이 형식으로 바꿉니다.

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

- `pause`는 대상 로봇을 멈추지만 관제의 `armed`를 꺼서 다른 로봇의 다음 단계도 멈춥니다. 복구는 `arm` 다음 `resolve`입니다.
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
