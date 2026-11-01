# cobot_control_center

관제 PC에서 로봇 3대(pinky1~3)의 상태를 모아 웹 화면으로 보여 주는 **읽기 전용 관제** 패키지입니다.
로봇 토픽(`/pinkyN/*`, `/zone_manager/*`)에는 아무것도 발행하지 않으므로 **로봇을 움직이지 않습니다.**

담당: 김지혜 (로봇 수행 관제)
환경: Ubuntu 24.04 / ROS 2 Jazzy / Python 3.12

## 구성

```
로봇(도메인 10/20/30) ─▶ cobot_domain_bridge ─▶ 관제 PC(도메인 100)
                                                 │ /pinkyN/patrol_status, amcl_pose, battery/percent
                                                 │ /zone_manager/status
                                                 ▼
                                        fleet_status_node ── /control_center/fleet_status (JSON, 1 Hz)
                                                 ▼
                                        fleet_api_node (FastAPI) ── HTTP·WebSocket ──▶ 브라우저 (web/)
```

| 구성 | 파일 | 하는 일 |
|---|---|---|
| `fleet_status_node` | `fleet_status_node.py`, `fleet_status_utils.py` | 로봇별 순찰 상태·위치·배터리와 구역 점유를 모아 1초마다 JSON 으로 발행. 위치·배터리가 3초 끊기면 offline |
| `fleet_api_node` | `fleet_api_node.py`, `fleet_api_app.py`, `fleet_api_utils.py` | 위 JSON 을 받아 웹 API·WebSocket 으로 내고, 화면(`web/`)과 지도를 서빙 |
| 화면 | `web/index.html`, `app.js`, `style.css` | 로봇 카드, 위험구역 A/B/C, 지도 위 로봇 위치·방향. 외부 라이브러리·CDN 없음 |
| `map_hash`, `map_lint` | `map_contract.py` | 맵 계약 도구 (기존, 이 문서 범위 밖) |

`patrol_status` 는 순찰 노드가 **상태가 바뀔 때만** 보내므로 연결 판단에 쓰지 않습니다. 연결 여부는 위치·배터리 수신 시각으로 봅니다.

## 처음 설치

워크스페이스 최상위(`src/` 가 있는 곳)에서 한 번만 합니다. 웹 서버 패키지는 시스템 파이썬이 아니라 `.venv` 에 설치합니다 (CLAUDE.md §5).

```bash
source /opt/ros/jazzy/setup.bash
python3 -m venv --system-site-packages .venv
touch .venv/COLCON_IGNORE
source .venv/bin/activate
pip install fastapi==0.115.6 uvicorn==0.34.0 websockets==14.1 httpx==0.28.1
```

`websockets` 는 uvicorn 의 WebSocket 지원, `httpx` 는 시험(`TestClient`)용입니다.

## 빌드·시험

**`.venv` 를 켠 셸에서** 빌드해야 `fleet_api_node` 실행 파일이 venv 파이썬을 씁니다.

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python -m colcon build --symlink-install --packages-up-to cobot_bringup
python -m colcon test --packages-select cobot_control_center cobot_bringup
python -m colcon test-result --verbose
```

`--packages-up-to cobot_bringup` 은 브릿지·zone_manager·이 패키지를 함께 빌드합니다.

## 실행

### 관제 PC 전체 (권장)

```bash
source /opt/ros/jazzy/setup.bash && source .venv/bin/activate && source install/setup.bash
export ROS_DOMAIN_ID=100
ros2 launch cobot_bringup bringup.launch.xml
```

한 번에 뜨는 것: 도메인 브릿지 3개, zone_manager, `fleet_status_node`, `fleet_api_node`.

| 인자 | 기본값 | 뜻 |
|---|---|---|
| `pinky1` / `pinky2` / `pinky3` | `true` | 해당 로봇 브릿지 실행 여부. 일부 로봇만 켤 때 `pinky2:=false` |
| `fleet_api` | `true` | 백엔드·화면 실행 여부. `.venv` 가 없는 환경이면 `fleet_api:=false` |

로봇 쪽(Nav2, 순찰 노드)은 각 로봇에서 따로 켭니다. 순서는 [`cobot_navigation/README.md`](../cobot_navigation/README.md#실행-순서) 를 봅니다.

### 노드만 따로

```bash
ros2 launch cobot_control_center fleet_status.launch.xml
ros2 launch cobot_control_center fleet_api.launch.xml                  # 지도 기본값 사용
ros2 launch cobot_control_center fleet_api.launch.xml map_yaml:=<지도.yaml>
```

### SSH 접속이 끊겨도 계속 띄워 두기

SSH 터미널에서 그냥 띄우면 접속이 끊길 때 같이 꺼질 수 있습니다. 관제 PC 에서 tmux 안에 띄웁니다.

```bash
tmux new -s fms            # 위 '관제 PC 전체' 명령 실행 → Ctrl+B, D 로 빠져나옴
tmux attach -t fms         # 다시 보기 (끄려면 들어가서 Ctrl+C)
```

## 화면 보기

백엔드는 보안을 위해 기본으로 **관제 PC 안(`127.0.0.1:8080`)에서만** 열립니다 (로그인 기능이 아직 없음).

- 관제 PC 에서: 브라우저로 `http://localhost:8080/`
- 다른 PC(노트북)에서: SSH 터널을 연 채로 그 PC 브라우저에서 `http://localhost:8080/`

  ```bash
  ssh -N -L 8080:127.0.0.1:8080 <사용자>@<관제 PC 주소>
  ```

