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

## API

모두 읽기 전용입니다. 쓰기(POST 등) 경로는 없습니다.

| 경로 | 응답 |
|---|---|
| `GET /` | 관제 화면 |
| `GET /api/health` | `{"ok": true, "source_online": bool, "source_age": 초 또는 null}` |
| `GET /api/fleet` | 최신 스냅샷 전체 + `source_online`, `source_age`. 아직 못 받았으면 503 |
| `GET /api/robots` | 로봇 목록 (`robot_id` + 로봇 값) |
| `GET /api/robots/{robot_id}` | 로봇 하나. 없으면 404 |
| `GET /api/map/info` | `{"image_width", "image_height", "resolution", "origin"}`. 지도 없으면 404 |
| `GET /api/map/image` | 지도 PGM 원본 바이트 |
| `WS /ws/fleet` | 연결 즉시 최신 스냅샷 1건, 이후 새 스냅샷마다 push |

### `/control_center/fleet_status` (= `/api/fleet`) 형식

```json
{
  "time": 1793517871.2,
  "robots": {
    "pinky1": {
      "online": true, "never_seen": false, "last_seen_age": 0.4,
      "state": "MOVING", "waypoint": 2, "detail": "ZB", "status_time": 1793517870.9,
      "pose": {"x": 0.30, "y": 0.40, "yaw": 1.57},
      "battery_percent": 87.0,
      "extra": {}
    }
  },
  "zones": {"A": "free", "B": "occupied_by:pinky1"}
}
```

- 단위: `pose.x`·`y` [m], `yaw` [rad], `last_seen_age` [s], `battery_percent` [%]. 모르는 값은 `null`.
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

`fleet_api_node` (`config/fleet_api_node.yaml`)

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `host` | `127.0.0.1` | 바인드 주소. 다른 PC 에서 직접 접속하려면 `0.0.0.0` (로그인 없음 주의) |
| `port` | `8080` | |
| `source_stale_sec` | `3.0` | `fleet_status` 가 이만큼 끊기면 `source_online=false` [s] |
| `map_yaml` | launch 인자가 채움 | 지도 YAML. 비거나 읽지 못하면 지도 없이 시작 |
| `web_dir` | `share/cobot_control_center/web` | 화면 정적 파일 폴더 |

지도 기본값은 로봇이 쓰는 지도 `src/cobot_navigation/map_view_pc/maps/cobot_map_v9.yaml` 입니다.
launch 가 colcon 표준 배치(`<ws>/install/<pkg>/share/<pkg>`)에서 `<ws>/src` 로 거슬러 올라가 찾습니다. 지도를 바꾸면 `map_yaml:=` 로 지정합니다.

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
