# 장애물 회피 + 사람(인형) 정지 사용 가이드

핑키가 Nav2 로 목표 지점까지 주행하면서

- **일반 장애물**은 감속·정지·회피해서 지나가고,
- **사람(인형)** 은 피하지 않고 앞에서 정지했다가, 사라지면 다시 주행

하도록 하는 기능의 실행 방법과 입력 파라미터를 정리한 문서입니다.
2026-11-14 핑키 2 실물 시험에서 쓴 명령·값을 그대로 기록했습니다.

> 이 프로젝트에서 "사람"은 **인형**입니다. YOLO 모델이 인형을 사람 클래스(`{0: 'human'}`)로 학습했습니다.

## 1. 구성

| 패키지 | 위치 | 실행 장소 | 역할 |
|---|---|---|---|
| `cobot_obstacle_avoidance` | `src/cobot_navigation/` | 핑키 | Nav2 와 구동부 사이에서 속도를 그대로 넘기거나 감속·정지·회피·후진으로 바꿈. 사람이면 정지 후 재출발 |
| `cobot_person_detector` | `src/cobot_vision/` | PC | 카메라 영상 → YOLO → 사람 bbox(`person_detections`) 발행 |
| `cobot_camera_topic_test` | `feature/vision-camera-topic-besteffort` 브랜치 | 핑키 | 핑키 카메라 → `/camera/image_raw/compressed` (JPEG, BEST_EFFORT) |
| `pinky_bringup`, `pinky_navigation` | `pinky_pro` | 핑키 | 구동부·라이다, AMCL·지도·Nav2 파라미터 |

카메라 패키지는 이 브랜치에 들어 있지 않습니다. `feature/vision-camera-topic-besteffort` 브랜치에서 받아 핑키에서 빌드합니다.

### 데이터 흐름

```
[핑키]                                                          [PC]
 카메라 ─ /camera/image_raw/compressed ───────────────────────▶ person_detector_node (YOLO)
                                                                      │
 obstacle_avoidance_node ◀────────────── /person_detections ──────────┘
   ▲   ▲ /scan (라이다)
   │   └ /odom, /us_sensor/range(선택), /patrol_status(선택), TF(front_camera_link)
   │
 Nav2 controller ─ cmd_vel_nav ─▶ velocity_smoother ─ cmd_vel_avoid_in ─▶ obstacle_avoidance_node ─ /cmd_vel ─▶ pinky_bringup
```

- `cobot_obstacle_avoidance/launch/bringup.launch.xml` 은 Nav2 를 직접 띄우고, Nav2 의 최종 출력을 `cmd_vel_avoid_in` 으로 바꿉니다.
  **`pinky_navigation` 의 Nav2 bringup 과 동시에 띄우면 안 됩니다** (`cmd_vel` 충돌).
- 사람 판별: YOLO bbox 의 화면 방향을 TF(`front_camera_link`)로 라이다 점과 맞춰, 그 방향 라이다 점을 "사람 점"으로 봅니다.

## 2. 준비

### 2-1. 핑키

```bash
cd ~/pinky_pro/src
# 이 브랜치
git clone -b feature/vision-avoding --single-branch https://github.com/kernel-robot-8th/kernel-robot-repo-4.git kernel-robot
# 카메라 패키지 (다른 브랜치) - 같은 저장소를 다른 폴더로 받는다
git clone -b feature/vision-camera-topic-besteffort --single-branch --depth 1 \
  https://github.com/kernel-robot-8th/kernel-robot-repo-4.git kernel-robot-camera

cd ~/pinky_pro && source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_obstacle_avoidance cobot_camera_topic_test
source install/setup.bash
```

- 사람 정지 기능을 켜면 `vision_msgs` 가 필요합니다: `ros-jazzy-vision-msgs` (핑키 1·2 에는 설치되어 있었음).
- 카메라는 제조사 `pinkylib` 를 씁니다. 확인: `python3 -c 'from pinkylib import Camera'`

### 2-2. PC (YOLO)

