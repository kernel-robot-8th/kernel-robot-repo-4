# cobot_control_center API·데이터 형식·파라미터

개발할 때 보는 참고 문서입니다. 설치·실행은 [README](../README.md), 화면 사용법은 [screen_guide.md](screen_guide.md) 를 봅니다.

## 웹 API

`/api/tasks`·정지·해제·작업 명령 켜기/끄기·개발용 수동 명령 외에는 읽기 전용입니다. 명령 경로는 `task_manager_node` 에 넘기기만 하고, 작업 노드가 없거나 읽기 전용 백엔드(`read_only`)면 503 입니다.
작업 노드는 **작업 명령 꺼짐**으로 시작합니다. 꺼져 있는 동안 `POST /api/tasks`·`raw_cmd` 는 `423` 이고, 정지·해제는 항상 됩니다.
GET·WS 가 돌려주는 값은 모두 `fleet_api_node` 가 토픽으로 받아 메모리에 둔 최신값입니다 (DB 를 읽지 않음, [README 데이터 흐름](../README.md#데이터-흐름)).

| 경로 | 응답 |
|---|---|
| `GET /` | 관제 화면 |
| `GET /api/health` | `{"ok": true, "domain_id": 백엔드의 ROS_DOMAIN_ID, "read_only": 개발용 읽기 전용 백엔드인지, "source_online": bool, "source_age": 초 또는 null, "task_manager_online", "task_manager_age", "spec": 로봇별 v1/v2, "raw_cmd_enabled": 수동 명령 칸을 보일지, "commands_armed": 작업 명령이 켜져 있는지 (작업 노드가 꺼지면 false), "cameras": {"pinky1": {"age_sec": 마지막 영상 프레임 뒤 지난 초 또는 null, "frames": 받은 수}}}` |
| `GET /api/fleet` | 최신 스냅샷 전체 + `source_online`, `source_age`. 아직 못 받았으면 503 |
| `GET /api/robots` | 로봇 목록 (`robot_id` + 로봇 값) |
| `GET /api/robots/{robot_id}` | 로봇 하나. 없으면 404 |
| `GET /api/robots/{robot_id}/camera` | 카메라 영상 MJPEG 스트림 (`multipart/x-mixed-replace; boundary=frame`). 로봇이 낸 JPEG 를 풀지 않고 새 프레임마다 그대로 보냄. 프레임이 없으면 보내지 않고 기다림. `camera_robots` 에 없는 로봇이면 404 |
| `GET /api/robots/{robot_id}/camera.jpg` | 마지막 프레임 1장 (`image/jpeg`). 아직 못 받았거나 구독하지 않는 로봇이면 404 |
| `GET /api/map/info` | `{"image_width", "image_height", "resolution", "origin"}`. 지도 없으면 404 |
| `GET /api/map/image` | 지도 PGM 원본 바이트 |
| `GET /api/map/layers` | `{"zones": {"A": {"points": {"ZA": [x, y, yaw]}, "exit": {"name", "pose"} 또는 null, "queue": [[x, y, yaw], ..]}}, "homes": {"pinky1": {"name", "pose"}}, "points": {"P1": [x, y, yaw], ..}, "hidden_points": 숨긴 예비 지점 수, "warnings": [..]}`. 설정이 없으면 404 |
| `GET /api/events?after=&robot=&limit=` | 이벤트 로그 (오래된 것부터, `id` 오름차순). `after` 보다 큰 `id` 만, `robot` 을 주면 그 로봇만, `limit` 1~1000 (기본 200) |
| `WS /ws/fleet` | 연결 즉시 최신 스냅샷 1건, 이후 새 스냅샷마다 push |
| `POST /api/tasks` | `{"client_request_id", "robot_id", "operation": "goto"\|"zone"\|"leave"\|"home", "points": [..]}` → `202` 작업 / `200` 같은 요청 재전송 / `400` 형식·지점 / `404` 없는 로봇 / `409` 작업 중·결과 모름 / `423` 작업 명령 꺼짐 (기록하지 않음) / `503` 끊김·작업 노드 없음. 거절은 `{"detail", "task"}` |
| `POST /api/commands/arm` | `{"client_request_id", "armed": true\|false}` → `200 {"armed", "changed", "source": 요청한 IP, "client_request_id"}` / `400` armed 가 bool 이 아님. 작업 노드 사건 `operator_arm` 으로 남김 |
| `POST /api/robots/{robot_id}/stop` | `{"client_request_id", "emergency": false}` → `202 {"robot_id", "operation", "spec", "task_id"(멈출 작업), "warning"}`. 바쁨과 무관하게 항상 보냄 |
| `POST /api/robots/{robot_id}/raw_cmd` | 개발용. `{"client_request_id", "command": "goto:P3,P7"}` → `202 {"robot_id", "command", "raw_id", "spec": "v1", "topic": "/pinky1/patrol_cmd", "msg_type": "std_msgs/msg/String", "warning"}` / `423` 작업 명령 꺼짐 / `403` allow_raw_cmd 꺼짐 / `400` 빈 명령·여러 줄·200자 넘음 / `409` 진행 중·결과 모름 작업. 검사 없이 `patrol_cmd` 에 그대로 |
| `POST /api/tasks/{task_id}/resolve` | `{"client_request_id", "result": "FAILED", "note"}`. `UNKNOWN` 만 해제 (그 밖은 409) |
| `GET /api/tasks?robot_id=&state=&limit=50` | 최근 작업 (최신순) |
| `GET /api/tasks/{task_id}` | 작업 하나 `{"task_id", "robot_id", "operation", "points", "command", "spec", "state", "detail", "created_at", "updated_at", "history": [{"at", "state", "detail"}]}` |
| `WS /ws/tasks` | 연결 즉시 `{"type": "tasks", "tasks": [..]}`, 이후 바뀐 작업마다 `{"type": "task", "task": {..}}` |

## `/control_center/fleet_status` (= `/api/fleet`) 형식

```json
{
  "time": 1793517871.2,
  "robots": {
    "pinky1": {
      "online": true, "never_seen": false, "last_seen_age": 0.4,
      "state": "MOVING", "waypoint": 2, "detail": "ZB", "status_time": 1793517870.9,
      "pose": {"x": 0.30, "y": 0.40, "yaw": 1.57}, "pose_age": 0.4,
      "teach": {"ok": false, "warnings": ["이동 중 (MOVING). 멈춘 뒤 복사"], "std_xy": 0.021, "std_yaw": 0.05},
      "battery_percent": 87.0,
      "extra": {}
    }
  },
  "zones": {"A": "free", "B": "occupied_by:pinky1"},
  "queues": {"B": ["pinky2", "pinky3"]},
  "infra": {
    "domain_id": 100, "control_domain_id": 100, "mode": "real",
    "zone_manager": {"state": "ok", "count": 1},
    "bridges": {
      "pinky1": {"state": "ok", "count": 1, "node": "pinky_bridge_pinky1_only_100"}
    }
  }
}
```

- 단위: `pose.x`·`y` [m], `yaw` [rad], `last_seen_age` [s], `battery_percent` [%]. 모르는 값은 `null`.
- `state`·`waypoint`·`detail`·`status_time` 은 순찰 노드 `patrol_status` 를 그대로 옮긴 값입니다. 그 밖의 필드(예: `command_id`, `task_finished`)가 오면 버리지 않고 `extra` 에 담습니다.
- `patrol_status` 는 순찰 노드가 **상태가 바뀔 때만** 보내므로 연결 판단에 쓰지 않습니다. 연결 여부(`online`)는 위치·배터리 수신 시각으로 봅니다.
- `topic_age` [s]: 토픽별 마지막 수신 뒤 지난 시간 `{"pose", "battery", "status"}`. 위치(amcl)는 로봇이 멈춰 있으면 새로 오지 않는 게 정상입니다.
- `pose_age` [s]: 위치를 마지막으로 받은 뒤 지난 시간. `teach`: 위치 복사 판정 `{"ok", "warnings": [..], "std_xy" [m], "std_yaw" [rad]}`.
- `queues`: 구역별 대기 로봇 (앞 순번부터). `/zone_manager/queue_slot`(`"<구역>:<로봇>:<k>:<x>,<y>,<yaw>"`, 1초마다 다시 옴)으로 만들고, `queue_stale_sec` 동안 안 온 로봇과 이미 그 구역을 점유한 로봇은 뺍니다. 대기자가 없는 구역은 싣지 않습니다.
- `alerts`: 지금 경고 `[{"robot", "code", "level", "text"}]`. `code` 는 `offline`·`battery_low`·`state_bad`(FAILED/STOPPED)·`stuck`(끼임 의심)·`zone_hold`(구역 오래 점유, `zone` 포함). `level` 은 `warn`/`bad`.
- `events`: 이번 주기에 새로 생긴 이벤트 `[{"id", "time", "robot", "kind", "level", "text", "data"?}]`. `kind` 는 `state`·`link`·`zone`·`alert`·`clear`. `id` 는 백엔드가 붙입니다. state 이벤트의 `data.extra` 에 `command_id` 같은 모르는 필드가 그대로 남습니다.
- `infra` 는 ROS 그래프 조회로만 만듭니다 (구독·발행 없음). 1초마다 갱신합니다.
  - `mode`: 가짜 핑키 노드가 보이면 `mock`, 도메인이 `control_domain_id` 이면 `real`, 그 밖은 `test`.
  - `state`: `ok` / `missing` / `duplicate` / `unknown`(이름이 안 보임) / `n/a`(실물 아님).
  - zone_manager 는 `/zone_manager/status` **발행자 수**로 셉니다. DDS 구현이 달라 노드 이름이 안 보여도 개수는 보이기 때문입니다.
  - 브릿지는 노드 이름(`bridge_node_format`)으로 셉니다. 로봇이 꺼져 있으면 브릿지가 위치 토픽을 만들지 않으므로, 이름이 안 보이는 브릿지는 로봇이 켜졌을 때만 `unknown` 으로 드러납니다.
- 지금은 `std_msgs/String` JSON 입니다. 필드가 정해지면 `cobot_interfaces` 메시지로 바꿀 예정입니다 (팀 공지·리뷰 필요).

## 작업 (task_manager_node)

### 작업 상태

```
ACCEPTED ─▶ SENT ─▶ RUNNING ─▶ SUCCEEDED / FAILED / STOPPED
   └─ 검증 실패 ─▶ REJECTED      └─ 응답 없음·시간 초과 ─▶ UNKNOWN ─(사람이 해제)─▶ FAILED 등
```

- **기록이 먼저**: `ACCEPTED` 를 SQLite 에 적은 뒤에만 로봇에 보냅니다.
- **거절(REJECTED)**: 없는 지점(`unknown point: ['P99']`), 구역 지점을 goto 로(`use zone`), 미실측 `(0,0,0)` 지점(`unmeasured point` — 로봇은 받지만 원점으로 감), 연결 끊김, 진행 중 작업, 결과 모름 작업. v2 로봇이 ack 로 거절해도 `REJECTED`(`robot: <이유>`).
- **결과 모름(UNKNOWN)**: 보낸 뒤 `ack_timeout_sec` 안에 시작 응답이 없거나(v1 로봇은 바쁠 때 아무 응답 없이 무시함), 시작 뒤 `task_timeout_sec` 를 넘김. 실제로는 움직이고 있을 수 있으므로 해제 전에는 그 로봇에 새 작업을 보내지 않습니다.
- **재시작**: `task_manager_node` 를 켤 때 끝나지 않은 작업은 다시 보내지 않고 `UNKNOWN`(관제 재시작: 현장 확인 필요)으로 바꿉니다.
- 같은 `client_request_id` 로 다시 오면 새로 보내지 않고 기존 작업을 돌려줍니다 (두 번 눌러도 한 번만 움직임).

### v1 / v2

`spec_mode: auto`(기본)이면 그 로봇의 v2 `patrol_state` 가 최근 `v2_fresh_sec` 안에 왔을 때만 v2 로 보냅니다. 실물은 v2 토픽이 브릿지되지 않아 v1 로 갑니다.

| | v1 (실물 순찰 노드) | v2 (`cobot_patrol_interfaces`, 지금은 가짜 핑키만) |
|---|---|---|
| 명령 | `patrol_cmd` 문자열 `goto:P1,P2` | `PatrolCommand(task_id, operation, points)` |
| 시작 | 보낸 뒤 첫 `STARTING`(유휴 복귀 `idle return` 제외) 또는 이동 상태 | `PatrolCommandAck.accepted` |
| 끝 | 다음 `DONE`/`FAILED`/`STOPPED` 를 그 작업 것으로 **추정** | `task_id` 가 같고 `task_finished` 인 상태 |

### 개발용 수동 명령 (`raw_cmd`)

- 작업 관리를 거치지 않는 1회성 직접 명령입니다. 지점·바쁨 검사, 작업 기록, 결과 추적(UNKNOWN)이 없고 `task_manager_node` 의 사건 기록(`operator_raw`)에만 남습니다.
- 보내는 곳은 v1 `/pinkyN/patrol_cmd` 하나입니다 (v2 는 구조화된 메시지라 자유 문자열을 싣지 않음).
- `allow_raw_cmd` 가 켜져 있을 때만 받습니다 (기본 꺼짐, 가짜 핑키 launch 만 켬). 그 로봇에 진행 중이거나 결과를 모르는 관제 작업이 있으면 거절합니다.

## 파라미터

`fleet_status_node` (`config/fleet_status_node.yaml`)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `robots` | `[pinky1, pinky2, pinky3]` | 관제 PC 쪽 토픽 접두사 |
| `stale_timeout_sec` | `8.0` | 위치·배터리가 이만큼 끊기면 offline [s]. 실물 배터리 토픽이 5초 주기라 그보다 길게 |
| `publish_period_sec` | `1.0` | `fleet_status` 발행 주기 [s] |
| `control_domain_id` | `100` | 실물 관제 도메인. 이 도메인에서만 브릿지·zone_manager 를 검사 |
| `bridge_node_format` | `pinky_bridge_{robot}_only_{domain}` | 관제 PC 쪽 브릿지 노드 이름. 브릿지 설정 `name` 에 도메인이 붙은 모양 |
| `mock_node_name` | `mock_pinky_node` | 이 노드가 보이면 `mock` 모드 |
| `teach_max_std_xy` | `0.05` | 위치 복사 경고 기준, amcl 위치 표준편차 [m]. 임시값 (현장 실측 뒤 조정) |
| `teach_max_std_yaw` | `0.1` | 위치 복사 경고 기준, amcl 방향 표준편차 [rad]. 임시값 |
| `battery_warn_percent` | `20.0` | 이 값 이하면 배터리 경고 [%] |
| `stuck_sec` | `15.0` | 이동 중 state 인데 이만큼 거의 제자리면 끼임 의심 [s]. 임시값 |
| `stuck_distance_m` | `0.05` | '거의 제자리' 기준 거리 [m]. 임시값 |
| `zone_hold_warn_sec` | `200.0` | 구역을 이만큼 점유하면 경고 [s] (zone_manager `max_hold_sec` 240 보다 먼저) |
| `queue_stale_sec` | `2.5` | 대기 슬롯 알림이 이만큼 안 오면 대기열을 떠난 것으로 봄 [s] (zone_manager 는 1초마다 다시 냄) |

`fleet_api_node` (`config/fleet_api_node.yaml`)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `host` | `127.0.0.1` | 바인드 주소. 다른 PC 에서 직접 접속하려면 `0.0.0.0` (로그인 없음 주의) |
| `port` | `8080` | launch 인자 `port:=` 로 바꿈. 가짜 핑키(`cobot_mock`)는 8081 을 써서 한 PC 에서 함께 띄울 수 있음 |
| `source_stale_sec` | `3.0` | `fleet_status` 가 이만큼 끊기면 `source_online=false` [s] |
| `map_yaml` | launch 인자가 채움 | 지도 YAML. 비거나 읽지 못하면 지도 없이 시작 |
| `web_dir` | `share/cobot_control_center/web` | 화면 정적 파일 폴더 |
| `points_dir` | launch 인자가 채움 | 순찰 설정 `pinkyN.yaml` 폴더 (구역 지점·출구·홈·일반 지점) |
| `zone_params` | launch 인자가 채움 | zone_manager 설정 (로봇 목록 `robot_ids`, 대기 슬롯). 둘 중 하나라도 비거나 못 읽으면 구역 표시 없이 시작 |
| `events_max` | `500` | 이벤트 로그 보관 개수. 메모리에만 두므로 백엔드를 다시 켜면 지워짐 |
| `task_stale_sec` | `3.0` | 작업 노드 목록이 이만큼 끊기면 명령을 받지 않음 (503) [s] |
| `reply_timeout_sec` | `2.0` | 명령 요청에 작업 노드가 답하기를 기다리는 시간 [s] |
| `read_only` | `false` | `true` 면 명령 경로가 모두 503 이고 `task_request` 발행자를 만들지 않음. `fleet_api_dev.launch.xml` 이 켬 (노드 이름 `fleet_api_node_dev`, 포트 8083) |
| `camera_robots` | `[pinky1, pinky2, pinky3]` | 카메라를 구독할 로봇. `['']` 이면 끔 |
| `camera_topic_format` | `/{robot}/camera/image_raw/compressed` | 카메라 토픽 (`sensor_msgs/CompressedImage`, JPEG). QoS `BEST_EFFORT / VOLATILE / KEEP_LAST(1)`. 이름은 가정값(비전 브랜치 592ebd4 규격 + 로봇 접두사)이라 확정되면 바꿈. 실물은 브릿지에 카메라 토픽이 있어야 들어옴 (아직 없음) |

`task_manager_node` (`config/task_manager_node.yaml`)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `robots` | `[pinky1, pinky2, pinky3]` | 관제 PC 쪽 토픽 접두사 |
| `db_path` | `~/.ros/cobot_control_center/tasks.db` | 작업·사건 기록 (SQLite, WAL). 가짜 핑키는 `tasks_mock.db` |
| `points_dir` | launch 인자가 채움 | `pinkyN.yaml` 폴더 (지점 검사). 비면 검사를 로봇에만 맡기고 경고 |
| `ack_timeout_sec` | `3.0` | 보낸 뒤 시작 응답 기다림 [s]. 실측 필요 |
| `task_timeout_sec` | `300.0` | 시작 뒤 끝 기다림 [s]. 실측 필요 |
| `fleet_stale_sec` | `3.0` | `fleet_status` 가 끊기면 새 작업을 받지 않음 [s] |
| `retention_days` | `30.0` | 켤 때 이보다 오래된 사건을 지움 [일]. 0 이하면 지우지 않음. 작업 표는 남김 |
| `spec_mode` | `auto` | `auto` / `v1` / `v2` (launch 인자 `spec_mode:=`) |
| `v2_fresh_sec` | `3.0` | auto 에서 v2 로봇으로 보는 기준 [s] |
| `tick_period_sec` | `0.2` | 시간 초과 검사 주기 [s] |
| `publish_period_sec` | `1.0` | `/control_center/tasks` 를 다시 내는 주기 [s] |
| `list_limit` | `50` | `/control_center/tasks` 에 싣는 최근 작업 수 |
| `allow_raw_cmd` | `false` | 개발용 수동 명령 (launch 인자 `allow_raw_cmd:=`). 가짜 핑키 launch 만 `true` |
| `start_armed` | `false` | 작업 명령 켜진 상태로 시작할지 (launch 인자 `start_armed:=`). 실물은 꺼 두고 화면에서 켬. 가짜 핑키 launch 만 `true` |

### 지도·구역 기본 경로

지도 기본값은 로봇이 쓰는 지도 `src/cobot_navigation/map_view_pc/maps/cobot_map_v9.yaml` 입니다.
launch 가 colcon 표준 배치(`<ws>/install/<pkg>/share/<pkg>`)에서 `<ws>/src` 로 거슬러 올라가 찾습니다. 지도를 바꾸면 `map_yaml:=` 로 지정합니다.
구역 표시 기본값도 같은 방식으로 `src/cobot_navigation/cobot_pinky_patrol/config`, `src/cobot_navigation/cobot_zone_traffic_control/config/zone_params.yaml` 을 가리킵니다 (`points_dir:=`, `zone_params:=`).

## 화면 스크립트 (`web/`)

외부 라이브러리·CDN·빌드 단계가 없습니다. `index.html` 에 적은 순서로 읽히고 전역 이름을 함께 씁니다 (core.js 먼저, main.js 마지막). 파일을 새로 만들면 다시 빌드합니다.

| 파일 | 맡은 일 |
|---|---|
| `core.js` | 공통 함수, `/ws/fleet` 연결 |
| `cards.js` | 로봇 카드, 위험구역 칸 |
| `events.js` | 경고 띠, 이벤트 로그 |
| `commands.js` | 명령 보내기, 지점 고르기 |
| `tasks.js` | 작업 목록 (`/ws/tasks`) |
| `map.js` | 지도, 구역·지점 표시 |
| `raw.js` | 개발용 수동 명령 |
| `detail.js` | 로봇 상세 화면 (`#/robot/<id>`): 상태줄·카메라·확대 지도·요약·타임라인·진단 |
| `main.js` | 시작, `/api/health` 확인 |
