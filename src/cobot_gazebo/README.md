# cobot_gazebo

가제보(Harmonic) 시뮬레이션입니다. v9 지도 월드에 핑키 3대를 띄우고, 로봇마다 **Nav2 + 실제 순찰 노드**(`cobot_pinky_patrol`, 코드 수정 없음)를 돌립니다. 순찰 설정은 `common.yaml`·`sites/lab.yaml`·`robots/pinkyN.yaml` 을 그대로 읽습니다. 작업 노드는 실물과 같은 `fleet_control` 이고 순찰 노드도 실물처럼 `central_controlled: true` 입니다 (예전 방식은 `controller:=task_manager`, 이때만 `central_controlled: false`).
실제 `cobot_domain_bridge`·`zone_manager` 로 관제 도메인에 연결하므로 관제는 실물과 같은 `/pinkyN/patrol_status`·`/pinkyN/patrol_cmd`·`/zone_manager/*` 를 봅니다.
목적·범위는 [docs/prd.md](docs/prd.md) 를 봅니다.

## 구성

```
가제보 월드 (cobot_sim, GZ_IP=127.0.0.1)
 ├─ pinky1 ── 도메인 141: ros_gz_bridge, robot_state_publisher, Nav2, fake_led, fake_battery, 순찰 노드
 ├─ pinky2 ── 도메인 142: (같음)
 └─ pinky3 ── 도메인 143: (같음)
관제 도메인 140: domain_bridge ×3 (관제 하트비트 `/pinkyN/fleet_heartbeat` 포함), zone_manager, sim_guard, (관제 fleet_status·fleet_api·fleet_control)
```

| 실물 | 시뮬 |
|---|---|
| 관제 PC `ROS_DOMAIN_ID=100` | 140 |
| pinky1/2/3 = 10/20/30 | 141/142/143 |
| 관제 화면 8080 (가짜 핑키 8081) | 8082 |

도메인은 `launch/sim_fleet.launch.xml` 에 고정되어 있고 `config/domain_bridge_pinkyN.yaml` 과 숫자가 같아야 합니다 (`test_sim_guard_utils` 가 확인).
모든 통신은 이 PC 안에서만 돕니다 (`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`). 실물 도메인이면 `sim_guard_node` 가 시뮬 전체를 내립니다.

## 설치 (한 번만, 팀 허락 필요한 새 의존성)

```bash
sudo apt install -y ros-jazzy-ros-gz ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-xacro ros-jazzy-robot-state-publisher
```