```bash
cd ~/<ws>/src
git clone -b feature/vision-avoding --single-branch https://github.com/kernel-robot-8th/kernel-robot-repo-4.git kernel-robot
sudo apt install ros-jazzy-vision-msgs ros-jazzy-cv-bridge
pip install ultralytics "numpy<2"        # Jazzy cv_bridge 는 numpy 1.x 필요
cd ~/<ws> && source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_person_detector
source install/setup.bash
```

### 2-3. YOLO 모델 (커밋 금지)

모델 가중치는 저장소에 넣지 않습니다 (CLAUDE.md 3-1). 시험에 쓴 모델:

| 항목 | 값 |
|---|---|
| 위치 | 이 저장소 `feature/vision` 브랜치의 `human/best.pt` (5.4 MB) |
| 클래스 | `{0: 'human'}` (= 인형) |
| git blob | `ac538ad47b0757b26d881f6c15afddd738ea5141` |

```bash
mkdir -p ~/models
git -C <저장소> show origin/feature/vision:human/best.pt > ~/models/best.pt   # 또는 GitHub 에서 직접 받기
```

저장소 폴더 안에 두면 `.gitignore` 에 `.pt` 규칙이 없어 커밋될 수 있으니 **저장소 밖**(예: `~/models/`)에 둡니다.

## 3. 실행 전 필수 확인 (통신)

시험에서 가장 오래 걸린 부분입니다. 아래가 맞지 않으면 토픽이 보이지 않거나, 이동 명령이 무시됩니다.

| 항목 | 핑키 1 (`192.168.45.21`) | 핑키 2 (`192.168.45.22`) | PC |
|---|---|---|---|
| `ROS_DOMAIN_ID` | 10 | 20 | **시험할 핑키와 같은 값** |
| `RMW_IMPLEMENTATION` | `rmw_cyclonedds_cpp` | `rmw_cyclonedds_cpp` | `rmw_cyclonedds_cpp` |
| `CYCLONEDDS_URI` | `~/.ros/cyclonedds_robot.xml` | `~/.ros/cyclonedds_robot.xml` | `~/.ros/cyclonedds_pc.xml` |

(2026-11-14 각 장비 `~/.bashrc` 에서 확인한 값. 바꾸지 말고 확인만 합니다.)

- **CycloneDDS 는 멀티캐스트를 끄고 피어 IP 목록으로만 서로를 찾습니다.**
  PC 설정 파일의 `<Peers>` 에 시험할 핑키 IP 가, 핑키 설정에 PC IP 가 있어야 합니다.
  예: PC 의 `cyclonedds_pc.xml` 에 `192.168.45.22` 만 있으면 핑키 1(`.21`)은 보이지 않습니다.
  공용 설정을 고치지 않으려면 사본을 만들어 그 터미널에서만 `export CYCLONEDDS_URI=file://<사본>` 으로 씁니다.
- **SSH 로 명령 한 줄을 보낼 때(`ssh pinky@... '명령'`)는 `~/.bashrc` 가 실행되지 않습니다.**
  도메인 ID 와 DDS 설정이 빠져 기본값(도메인 0, FastDDS)으로 실행됩니다. 이 경우 아래처럼 직접 넣습니다.

```bash
export ROS_DOMAIN_ID=20          # 핑키 2 기준
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///home/pinky/.ros/cyclonedds_robot.xml
source /opt/ros/jazzy/setup.bash
source ~/pinky_pro/install/setup.bash
```

확인: PC 에서 `ros2 topic list` 에 핑키의 `/scan`, `/battery/percent` 가 보여야 합니다.

## 4. 실행 순서

### 핑키 터미널 1 - 구동부·라이다

```bash
ros2 launch pinky_bringup bringup_robot.launch.xml
```

### 핑키 터미널 2 - 카메라

```bash
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  publisher:=true subscriber:=false source:=pinky fps:=10.0 transport:=compressed
```

