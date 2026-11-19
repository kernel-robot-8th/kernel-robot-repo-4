# cobot_control_center API·데이터 형식·파라미터

개발할 때 보는 참고 문서입니다. 설치·실행은 [README](../README.md), 화면 사용법은 [screen_guide.md](screen_guide.md) 를 봅니다.

## 웹 API

`/api/tasks`·정지·해제·작업 명령 켜기/끄기·개발용 수동 명령·로봇팔 명령 외에는 읽기 전용입니다. 명령 경로는 작업 노드 `fleet_control_node`(`cobot_fleet_control`)에 넘기기만 하고, 작업 노드가 없거나 읽기 전용 백엔드(`read_only`)면 503 입니다.
작업 노드는 **작업 명령 꺼짐**으로 시작합니다. 꺼져 있는 동안 `POST /api/tasks`·`raw_cmd`는 `423`입니다. 정지는 항상 요청할 수 있고, 해제에는 최신 정지 상태 확인이 필요합니다.
GET·WS 가 돌려주는 값은 모두 `fleet_api_node` 가 토픽으로 받아 메모리에 둔 최신값입니다 (DB 를 읽지 않음, [README 데이터 흐름](../README.md#데이터-흐름)).

| 경로 | 응답 |
|---|---|
| `GET /` | 관제 화면 |
| `GET /api/health` | `{"ok": true, "domain_id": 백엔드의 ROS_DOMAIN_ID, "read_only": 개발용 읽기 전용 백엔드인지, "source_online": bool, "source_age": 초 또는 null, "controller_online": 작업 노드(fleet_control_node)가 켜져 있는지 (`cobot_fleet_control` 의 도커 smoke_check 도 읽음), "controller_age", "spec": 로봇별 명령 규격, "raw_cmd_enabled": 수동 명령 칸을 보일지, "commands_armed": 작업 명령이 켜져 있는지 (작업 노드가 꺼지면 false), "holds": {"pinky1": "ESTOP"} fleet 이 보류한 로봇 → 사유, "orders": [끝나지 않은 주문, 아래 형식], "routes": {"pinky1": 마지막 경로 (`GET /api/routes` 의 robots)}, "cameras": {"pinky1": {"age_sec": 마지막 영상 프레임 뒤 지난 초 또는 null, "frames": 받은 수}}, "arm_controller_online": 로봇팔 명령 노드(arm_command_node)가 켜져 있는지}` |
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
| `POST /api/routes` | 경로 (여러 지점 섞어 연결 주행). `{"client_request_id", "robot_id", "points": ["P1", "ZA", "P3", "I1"]}`. 백엔드가 구간으로 나눔 (이어지는 일반 지점·자기 홈은 `goto` 하나, 구역 지점은 하나씩 `zone`) → 첫 구간을 바로 보내고 `202` 경로 / `400` 모르는 지점·구역 출구·다른 로봇 홈·지점 없음·20개 넘음 / `404` 없는 로봇 / `409` 진행 중인 경로가 있음, 또는 첫 구간 거절 (`{"detail", "route"}`) / `423` 작업 명령 꺼짐 / `503` 작업 노드·지점 설정 없음. 앞 구간이 `SUCCEEDED` 면 다음 구간, `FAILED`·`STOPPED`·`REJECTED`·`UNKNOWN` 이면 경로 `FAILED`. 작업이 안 만들어진 `409`·`503`·응답 없음은 `route_retry_sec` 동안 같은 `client_request_id`(`<route_id>-<구간 번호>`)로 다시 보냄. 정지·비상정지·전체 비상정지는 남은 구간을 버림 (`CANCELED`). 시작·구간 성공·완료·취소·중단은 이벤트 로그에 `kind: "route"` 로 남김 (`data`: `route_id`, `index`, `total`, `state`) |
| `GET /api/routes` | `{"robots": {"pinky1": 마지막 경로}, "recent": [끝난 경로, 최신순 20개]}`. 경로 = `{"route_id", "robot_id", "points", "legs": [{"operation", "points", "task_id", "state": WAITING·작업 상태}], "index": 지금 구간, "state": RUNNING·SUCCEEDED·FAILED·CANCELED, "detail", "created_at", "updated_at"}`. 백엔드 메모리라 다시 켜면 사라짐 |
| `POST /api/routes/{robot_id}/cancel` | 남은 구간만 버림 → `{"canceled": [route_id]}`. 지금 가는 구간은 멈추지 않음 (멈추려면 정지) |
| `GET /api/waypoints` | 관제 웨이포인트·묶음 (2026-11-18). `{"waypoints": [{"name", "x", "y", "yaw", "robot_id", "captured_at", "warnings", "note"}], "groups": [{"name", "points", "note", "updated_at"}], "keepout_m", "load_error"}` |
| `POST /api/waypoints` | `{"robot_id", "name"?, "note"?}` → 그 로봇의 **지금 위치**(이 서버가 받은 마지막 fleet_status)로 저장, `201`. 이름을 비우면 `W1, W2 …`. `400` 이름 형식 / `404` 없는 로봇 / `409` 위치 모름·로봇 설정과 같은 이름·이미 있는 이름·구역 지점·출구에서 `zone_keepout_m` 안 (기본 0 = 검사 안 함) / `503` 읽기 전용·파일 못 씀 |
| `PATCH /api/waypoints/{name}` | `{"name"?, "note"?}` 이름 바꾸기(묶음 안 이름도 바뀜)·메모 |
| `DELETE /api/waypoints/{name}` | 지움 → `{"deleted", "groups_changed": [이 이름을 빼낸 묶음]}` |
| `GET /api/waypoints/export?names=W1,W2` | 로봇 설정 `points:` 에 붙일 YAML 줄 (text/plain). names 를 비우면 전체 |
| `PUT /api/waypoint_groups/{name}` | `{"points": [...], "note"?}` 묶음 만들기·바꾸기. 지점은 로봇 설정 지점 또는 관제 웨이포인트, 1~20개 |
| `DELETE /api/waypoint_groups/{name}` | 묶음 지움 (지점은 남음) |

**관제 웨이포인트를 이동·경로에 쓰면**: `POST /api/tasks`(goto)·`POST /api/routes` 의 지점 이름 중 관제 웨이포인트는 좌표를 `poses: {"W1": [x, y, yaw]}` 로 붙여 작업 노드에 넘긴다. 작업 노드(`fleet_control`)가 이름 충돌·구역 거리를 다시 검사하고 순찰 노드 봉투에 `poses` 를 실어 보낸다. 순찰 노드는 로봇 설정에 없는 이름이면 그 좌표로 간다 (goto 만). `poses` 를 모르는 예전 순찰 노드는 `unknown point` 로 거절한다.
| `POST /api/commands/arm` | `{"client_request_id", "armed": true\|false}` → `200 {"armed", "changed", "source": 요청한 IP, "client_request_id"}` / `400` armed 가 bool 이 아님. 작업 노드 사건 `operator_arm` 으로 남김 |
| `POST /api/robots/{robot_id}/stop` | `{"client_request_id", "emergency": false}` → `202`. 바쁨과 무관하게 항상 보냄. `emergency: true` 면 그 로봇 `estop` 으로 바꿔 보냄 |
| `POST /api/commands/estop` | `{"client_request_id"}` → 전체 비상정지 (로봇·팔 모두) |
| `POST /api/robots/{robot_id}/initial_pose` | AMCL 위치를 다시 잡음 (로봇은 움직이지 않음). body `{"client_request_id", "pose"?}`. `pose` 가 없으면 fleet 이 순찰 설정의 홈을 씀. `pose: {x, y, yaw}` ([m], [m], [rad], map 프레임)면 그 좌표 (화면 상세 지도의 좌표 지정). 숫자가 아니거나 지도 밖이면 이 백엔드가 400. 누가는 접속 IP(`source`). 202 면 `{robot_id, mode: home\|manual, point, x, y, yaw, topic}` (좌표면 `point` 는 `좌표`), 거절이면 fleet 사유를 `detail` 로 |
| `POST /api/robots/{robot_id}/release_control` | 정지 잠금 복구 (주문 없는 로봇). `operator`·`note`는 선택. 최신 정지 상태를 확인한 뒤 `202 {robot_id, released: false, reset_pending: true}`. 로봇 해제 응답 후 `/api/health`의 보류가 사라짐. 상태 미확인은 409 |
| `POST /api/zones/{zone}/release` | 구역 강제 해제 (토큰을 쥔 채 꺼졌거나 다시 켜져 잊은 로봇). body `{"robot_id", "client_request_id"?, "note"?}`. fleet 이 최신 zone_manager 상태(3초 안)가 `occupied_by:<robot_id>` 인지, 로봇이 연결 끊김이거나 멈춰 있고 `held_zone` 이 그 구역이 아닌지 본 뒤 `/zone_manager/notify_exit "<zone>:<robot_id>"` 를 한 번 냄. `202 {zone, robot_id, robot_online, released: "sent"}`. 점유자 다름·아직 잡고 있음·움직임·주문 있음·`held_zone` 보고 없음은 409, 구역 상태 없음은 503. 작업 명령 켜기 불필요. 누가는 접속 IP(`source`) |
| `POST /api/robots/{robot_id}/raw_cmd` | 개발용. `{"client_request_id", "command": "goto:P3,P7"}` → `202 {"robot_id", "command", "raw_id", "spec": "v1", "topic": "/pinky1/patrol_cmd", "msg_type": "std_msgs/msg/String", "warning"}` / `423` 작업 명령 꺼짐 / `403` allow_raw_cmd 꺼짐 / `400` 빈 명령·여러 줄·200자 넘음 / `409` 진행 중·결과 모름 작업. 검사 없이 `patrol_cmd` 에 그대로 |
| `POST /api/tasks/{task_id}/resolve` | `{"client_request_id", "result": "FAILED", "note"?}`. UNKNOWN만 접수. 202의 작업은 UNKNOWN·`reset_pending=true`이며 로봇 해제 응답 후 FAILED로 변경. 정지 미확인은 409 |
| `POST /api/orders/{order_id}/recover` | `{"client_request_id", "decision": "resume" \| "fail", "evidence"?, "operator"?, "note"?}`. 재개는 `MOVE_PICKUP`·`MOVE_DROPOFF`·`RETURN_HOME`·`CUSTOMER`만 가능. 로봇은 최신 정지 상태여야 함. 자원을 예약한 주문 취소는 `evidence`의 `arms_safe`·`cargo_reconciled`·`resources_clear` 모두 true 필요. 화면에서 각각 현장 확인. 취소 후에도 로봇 해제 응답 전에는 보류 유지 |
| `POST /api/orders/{order_id}/confirm_loaded` | 수동 상차 확인 (화면: 카드의 상차 확인 대기 줄). `{"client_request_id", "operator", "note", "evidence": {"sku", "load_present": true, "arm_safe": true, "pickup_path_clear": true}}` → `200` 갱신된 주문 / `400` 검사 실패(fleet 이 낸 사유를 `detail` 로) / `503` 작업 노드 없음. 통과하면 fleet 이 상차 구역 이탈부터 재개 |
| `GET /api/tasks?robot_id=&state=&limit=50` | 최근 작업 (최신순) |
| `GET /api/tasks/{task_id}` | 작업 하나 `{"task_id", "robot_id", "operation", "points", "command", "spec", "state", "detail", "created_at", "updated_at", "history": [{"at", "state", "detail"}]}` |
| `GET /api/network?history=` | 네트워크 화면 구조도 (아래 [네트워크](#네트워크-net_status_node)). `history=true` 면 대상별 최근 핑 기록도 |
| `POST /api/network/check` | 자세히 확인 (10 s 동안 1 s 마다 핑 + 상태 토픽 주기). `202 {"duration_sec"}` / `503` 측정 노드 없음. 로봇에는 아무것도 보내지 않아 읽기 전용 백엔드에서도 된다 |
| `GET /api/arms` | 로봇팔 상태 모음 `{"controller_online", "controller_age", "ttl_ms", "arms": [..]}` (아래 [로봇팔](#로봇팔-arm_command_node)). 명령 노드가 끊기면 팔마다 `STALE` 로 바꿔 냄 |
| `GET /api/arms/events?after=0&arm=&limit=100` | 로봇팔 알람 기록, 오래된 것부터 `[{"id", "time", "arm", "kind", "level", "text", "data"?}]`. `after` 로 이어 받기. 아래 [알람](#알람-활성-알람기록) |
| `POST /api/arms/{arm_id}/work` | 작업 시험 한 건 (개발용, **실제 팔이 움직임**). `{"action": "pick"\|"load"\|"unload"\|"warehouse_store"\|"arrange_shoe", "shelf_row": 1..9 (선택, 상자 번호 모델용), "client_request_id"}` → `202` 보냄 (`work_id`, 결과는 `/api/arms` 의 `arm.work`) / `409` 작업 명령 꺼짐(`commands_armed` 거짓, 작업 노드 없음 포함)·그 자리 팔이 하지 않는 작업(`site_arms.yaml` `actions`)·팔이 `READY` 아님·앞 작업 진행 중 / `404` 등록 안 된 팔 / `400` 모르는 작업 / `503` 읽기 전용·명령 노드 없음·응답 없음. 아래 [작업 시험](#작업-시험-개발용) |
| `POST /api/arms/{arm_id}/command` | `{"command": "start"\|"reset"\|"hold"\|"release_hold"\|"soft_latch", "client_request_id"}` → `200` 팔이 수락 (정지는 거절돼도 `stop_executed` 면 200) / `409` 팔이 거절 (`result`, `reason`) / `404` 등록 안 된 팔 / `400` 모르는 명령 / `503` 읽기 전용·명령 노드 없음·응답 없음 / `504` 팔 노드가 기한(8 s) 안에 답하지 않음. `/api/commands/arm` (작업 명령 켜기)와 다른 것 |
| `WS /ws/tasks` | 연결 즉시 `{"type": "tasks", "tasks": [..]}`, 이후 바뀐 작업마다 `{"type": "task", "task": {..}}` |

해제 응답은 같은 부팅의 `control_reset_id`와 요청 ID가 일치해야 합니다. 일반 하트비트만으로
복구를 완료하지 않습니다. `RESET_PENDING`은 응답 대기, `RESET_UNCONFIRMED`는 만료·재시작 등으로
확인하지 못한 보류입니다. 최신 상태를 확인하고 다시 요청할 수 있습니다.
관제·웹과 로봇의 `cobot_pinky_patrol`을 함께 배포해야 합니다.

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
- `events`: 이번 주기에 새로 생긴 이벤트 `[{"id", "time", "robot", "kind", "level", "text", "data"?}]`. `kind` 는 `state`·`link`·`zone`·`alert`·`clear`·`cmd`. `id` 는 백엔드가 붙입니다. state 이벤트의 `data.extra` 에 `command_id` 같은 모르는 필드가 그대로 남습니다.
  - `cmd`: 관제(`fleet_control_node`)가 `/pinkyN/patrol_cmd` 로 낸 주행 명령. `fleet_status_node` 가 **구독만** 해서 남깁니다. 글 `명령 zone:ZA (a1b2c3)` (봉투 없는 문자열이면 `(봉투 없음)`), `data: {command_id, command}`. `stop`·`control_reset` 은 warn, `emergency_stop` 은 bad.
    같은 `command_id` 의 `patrol_status` 가 `task_finished: true` 를 내면 `명령 완료 zone:ZA (12.3 s)` (FAILED 면 `명령 실패 …: 사유`, bad), `data` 에 `state`·`duration` 을 더합니다. 순찰 상태가 올 때마다 보므로 1초 사이에 끝나도 놓치지 않습니다.
- 주문 이벤트(`kind: "order"`)는 이 스냅샷이 아니라 `fleet_api_node` 가 `/control_center/tasks` 의 `orders` 를 1초마다 비교해 같은 이벤트 로그(`/api/events`, `/ws/fleet` 의 `events`)에 넣습니다 (`fleet_api_utils.order_events`). `robot` 은 주문의 `robot_id`(배정 전 null), `data` 는 주문 필드(`order_id`·`robot_id`·`state`·`stage`·`sku`·`route` 등).
  - 접수 `주문 <id> 접수 (SKU, 루트 …)`, 단계 `주문 <id> MOVE_PICKUP → PICK`, 로봇 배정, 완료 info.
  - 실패 사유가 생김(fleet 은 사유를 먼저 적고 HOME 복귀 뒤 FAILED 로 끝냄)·`FAILED`·`UNKNOWN` 등 보류 상태 bad.
  - 백엔드를 막 켜면 끝나지 않은 주문만 `진행 중 <state> <stage>` 한 줄씩 남깁니다.
- `infra` 는 ROS 그래프 조회로만 만듭니다 (구독·발행 없음). 1초마다 갱신합니다.
  - `mode`: 가짜 핑키 노드가 보이면 `mock`, 도메인이 `control_domain_id` 이면 `real`, 그 밖은 `test`.
  - `state`: `ok` / `missing` / `duplicate` / `unknown`(이름이 안 보임) / `n/a`(실물 아님).
  - zone_manager 는 `/zone_manager/status` **발행자 수**로 셉니다. DDS 구현이 달라 노드 이름이 안 보여도 개수는 보이기 때문입니다.
  - 브릿지는 노드 이름(`bridge_node_format`)으로 셉니다. 로봇이 꺼져 있으면 브릿지가 위치 토픽을 만들지 않으므로, 이름이 안 보이는 브릿지는 로봇이 켜졌을 때만 `unknown` 으로 드러납니다.
- 지금은 `std_msgs/String` JSON 입니다. 필드가 정해지면 `cobot_interfaces` 메시지로 바꿀 예정입니다 (팀 공지·리뷰 필요).

## 작업·주문 (fleet_control_node)

작업 상태, 관제 재시작 뒤 처리(`UNKNOWN`), 수동 명령(`raw_cmd`) 검사는 작업 노드가 정합니다 → [`cobot_fleet_control/README.md`](../../cobot_navigation/cobot_fleet_control/README.md). 이 백엔드는 `/control_center/tasks` 에 실려 오는 값을 그대로 보여 줍니다. 예전 작업 노드 `task_manager_node` 는 2026-11-09 에 지웠습니다.

### `/api/health` 의 `orders`

fleet 이 `/control_center/tasks` 에 싣는 주문 원장 사본(`orders`)에서 **끝나지 않은 주문**(`state` 가 `COMPLETED`·`FAILED` 가 아닌 것)만 골라, 화면에 필요한 필드만 냅니다 (`fleet_api_utils.active_orders`).

| 필드 | 뜻 |
|---|---|
| `order_id`, `robot_id`, `sku`, `route` | 주문 ID, 배정된 로봇(없으면 null), 상품, 경로 (`lab_delivery` 등) |
| `state`, `stage`, `completed`, `detail` | fleet 주문 상태(`WAITING`·`RUNNING`·`UNKNOWN` 등), 지금 단계(`MOVE_PICKUP` 등), 끝낸 단계 목록, 설명 |
| `load_confirmed` | 운영자 수동 상차 확인을 이미 받았는지 |
| `load_confirmable` | 화면에 **상차 확인** 을 보일지. `state` 가 `RUNNING`/`UNKNOWN`, `stage` 가 `PICKUP_EXIT`~`VERIFY_LOAD` 또는 `CORRECT_PICKUP`, `completed` 에 `MOVE_PICKUP`, 로봇 배정됨, 실패 없음, 아직 확인 안 함 (`fleet_api_utils.load_confirmable`). fleet 의 검사(`scenario_safety.confirm_loaded`)와 같은 조건이지만 표시용이고, 최종 검사(정지·통신·구역·예약)는 fleet 이 합니다 |

## 로봇팔 (arm_command_node)

웹은 팔 토픽을 모릅니다. `fleet_api_node` 가 요청을 `/control_center/arm_request` 로 넘기고, `arm_command_node` 가
`ArmCommand` 로 바꿔 Station PC 의 팔 노드(`cobot_manipulation` 의 `arm_adapter_node`, 브랜치 `feature/manipulation-station-adapter`)에 냅니다.
`ArmCommand` 로는 팔 모션을 시작하지 않습니다 (`ArmCommand.msg`). 켜기는 연결·토크, 끄기는 쉬는 자세에서 토크 끄기, 나머지는 정지·해제입니다.
주문의 작업(pick·load)은 `fleet_control_node` 가 `/fleet/work_request` 로 보냅니다. 개발용 [작업 시험](#작업-시험-개발용)은 이 노드가 같은 토픽으로 한 건씩 보냅니다.

```text
브라우저 ─HTTP→ fleet_api_node ─/control_center/arm_request→ arm_command_node ─/control_center/omx_N/command (ArmCommand)→ 팔 노드
        ←──────              ←─/control_center/arm_events (응답)─┤  ←─/manipulation/omx_N/command_ack (CommandAck)─┤
                             ←─/control_center/arms (상태 모음)──┘  ←─/manipulation/omx_N/status (ArmStatus, 10 Hz)─┤
                                                                     ←─/manipulation/omx_N/info (String JSON)────────┘
```

| 토픽 | 타입·QoS |
|---|---|
| `/control_center/arm_request`, `/control_center/arm_events` | `std_msgs/String` JSON, RELIABLE depth 50. `arm_events` 는 요청 응답(`type: reply`)과 알람 기록(`type: event`)을 함께 나른다 |
| `/control_center/arms` | `std_msgs/String` JSON, RELIABLE TRANSIENT_LOCAL depth 1, 0.2 s 주기 |
| `/control_center/omx_N/command` | `ArmCommand`, RELIABLE depth 10 (팔 노드와 같음) |
| `/manipulation/omx_N/command_ack` | `CommandAck`, RELIABLE depth 50 |
| `/manipulation/omx_N/status` | `ArmStatus`, BEST_EFFORT KEEP_LAST 1 |
| `/manipulation/omx_N/info` | `std_msgs/String` JSON, RELIABLE TRANSIENT_LOCAL depth 1. 팔 노드가 바뀔 때 + 5 s 마다. 백엔드·보드 탐지·실행기 모델·쉬는 자세 (`ArmStatus` 에 칸이 없어 따로, 팔 노드 `arm_info_utils`) |
| `/fleet/work_request`, `/fleet/work_result` | `std_msgs/String` JSON, RELIABLE depth 50 (`fleet_control_node` 와 같음). 작업 시험을 내고, 주문(`fleet_control_node`)이 낸 요청도 **듣기만** 해서 그 팔 카드 `work` 와 기록에 남김. 결과는 `request_id` 로 짝지음 |

헤더 (`CommandHeader`): `command_id` 새 UUID, `tx_id` = `client_request_id`, `robot_id` = `omx_N`, `ttl_ms` 5000, `issued_by` `control_center`, `issued_at` 관제 PC 시계.
팔 노드가 `issued_at + ttl` 을 자기 시계로 보므로 **두 PC 시계가 맞아야** 합니다 (안 맞으면 모두 `REJECTED_TTL`). 서명(`sig`)은 아직 채우지 않습니다 (팔 노드도 안 봄).

- **epoch**: START 는 (내가 쓴 값, 팔이 받아들인 값) 중 큰 값 + 1. 팔 노드를 다시 켜면 팔 쪽이 0 으로 돌아가도 새 START 가 받아들여집니다. 그 밖의 명령은 팔이 받아들인 epoch (`ArmStatus.epoch_accepted`).
- **seq**: (내가 쓴 값, 팔이 받아들인 값) 중 큰 값 + 1.
- 같은 `CommandAck` 가 두 번 와도 한 번만 답하고 첫 기록을 남깁니다.

`arms[]` 한 칸:

| 필드 | 뜻 |
|---|---|
| `arm_id`, `alias` | 명세 이름 `omx_1`, 관제 시나리오 이름 `omx1` |
| `online`, `age` | `ArmStatus` 를 `status_stale_sec`(1 s) 안에 받았는지, 지난 초 |
| `state` | 화면 상태 (아래), `allowed` 는 그 상태에서 켤 버튼 힌트 (최종 판정은 팔 노드) |
| `status` | 마지막 `ArmStatus` (NaN 은 null, `stamp` 는 측정 시각 [s]) |
| `last_ack` | 그 팔의 마지막 응답 `{command, result, accepted, reason, stop_executed, epoch, seq, received_at}`. 다른 곳이 낸 명령이면 `command` 없음 |
| `pending`, `epoch`, `seq` | 응답 기다리는 명령 수, 팔이 받아들인 epoch·seq |
| `site` | 현장 팔 배치 `{station, role, host, serial, actions}` 또는 null (`config/site_arms.yaml`, 빈 칸은 미정). `actions` 말고는 표시용 |
| `work_actions` | 그 팔에 작업 시험으로 보낼 수 있는 작업 (`site.actions`, 칸이 없으면 전체). 비면 `allowed` 에 `work` 가 없음 |
| `work` | 마지막 작업 `{request_id, action, state, seq, sent_at, finished_at, duration, detail, retry_safe, data, source, requested_by, order_id, robot_id, stage}` 또는 null. `state`: `RUNNING`·`SUCCEEDED`·`FAILED`·`NO_RESULT`. `source`: `test`(웹 작업 시험, `requested_by` 는 누른 곳 IP) / `order`(fleet_control 주문 작업, `order_id`·`robot_id`·`stage` 채움). 주문 작업이 진행 중이면 작업 시험은 409. 결과 기한은 요청의 `timeout_sec` + `work_result_margin_sec` (작업 시험은 `work_timeout_sec`). `stage: SAFETY`(release_hold 등) 요청은 `work` 를 바꾸지 않고 기록만. 실행기가 모델을 알려 주면 `data.model` (`omx_pick_za@v1`) |
| `info` | 팔 노드 info 그대로 `{v, arm_id, interface_arm_id, boot_id, backend, detect: {state, reason, port}, power, worker: {ready, actions, models, rest_pose, safe_tol} 또는 {fake, ready}, dead, at}` 또는 null (예전 팔 노드). `worker.models` 는 작업별 `{bundle, version, model_name, path, init_pose, success_judge}` (`omx_fleet` 번들 규격), 끈 뒤에도 마지막 값 |
| `start_block` | 켜기가 안 되는 이유 (`backend=none`, 보드 탐지 실패, 실행기 고장) 또는 `''`. 있으면 `OFF` 의 `allowed` 에서 `start` 를 뺌 (`arm_command_utils.start_block`). info 가 없으면 `''` |
| `rest_check` | 지금 관절과 실행기 `rest_pose` 차이 `{configured, tol, diff: {관절: 지금-쉬는자세}, worst, at_rest}` 또는 null (info·실행기 정보 없음, fake). 그리퍼 제외. `configured=false` 면 끄기는 늘 거절. 관절 값이 없으면 `diff`·`at_rest` null (`arm_command_utils.rest_check`) |
| `alarms` | 활성 알람 `[{code, level, since, text}]` (아래 [알람](#알람-활성-알람기록)) |

스냅샷 맨 위의 `work_actions` 는 작업 시험에 쓸 수 있는 작업 목록입니다.

`ArmStatus` 에 전원 상태 칸이 없어 `state` 는 추정입니다 (`arm_command_utils.derive_state`).

| `state` | 조건 | `allowed` |
|---|---|---|
| `STALE` | 상태가 안 들어옴 | hold, soft_latch |
| `SOFT_LATCH` | `hold_reason == SOFT_LATCH` | reset, hold |
| `HOLD` | `hold_active` | release_hold, reset, soft_latch |
| `OFF` | 토크 꺼짐 | start (`start_block` 이 있으면 뺌), hold, soft_latch |
| `FAULT` | 토크 꺼짐이고 마지막 응답이 켜기 거절 `(지금 FAULT)` (팔 실행기가 멈춤). `ArmStatus` 에 전원 상태 칸이 없어 거절 사유로 판단하는 임시 방법. 끄기 수락 등 다음 응답이 오면 풀림 | reset, hold, soft_latch |
| `READY` | 토크 켜짐, `work_step == IDLE` | work (작업 시험 진행 중이면 뺌), reset, hold, soft_latch |
| `BUSY` | 토크 켜짐, 그 밖 (연결·작업·끄는 중) | hold, soft_latch |

### 알람 (활성 알람·기록)

화면에서는 핑키와 합쳐 보여 줍니다: 활성 알람은 상단 경고 띠(와 팔 카드 요약), 기록은 이벤트 로그에 핑키 기록과 시각 순으로 섞음 (`web/events.js`). API 는 핑키와 따로입니다 (번호 체계가 달라 화면이 섞음). 둘 다 `arm_command_node` 가 만듭니다 (`arm_command_utils.ArmCommander`).

**활성 알람** (`arms[].alarms`): 지금 이어지는 상태라 풀리면 사라집니다.

| `code` | `level` | 조건 | 풀림 |
|---|---|---|---|
| `offline` | bad | 한 번 받은 팔 상태가 `status_stale_sec` 넘게 끊김 | 상태가 다시 들어옴 |
| `soft_latch` | bad | 비상정지 잠김 (화면 버튼 '비상정지') | 끄기(RESET) |
| `fault` | bad | 화면 상태 `FAULT` (켜기가 `(지금 FAULT)` 로 거절됨) | 끄기 수락 등 다음 응답 |
| `hold` | warn | 정지 유지 | 정지 해제·끄기 |
| `posture_unknown` | bad | 작업(작업 시험·주문)이 도중에 실패(`retry_safe` 아님)했거나 작업 시험 결과 없음 | 다음 작업 성공 또는 끄기 수락 |

**기록** (`GET /api/arms/events`): `arm_command_node` 가 `/control_center/arm_events` 로 `{"type": "event", "event": {...}}` 를 보내고, `fleet_api_node`(`ArmStore`) 가 번호를 붙여 `arm_events_max` 개까지 메모리에 둡니다 (백엔드를 다시 켜면 지워짐). 스냅샷(depth 1)에 싣지 않아 빠지지 않습니다.

| `kind` | 언제 | `level` |
|---|---|---|
| `link` | 연결됨 / 연결 끊김 | info / bad |
| `state` | 화면 상태가 바뀜 (대기 ↔ 작업 중은 작업마다 바뀌어 빼고, 작업 결과로 대신) | 정지 warn, 비상정지(SOFT_LATCH) bad, 그 밖 info |
| `boot` | 팔 노드가 다시 켜짐 (`ArmStatus.robot_boot_id` 바뀜) | warn |
| `ack` | 명령 응답. 다른 곳이 낸 명령이면 `다른 곳이 낸 명령` | 수락·정지 실행 info, 거절 warn |
| `timeout` | 명령 응답 없음 (`ack_timeout_sec`) | bad |
| `work` | 주문 작업 요청(`주문 작업 PICK pick 요청 (order, robot)`)·SAFETY 요청, 작업 결과: 작업 시험과 **주문 작업** (`/fleet/work_result` 의 `source` 가 그 팔, 걸린 시간 포함) | 요청 info, 성공 info, 팔 안 움직인 실패 warn, 도중 실패·결과 없음 bad |

2026-11-16 도메인 101 시험 (가짜 핑키 + `fleet_control_node` + 팔 노드 4934bac `backend:=fake` 3대): 켜기 → 작업 시험 성공 → 작업 중 정지(활성 `hold`·`posture_unknown`) → 정지 해제 → 끄기(둘 다 풀림) → 또 끄기(거절 warn 기록) → 다른 곳이 낸 주문 작업 실패 결과(omx_2 `posture_unknown`) → omx3 팔 노드 끔(활성 `offline`, 끊김 기록) → 다시 켬(`boot`·연결됨 기록, `offline` 풀림). 헤드리스 크롬으로 알람 칸 확인.

### 작업 시험 (개발용)

가짜 팔로 시험하려면 도메인 101 에서 `ros2 launch cobot_mock mock_fleet.launch.xml` 을 띄웁니다 (가짜 핑키·관제·가짜 팔 3대, 화면 8081). [cobot_mock README](../../cobot_mock/README.md#가짜-팔).

이 화면은 기능별 시험용 개발 대시보드라, 팔 하나에 작업 한 건을 바로 시켜 볼 수 있습니다. 주문 흐름은 나중에 서비스용 화면에서 다룹니다.
**실제 팔이 움직입니다.** 그래서 주행 명령처럼 상단 **작업 명령 켜기**(`commands_armed`)가 켜져 있어야 하고, 팔이 `READY` 여야 합니다. 서버(`fleet_api_app`)와 `arm_command_node` 가 둘 다 검사합니다.

`arm_command_node` 가 `/fleet/work_request` 로 내는 JSON (팔 노드 `work_contract_utils.RequestFilter` 계약, 정본은 `fleet_control_node.work()`):

| 필드 | 값 |
|---|---|
| `request_id` | 새 UUID (응답의 `work_id`) |
| `order_id`, `robot_id` | `""` (주문 아님) |
| `stage` | `work_stage` (`MANUAL_TEST`) |
| `target` | 시나리오 팔 이름 `omx1` |
| `action` | `pick`·`load`·`unload`·`warehouse_store`·`arrange_shoe` |
| `session_id`, `seq` | 노드 실행마다 새 session, seq 는 팔마다 1부터 |
| `issued_at`, `ttl_sec` | 관제 PC 시각 [s], `ttl_ms`/1000 (5 s) |
| `timeout_sec`, `attempt` | `work_timeout_sec` (120 s, 팔 노드는 자기 `worker_timeout_sec` 와 작은 값), 1 |

- `/fleet/work_result` 에서 **내가 낸 `request_id` 의 결과만** 기록합니다. 주문 결과나 두 번 온 결과는 버립니다.
- `timeout_sec + work_result_margin_sec` 안에 결과가 없으면 `NO_RESULT` 입니다. 팔 자세를 모르니 현장에서 확인합니다.
- 실패의 `retry_safe` 가 참이면 팔이 움직이기 전에 거절된 것입니다 (만료·정지 유지 중 등). 거짓이면 작업 도중 멈춘 것이라 팔 자세를 확인합니다.
- 작업 중 멈추려면 **정지**(ArmCommand HOLD)를 누릅니다. 팔 노드가 작업을 끝내고 실패 결과를 보냅니다.
- **주문과 같이 쓰지 않습니다.** `fleet_control_node` 도 같은 토픽에 자기 `session_id` 로 보냅니다. 팔 노드는 session 이 바뀔 때마다 순번 기록을 비우고, 작업 중인 팔은 다른 요청을 거절합니다. 이 노드의 결과는 `fleet_control` 이 모르는 `request_id` 라 버립니다.
- 두 PC 시계가 5 s 넘게 어긋나면 팔 노드가 만료로 거절합니다 (`detail` 에 사유).

2026-11-15 도메인 101 시험: 가짜 핑키 + `fleet_control_node` + 팔 노드(4934bac) `backend:=fake`(작업 6 s) 3대, 웹 API·헤드리스 크롬으로 보냄. 실물 팔은 쓰지 않았습니다.

| 보낸 것 | 결과 |
|---|---|
| 작업 명령 꺼짐에서 pick | 409 `작업 명령이 꺼져 있음` (팔 노드에 안 보냄) |
| 꺼진 팔(OFF) pick / `dance` / `omx_9` | 409 / 400 / 404 |
| 켜기 뒤 pick | 202 → `BUSY`, `work.state RUNNING` → 6 s 뒤 `SUCCEEDED` |
| 진행 중 두 번째 작업 | 409 `앞 작업이 아직 진행 중` |
| unload 중 정지 | 정지 200 → `FAILED` `hold 로 작업 중단`, `retry_safe` 거짓 → 정지 해제 뒤 `READY` |
| 화면에서 load (확인 창) | 진행 중 경과 표시 → 성공 6초. 스위치를 끄면 버튼이 잠기고 이유가 나옴 |

`NO_RESULT`(결과 없음)는 단위 시험으로만 확인했습니다 (실제 시험은 135 s 를 기다려야 함).

### 팔 노드와 함께 시험 (2026-11-15, 도메인 101)

`feature/manipulation-station-adapter`(52cd5d1)의 `arm_adapter_node` 3대를 `backend:=fake` 로, 가짜 by-id 폴더(장치는 열지 않음)와 함께 띄우고 웹 API 로 보냈습니다. 실물 팔은 쓰지 않았습니다.

| 보낸 것 | 결과 |
|---|---|
| omx_1 켜기 | 200 → `READY` (epoch 1) |
| omx_3 켜기 (등록 안 된 보드) | 409 `팔 탐지 안 됨` |
| omx_2 끄기 (이미 꺼짐) / omx_1 다시 켜기 | 409 `REJECTED_STATE` |
| 작업 중 omx_1 끄기 | 409 `작업 중에는 끌 수 없음 (먼저 HOLD)` |
| 작업 중 omx_1 정지 → 정지 해제 | 200 (`stop_executed`) → `HOLD` → 200 → `READY` |
| omx_2 비상정지(soft_latch, 꺼짐) → 끄기 | 200 → `SOFT_LATCH` → 200 → `OFF` |
| 대기 중 omx_1 끄기 | 200 → `OFF` |
| 팔 노드 재시작 뒤 켜기 | 200 (새 epoch 가 팔의 0 보다 큼) |

팔 노드 쪽 확인할 것: RESET 으로 꺼진 뒤에도 그 전 HOLD 표시가 남아 `hold_active=true` 로 옵니다 (`held` 를 RESET 에서 지우지 않음). 화면은 `HOLD` 로 보여 주고 정지 해제를 먼저 하게 합니다.

## 네트워크 (net_status_node)

관제 PC 에서 잴 수 있는 것만 잽니다. 로봇·Station PC 의 DDS 종류는 ROS 로 물어볼 수 없어
데이터가 오는지로만 적습니다 (`dds` 칸).

**빠르기 두 가지** (헬스체크는 가볍게 계속, 자세한 확인은 필요할 때만):

| | 핑 | 상태 토픽 수신 주기 |
|---|---|---|
| 평소 | 대상마다 5 s 에 한 번 (장치 5대 → 초당 약 80 바이트) | 재지 않음 (구독 안 함) |
| 자세히 확인 (`POST /api/network/check`, 화면 버튼) | 10 s 동안 1 s 마다 | 10 s 동안 구독해서 잼. 끝나면 구독을 지우고 결과를 `checked_at` 과 함께 그대로 냄 |

팔 상태(10 Hz)를 관제 PC 가 하나 더 구독하면 Station PC 가 한 벌 더 보낼 수 있어서 평소에는 구독하지 않습니다.

`/control_center/host_status` (std_msgs/String JSON, 3 s, RELIABLE, 각 PC 의 `host_status_node` → `fleet_api_node`):
관제 PC 가 아닌 PC 가 자기 상태를 보낸다. 여러 PC 가 같은 토픽에 내고 `host` 로 나눈다 (`station` 이면 Station PC 카드).

```json
{"host": "station", "label": "Station PC", "hostname": "station-pc", "time": 1794763662.3, "period_sec": 3.0,
 "local_ip": "192.168.45.10",
 "dds": {"rmw": "rmw_cyclonedds_cpp", "domain_id": 100, "rmw_env": "rmw_cyclonedds_cpp",
         "cyclonedds_uri": null, "discovery_range": null},
 "interfaces": [아래 net_status 의 interfaces 와 같은 모양],
 "system": {"cpu_pct": 2.0, "cpu_count": 8, "load1": 0.56, "mem": {"total_mb": 15395, "used_pct": 66.0},
            "temp_c": 51.0, "temp_zone": "x86_pkg_temp", "disk_pct": 28.0, "uptime_sec": 132600},
 "thresholds": {"cpu_warn_pct": 90.0, "mem_warn_pct": 90.0, "temp_warn_c": 80.0, "disk_warn_pct": 90.0,
                "wifi_warn_dbm": -70.0, "wifi_warn_pct": 40.0}}
```

- `cpu_pct` 는 앞 보고와의 차이라 첫 보고는 `null`. 온도는 CPU thermal zone(`x86_pkg_temp`, `cpu-thermal` 등), 없으면 가장 높은 zone.
- 화면 판정: 보고가 `host_stale_sec`(10 s) 넘게 끊기면 빨강, DDS·도메인이 관제와 다르면 주황, 각 값이 `thresholds` 이상이면 주황.

`/control_center/net_check` (std_msgs/String JSON `{"source": 누른 곳 IP}`, `fleet_api_node` → `net_status_node`):
자세히 확인 시작. 진행 중에 또 오면 끝 시각만 늘립니다.

`/control_center/net_status` (std_msgs/String JSON, 1 Hz, transient_local, `net_status_node` → `fleet_api_node`)

```json
{"time": 1794761073.5, "ping_available": true, "local_ip": "192.168.45.9", "pid": 1234,
 "targets": {"pinky1": {"host": "192.168.45.21", "state": "ok", "samples": 12, "last_ms": 2.4,
                        "avg_ms": 2.6, "max_ms": 7.1, "loss_pct": 0.0, "last_ok_age": 0.4,
                        "mac": "2c:cf:67:a8:67:b5", "mac_fresh": true}, "...": {}},
 "topics": {"pinky1/patrol_status": {"topic": "/pinky1/patrol_status", "hz": 0.9, "age": 0.8,
                                     "state": "ok", "expect_hz": null, "checked_at": 1794762439.3},
            "omx_1/status": {"topic": "/manipulation/omx_1/status", "hz": 10.0, "...": 0}},
 "interfaces": [{"name": "wlo1", "kind": "wifi", "oper": "up", "ips": ["192.168.45.9/24"],
                 "mac": "40:d1:33:34:56:ac", "gateway": "192.168.45.1", "default_route": true,
                 "robot_net": true, "carrier_changes": 4, "state": "ok",
                 "wifi": {"ssid": "SK_D490_5G", "signal_pct": 77, "level_dbm": null, "chan": "44",
                          "rate": "270 Mbit/s", "same_channel": ["FASTCAMPUS_10F"], "state": "ok"}},
                {"name": "enp130s0", "kind": "ethernet", "oper": "up", "ips": ["192.168.0.9/24"],
                 "mac": "...", "gateway": null, "default_route": false, "robot_net": false,
                 "speed_mbps": 1000, "duplex": "full", "state": "ok"},
                {"name": "tailscale0", "kind": "vpn", "oper": "unknown", "ips": ["100.92.218.126/32"],
                 "mac": null, "robot_net": false, "state": "ok"}],
 "detail": {"active": false, "remaining_sec": 0.0, "started_at": 1794762428.4, "duration_sec": 10.0},
 "thresholds": {"ping_warn_ms": 100.0, "ping_warn_loss_pct": 10.0, "ping_bad_fails": 3,
                "wifi_warn_dbm": -70.0, "wifi_warn_pct": 40.0, "ping_period_sec": 5.0, "detail_period_sec": 1.0}}
```

- 핑 대상 `mac` 은 관제 PC 의 ARP 표(`/proc/net/arp`) 값이다. 핑을 보내므로 이미 있고 따로 패킷을 보내지 않는다.
  `mac_fresh` 가 거짓이면 예전에 알던 값.
- 핑 대상 키: `router`, `station`, 로봇 이름. `state`: `ok` / `warn`(평균 지연 또는 손실률이 기준 이상) /
  `bad`(마지막 `ping_bad_fails` 번 연속 실패) / `na`(아직 안 잼, 또는 이 PC 에 `ping` 이 없음).
- 토픽 `state`: 끊긴 지 `*_stale_sec` 넘으면 `bad`, 기대 주기(`expect_hz`)의 절반 미만이면 `warn`.
  `topics` 는 자세히 확인을 한 번도 안 했으면 비어 있다.
- `interfaces`: 이 PC 의 연결 전부 (`/sys/class/net`, 도커·가상 연결 제외). 관제 PC 는 Wi-Fi 와 유선이 함께 있을 수 있다.
  `kind`: `ethernet` / `wifi` / `vpn`(터널 장치) / `other`. `robot_net` 은 공유기(`router_host`)로 가는 경로의 연결,
  `default_route`·`gateway` 는 `ip -4 route show default` 의 기본 경로. `carrier_changes` 는 켜진 뒤 링크가 끊겼다 붙은 횟수.
  Wi-Fi 신호는 `/proc/net/wireless` 의 dBm 이 있으면 그것, 없으면(드라이버에 따라 비어 있음) `nmcli` 신호 %.
  `nmcli` 는 다시 찾기(rescan) 없이 10 s 에 한 번 읽는다. `same_channel` 은 같은 채널의 다른 AP (겹치면 느려질 수 있음).

`GET /api/network` 응답 (상태 이름은 위와 같음):

| 키 | 내용 |
|---|---|
| `overall` | 전체에서 가장 나쁜 상태, 헬스체크 포함 (상단 바 '네트워크 상태보기' 점 색) |
| `health` | 헬스체크 `{"state", "counts": {"ok", "warn", "bad", "na"}, "cards": [{"id", "label", "kind": "robot"\|"arm" (장비 줄) \| "station"\|"control" (PC 줄), "select": 구조도에서 열 상자(팔은 "station"), "state", "checks": [{"name", "state", "value"}]}], "issues": [정상이 아닌 점검, 나쁜 것부터 + "card", "select", "label"]}`. 관제 PC 카드의 연결 줄은 유선 → 무선 → VPN·기타 순서이고 판정은 로봇망 연결만 한다. 로봇 점검은 `fleet_status` 의 `alerts`(배터리·FAILED·끼임·시계)를 그대로 써서 경고 띠와 기준이 같다 |
| `local` | 이 PC: `rmw`(직접 확인), `rmw_env`, `domain_id`, `cyclonedds_uri`, `discovery_range`, `static_peers`, `nodes`(도메인에서 이름이 보이는 노드), `unknown_nodes`(이름이 안 보이는 노드 수, DDS 가 다를 때) |
| `control` | 관제 PC 안 노드 상자 `[{"id", "label", "state", "text"}]`: fleet_api, fleet_status, fleet_control, zone_manager, arm_command, net_status |
| `bridges` | 로봇별 브릿지 상자 (`fleet_status` 의 `infra` 판정, `node`, `note`) |
| `router` · `station` · `robots` | 장치 상자. `ping`(위 핑 요약), 로봇은 `rate`(patrol_status)·`topic_age`, Station PC 는 `arms`·`rates`(팔별 ArmStatus 주기). `text` 는 끊긴 곳 설명 (예: "핑은 되는데 데이터 없음 (브릿지 확인)") |
| `links` | 선 `[{"from", "to", "state", "ms"}]`: 관제 PC─공유기, 공유기─각 장치 |
| `net_online` | 측정 노드 값이 `net_stale_sec`(3 s) 안에 왔는지. 거짓이면 핑 칸이 비고 나머지는 그대로 그림 |
| `interfaces` | 측정 노드 값 + `summary`(화면 한 줄, 예: "연결됨 · 192.168.45.9/24 · SK_D490_5G · 77% · 5 GHz ch44 · 270 Mbit/s"), `badges`(["로봇망", "기본 경로", "VPN"] 중), `kind_text`(유선·무선·VPN·기타) |
| `detail` · `local_ip` · `ping_available` · `thresholds` | 측정 노드 값 그대로 |
| `history` | (`history=true` 일 때) 대상별 `[[UNIX 시각, rtt ms 또는 null], ..]` 최근 300개 |
| `alerts` | 상단 경고 띠에 더할 네트워크·PC 경고 `[{"robot", "code": "net:<카드>:<줄>", "level", "text"}]` (`fleet_status` alerts 와 같은 모양). 로봇은 '네트워크' 줄만, 팔은 빼고(로봇팔 패널에 있음), Station PC·관제 PC 는 관제 노드·브릿지(상단 점) 말고 모두 |

네트워크·PC 경고가 생기고 풀릴 때는 `fleet_api_node` 가 2 초마다 비교해 이벤트(`kind: "network"`, 풀림은
`level: "info"`, `"… 회복"`)를 `/api/events` 와 `/ws/fleet` 스냅샷 `events` 에 넣습니다. 값(지연 ms 등)만 바뀌면 새 이벤트를 내지 않습니다.

## 파라미터

`net_status_node` (`config/net_status_node.yaml`). 주소는 2026-11-16 기준이며 바뀌면 여기만 고칩니다.

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `robots` · `robot_hosts` | `[pinky1..3]` · `[192.168.45.21..23]` | 핑할 로봇과 주소 (같은 순서) |
| `station_host` · `router_host` | `192.168.45.10` · `192.168.45.1` | Station PC · 공유기. 비우면 재지 않음 |
| `arm_ids` | `[omx_1, omx_2, omx_3]` | 수신 주기를 볼 팔 (`/manipulation/{arm}/status`) |
| `ping_period_sec` · `ping_timeout_sec` · `ping_window` | `5.0` · `1` · `12` | 평소 대상마다 핑 주기 [s], `ping -W` [s], 손실률·평균을 낼 최근 횟수 |
| `detail_period_sec` · `detail_duration_sec` | `1.0` · `10.0` | 자세히 확인 중 핑 주기 [s], 자세히 확인 길이 [s] (토픽 주기도 이 구간) |
| `check_topic` | `/control_center/net_check` | 자세히 확인 요청 |
| `ping_warn_ms` · `ping_warn_loss_pct` · `ping_bad_fails` | `100` · `10` · `3` | 주황 기준 [ms]·[%], 빨강이 되는 연속 실패 수 |
| `robot_status_stale_sec` · `arm_status_stale_sec` · `arm_status_expect_hz` | `3.0` · `1.0` · `10.0` | 토픽이 끊긴 것으로 볼 시간 [s], 팔 기대 주기 [Hz] |
| `wifi_warn_dbm` · `wifi_warn_pct` | `-70` · `40` | 관제 PC Wi-Fi 가 이보다 약하면 주황 (dBm 이 없으면 % 로) |
| `nmcli_period_sec` | `10.0` | nmcli 로 Wi-Fi 연결 정보를 읽는 주기 [s] |
| `interface_skip_prefixes` | `[lo, docker, veth, br-, p2p, virbr]` | 화면에 안 보일 연결 이름 앞부분 |

`host_status_node` (`config/host_status_node.yaml`, 관제 PC 가 아닌 PC 에서): `host`(`station`, launch 인자), `label`,
`router_host`(로봇망으로 볼 연결), `publish_period_sec`(3.0), `nmcli_period_sec`, `interface_skip_prefixes`,
`cpu_warn_pct`·`mem_warn_pct`·`disk_warn_pct`(90), `temp_warn_c`(80), `wifi_warn_dbm`·`wifi_warn_pct`.

`fleet_api_node` 경로: `route_retry_sec`(8.0, 작업이 안 만들어진 일시 거절을 다시 보내 보는 시간 [s]), `route_period_sec`(0.5, 구간 결과를 보는 주기 [s]). 읽기 전용 백엔드에는 경로가 없음.

`fleet_api_node` 쪽: `host_status_topic`, `host_stale_sec`(10.0), `net_stale_sec`(3.0), `network_robots`, `network_arms`(구조도에 그릴 목록), `net_status_topic`, `net_check_topic`,
`station_node_patterns`(`['omx*_adapter']`, Station PC 노드로 볼 이름. ROS 그래프는 노드가 어느 PC 에 있는지 모르므로 이름으로 고른다 → `local.station_nodes`, `station.nodes`).

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
| `arm_stale_sec` | `3.0` | 로봇팔 명령 노드의 상태 모음이 이만큼 끊기면 로봇팔 명령을 받지 않음 (503) [s] |
| `arm_events_max` | `300` | 로봇팔 알람 기록 보관 개수 (메모리) |
| `arm_reply_timeout_sec` | `10.0` | 로봇팔 명령 응답을 기다리는 시간 [s]. `arm_command_node` 의 `ack_timeout_sec` 보다 길어야 504 가 화면까지 감 |
| `camera_robots` | `[pinky1, pinky2, pinky3]` | 카메라를 구독할 로봇. `['']` 이면 끔 |
| `camera_topic_format` | `/{robot}/camera/image_raw/compressed` | 카메라 토픽 (`sensor_msgs/CompressedImage`, JPEG). QoS `BEST_EFFORT / VOLATILE / KEEP_LAST(1)`. 이름은 가정값(비전 브랜치 592ebd4 규격 + 로봇 접두사)이라 확정되면 바꿈. 실물은 브릿지에 카메라 토픽이 있어야 들어옴 (아직 없음) |

`arm_command_node` (`config/arm_command_node.yaml`). `fleet_api.launch.xml` 이 함께 띄웁니다 (`arm_command:=false` 로 끔, 개발용 읽기 전용 launch 는 끔).

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `arm_ids` | `[omx_1, omx_2, omx_3]` | 팔 이름. `omx1` 로 써도 `omx_1` 로 바꿈. `site_arms_file` 을 읽으면 그 파일의 팔 목록이 우선 |
| `site_arms_file` | `''` (launch 가 설치된 `config/site_arms.yaml` 을 넘김) | 현장 팔 배치 파일. 못 읽으면 오류 로그를 남기고 `arm_ids` 로 계속 |
| `command_topic_format`, `status_topic_format`, `ack_topic_format` | `/control_center/{arm}/command`, `/manipulation/{arm}/status`, `/manipulation/{arm}/command_ack` | 팔 노드 기본 토픽과 같음 |
| `ttl_ms` | `5000` | 명령 유효 기한 [ms] |
| `ack_timeout_sec` | `8.0` | 팔 응답 기다리는 시간 [s]. 팔 노드의 끄기는 쉬는 자세 확인에 5 s 까지 걸림 |
| `status_stale_sec` | `1.0` | `ArmStatus` 가 이만큼 끊기면 `STALE` [s] |
| `snapshot_period_sec` | `0.2` | `/control_center/arms` 발행 주기 [s] |
| `work_request_topic`, `work_result_topic` | `/fleet/work_request`, `/fleet/work_result` | 작업 시험 토픽 (`fleet_control_node` 와 같음) |
| `work_stage` | `MANUAL_TEST` | 작업 시험 요청의 `stage` (팔 노드가 결과에 그대로 돌려줌) |
| `work_timeout_sec` | `120.0` | 요청 `timeout_sec` [s] |
| `work_result_margin_sec` | `15.0` | `timeout_sec` 뒤 이만큼 더 결과가 없으면 `NO_RESULT` [s] |

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
| `pose.js` | 초기위치 [홈]·[좌표 지정] (상세 위치 칸, 확대 지도 누르고 끌기) |
| `arms.js` | 로봇팔 패널 (`/api/arms`·`/api/arms/events` 1 s 마다, 켜기·끄기·정지, 작업 시험, 알람) |
| `network.js` | 네트워크 상태 화면 (`#/network`): 헬스체크 카드·구조도·자세히·핑 지연 그래프, 상단 바 버튼 점, 경고 띠의 네트워크·PC 경고 (`/api/network` 2 s 마다) |
| `main.js` | 시작, `/api/health` 확인 |