화면 상단의 **백엔드**(WebSocket)·**관제 노드**(`fleet_status` 수신) 표시가 빨강이면 해당 연결이 끊긴 것입니다.
로봇 카드의 배지는 `연결` / `끊김`(3초 이상 수신 없음) / `미수신`(켠 뒤 한 번도 못 받음)입니다.

제목 옆 칩은 지금 보는 도메인과 모드입니다. `도메인 100 · 실물` 이 아니면(가짜 핑키, 시험) 주황으로 표시합니다.
그 옆 **zone_manager**·**브릿지 1 2 3** 점은 관제 PC 기반 노드 상태입니다 (마우스를 올리면 설명).

| 점 | 뜻 |
|---|---|
| 초록 | 정상 (하나 떠 있음) |
| 빨강 | 없음, 또는 **중복**(같은 도메인에 두 벌. zone_manager 가 둘이면 구역 판단이 갈라짐) |
| 주황 | 확인 불가. 위치를 내는 노드는 있지만 DDS 구현이 달라(예: Cyclone ↔ Fast DDS) 이름이 안 보임 |
| 회색 | 해당 없음(실물 도메인이 아님) 또는 관제 노드 끊김 |

지도에는 위험구역을 겹쳐 그립니다. 주행 설정 파일(`pinkyN.yaml`, `zone_params.yaml`)을 읽기만 합니다.

| 표시 | 뜻 |
|---|---|
| 큰 원 + `A` | 구역 지점(`ZA` 등). 초록 비어 있음, 주황 점유, 회색 상태 모름. 원 크기는 표시용이며 실제 구역 넓이가 아님 |
| 빨간 × `A 출구` | `ZA_EXIT`. 구역을 나와 토큰을 반납하는 지점 |
| 빈 원 `A0`, `A1` .. | 대기 슬롯 (`A0` 이 맨 앞). 같은 자리의 슬롯은 `A0·B0` 처럼 합쳐 표시 |
| 마름모 `I1` .. | 로봇 홈 |
| 파란 점 + 선 `P1` .. | 일반 웨이포인트. 선은 도착 방향(yaw). 같은 자리는 `P1·P10` 처럼 합쳐 표시. `(0, 0, 0)` 인 P 지점은 미실측 예비값이라 숨기고 범례에 개수만 표시 |

로봇마다 구역 좌표가 다르면 `fleet_api_node` 가 시작할 때 경고를 남깁니다.
지도 아래 **구역 표시**(구역·출구·대기 슬롯·홈)와 **웨이포인트**(P) 체크박스로 따로 끄고 켭니다 (선택은 브라우저에 기억).