> **핑키 2 주의**: 그대로 실행하면 `ipa_rpi_pisp.so: undefined symbol ... libpisp::BackEnd::GetDebin` 으로 카메라 노드가 죽습니다.
> `ros-jazzy-libcamera` 패키지의 `libpisp 1.3.0`(`/opt/ros/jazzy/lib`)이 제조사 libcamera 가 쓰는 `libpisp 1.0.7`(`/usr/local/lib/aarch64-linux-gnu`)보다 먼저 로드되기 때문입니다.
> 시스템 패키지는 건드리지 않고 **카메라 터미널에서만** 아래를 먼저 실행합니다. 로그에 `libpisp version v1.0.7` 이 나오면 정상입니다.
>
> ```bash
> export LD_LIBRARY_PATH=/usr/local/lib/aarch64-linux-gnu:$LD_LIBRARY_PATH
> ```

### 핑키 터미널 3 - Nav2 + 장애물 회피 + 사람 정지

```bash
ros2 launch cobot_obstacle_avoidance bringup.launch.xml \
  map:=/home/pinky/cobot_map_v9.yaml \
  use_patrol_gate:=false \
  use_person_detection:=true
```

### PC 터미널 - YOLO

```bash
ros2 launch cobot_person_detector person_detector.launch.xml \
  model_path:=$HOME/models/best.pt \
  image_topic:=/camera/image_raw/compressed \
  use_compressed:=true \
  device:=cpu
```

### 초기 위치 → 목표 전송

1. 초기 위치(AMCL). `pinky_navigation` 기본값은 지도 원점 `(0, 0, 0)` 입니다. 핑키가 다른 곳에 있으면 반드시 다시 지정합니다.
   - RViz2: Fixed Frame `map` → **2D Pose Estimate** 로 실제 위치를 찍음. 라이다 점이 지도 벽과 겹치면 성공.
   - 명령: (핑키 2 홈 I2 예시)
     ```bash
     ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
       "{header: {frame_id: map}, pose: {pose: {position: {x: 0.0, y: -0.2}, orientation: {z: 0.0, w: 1.0}}}}"
     ```
2. 핑키를 손으로 옮긴 뒤라면 코스트맵에 이전 위치 기준의 장애물 흔적이 남습니다. 초기 위치를 다시 준 뒤 비웁니다.
   ```bash
   ros2 service call /global_costmap/clear_entirely_global_costmap nav2_msgs/srv/ClearEntireCostmap "{}"
   ros2 service call /local_costmap/clear_entirely_local_costmap nav2_msgs/srv/ClearEntireCostmap "{}"
   ```
3. 목표 전송 (P22 예시. yaw 1.5 rad → `z = sin(0.75)`, `w = cos(0.75)`)
   ```bash
   ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
     "{pose: {header: {frame_id: map}, pose: {position: {x: -0.5, y: -0.8}, orientation: {z: 0.6816, w: 0.7317}}}}"
   ```
   주행 없이 경로만 확인하려면 `/compute_path_to_pose`(`nav2_msgs/action/ComputePathToPose`, `use_start: false`)를 씁니다.
   경로 끝이 목표에서 약 0.5 m 떨어져 있으면 목표 지점이 코스트맵에서 막힌 것입니다 (2번 확인).

현장 좌표(`cobot_map_v9` 기준, m·rad)는 `src/cobot_navigation/cobot_pinky_patrol/config/` 에 있습니다.
홈: I1 `(0.0, 0.0, 0.0)` 핑키 1, I2 `(0.0, -0.2, 0.0)` 핑키 2, I3 `(0.0, -0.4, 0.0)` 핑키 3. P22 `(-0.5, -0.8, 1.5)`.

### 상태 확인

```bash
ros2 topic echo /obstacle_avoidance/state     # 상태가 바뀔 때만 발행 (멈춰 있으면 아무것도 안 나와도 정상)
ros2 topic echo /person_detections            # 사람 없으면 detections: [] 가 계속 나옴
```

| 상태 | 의미 |
|---|---|
| `IDLE` | Nav2 명령 없음 |
| `PASS` | 앞이 비어 있음, Nav2 속도 그대로 |
| `SLOW` | 장애물이 가까움(`slow_dist` 안), 감속 |
| `STOP` | 정지 장애물이 `stop_dist` 안, 정지. `block_time` 넘게 막히면 `AVOID` |
| `WAIT` | 움직이는 장애물과 곧 부딪힘(TTC), 정지 후 대기. `wait_timeout` 넘으면 `AVOID` |
| `AVOID` | 빈 방향(VFH)으로 돌아 나감. 앞이 트이면 `PASS` |
| `BACKUP` | 빈 방향이 없어 후진 후 다시 `AVOID` |
| `PERSON_WAIT` | 앞 구역에 사람(인형). 피하지 않고 정지. 사라진 뒤 `person_release_time` 이 지나면 재출발 (다른 상태보다 우선) |

