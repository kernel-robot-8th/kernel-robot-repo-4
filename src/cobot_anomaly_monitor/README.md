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
| `monitor_node.py` | 위 모듈을 ROS에 연결합니다 |

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

`VisionEvent.msg`에는 클래스와 맵 좌표가 없어서 현장 감지기가 이 토픽으로 보내는 경로는 아직 정해지지 않았습니다.

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
