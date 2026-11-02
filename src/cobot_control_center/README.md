# cobot_control_center

관제 PC에서 로봇 3대(pinky1~3)의 상태를 모아 웹 화면으로 보여 주고, 화면에서 순찰 명령(이동·구역·나가기·홈·정지)을 보내는 관제 패키지입니다.

- 로봇 명령 토픽(`/pinkyN/patrol_cmd`, v2 `/pinkyN/patrol_command`)에 발행하는 것은 **`task_manager_node` 하나**입니다. 이 노드를 켜지 않으면 관제는 읽기 전용입니다.
- **`task_manager_node` 는 bringup 에 들어 있지 않습니다.** 실물 도메인(100)에서 켜면 실물 로봇이 움직이므로 따로 켭니다 ([명령 켜기](#명령-켜기)).
- `/pinkyN/cmd_vel`·`goal_pose`·`initialpose` 는 쓰지 않습니다.

담당: 김지혜 (로봇 수행 관제)
환경: Ubuntu 24.04 / ROS 2 Jazzy / Python 3.12

| 문서 | 내용 |
|---|---|
| 이 README | 구성, 설치, 실행, 시험 |
| [docs/screen_guide.md](docs/screen_guide.md) | 화면 사용법 (점·배지 뜻, 명령 보내기, 결과 모름 해제) |
| [docs/api.md](docs/api.md) | 웹 API, `fleet_status` JSON 형식, 작업 상태, 파라미터 |

## 구성

```
로봇(도메인 10/20/30) ─▶ cobot_domain_bridge ─▶ 관제 PC(도메인 100)
                                                 │ /pinkyN/patrol_status, amcl_pose, battery/percent
                                                 │ /zone_manager/status, queue_slot
                                                 ▼
                                        fleet_status_node ── /control_center/fleet_status (JSON, 1 Hz)
                                                 ▼
                                        fleet_api_node (FastAPI) ── HTTP·WebSocket ──▶ 브라우저 (web/)
                                                 │ ▲ /control_center/task_request · task_events · tasks (JSON)
                                                 ▼ │
                                        task_manager_node ── /pinkyN/patrol_cmd (v1) · patrol_command (v2) ──▶ 로봇
                                          (검증·SQLite 기록)  ◀── patrol_status (v1) · patrol_state·_ack (v2) ──┘
```

| 노드 | 파일 | 하는 일 |
|---|---|---|
| `fleet_status_node` | `fleet_status_node.py`, `fleet_status_utils.py` | 로봇별 순찰 상태·위치·배터리와 구역 점유를 모아 1초마다 JSON 으로 발행. 위치·배터리가 3초 끊기면 offline |
| `fleet_api_node` | `fleet_api_node.py`, `fleet_api_app.py`, `fleet_api_utils.py` | 토픽 값을 받아 웹 API·WebSocket 으로 내고, 화면(`web/`)과 지도를 서빙 |
| `task_manager_node` | `task_manager_node.py`, `task_manager_utils.py` | 명령 요청을 검증·기록(SQLite)한 뒤 로봇에 보내고, 로봇 상태로 작업 결과를 추적 |

`map_contract.py`(`map_hash`, `map_lint`)는 맵 계약 도구로, 이 문서 범위 밖입니다.

## 데이터 흐름

웹 서버(`fleet_api_node`)는 **토픽으로 받은 값을 메모리에 두고 GET·WebSocket 으로 보여 주기만** 합니다. DB 를 읽지 않습니다.
SQLite 를 쓰는 것은 명령을 맡은 `task_manager_node` 하나입니다.

**상태** (읽기)

```
로봇 토픽 ─▶ fleet_status_node ─▶ /control_center/fleet_status
                                        ▼ 구독
                         fleet_api_node 메모리 (최신 스냅샷 + 이벤트 로그)
                                        ├─ GET /api/fleet, /api/robots   처음 한 번
                                        └─ WS  /ws/fleet                 바뀔 때마다 push
```

**명령** (쓰기)

```
브라우저 POST /api/tasks ─▶ fleet_api_node ─▶ /control_center/task_request
                                                   ▼
                   task_manager_node: 검사 → SQLite 기록 → /pinkyN/patrol_cmd ─▶ 로봇
                                                   ▼
                   /control_center/tasks (전체 목록, transient_local) · task_events (바뀐 작업)
                                                   ▼ 구독
                   fleet_api_node 메모리 ─▶ GET /api/tasks, WS /ws/tasks
```

- 이벤트 로그는 메모리에만 있어 백엔드를 다시 켜면 지워집니다. 작업 기록은 SQLite 에 남습니다.
- 지도·구역 표시는 `fleet_api_node` 가 시작할 때 파일에서 한 번 읽습니다.
- `/control_center/tasks` 가 transient_local 이라 `fleet_api_node` 가 늦게 켜져도 마지막 목록을 바로 받습니다.

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

`--packages-up-to cobot_bringup` 은 브릿지·zone_manager·이 패키지와, `task_manager_node` 가 쓰는 v2 메시지 `cobot_patrol_interfaces` 까지 함께 빌드합니다.

## 실행

관제 PC 전체 (권장):

```bash
source /opt/ros/jazzy/setup.bash && source .venv/bin/activate && source install/setup.bash
export ROS_DOMAIN_ID=100
ros2 launch cobot_bringup bringup.launch.xml
```

한 번에 뜨는 것: 도메인 브릿지 3개, zone_manager, `fleet_status_node`, `fleet_api_node` (명령 노드는 빠짐).

| 인자 | 기본값 | 뜻 |
|---|---|---|
| `pinky1` / `pinky2` / `pinky3` | `true` | 해당 로봇 브릿지 실행 여부. 일부 로봇만 켤 때 `pinky2:=false` |
| `fleet_api` | `true` | 백엔드·화면 실행 여부. `.venv` 가 없는 환경이면 `fleet_api:=false` |

로봇 쪽(Nav2, 순찰 노드)은 각 로봇에서 따로 켭니다. 순서는 [`cobot_navigation/README.md`](../cobot_navigation/README.md#실행-순서) 를 봅니다.

노드만 따로 띄울 때:

```bash
ros2 launch cobot_control_center fleet_status.launch.xml
ros2 launch cobot_control_center fleet_api.launch.xml                  # 지도 기본값 사용
ros2 launch cobot_control_center fleet_api.launch.xml map_yaml:=<지도.yaml>
```

SSH 터미널에서 띄우면 접속이 끊길 때 같이 꺼질 수 있으므로 관제 PC 의 tmux 안에서 띄웁니다 (`tmux new -s fms` → 실행 → Ctrl+B, D / 다시 보기 `tmux attach -t fms`).

## 화면 보기

백엔드는 기본으로 **관제 PC 안(`127.0.0.1:8080`)에서만** 열립니다 (로그인 기능이 아직 없음).

- 관제 PC 에서: 브라우저로 `http://localhost:8080/`
- 다른 PC(노트북)에서: SSH 터널을 연 채로 그 PC 브라우저에서 `http://localhost:8080/`

  ```bash
  ssh -N -L 8080:127.0.0.1:8080 <사용자>@<관제 PC 주소>
  ```

화면 사용법은 [docs/screen_guide.md](docs/screen_guide.md) 를 봅니다.

## 명령 켜기

**로봇 없이 (권장, 먼저 이것으로)**: 가짜 핑키 launch 가 `task_manager_node` 까지 함께 띄웁니다. 기록은 `~/.ros/cobot_control_center/tasks_mock.db`.

```bash
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_mock mock_fleet.launch.xml auto_patrol:=false        # 화면 http://localhost:8081/
```

**실물 (도메인 100)**: bringup 을 띄운 뒤 **현장·사용자 확인 후** 따로 켭니다. 기록은 `~/.ros/cobot_control_center/tasks.db`.

```bash
export ROS_DOMAIN_ID=100
ros2 launch cobot_control_center task_manager.launch.xml
```

## 로봇 없이 시험하기

실물 도메인(100, 10/20/30)과 섞이지 않게 **다른 도메인·이 PC 안에서만** 돌립니다. 브릿지는 띄우지 않습니다.

보통은 가짜 핑키 3대와 관제 노드를 한 번에 띄우는 [`cobot_mock`](../cobot_mock/README.md) 이 편합니다 ([명령 켜기](#명령-켜기)).
아래는 노드 하나만 손으로 확인할 때입니다.

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
- **명령 기능은 실물을 움직입니다**: `task_manager_node`(수동 명령 포함)는 가짜 핑키로만 시험했습니다. 실물 시험은 매번 사용자·현장 확인 뒤, 한 대씩 합니다. `ack_timeout_sec`·`task_timeout_sec` 는 실물 응답 시간을 재 보고 정합니다.
- **로그인 없음**: 명령을 보낼 수 있으므로 `host` 를 `127.0.0.1` 로 유지하고 SSH 터널로만 접속합니다. 여러 사람이 쓰게 되면 로그인·권한을 먼저 넣습니다.
- **`cobot_patrol_interfaces` 의존**: `task_manager_node` 가 v2 메시지를 쓰므로 함께 빌드해야 합니다 ([빌드·시험](#빌드시험)).