로봇 카드의 **위치 복사** 버튼은 웨이포인트 실측을 돕습니다. 사람이 로봇을 원하는 자리에 세운 뒤 누르면
지금 위치 `[0.123, -0.456, 1.57]` (x, y [m], yaw [rad]) 가 바로 클립보드에 들어가고 버튼이 잠깐 `복사됨 ✓` 으로 바뀝니다.
`pinkyN.yaml` 의 `points` 값 형식과 같으므로 `P36: ` 뒤에 붙여 넣으면 됩니다. 서버에 저장하거나 로봇에 보내지 않고, 파일도 고치지 않습니다.
클립보드를 못 쓰는 환경이면 그 줄을 카드에 띄워 선택해 두므로 Ctrl+C 로 복사합니다.
다음이면 버튼 옆에 주황 경고가 뜹니다 (마우스를 올리면 전체 문장, 복사는 막지 않음): 이동 중 상태, 연결 끊김, 위치를 받은 적 없음,
amcl 공분산의 표준편차가 `teach_max_std_xy`·`teach_max_std_yaw` 초과.
amcl 은 로봇이 멈춰 있으면 위치를 새로 내지 않으므로(`update_min_d`·`update_min_a`) 평균 대신 마지막 추정값을 씁니다.

## API

모두 읽기 전용입니다. 쓰기(POST 등) 경로는 없습니다.

| 경로 | 응답 |
|---|---|
| `GET /` | 관제 화면 |
| `GET /api/health` | `{"ok": true, "domain_id": 백엔드의 ROS_DOMAIN_ID, "source_online": bool, "source_age": 초 또는 null}` |
| `GET /api/fleet` | 최신 스냅샷 전체 + `source_online`, `source_age`. 아직 못 받았으면 503 |
| `GET /api/robots` | 로봇 목록 (`robot_id` + 로봇 값) |
| `GET /api/robots/{robot_id}` | 로봇 하나. 없으면 404 |
| `GET /api/map/info` | `{"image_width", "image_height", "resolution", "origin"}`. 지도 없으면 404 |
| `GET /api/map/image` | 지도 PGM 원본 바이트 |
| `GET /api/map/layers` | `{"zones": {"A": {"points": {"ZA": [x, y, yaw]}, "exit": {"name", "pose"} 또는 null, "queue": [[x, y, yaw], ..]}}, "homes": {"pinky1": {"name", "pose"}}, "points": {"P1": [x, y, yaw], ..}, "hidden_points": 숨긴 예비 지점 수, "warnings": [..]}`. 설정이 없으면 404 |
| `WS /ws/fleet` | 연결 즉시 최신 스냅샷 1건, 이후 새 스냅샷마다 push |