## 5. 입력 파라미터

### 5-1. 꼭 직접 넣어야 하는 값

| 어디 | 인자 | 넣을 값 | 틀리면 |
|---|---|---|---|
| 회피 launch | `map` | 현장 지도 `/home/pinky/cobot_map_v9.yaml` | 기본값 `pinky_navigation/map/my_map.yaml`(다른 공간)로 떠서 위치 추정이 안 맞음 |
| 회피 launch | `use_patrol_gate` | 순찰 노드 없이 시험: `false` / 순찰 노드와 함께: `true` | `true` 인데 순찰 노드가 없으면 회피가 꺼진 채 Nav2 속도만 전달 |
| 회피 launch | `use_person_detection` | `true` | `false`(기본)면 사람도 일반 장애물처럼 피함 |
| 회피 launch | `use_ultrasonic` | `pinky_sensor_adc` 를 띄웠을 때만 `true` | 안 띄우고 `true` 면 초음파 값이 없음 |
| YOLO launch | `model_path` | `best.pt` 절대 경로 | 비어 있으면 노드가 시작을 거부 |
| YOLO launch | `image_topic` | `/camera/image_raw/compressed` (`/compressed` 포함) | 영상을 못 받아 감지 없음 |
| YOLO launch | `use_compressed` | `true` (카메라가 JPEG 일 때) | 메시지 타입이 달라 구독 실패 |
| YOLO launch | `device` | `cpu`, GPU 면 `'0'` | - |
| 카메라 launch | `publisher` / `source` | `true` / `pinky` | 기본값은 수신기만 실행 |
| 초기 위치 | `/initialpose` | 핑키의 실제 위치 | 엉뚱한 경로로 주행 |

### 5-2. `cobot_obstacle_avoidance` launch 인자 (`bringup.launch.xml`)

| 인자 | 기본값 | 설명 |
|---|---|---|
| `map` | `pinky_navigation/map/my_map.yaml` | 지도 yaml |
| `params_file` | `pinky_navigation/params/nav2_params.yaml` | Nav2 파라미터 (AMCL 초기 위치 포함) |
| `avoidance_params_file` | `cobot_obstacle_avoidance/config/obstacle_avoidance.yaml` | 회피 노드 파라미터 |
| `use_patrol_gate` | `true` | 5-1 참고 |
| `use_ultrasonic` | `false` | 5-1 참고 |
| `use_person_detection` | `false` | 5-1 참고 |
| `run_person_detector` | `false` | `true` 면 같은 기기에서 YOLO 노드도 실행 (`model_path` 필요). 핑키에는 ultralytics 가 없어 PC 실행을 권장 |
| `model_path`, `device` | `''`, `cpu` | `run_person_detector:=true` 일 때만 사용 |
| `namespace` | `''` | 노드 네임스페이스 |
| `use_sim_time` | `False` | Gazebo 면 `True` |
| `autostart`, `use_composition`, `container_name`, `use_respawn`, `log_level` | `True`, `True`, `nav2_container`, `False`, `info` | Nav2 공통 |

`obstacle_avoidance.launch.xml` 은 회피 노드만 띄웁니다 (`namespace`, `use_sim_time`, `params_file`, `use_patrol_gate`, `use_ultrasonic`, `use_person_detection`). 이 경우 Nav2 는 같은 패키지의 `navigation.launch.xml` 로 띄워야 출력이 `cmd_vel_avoid_in` 으로 바뀝니다.

### 5-3. `obstacle_avoidance_node` 파라미터 (`config/obstacle_avoidance.yaml`)

**기본·형상**

