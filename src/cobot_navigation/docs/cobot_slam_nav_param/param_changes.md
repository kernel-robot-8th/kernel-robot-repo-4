# Nav2 / slam_toolbox 파라미터 변경 사항 정리 (원본 → 수정본)

환경: ROS 2 (Ubuntu 24.04, Jazzy 기준) / 정적 비교 결과이며 실제 실행 검증은 하지 않았습니다.

- **원본**: 나중에 올려주신 파일 (resolution 0.05, 보수적 SLAM 임계값 등)
- **수정본**: 처음 올려주신 파일 (정밀도 위주로 튜닝)

---

## 1. nav2_params.yaml 변경 값

| 섹션 | 파라미터 | 원본 | 수정본 |
|---|---|---|---|
| amcl | `min_particles` | 500 | 1000 |
| amcl | `update_min_d` | 0.15 | 0.1 |
| controller (FollowPath) | `desired_linear_vel` | 0.2 | 0.15 |
| controller (FollowPath) | `max_angular_accel` | 3.2 | 1.5 |
| controller (FollowPath) | `lookahead_dist` | 0.6 | 0.25 |
| controller (FollowPath) | `min_lookahead_dist` | 0.3 | 0.15 |
| controller (FollowPath) | `max_lookahead_dist` | 0.9 | 0.4 |
| controller (FollowPath) | `rotate_to_heading_angular_vel` | 1.0 | 0.45 |
| controller (FollowPath) | `inflation_cost_scaling_factor` | 3.0 | 5.0 |
| goal checker | `xy_goal_tolerance` | 0.25 | 0.1 |
| goal checker | `yaw_goal_tolerance` | 0.25 | 0.17 |
| progress checker | `movement_time_allowance` | 10.0 | 20.0 |
| progress checker | `required_movement_radius` | 0.5 | 0.25 |
| local costmap | `resolution` | 0.05 | 0.025 |
| local costmap | `inflation_radius` | 0.15 | 0.45 |
| global costmap | `resolution` | 0.05 | 0.025 |
| global costmap | `inflation_layer.cost_scaling_factor` | 3.0 | 8.0 |
| global costmap | `inflation_layer.inflation_radius` | 0.15 | 0.45 |

`allow_reversing`은 `false` → `False` 표기만 변경(의미 동일).

## 2. mapper_params.yaml 변경 값

| 파라미터 | 원본 | 수정본 |
|---|---|---|
| `resolution` | 0.05 | 0.01 |
| `minimum_time_interval` | 0.5 | 0.2 |
| `minimum_travel_distance` | 0.5 | 0.03 |
| `minimum_travel_heading` | 0.5 | 0.05 |
| `scan_buffer_size` | 10 | 20 |
| `correlation_search_space_resolution` | 0.01 | 0.005 |
| `correlation_search_space_smear_deviation` | 0.1 | 0.02 |

---

## 3. 수정본에서 좋아진 점

- 룩어헤드 축소(0.6 → 0.25), 속도 감소(0.2 → 0.15)로 좁은 공간에서 코너를 덜 깎고 벽 충돌 위험이 줄어듦
- `inflation_radius` 0.15 → 0.45로 벽 주변 안전 거리 확보 (원본은 벽에서 약 6cm만 비용 생성)
- 목표 허용 오차 축소(0.25 → 0.1)로 정밀 정지 가능
- progress checker 완화(20초 / 0.25m)로 끼임 오탐 감소
- SLAM 이동·회전 임계값 축소(0.5 → 0.03 / 0.05)와 해상도 0.01로 지도 품질 향상

## 4. 수정본에서 새로 생긴 문제

1. **인플레이션 `cost_scaling_factor` 불일치**: local 3.0, global 8.0, 컨트롤러 5.0. 원본은 모두 3.0으로 통일되어 있었음. 전역 경로는 벽에 바짝 붙는데 로컬/컨트롤러는 위험으로 판단해 좁은 곳에서 멈추거나 떨림 발생 가능. 세 곳을 같은 값으로 통일 필요.
2. **SLAM 해상도(0.01) vs 코스트맵 해상도(0.025) 불일치**: 원본은 둘 다 0.05로 일치. `/map` 전송과 static layer 리샘플링 부하 증가. 0.025 이상으로 맞추거나 코스트맵과 동일하게 조정 권장.
3. **SBC 부하 증가**: `resolution` 0.01, `correlation_search_space_resolution` 0.005, `scan_buffer_size` 20, `min_particles` 1000, 코스트맵 해상도 0.025가 모두 연산량을 늘리는 방향. CPU 부족 시 TF 지연과 `extrapolation` 경고로 이어질 수 있음.
4. **`minimum_travel_distance: 0.03` / `minimum_travel_heading: 0.05`가 매우 작음**: 거의 모든 스캔을 처리하므로 부하가 크고, 정지 중 노이즈로 포즈 그래프가 불필요하게 커질 수 있음. 0.1~0.2 / 0.1~0.2 정도 권장.
5. **`inflation_radius: 0.45`가 로봇 크기(반경 약 6cm) 대비 큼**: 좁은 통로에서 경로가 안 나오거나 통과 못 할 수 있음. 0.25~0.3에서 시험 권장.

## 5. 원본/수정본 모두 남아 있는 기존 문제 (우선순위 순)

| 순번 | 문제 | 조치 |
|---|---|---|
| 1 | `map → odom` TF를 slam_toolbox(mapping)와 AMCL(`tf_broadcast: true`)이 동시에 발행 | 지도 작성 시 `navigation_launch.py`만 사용(AMCL/map_server 제외), 저장 지도 주행 시 slam_toolbox 종료 후 `bringup_launch.py slam:=False` |
| 2 | `bt_navigator.robot_base_frame: base_link` (나머지는 `base_footprint`) | `base_footprint`로 통일 |
| 3 | AMCL `initial_pose: [0, 0, 0]` 리스트 형식 (무시됨) | `x`, `y`, `z`, `yaw` 키로 분리 |
| 4 | `/bond_disable_heartbeat_timeout` 키 이름 | 슬래시 제거 또는 삭제, lifecycle_manager의 `bond_timeout` 사용 검토 (Jazzy 동작 미확인) |
| 5 | 로컬 코스트맵 `voxel_layer` (2D 라이다에 불필요, 설정 불일치) | `obstacle_layer`로 교체 |
| 6 | `behavior_server.transform_tolerance: 0.1` | TF 경고가 날 때만 0.3으로 상향 (`tf2_monitor`로 지연 측정 후) |

수정 예시:

```yaml
bt_navigator:
  ros__parameters:
    robot_base_frame: base_footprint

amcl:
  ros__parameters:
    set_initial_pose: true
    initial_pose:
      x: 0.0
      y: 0.0
      z: 0.0
      yaw: 0.0

behavior_server:
  ros__parameters:
    transform_tolerance: 0.3

# 인플레이션 값 통일 예시 (세 곳 동일하게)
controller_server:
  ros__parameters:
    FollowPath:
      inflation_cost_scaling_factor: 5.0
local_costmap:
  local_costmap:
    ros__parameters:
      inflation_layer:
        cost_scaling_factor: 5.0
global_costmap:
  global_costmap:
    ros__parameters:
      inflation_layer:
        cost_scaling_factor: 5.0
```

## 6. 확인 명령

```bash
ros2 run tf2_tools view_frames
ros2 topic info /tf -v
ros2 run tf2_ros tf2_monitor map base_footprint
ros2 param get /bt_navigator robot_base_frame
ros2 param get /amcl initial_pose.y
ros2 topic hz /scan
```