### `/control_center/fleet_status` (= `/api/fleet`) 형식

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
  "infra": {
    "domain_id": 100, "control_domain_id": 100, "mode": "real",
    "zone_manager": {"state": "ok", "count": 1},
    "bridges": {
      "pinky1": {"state": "ok", "count": 1, "node": "pinky_bridge_pinky1_only_100"}
    }
  }
}
```

- `infra` 는 ROS 그래프 조회로만 만듭니다 (구독·발행 없음). 1초마다 갱신합니다.
  - `mode`: 가짜 핑키 노드가 보이면 `mock`, 도메인이 `control_domain_id` 이면 `real`, 그 밖은 `test`.
  - `state`: `ok` / `missing` / `duplicate` / `unknown`(이름이 안 보임) / `n/a`(실물 아님).
  - zone_manager 는 `/zone_manager/status` **발행자 수**로 셉니다. DDS 구현이 달라 노드 이름이 안 보여도 개수는 보이기 때문입니다.
  - 브릿지는 노드 이름(`bridge_node_format`)으로 셉니다. 로봇이 꺼져 있으면 브릿지가 위치 토픽을 만들지 않으므로, 이름이 안 보이는 브릿지는 로봇이 켜졌을 때만 `unknown` 으로 드러납니다.

- 단위: `pose.x`·`y` [m], `yaw` [rad], `last_seen_age` [s], `battery_percent` [%]. 모르는 값은 `null`.
- `pose_age` [s]: 위치를 마지막으로 받은 뒤 지난 시간. `teach`: 위치 복사 판정 `{"ok", "warnings": [..], "std_xy" [m], "std_yaw" [rad]}`.
- `state`·`waypoint`·`detail`·`status_time` 은 순찰 노드 `patrol_status` 를 그대로 옮긴 값입니다.
- `patrol_status` 에 그 밖의 필드(예: `command_id`, `task_finished`)가 오면 버리지 않고 `extra` 에 담습니다.
- 지금은 `std_msgs/String` JSON 입니다. 필드가 정해지면 `cobot_interfaces` 메시지로 바꿀 예정입니다 (팀 공지·리뷰 필요).

## 파라미터

`fleet_status_node` (`config/fleet_status_node.yaml`)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `robots` | `[pinky1, pinky2, pinky3]` | 관제 PC 쪽 토픽 접두사 |
| `stale_timeout_sec` | `3.0` | 위치·배터리가 이만큼 끊기면 offline [s] |
| `publish_period_sec` | `1.0` | `fleet_status` 발행 주기 [s] |
| `control_domain_id` | `100` | 실물 관제 도메인. 이 도메인에서만 브릿지·zone_manager 를 검사 |
| `bridge_node_format` | `pinky_bridge_{robot}_only_{domain}` | 관제 PC 쪽 브릿지 노드 이름. 브릿지 설정 `name` 에 도메인이 붙은 모양 |
| `mock_node_name` | `mock_pinky_node` | 이 노드가 보이면 `mock` 모드 |
| `teach_max_std_xy` | `0.05` | 위치 복사 경고 기준, amcl 위치 표준편차 [m]. 임시값 (현장 실측 뒤 조정) |
| `teach_max_std_yaw` | `0.1` | 위치 복사 경고 기준, amcl 방향 표준편차 [rad]. 임시값 |

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

지도 기본값은 로봇이 쓰는 지도 `src/cobot_navigation/map_view_pc/maps/cobot_map_v9.yaml` 입니다.
launch 가 colcon 표준 배치(`<ws>/install/<pkg>/share/<pkg>`)에서 `<ws>/src` 로 거슬러 올라가 찾습니다. 지도를 바꾸면 `map_yaml:=` 로 지정합니다.
구역 표시 기본값도 같은 방식으로 `src/cobot_navigation/cobot_pinky_patrol/config`, `src/cobot_navigation/cobot_zone_traffic_control/config/zone_params.yaml` 을 가리킵니다 (`points_dir:=`, `zone_params:=`).

## 로봇 없이 시험하기

실물 도메인(100, 10/20/30)과 섞이지 않게 **다른 도메인·이 PC 안에서만** 돌립니다. 브릿지는 띄우지 않습니다.

```bash
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_control_center fleet_status.launch.xml &
ros2 launch cobot_control_center fleet_api.launch.xml &
ros2 topic pub -r 5 /pinky1/amcl_pose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{pose: {pose: {position: {x: 0.3, y: 0.4}, orientation: {w: 1.0}}}}" &
ros2 topic pub -r 1 /pinky1/battery/percent std_msgs/msg/Float32 "{data: 87.0}" &
ros2 topic pub --once /pinky1/patrol_status std_msgs/msg/String \
  "{data: '{\"state\": \"MOVING\", \"waypoint\": 1, \"detail\": \"P3\"}'}"
ros2 topic pub --once /zone_manager/status std_msgs/msg/String "{data: 'B:occupied_by:pinky1'}"
curl http://127.0.0.1:8080/api/robots/pinky1
```

가짜 발행을 멈추면 3초 뒤 그 로봇이 `끊김`이 됩니다.

## 주의

- **새 의존성**: fastapi·uvicorn(·websockets·httpx)은 팀 허락을 PR 에서 받습니다. `.venv` 없이 빌드하면 `fleet_api_node` 와 그 시험이 실패합니다.
- **`web/` 위치**: CLAUDE.md §3-7 은 웹 자원을 `cobot_gui/web/` 에만 두게 하지만, 관제 전용 화면이라 이 패키지에 두었습니다. 규칙 개정 합의가 필요합니다.
- **명령 기능 없음**: 이 패키지는 아직 로봇에 명령(`/pinkyN/patrol_cmd`)을 보내지 않습니다. 명령 기능을 넣을 때는 실물 로봇이 움직이므로 시험마다 확인을 받습니다. `/pinkyN/cmd_vel`·`goal_pose` 는 관제에서 쓰지 않습니다.