| 이름 | 기본값 | 단위 | 설명 |
|---|---|---|---|
| `base_frame` | `base_footprint` | - | 로봇 기준 frame |
| `control_rate` | 20.0 | Hz | Nav2 `controller_frequency` 와 맞춤 |
| `cmd_timeout` | 0.5 | s | Nav2 명령이 이만큼 없으면 발행 중지 |
| `scan_timeout` | 0.5 | s | 회피 중 scan 이 끊기면 정지 |
| `use_patrol_gate` | true | - | 순찰 상태가 `active_states` 일 때만 회피 |
| `active_states` | `[STARTING, MOVING, RETURNING, RETREATING, LEAVING_ZONE]` | - | 회피를 켜는 순찰 상태 |
| `robot_front_x` / `robot_rear_x` | 0.06 / 0.06 | m | 로봇 앞·뒷면 위치 (footprint 0.12 m) |
| `corridor_half_width` | 0.10 | m | 앞·뒤 통로 반폭 (0.06 + 여유 0.04) |
| `use_ultrasonic` | false | - | 정면 초음파 보조 |
| `ultrasonic_x` / `ultrasonic_timeout` | 0.0267 / 0.5 | m / s | 초음파 위치·유효 시간 |

**정지·감속·회피**

| 이름 | 기본값 | 단위 | 설명 |
|---|---|---|---|
| `stop_dist` | 0.12 | m | 앞 여유가 이보다 작으면 정지 |
| `resume_dist` | 0.20 | m | 정지 후 이보다 커져야 재출발 |
| `slow_dist` | 0.40 | m | 감속 시작 거리 |
| `min_slow_scale` | 0.3 | - | 감속 최소 배율 |
| `block_time` | 2.0 | s | 정지가 이어지면 회피 시작 |
| `rear_stop_dist` | 0.10 | m | 뒤 여유가 이보다 작으면 후진 금지 |
| `ttc_stop` / `ttc_slow` | 2.0 / 4.0 | s | 움직이는 장애물 TTC 대기·감속 기준 |
| `wait_timeout` | 5.0 | s | 대기가 길어지면 회피로 전환 |
| `wait_confirm_time` / `wait_release_time` | 0.3 / 0.5 | s | 대기 진입·해제 확인 시간 (깜박임 방지) |
| `avoid_clearance` | 0.35 | m | 빈 방향 판단 거리 |
| `robot_radius` | 0.10 | m | 빈 방향 폭 검사 반경 |
| `avoid_max_angle` | 1.75 | rad | 회피 방향 탐색 범위 (±100°) |
| `avoid_linear_speed` | 0.06 | m/s | 회피 중 전진 속도 |
| `avoid_angular_gain` / `max_angular_speed` | 1.5 / 1.0 | - / rad/s | 회피 회전 이득·최대 속도 |
| `align_tol` | 0.35 | rad | 이 각도 안으로 맞으면 전진 |
| `avoid_clear_dist` | 0.40 | m | 회피 중 앞 여유가 이 이상이면 Nav2 로 복귀 |
| `avoid_min_time` / `avoid_timeout` | 1.0 / 8.0 | s | 회피 최소 유지 / 길어지면 Nav2 재계획에 맡김 |
| `backup_speed` / `backup_time` | 0.05 / 2.0 | m/s / s | 후진 속도·시간 |
| `histogram_sectors` / `histogram_range` | 72 / 1.5 | - / m | VFH 히스토그램 (5° 간격) |

**움직이는 장애물 추적**

| 이름 | 기본값 | 단위 | 설명 |
|---|---|---|---|
| `track_range` | 1.5 | m | 이 안의 덩어리만 추적 |
| `cluster_gap` / `cluster_min_points` | 0.08 / 3 | m / 개 | 덩어리 묶기 |
| `cluster_max_extent` | 0.5 | m | 이보다 긴 덩어리(벽)는 추적 안 함 |
| `track_match_dist` / `track_max_age` | 0.25 / 0.5 | m / s | 추적 매칭 |
| `track_alpha` / `track_min_hits` | 0.4 / 3 | - | 속도 저역통과 / 최소 관측 횟수 |
| `moving_min_speed` | 0.08 | m/s | 이 이상이면 움직이는 물체 |
| `collision_radius` | 0.25 | m | TTC 계산용 로봇+물체 반경 |

