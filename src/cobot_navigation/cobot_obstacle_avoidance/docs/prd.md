# cobot_obstacle_avoidance PRD

## 1. 목적
핑키가 **주행 중** 앞을 막는 장애물(정지·이동 모두)을 만나면 멈추거나 감속하고,
필요하면 비켜 가거나 후진한 뒤 다시 Nav2 경로로 돌아가게 한다.
핑키 기본 Nav2(RPP 컨트롤러)는 경로를 따라가기만 하고 스스로 피하지 않기 때문에 만든다.

## 2. 범위
| 포함 | 제외 |
|---|---|
| 라이다 기반 정지·감속 | 구역 대기열(`QUEUEING`)·구역 점유(`HOLDING_ZONE`) 등 주행 외 상태의 회피 |
| 정지 장애물 우회(VFH), 후진 | 회피가 꺼진 상태의 비상 정지 (사용자 결정: 넣지 않음) |
| 움직이는 장애물 추적·TTC 대기 | Nav2 파라미터·`pinky_pro` 코드 수정 |
| 초음파 정면 보조(실물) | 카메라 기반 인식 |

## 3. 구조
```
controller_server ─ cmd_vel_nav ─▶ velocity_smoother ─┐
behavior_server (Spin/BackUp) ────────────────────────┴─ cmd_vel_avoid_in ─▶ obstacle_avoidance_node ─ cmd_vel ─▶ pinky_bringup
                                         scan, us_sensor/range, odom, patrol_status ─┘
```
- `launch/navigation.launch.xml`: `pinky_navigation/launch/navigation_launch.xml`(pinky_pro `014a09f`) 사본.
  velocity_smoother·behavior_server 의 출력만 `cmd_vel_avoid_in` 으로 바꿨다. pinky_pro 를 갱신하면 이 사본도 비교해 맞춘다.
- `launch/bringup.launch.xml`: `pinky_navigation` 의 `bringup_launch.xml` 대체. localization 은 원본, navigation 은 사본 + 회피 노드.

| 파일 | 내용 |
|---|---|
| `obstacle_avoidance_node.py` | 토픽 입출력, 회피 켜기/끄기, 센서 결합 |
| `scan_utils.py` | scan → 점, 통로 여유 거리, 군집화, 극좌표 히스토그램, 빈 방향 선택(VFH) |
| `tracker_utils.py` | odom 좌표 추적, 속도 추정, TTC |
| `avoidance_utils.py` | 상태 머신 |

## 4. 토픽
| 방향 | 토픽 | 타입 | 비고 |
|---|---|---|---|
| 입력 | `cmd_vel_avoid_in` | `geometry_msgs/Twist` | Nav2 최종 속도 |
| 입력 | `scan` | `sensor_msgs/LaserScan` | SensorDataQoS, TF 로 `base_footprint` 변환 (라이다 yaw=pi) |
| 입력 | `us_sensor/range` | `sensor_msgs/Range` | `use_ultrasonic: true` 일 때만 사용 |
| 입력 | `odom` | `nav_msgs/Odometry` | 이동 장애물 추적용 |
| 입력 | `patrol_status` | `std_msgs/String`(JSON) | `state` 로 회피 켜기/끄기 |
| 출력 | `cmd_vel` | `geometry_msgs/Twist` | 구동부 |
| 출력 | `obstacle_avoidance/state` | `std_msgs/String` | 상태 바뀔 때 발행 (디버깅) |

## 5. 회피 켜기/끄기
- `patrol_status.state` 가 `active_states`(`STARTING`, `MOVING`, `RETURNING`, `RETREATING`, `LEAVING_ZONE`)일 때만 켠다.
- 그 외 상태와 순찰 노드가 아직 상태를 안 보낸 경우에는 끈다. 꺼지면 Nav2 속도를 **그대로** 넘긴다(비상 정지 없음).
- `use_patrol_gate: false` 면 순찰 상태와 무관하게 항상 켠다(시뮬 시험용).
- 켜진 상태에서 Nav2 명령이 `cmd_timeout` 동안 없으면 정지 명령 한 번 후 발행을 멈춘다(다른 노드의 `cmd_vel` 을 가리지 않음).
- 켜진 상태에서 scan 이 `scan_timeout` 동안 끊기면 정지한다(`NO_SCAN`).

