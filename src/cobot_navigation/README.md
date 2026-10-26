# cobot_navigation

Pinky 로봇 3대의 주행·순찰과 위험구역 교통 관제를 담당하는 폴더입니다.
이 폴더 자체는 colcon 패키지가 아니라 아래 하위 패키지·도구를 묶는 자리입니다.
이 문서는 **전체를 어떤 순서로 켜는지**만 정리합니다. 세부 설명은 각 README를 봅니다.

## 구성

| 폴더 | 종류 | 실행 위치 | 역할 | 상세 |
|---|---|---|---|---|
| `cobot_domain_bridge` | ROS 2 패키지 | 관제 PC | 관제 PC(도메인 100)와 로봇(10/20/30) 사이 토픽 중계 | [README](cobot_domain_bridge/README.md) |
| `cobot_zone_traffic_control` | ROS 2 패키지 | 관제 PC(매니저) / 로봇(클라이언트 import) | 위험구역에 한 대만 들어가도록 허가·대기열 슬롯 관리 | [README](cobot_zone_traffic_control/README.md) |
| `cobot_pinky_patrol` | ROS 2 패키지 | 각 로봇 | Nav2 순찰 노드 (`pinky_patrol_node_pinky1/2/3`) | [README](cobot_pinky_patrol/README.md) |
| `cobot_pinky_patrol_cmd` | 스크립트 | 관제 PC | 터미널에서 순찰 명령 전송·상태 모니터 | [README](cobot_pinky_patrol_cmd/README.md) |
| `map_view_pc` | 웹 뷰어 | 아무 PC | 지도 위에서 map 좌표 확인 | [README](map_view_pc/README.md) |
| `ros2_network_test` | 진단 도구 | 관제 PC | ROS 2 네트워크 진단·이상 이력 대시보드 | [README](ros2_network_test/README.md) |
| `docs/` | 자료 | - | 맵 v6(`cobot_map/`), Nav2·SLAM 파라미터(`cobot_slam_nav_param/`) | - |

## 구성도

```
관제 PC (ROS_DOMAIN_ID=100)                          로봇 (pinky1=10, pinky2=20, pinky3=30)
  pinky_control_client ──/pinkyN/patrol_cmd──▶ cobot_domain_bridge ──▶ pinky_patrol_node
                       ◀─/pinkyN/patrol_status─                              │ import
  zone_manager_node ◀── request_entry / cancel_entry / notify_exit ── ZoneGateClient
                    ──▶ grant_entry / queue_slot / status ───────────────────▶
```

| 장비 | ROS_DOMAIN_ID |
|---|---|
| 관제 PC | 100 |
| pinky1 | 10 |
| pinky2 | 20 |
| pinky3 | 30 |

## 빌드

각 장비에서 워크스페이스 최상위(`src/` 가 있는 곳)에서 실행합니다.

```bash
source /opt/ros/jazzy/setup.bash

# 관제 PC
colcon build --symlink-install --packages-select cobot_zone_traffic_control cobot_domain_bridge

# 각 로봇 (patrol 노드가 zone_gate_client 를 import 하므로 둘 다 필요)
colcon build --packages-select cobot_zone_traffic_control cobot_pinky_patrol

source install/setup.bash
```

## 실행 순서

모든 터미널에서 `source /opt/ros/jazzy/setup.bash && source install/setup.bash` 를 먼저 합니다.
순서를 지켜 위에서부터 켭니다.

### 1. 로봇: Nav2 bringup
각 로봇에서 먼저 실행합니다. 로봇에 이미 설치된 Nav2·`pinky_interfaces`·`pinky_led` 를 쓰며 이 저장소에는 없습니다.
Nav2 파라미터는 [`docs/cobot_slam_nav_param/`](docs/cobot_slam_nav_param/param_changes.md) 에 정리되어 있습니다.