**사람(인형) 정지**

| 이름 | 기본값 | 단위 | 설명 |
|---|---|---|---|
| `use_person_detection` | false | - | 사람 정지 켜기 |
| `person_topic` | `person_detections` | - | `vision_msgs/Detection2DArray` |
| `camera_info_topic` | `camera/camera_info` | - | 없으면 아래 `camera_hfov`·`camera_image_width` 사용 (핑키 카메라 패키지는 camera_info 를 내지 않음) |
| `camera_frame` | `front_camera_link` | - | URDF 정면 카메라 frame (TF 필요) |
| `camera_hfov` | 1.1519 | rad | 카메라 수평 화각 (66°) |
| `camera_image_width` | 640 | px | 영상 가로 크기 |
| `person_min_score` | 0.5 | - | 이 점수 이상 bbox 만 사용 |
| `person_timeout` | 1.0 | s | 마지막 감지가 이보다 오래되면 사람 없음 |
| `person_bearing_margin` | 0.05 | rad | bbox 방향 구간 여유 |
| `person_max_range` | 3.0 | m | 이보다 먼 라이다 점은 사람 점으로 안 봄 |
| `person_half_width` | 0.30 | m | 사람 정지 구역 반폭 (일반 통로보다 넓게) |
| `person_stop_dist` | 0.6 | m | 사람 점이 앞 이 거리 안이면 정지 |
| `person_release_time` | 1.0 | s | 사람이 벗어난 뒤 재출발까지 대기 |

### 5-4. `cobot_person_detector` 인자·파라미터

launch(`person_detector.launch.xml`) 인자: `model_path`(필수), `image_topic`, `use_compressed`, `output_topic`, `device`, `namespace`, `use_sim_time`, `params_file`.

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `model_path` | `''` | YOLO `.pt` 경로. 비면 시작 거부 |
| `image_topic` | `camera/image_raw` | 입력 영상. 압축이면 `/camera/image_raw/compressed` |
| `use_compressed` | false | `true` 면 `sensor_msgs/CompressedImage` 구독 |
| `output_topic` | `person_detections` | 출력 bbox. header 는 입력 영상 header 그대로 |
| `person_class` | 0 | 모델의 사람(인형) 클래스 번호 |
| `min_confidence` | 0.5 | 이 점수 이상만 발행 |
| `min_box_height` | 20.0 | 이보다 작은(먼) bbox 무시 [px] |
| `imgsz` | 640 | YOLO 입력 크기 |
| `device` | `cpu` | GPU 면 `'0'` |
| `max_rate` | 5.0 | 처리 주기 상한 [Hz]. 밀린 프레임은 버림 |

입력 QoS 는 `qos_profile_sensor_data`(BEST_EFFORT)로, 카메라 발행 QoS 와 맞습니다.

### 5-5. 카메라 (`cobot_camera_topic_test`, 참고)

자세한 내용은 해당 브랜치의 `src/cobot_vision/cobot_camera_topic_test/README.md`. 시험에 쓴 값만 적습니다.

| 인자 | 시험 값 | 설명 |
|---|---|---|
| `publisher` / `subscriber` | `true` / `false` | 핑키에서는 발행기만 |
| `source` | `pinky` | 제조사 `pinkylib.Camera` |
| `transport` | `compressed` | `/camera/image_raw/compressed` (JPEG) |
| `fps` | 10.0 | 발행 목표 주기 |
| `jpeg_quality` | 85 (기본) | 1~100 |

출력 frame_id `front_camera_link`, QoS `BEST_EFFORT / VOLATILE / KEEP_LAST(1)`, 640×480.

## 6. 관제 PC 도메인 브릿지 (미시험)

`cobot_domain_bridge/config/pinky_bridge_pinky{1,2,3}.yaml` 에 `PERSON-STOP ADDED` 구간을 추가했습니다.
관제 PC(도메인 100)에서 YOLO 를 돌릴 때 카메라 영상(로봇 → 100, `/pinkyN/camera/image_raw/compressed`)과 bbox(100 → 로봇, `/person_detections`)를 넘깁니다.
이때 YOLO 는 `image_topic:=/pinkyN/camera/image_raw/compressed use_compressed:=true output_topic:=/pinkyN/person_detections` 로 실행합니다.