## 6. 상태 머신
| 상태 | 들어가는 조건 | 출력 |
|---|---|---|
| PASS | 앞 여유 ≥ `slow_dist`, TTC ≥ `ttc_slow` | Nav2 속도 |
| SLOW | 앞 여유 < `slow_dist` 또는 TTC < `ttc_slow` | 선속도 × 배율(≥ `min_slow_scale`) |
| STOP | 앞 여유 < `stop_dist` (해제는 `resume_dist` 이상) | 0 |
| WAIT | 움직이는 장애물 TTC < `ttc_stop` | 0, `wait_timeout` 지나면 AVOID |
| AVOID | STOP 이 `block_time` 이상 지속, 또는 WAIT 시간 초과 | 빈 방향으로 회전, 정렬되면 `avoid_linear_speed` 로 전진 |
| BACKUP | AVOID 중 빈 방향 없음 + 뒤 여유 ≥ `rear_stop_dist` | `-backup_speed` 로 `backup_time` 동안 후진 후 AVOID |

- AVOID → PASS: 앞 여유 ≥ `avoid_clear_dist` 이고 `avoid_min_time` 경과, 또는 회피 전체가 `avoid_timeout` 초과(Nav2 재계획에 맡김).
- Nav2 가 스스로 후진 명령(v < 0)을 내면 뒤 여유만 검사한다.
- 앞 여유 = 로봇 앞면에서 통로(`|y| ≤ corridor_half_width`) 안 가장 가까운 점까지. 초음파를 켜면 둘 중 작은 값.

## 7. 움직이는 장애물
1. `track_range` 안 점을 `cluster_gap` 으로 군집화하고, 점 `cluster_min_points` 개 이상·길이 `cluster_max_extent` 이하만 남긴다(벽 제외).
2. 군집 중심을 odom 좌표로 바꿔 최근접 매칭(`track_match_dist`)으로 이어 붙이고 속도를 저역통과(`track_alpha`)로 추정한다.
3. `track_min_hits` 이상 이어지고 `moving_min_speed` 이상인 것만 움직이는 물체로 보고,
   로봇과의 상대 위치·속도로 반경 `collision_radius` 에 닿는 시간(TTC)을 계산한다. 옆으로 지나가는 물체는 TTC = ∞.

## 8. 실행
```bash
# 시뮬 (Gazebo)
ros2 launch pinky_bringup bringup_sim.launch.xml sim:=gz
ros2 launch cobot_obstacle_avoidance bringup.launch.xml use_sim_time:=True use_patrol_gate:=false \
  map:=<지도.yaml>
ros2 launch pinky_navigation gz_nav2_view.launch.xml

# 실물 (pinky_sensor_adc 로 초음파 발행 필요)
ros2 launch pinky_bringup bringup_robot.launch.xml
ros2 run pinky_sensor_adc main_node
ros2 launch cobot_obstacle_avoidance bringup.launch.xml map:=<지도.yaml> \
  params_file:=<핑키별 nav2_params.yaml> use_ultrasonic:=true
```
상태 확인: `ros2 topic echo /obstacle_avoidance/state`

## 9. 시험 시나리오 (Gazebo)
| # | 상황 | 기대 |
|---|---|---|
| 1 | 경로 위 장애물 없음 | PASS 만, 기존과 같은 주행 |
| 2 | 경로 옆 0.3 m 에 상자 | SLOW 후 PASS, 정지 없음 |
| 3 | 경로 정면에 상자 | SLOW → STOP → (2 s) AVOID → PASS, 목표 도착 |
| 4 | 막다른 곳(앞·좌·우 막힘) | AVOID → BACKUP → AVOID 반복, `avoid_timeout` 후 Nav2 재계획 |
| 5 | 정면에서 다가오는 물체 | WAIT, 물체가 비키면 PASS / 안 비키면 5 s 후 AVOID |
| 6 | 경로를 가로지르는 물체 | 가로지르는 동안 WAIT 또는 SLOW, 지나간 뒤 PASS |
| 7 | 순찰 노드 + `QUEUEING` | 회피 꺼짐 (`회피 끔` 로그), Nav2 속도 그대로 |

## 10. 알려진 한계
- 정지 판단은 Nav2 가 아닌 이 노드가 하므로 Nav2 progress checker(20 s / 0.25 m)보다 회피가 길면 Nav2 가 목표를 실패 처리할 수 있다.
- 군집 중심 기반 추적이라 큰 물체 일부만 보이면 속도가 튈 수 있다(`moving_min_speed`, `track_min_hits` 로 조정).
- Gazebo 에는 초음파가 없어 초음파 결합은 실물에서만 확인 가능하다.