### 2. 관제 PC: 도메인 브릿지
```bash
export ROS_DOMAIN_ID=100
ros2 launch cobot_domain_bridge bridges.launch.xml                  # pinky1~3 모두
ros2 launch cobot_domain_bridge bridges.launch.xml pinky2:=false    # pinky2 제외
```
확인: `ROS_DOMAIN_ID=100 ros2 topic echo /pinky1/amcl_pose --once`

### 3. 관제 PC: zone_manager (새 터미널, 1대만)
```bash
export ROS_DOMAIN_ID=100
ros2 launch cobot_zone_traffic_control zone_manager.launch.xml
```
`config/zone_params.yaml` 의 `robot_ids` 는 순찰 노드의 `robot_id` 와 같아야 합니다.

### 4. 각 로봇: 순찰 노드
```bash
# pinky1
export ROS_DOMAIN_ID=10
ros2 run cobot_pinky_patrol pinky_patrol_node_pinky1 --ros-args -p robot_id:=pinky1

# pinky2
export ROS_DOMAIN_ID=20
ros2 run cobot_pinky_patrol pinky_patrol_node_pinky2 --ros-args -p robot_id:=pinky2

# pinky3
export ROS_DOMAIN_ID=30
ros2 run cobot_pinky_patrol pinky_patrol_node_pinky3 --ros-args -p robot_id:=pinky3
```

### 5. 관제 PC: 순찰 명령
워크스페이스 최상위에서 `ROS_DOMAIN_ID=100` 으로 실행합니다. **명령을 보내면 로봇이 실제로 움직이므로** 주변을 확인한 뒤 보냅니다.
```bash
CLIENT=src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py
python3 $CLIENT pinky1 monitor          # 상태 출력 (별도 터미널, Ctrl+C 종료)
python3 $CLIENT pinky1 start            # 전체 순찰
python3 $CLIENT pinky1 goto P2 P3 P6    # 지점 이동 후 홈 복귀
python3 $CLIENT pinky1 stop             # 중지
ros2 topic echo /zone_manager/status    # free | occupied_by:<robot_id>
```

## 보조 도구

### 맵 뷰어
서버 없이 브라우저로 엽니다. 지도 위에서 좌표를 확인하고 순찰 지점을 정할 때 씁니다.
```bash
xdg-open src/cobot_navigation/map_view_pc/pinky_map_viewer.html
```
화면에서 `map_view_pc/maps/cobot_map_v6.yaml` 과 `.pgm` 을 함께 불러옵니다.

### 네트워크 진단
```bash
cd src/cobot_navigation/ros2_network_test
./ros2_net_diag.sh <로봇 IP>     # 터미널 1: 진단 수집 (ROS 환경 source 후)
python3 net_monitor.py           # 터미널 2: 대시보드 → http://localhost:8088/
```

## 테스트

```bash
# 대기열 통합 테스트 (격리 도메인에서만 실행, 아니면 skip)
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest src/cobot_navigation/cobot_pinky_patrol/test/test_patrol_queue.py -q

# zone 단위 테스트
cd src/cobot_navigation/cobot_zone_traffic_control && python3 -m pytest test/
```

## 주의

- 순찰 명령(`start`/`goto`)은 실제 로봇을 구동합니다. 실행 전에 주변 안전을 확인합니다.
- 같은 구역을 쓰는 로봇은 모두 같은 대기열 방식의 순찰 노드를 써야 합니다. 이전 세대(`v2-final` 태그)와 섞으면 두 대가 동시에 구역에 들어갈 수 있습니다.
- 개발·시뮬레이션은 `ROS_DOMAIN_ID=100`, 격리 시험은 77을 씁니다. 로봇 도메인 10/20/30 에서는 시험용 노드를 띄우지 않습니다.
- 브릿지 설정(토픽 추가·수정)은 `cobot_domain_bridge/config/pinky_bridge_pinky{1,2,3}.yaml` 세 파일을 같이 고칩니다.
