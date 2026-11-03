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
| 초음파 정면 보조(실물) | YOLO 추론 자체 (`cobot_person_detector` 담당) |
| 사람(YOLO bbox) 앞 정지 후 재출발 | |

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
| 입력 | `person_detections` | `vision_msgs/Detection2DArray` | `use_person_detection: true` 일 때. 다른 PC 의 YOLO 결과 |
| 입력 | `camera/camera_info` | `sensor_msgs/CameraInfo` | 있으면 fx·cx 사용, 없으면 `camera_hfov`·`camera_image_width` 로 근사 |
| 출력 | `cmd_vel` | `geometry_msgs/Twist` | 구동부 |
| 출력 | `obstacle_avoidance/state` | `std_msgs/String` | 상태 바뀔 때 발행 (디버깅) |

## 5. 회피 켜기/끄기
- `patrol_status.state` 가 `active_states`(`STARTING`, `MOVING`, `RETURNING`, `RETREATING`, `LEAVING_ZONE`)일 때만 켠다.
- 그 외 상태와 순찰 노드가 아직 상태를 안 보낸 경우에는 끈다. 꺼지면 Nav2 속도를 **그대로** 넘긴다(비상 정지 없음).
- `use_patrol_gate: false` 면 순찰 상태와 무관하게 항상 켠다(시뮬 시험용).
- 켜진 상태에서 Nav2 명령이 `cmd_timeout` 동안 없으면 정지 명령 한 번 후 발행을 멈춘다(다른 노드의 `cmd_vel` 을 가리지 않음). 이때 `obstacle_avoidance/state` 는 `IDLE` 이다.
- 켜진 상태에서 scan 이 `scan_timeout` 동안 끊기면 정지한다(`NO_SCAN`).

## 6. 상태 머신
| 상태 | 들어가는 조건 | 출력 |
|---|---|---|
| PASS | 앞 여유 ≥ `slow_dist`, TTC ≥ `ttc_slow` | Nav2 속도 |
| SLOW | 앞 여유 < `slow_dist` 또는 TTC < `ttc_slow` | 선속도 × 배율(≥ `min_slow_scale`) |
| STOP | 앞 여유 < `stop_dist` (해제는 `resume_dist` 이상) | 0 |
| WAIT | 움직이는 장애물 TTC < `ttc_stop` 이 `wait_confirm_time` 이상 지속 (해제는 TTC 위험이 `wait_release_time` 이상 사라진 뒤) | 0, `wait_timeout` 지나면 AVOID |
| AVOID | STOP 이 `block_time` 이상 지속, 또는 WAIT 시간 초과 | 빈 방향으로 회전, 정렬되면 `avoid_linear_speed` 로 전진 |
| BACKUP | AVOID 중 빈 방향 없음 + 뒤 여유 ≥ `rear_stop_dist` | `-backup_speed` 로 `backup_time` 동안 후진 후 AVOID |

- AVOID → PASS: 앞 여유 ≥ `avoid_clear_dist` 이고 `avoid_min_time` 경과, 또는 회피 전체가 `avoid_timeout` 초과(Nav2 재계획에 맡김).
- Nav2 가 스스로 후진 명령(v < 0)을 내면 뒤 여유만 검사한다.
- 앞 여유 = 로봇 앞면에서 통로(`|y| ≤ corridor_half_width`) 안 가장 가까운 점까지. 초음파를 켜면 둘 중 작은 값.

## 7. 사람 정지 (YOLO 연동)
- 사람 bbox 좌우 끝을 카메라(`camera_frame`, TF 로 위치·방향 조회) 기준 방향 각도로 바꾸고
  (`bbox_bearing_interval`, 양쪽 `person_bearing_margin` 여유), 그 각도 안의 라이다 점을 '사람 점'으로 본다.
- 사람 점이 앞 구역(반폭 `person_half_width`) 안 `person_stop_dist` 이내면 **PERSON_WAIT**: 정지만 하고 회피·후진은 하지 않는다.
  다른 상태(STOP/WAIT/AVOID/BACKUP)보다 우선한다. 시간 제한 없이 사람이 비킬 때까지 기다린다.
- 사람이 구역을 벗어나고 `person_release_time` 이 지나면 PASS 로 돌아가 Nav2 가 다시 출발시킨다.
- 인식 결과는 받은 시각 기준 `person_timeout` 이 지나면 버린다(다른 PC 와 시계가 달라서 영상 시각은 쓰지 않음).
- 사람이 아닌 장애물은 기존과 같이 STOP → AVOID / BACKUP.
- 카메라는 정면(화각 약 66°)만 보므로 후진 중 뒤의 사람은 일반 장애물로 처리된다.

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `use_person_detection` | false | 켜면 `person_detections`·`camera/camera_info` 구독 |
| `person_stop_dist` | 0.6 m | 사람 정지 거리 |
| `person_half_width` | 0.30 m | 사람 정지 구역 반폭 |
| `person_release_time` | 1.0 s | 사람이 벗어난 뒤 재출발 대기 |
| `person_timeout` | 1.0 s | 인식 결과 유효 시간 |
| `person_min_score` | 0.5 | 이 점수 미만 bbox 무시 |

## 7-1. 움직이는 장애물
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