## 빌드

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python -m colcon build --symlink-install --packages-up-to cobot_gazebo
source install/setup.bash
```

관제 노드(`fleet_api`)는 fastapi 를 `.venv` 에서 찾으므로 venv 안에서 `python -m colcon` 으로 빌드하고, 실행하는 터미널에서도 venv 를 켭니다 ([cobot_control_center/README.md](../cobot_control_center/README.md)).
venv 없이 빌드했다면 `fleet_api_node` 가 `No module named 'fastapi'` 로 죽습니다. 이때는 위처럼 다시 빌드하거나 `with_control_center:=false` 로 띄웁니다.

`pinky_interfaces`(src/pinky_interfaces_stub) 는 시뮬 PC 전용입니다. 실물 로봇 워크스페이스에서는 빌드하지 않습니다.

## 실행

```bash
ros2 launch cobot_gazebo sim_fleet.launch.xml                  # 가제보 화면 + 관제 화면 http://localhost:8082/
ros2 launch cobot_gazebo sim_fleet.launch.xml headless:=true   # 화면 없이
ros2 launch cobot_gazebo sim_fleet.launch.xml pinky3:=false    # 2대만
ros2 launch cobot_gazebo sim_fleet.launch.xml with_control_center:=false   # 관제 노드 없이
```

다른 터미널에서 관제 도메인을 볼 때는 두 환경 변수를 꼭 함께 줍니다.

```bash
export ROS_DOMAIN_ID=140 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 topic echo /pinky1/patrol_status
ros2 topic pub --once /pinky1/patrol_cmd std_msgs/msg/String "{data: 'goto:P1'}"
```

명령 형식은 [cobot_pinky_patrol_cmd/README.md](../cobot_navigation/cobot_pinky_patrol_cmd/README.md) 와 같습니다.
순찰 노드는 첫 명령 때 초기 위치를 내고 제자리 회전(약 13초)으로 위치를 맞춘 뒤 움직입니다.

## 파일

| 파일 | 내용 |
|---|---|
| `launch/sim_fleet.launch.xml` | 진입점. 도메인 고정, 관제 도메인, 월드, 로봇 3대 |
| `launch/sim_robot.launch.xml` | 로봇 한 대 (소환, ros_gz_bridge, Nav2, LED, 순찰 노드) |
| `launch/sim_nav2.launch.xml` | Nav2 노드 (실물 nav2_params.yaml 의 노드 구성) |
| `launch/sim_world.launch.xml` | 가제보 서버/화면 |
| `config/nav2_sim.yaml` | 실물 Nav2 파라미터 복사본 (sim time) |
| `config/domain_bridge_pinkyN.yaml` | 실물 브릿지 설정 복사본 (도메인만 다름, `/battery_state`·차선 뺌) |
| `config/fake_battery_node.yaml` | 가짜 배터리 값·주기 |
| `cobot_gazebo/last_pose_utils.py` | 순찰 노드 마지막 위치 파일을 소환 위치로 초기화 (`reset_last_pose`) |
| `config/map/cobot_map_v9.*` | 지도 복사본 (`cobot_navigation/map_view_pc/maps/`) |
| `worlds/cobot_map_v9.sdf` | 지도에서 만든 월드 (손으로 고치지 않음) |
| `urdf/pinky_sim.urdf.xacro` | 단순 핑키 (차동구동, 2D 라이다) |

원본(주행 코드)의 Nav2 파라미터·브릿지 설정·지도가 바뀌면 복사본도 다시 맞춥니다.

## 지도를 바꿨을 때

```bash
ros2 run cobot_gazebo make_world config/map/cobot_map_v9.yaml worlds/cobot_map_v9.sdf
```

`test_map_to_world_utils` 가 커밋된 월드와 지도에서 다시 만든 월드가 같은지 확인합니다.

## 문제 해결

| 증상 | 원인·조치 |
|---|---|
| 관제 도메인(140)에 `/pinkyN/*` 토픽이 없음 | 이전 실행의 가제보 서버·브릿지가 남아 있을 수 있습니다. `ps -ef \| grep -E 'gz sim\|domain_bridge'` 로 확인하고 끈 뒤 다시 띄웁니다 |
| `ros2 topic echo /pinkyN/patrol_status` 에 아무것도 안 나옴 | 순찰 노드는 일이 생길 때만 상태를 냅니다 (시작 IDLE 은 브릿지 연결 전이라 관제에 안 옴). 명령을 하나 보내면 나옵니다 |
| 관제에 보이는 위치가 실제(가제보)와 크게 다름 | 순찰 노드는 첫 명령 때 `~/.pinky_last_pose.json` 을 AMCL 초기 위치로 씁니다. 시뮬은 로봇마다 `~/.ros/cobot_gazebo/pinkyN/` 를 HOME 으로 주고 띄울 때마다 소환 위치로 다시 씁니다. 실제 홈 폴더의 `~/.pinky_last_pose.json` 은 시뮬이 읽지 않습니다 |
| 구역 명령에서 이동 실패·재시도가 반복됨 | 홈 간격이 0.2 m 라 다른 핑키가 라이다에 장애물로 잡힙니다. 순찰 노드가 재시도하므로 결국 진행되지만 시간이 걸립니다 |

## 한계

- 배터리는 `fake_battery_node` 가 고정값(100 %, 8.4 V)을 5초마다 냅니다 (`config/fake_battery_node.yaml`). 관제가 서 있는 로봇을 online 으로 보려면 필요합니다. 방전은 흉내 내지 않습니다 (방전 시험은 `cobot_mock`).
- `/battery_state`·차선·카메라 토픽은 내지 않습니다.
- 순찰 규격 v2(`cobot_patrol_interfaces`)는 내지 않습니다. 실물 순찰 노드가 아직 v1 이라서입니다 (v2 시험은 `cobot_mock`).
- 몸체·바퀴 크기는 Nav2 footprint(0.12 m)에 맞춘 근사값이고 실물 메시는 쓰지 않습니다.