2026-11-14 시험은 PC 와 핑키를 **같은 도메인으로 직접 연결**해서 했고, 브릿지 경로와 BEST_EFFORT 영상 전달은 아직 확인하지 않았습니다.

## 7. 현장 시험 결과 (2026-11-14, 핑키 2, 지도 v9)

조건: 홈 I2 → P22, 경로 약 3.5 m, 남색 장애물 1개 + 인형, YOLO PC(CPU), 위 4절 명령 그대로.

| 항목 | 결과 |
|---|---|
| 목표 도착 | 성공 (도착 위치 `(-0.53, -0.81)`, P22 와 약 3 cm 차이, 약 158 s) |
| 인형 앞 정지 → 치우면 재출발 | 성공 (인형 점수 0.76, 정지 약 5.5 s 후 재출발) |
| 일반 장애물 | `WAIT` 후 Nav2 가 옆으로 돌아 통과 |
| 오인식 | 남색 장애물을 인형으로(0.87) 오인식해 약 15 s 정지. 앞선 시험에서는 흰 벽·판을 0.5~0.9 로 오인식 |

주행 영상(카메라 시점, 상태·bbox 표시)은 용량 때문에 커밋하지 않았습니다. 필요하면 담당자에게 요청합니다.

## 8. 알려진 한계

1. **YOLO 오인식**: 흰 벽·판, 남색 장애물을 인형으로 인식합니다. 오인식 점수(0.50~0.91)가 실제 인형 점수와 겹쳐 `min_confidence` 만으로는 걸러지지 않습니다.
   근본 해결은 벽·장애물 사진을 "인형 아님"으로 넣어 다시 학습하는 것입니다.
2. **`PERSON_WAIT` 시간 제한 없음**: 오인식이 계속되면 무한정 정지합니다. (1차 시험에서 흰 벽 오인식으로 3분 넘게 정지 → 목표 취소)
3. **감지 깜박임**: 인형이 그대로 있어도 감지가 약 0.5 s 간격으로 켜졌다 꺼져 정지·재출발이 짧게 반복될 수 있습니다. `person_timeout`(1.0 s)을 늘리면 완화됩니다.
4. `camera_info` 가 없어 `camera_hfov`(66°) 기본값으로 방향을 계산합니다. 카메라가 바뀌면 화각을 맞춥니다.

## 9. 문제 해결

| 증상 | 확인 |
|---|---|
| PC 에서 핑키 토픽이 안 보임 | 3절: 도메인 ID, RMW, CycloneDDS 피어 IP. 설정을 바꿨으면 `ros2 daemon stop` |
| SSH 로 보낸 이동 명령이 무시됨 | SSH 한 줄 명령은 `.bashrc` 를 안 읽음 → 3절 환경 변수를 직접 넣기 |
| `/obstacle_avoidance/state` 가 안 나옴 | 상태가 바뀔 때만 발행. 노드 확인은 `ros2 node list` 의 `/obstacle_avoidance_node` |
| 카메라 노드 exit code 127, `undefined symbol ... GetDebin` | 4절 핑키 2 주의 (`LD_LIBRARY_PATH`) |
| `/person_detections` 가 계속 `[]` | 사람이 없으면 정상. 영상 수신은 `ros2 topic echo /camera/image_raw/compressed --qos-reliability best_effort --field header --once` |
| `tf error: Invalid frame ID "odom"` 반복 | 핑키 터미널 1(`pinky_bringup`)이 안 떠 있음 |
| 목표를 보냈는데 안 움직임 | 초기 위치 미지정, 또는 `pinky_navigation` Nav2 와 이중 실행 |
| 경로가 목표 0.5 m 앞에서 끝남 | 코스트맵 잔상 → 4절 코스트맵 비우기 |
| 사람이 없는데 계속 `PERSON_WAIT` | 8절 오인식. 목표 취소 후 영상·bbox 확인 |