사람 정지 사용 (YOLO 는 핑키와 연결된 PC 에서 실행):
```bash
# PC (관제, 도메인 100): YOLO
ros2 launch cobot_person_detector person_detector.launch.xml model_path:=<best.pt> \
  image_topic:=/pinky1/camera/image_raw/compressed use_compressed:=true output_topic:=/pinky1/person_detections
# 로봇: 회피 + 사람 정지
ros2 launch cobot_obstacle_avoidance bringup.launch.xml map:=<지도.yaml> use_person_detection:=true
# 한 PC 에서 모두 (시뮬): run_person_detector:=true model_path:=<best.pt> 추가
```
도메인 브릿지(`cobot_domain_bridge/config/pinky_bridge_pinkyN.yaml`)에 카메라 압축 영상(로봇→PC)과
`person_detections`(PC→로봇)를 추가했다. 브릿지 PC 에도 `vision_msgs` 가 설치돼 있어야 한다.

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

## 11. 시뮬레이션 결과 (2026-11-02, MuJoCo)
환경: `pinky_mujoco` (pinky_pro `014a09f`, GPU 없음), `room.yaml` 방 + 시나리오 장애물(지도에 없음),
Nav2 파라미터는 `pinky_navigation/params/nav2_params.yaml`, 출발 (0, 0) → 목표 (2.4, 0).
최소 거리 = 로봇 몸체(반경 0.06 m 근사) 표면과 장애물 표면 사이의 실제(ground truth) 거리.

| 시나리오 | Nav2 결과 | 회피 상태 변화 | 최소 거리 |
|---|---|---|---|
| S1 장애물 없음 | 성공 12.0 s | PASS 만 | - |
| S2 경로 옆 상자 | 성공 14.0 s | 개입 없음 | 0.15 m |
| S3 경로 정면 상자(미리 보임) | 성공 18.7 s | 개입 없음 (Nav2 재계획으로 우회) | 0.08 m |
| S4 막다른 곳 (ㄷ자 안에서 출발) | 성공 47~53 s | SLOW → STOP → AVOID → PASS | 0.04~0.07 m |
| S5 정면에서 다가오는 물체 | 성공 23.4 s | SLOW → WAIT(3 s) → STOP → PASS | 0.11 m |
| S6 경로를 가로지르는 물체 | 성공 17.6 s | SLOW → WAIT → PASS | 0.19 m |
| S9 0.5 m 앞에 갑자기 나타난 상자 | 성공 28.8 s | SLOW 반복 (Nav2 재계획과 함께) | 0.06 m |
| S10 좁은 통로가 갑자기 막힘 | 아래 참고 | SLOW → STOP → BACKUP → AVOID (→ BACKUP 반복) → PASS | 0.09~0.10 m |
| S7 순찰 `QUEUEING` + 정면 상자 | 성공 13.4 s | 꺼짐 (상태 발행 없음) | 0.18 m |
| S8 순찰 `MOVING` + 정면 상자 | 성공 14.5 s | SLOW (켜짐 확인) | 0.10 m |

- 모든 시나리오에서 충돌(거리 0 이하)은 없었다.
- S10 은 후진·회피 동작은 의도대로 나왔지만, 지도에 없는 긴 통로 벽 때문에 AMCL 위치가 0.7~2.7 m 틀어져
  Nav2 결과(성공/실패)를 믿을 수 없다. 회피를 끈 같은 장면(S10, `QUEUEING`)에서도 같은 위치 오차가 나서 회피 노드 원인은 아니다.
- 1차 실행에서 정지 물체가 움직이는 것으로 0.1 s 오검출되거나(S4, S8), 가로지르는 물체에서 WAIT/PASS 가 0.2 s 간격으로
  깜박였다(S6). `wait_confirm_time`(0.3 s)·`wait_release_time`(0.5 s) 추가 후 S8 오검출과 S6 깜박임은 사라졌고,
  S4 막다른 벽 근처에서는 0.5 s 짜리 WAIT 가 남아 있다.
- SLOW/PASS 는 경계 거리 근처에서 0.1~0.2 s 간격으로 바뀐다. 출력 속도는 연속적으로 변해 주행에는 영향이 작다.

## 12. 사람 정지 시뮬레이션 결과 (2026-11-02, MuJoCo)
MuJoCo 에는 사람 모델이 없어, 시뮬 안 상자 하나를 '사람'으로 정하고 실제 위치로 YOLO 와 같은 형식의 bbox
(`person_detections`, 5 Hz, 화각 1.1519 rad·폭 640 px 투영)를 발행했다. YOLO 노드는 별도로 시험했다(아래).

| 시나리오 | Nav2 결과 | 회피 상태 변화 | 최소 거리 |
|---|---|---|---|
| P1 사람이 경로로 들어와 5 s 서 있다가 비킴 | 성공 23.0 s | SLOW → PERSON_WAIT(7.8 s) → PASS | 0.28 m |
| P2 0.5 m 앞에 사람이 갑자기 나타나 6 s 뒤 사라짐 | 성공 18.9 s | SLOW → PERSON_WAIT(6.7 s) → PASS | 0.23 m |
| P3 같은 위치에 사람이 아닌 상자 (인식 켬) | 성공 20.0 s | PERSON_WAIT 없음, 기존 회피 | 0.10 m |

- 사람 앞에서는 AVOID/BACKUP 없이 정지했고, 사람이 사라진 뒤 약 1 s(`person_release_time`) 후 재출발했다.
- YOLO 노드(`best.pt`, 클래스 `{0: 'human'}`)를 `cobot_vision/pinky_camera.zip` 샘플 영상 50장으로 10 Hz 입력해
  `person_detections` 41건 모두 사람 bbox 포함(점수 0.97 예시)을 확인했다. CPU(4 코어) 추론 0.13 s/장.
