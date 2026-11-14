# cobot_pinky_patrol

Pinky 로봇에서 실행하는 Nav2 순찰 노드 패키지입니다. 로봇마다 노드(`pinky_patrol_node_pinky1`, `pinky_patrol_node_pinky2`, `pinky_patrol_node_pinky3`)가 하나씩 있으며, 위험 구역에 **한 대만** 들어가도록 `cobot_zone_traffic_control`의 대기열 슬롯 방식과 연동합니다.

## 주요 기능

- **명령 수신**: `patrol_cmd`(String)로 `goto:<P>[,<P>,...]` / `zone:<P>` / `leave` / `home` / `stop` / `emergency_stop` (아래 "명령과 동작" 표 참고). `start`(전체 순회)는 v1.1.0 에서 **비활성**이며 받으면 `FAILED`(detail `start disabled`)로 응답합니다
- **상태 발행**: `patrol_status`에 JSON 발행 — `{"state": "MOVING", "waypoint": 2, "detail": "ZB", "time": ...}`
  `IDLE` `STARTING` `MOVING` `QUEUEING` `ARRIVED` `HOLDING_ZONE` `LEAVING_ZONE` `RETREATING` `RETURNING` `IDLE_WAIT` `DONE` `STOPPED` `FAILED` `RETRY`
- **대기열 진입**: 구역 진입 전에 먼저 요청을 보냅니다.
  - 구역이 비어 있으면 바로 허가를 받아 목적지로 직행
  - 점유 중이면 매니저가 준 슬롯으로 이동해 `QUEUEING` 대기, 슬롯이 바뀌면 새 슬롯으로 재이동
  - 대기열이 가득 차면 `FAILED`(`queue_full`), `stop`/이동 실패 시 대기열에서 빠지고 허가를 받았다면 락 반납
- **위치 복원**: 마지막 위치를 `~/.pinky_last_pose.json`에 저장하고, 노드 실행 후 첫 작업에서만 AMCL 초기 위치로 보낸 뒤 제자리 한 바퀴 회전으로 방향 보정. 현재는 라이다가 틀어져 **꺼 둠**(`restore_last_pose: false`, `_prepare_nav` 의 호출 주석 처리) — RViz 로 찍은 초기 위치를 그대로 사용
- **위치 재설정**: patrol 노드와 별개인 `pinky_pose_recovery_node` 가 waypoint 이름을 받아 AMCL 초기 위치를 다시 잡고 좌우 스캔으로 방향을 맞춥니다 (위 "위치 복원"과는 다른 기능, 아래 "위치 재설정" 참고)
- **LED**: 대기 초록 깜박임 / 주행 초록 / 구역 대기 빨강 깜박임 / 도착 후 대기 노랑 깜박임

## 연관 파일

```
관제 PC(100)  pinky_control_client.py ──/<robot>/patrol_cmd──▶ domain_bridge ──▶ patrol_node (로봇 10/20/30)
             zone_manager_node ◀── request_entry / cancel_entry / notify_exit ── ZoneGateClient
                                  ──▶ grant_entry / queue_slot ──────────────────▶ (zone_gate_client)
```
![시스템 구성도](docs/pinky_patrol_flow.svg)

| 파일 | 실행 위치 | 역할 |
|---|---|---|
| `cobot_pinky_patrol/pinky_patrol_node_pinky{1,2,3}.py` | 각 로봇 | 순찰·goto, 구역 진입 절차 |
| `cobot_zone_traffic_control/.../zone_gate_client.py` | 각 로봇 (import) | 진입 요청·취소·이탈 통보, 허가·슬롯 수신 |
| `cobot_zone_traffic_control/.../zone_manager_node.py` | 관제 PC (1대) | 점유자 1명 + FIFO 대기열, 허가·슬롯 좌표 발행 |
| `cobot_pinky_patrol_cmd/pinky_control_client.py` | 관제 PC | 터미널에서 명령 전송 |

- 로봇 코드와 YAML 에는 대기 좌표(앵커·슬롯)가 없습니다. 로봇에는 출구 `Z<구역>_EXIT` 만 있고(`config/pinkyN.yaml`), 대기 앵커는 매니저 `zone_params.yaml` 의 구역별 `queue_anchor` 한 곳에만 둡니다. 매니저가 슬롯 좌표를 계산해 `queue_slot` 으로 주며, 로봇은 응답이 오기 전에는 제자리에서 기다립니다. 앵커 / 출구는 구역 A `(0.1, 0.6, 0.0)` / `(0.5, 0.0, -1.5)`, 구역 B `(0.1, 0.6, 0.0)`(A 와 같은 대기 위치) / `(0.55, -0.6, -1.5)`, 구역 C `(-0.7, -0.08, 1.5)` / `(-0.3, -0.4, 1.5)` 입니다 (2026-10-27 확정). 앵커는 구역 소속 지점과 좌표가 달라야 합니다(같으면 대기자가 점유자 자리로 갑니다). 대기줄은 세 구역 모두 -y 방향입니다.
- **같은 구역의 로봇은 모두 같은 대기열 방식으로 맞추세요.** 이전 세대(`v2-final` 태그)와 섞으면 두 대가 동시에 구역에 들어갈 수 있습니다.
- `robot_id`는 `zone_params.yaml`의 `robot_ids`와 같아야 합니다.

### 경로와 규칙

| 로봇 | - | goto 홈 |
|---|---|---|
| pinky1 | - | `I1` (0, 0) |
| pinky2 | - | `I2` (0, -0.2) |
| pinky3 | - | `I3` (0, -0.4) |

- 위험구역은 **3개(`A`, `B`, `C`)** 이고 구역마다 토큰(락)·대기열이 따로입니다. 구역 소속 지점은 `config/pinkyN.yaml` 의 `zone_points` 로 정하며 현재 A = `ZA`, B = `ZB`, C = `ZC` 입니다 (`P1`~`P50` 은 모두 구역 밖 일반 지점).
- 구역 대기 앵커(`queue_anchor`) 뒤쪽 대기 슬롯(`queue_back_dir`: 세 구역 모두 -y, 슬롯이 맵 안에 있어야 Nav2 가 받아들입니다)과 pinky1~3 의 구역 지점·일반 지점 좌표는 같은 값이며 실측 확인이 남아 있습니다. 확인 전에는 구역 지점으로 이동하지 마세요. A·B 가 같은 대기 위치를 쓰므로 A 대기자와 B 대기자가 동시에 생기면 같은 슬롯으로 가 충돌할 수 있고, A·B 슬롯 2 가 홈 I1 과 같은 자리이고 C 슬롯 1 이 ZC_EXIT 와 0.4 m 인 점도 현장에서 확인해야 합니다.

### 명령과 동작 (지점 단위 독립 이동)

| 명령 | 동작 |
|---|---|
| `goto:<P>[,<P>...]` | **구역 밖** 일반 지점(`P1`~`P50` 중 YAML 에 있는 것. `P1`·`P2` 필수, `P3`~`P50` 선택. **현재 P11~P50 은 모두 (0,0,0) 임시값이라 goto 하면 원점으로 갑니다**)과 자기 홈(`I<n>`)만 순서대로 이동. 도착 후 홈으로 가지 않고 대기. 구역 지점을 주면 `FAILED: use zone`, W*/Z*_EXIT 는 `not allowed` |
| `zone:<P>` | 구역 지점 **1개**로 이동. 매니저 응답(허가/대기 슬롯)을 받은 뒤 토큰(`request_entry` → `grant_entry`)을 받은 **뒤에만** 출발하고, 도착 후 토큰을 **유지**(`HOLDING_ZONE`) |
| `leave` | 보유 중인 구역의 `EXIT` 로 이동해 **도착한 뒤에** 토큰 반납. 보유 구역이 없으면 `FAILED: no zone held` |
| `home` | 초기 위치(`I<n>`)로 복귀. 구역 안이면 `EXIT` 에서 토큰을 반납한 뒤 이동합니다. 이미 홈이면 이동 없이 `DONE` (유휴 복귀와 같은 절차를 즉시 실행) |
| `stop` | 현재 작업 중단. 구역 안이면 `EXIT` 로 나와 락 반납. 작업 중이 아니면 상태 발행 없이 경고 로그만 남기고 무시 |
| `emergency_stop` | 그 자리 정지 + 락 유지(`max_hold_sec` 후 매니저가 강제 해제). 작업 중이 아니면 `stop` 과 같이 무시. 노드는 구역을 쥔 것으로 기억하지 않아 다음 `zone` 이 토큰을 다시 요청 |
| `start` | 비활성 (`FAILED: start disabled`) |

- 같은 구역 `zone` 재명령은 토큰을 다시 요청하지 않고 바로 이동합니다. 다른 구역 `zone` 이나 `goto` 는 먼저 **현재 구역 `EXIT` 에 도착해 토큰을 반납한 뒤** 출발합니다 (한 번에 한 구역 토큰만 쥐므로 교착이 없습니다).
- `EXIT` 에 도달하지 못하면 토큰을 반납하지 않고 `FAILED` 로 응답합니다(`max_hold_sec` 뒤 매니저가 해제). 다시 `leave` 로 재시도할 수 있습니다.
- **자동 홈 복귀는 없습니다.** 마지막 명령을 마친 뒤 `idle_return_sec`(`config/pinkyN.yaml`, 기본 `120.0`초, 0 이하이면 끔) 동안 새 명령이 없을 때만 홈으로 복귀합니다. 구역 안이면 `EXIT` 반납 후 홈으로 갑니다. 새 명령이 오면 타이머가 취소되고, `stop`/실패 뒤에는 타이머를 걸지 않습니다.
- 상태 토픽(`patrol_status`): `HOLDING_ZONE`(detail = 구역), `IDLE_WAIT`(detail = 복귀까지 초)가 추가되었습니다. 작업 중에 온 `goto` / `zone` / `leave` / `home` 은 상태 발행 없이 경고 로그만 남기고 무시됩니다 (`stop` / `emergency_stop` 만 작업 중에 받아들여집니다).
- `max_hold_sec`(`zone_params.yaml`, 240초)는 유휴 복귀 120초와 `EXIT` 이동 시간보다 길어야 합니다.
- `package.xml` 에는 아직 의존성(`cobot_zone_traffic_control`, `nav2_simple_commander`, `pinky_interfaces`)과 description / license 가 선언되어 있지 않습니다. 자세한 내용은 [cobot_navigation README 의 "알려진 제약"](../README.md#알려진-제약)을 봅니다.

## 설치 방법

로봇에는 Nav2, `pinky_interfaces`(`SetLed`), `pinky_led`가 이미 있어야 합니다 (이 저장소에 없음). 환경: Ubuntu 24.04, ROS 2 `jazzy`.

```bash
# 로봇 (저장소 루트에서)
git clone https://github.com/kernel-robot-8th/kernel-robot-repo-4.git
cd kernel-robot-repo-4
git checkout feature/navigation   # 주행 담당 작업 브랜치
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_zone_traffic_control cobot_pinky_patrol
source install/setup.bash
```

관제 PC는 `colcon build --packages-select cobot_zone_traffic_control cobot_domain_bridge` 후 `source install/setup.bash` 합니다.

## 실행 방법

각 터미널에서 `source /opt/ros/jazzy/setup.bash && source install/setup.bash`를 먼저 합니다.

1. **로봇**: Nav2 bringup 실행
2. **관제 PC**: 도메인 브릿지
   ```bash
   export ROS_DOMAIN_ID=100
   ros2 launch cobot_domain_bridge bridges.launch.xml
   ```
3. **관제 PC**: zone_manager (새 터미널)
   ```bash
   export ROS_DOMAIN_ID=100
   ros2 launch cobot_zone_traffic_control zone_manager.launch.xml
   ```
4. **각 로봇**: 순찰 노드
   좌표·홈 지점은 `config/pinkyN.yaml` 에서 읽으므로 **launch 로 실행**합니다. (YAML 없이 `ros2 run` 만 하면 필수 지점이 비어 노드가 시작을 거부합니다. `ros2 run` 을 쓰려면 `--ros-args --params-file <config/pinkyN.yaml>` 를 붙입니다.)
   ```bash
   # pinky1
   export ROS_DOMAIN_ID=10
   ros2 launch cobot_pinky_patrol pinky1_patrol.launch.xml

   # pinky2
   export ROS_DOMAIN_ID=20
   ros2 launch cobot_pinky_patrol pinky2_patrol.launch.xml

   # pinky3 (홈 I3 = (0, -0.4))
   export ROS_DOMAIN_ID=30
   ros2 launch cobot_pinky_patrol pinky3_patrol.launch.xml
   ```

## 사용 예시

관제 PC(워크스페이스 최상위)에서 `ROS_DOMAIN_ID=100`으로 실행합니다.

```bash
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 monitor          # 상태 출력 (별도 터미널, Ctrl+C 종료)
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 start            # (비활성) FAILED: start disabled 응답
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 goto P1 P2        # 구역 밖 지점 이동 (홈으로 가지 않음, idle_return_sec 후 복귀)
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 zone ZA          # 구역 A 지점: 토큰 받고 이동, 토큰 유지
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 leave            # 구역 EXIT 로 나가 토큰 반납
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 home             # 초기 위치로 복귀
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 stop             # 중지

# 대기열 확인: 두 로봇에 같은 구역 zone 을 거의 동시에 보내면 늦은 쪽이 QUEUEING으로 대기
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 zone ZA
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky2 zone ZA
ros2 topic echo /zone_manager/status      # <구역>:free | <구역>:occupied_by:<robot_id>
# 로봇 한 대로 대기열을 시험하려면 가짜 robot_id 로 구역을 먼저 잡는다: ../cobot_zone_traffic_control/README.md 의 "구역 수동 점유 / 해제"
```

테스트(가짜 navigator + 실제 매니저, 격리 도메인에서만 통합 테스트 실행). `src/cobot_navigation` 폴더에서 실행합니다.

```bash
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest cobot_pinky_patrol/test/test_patrol_queue.py -q
```

## 환경변수

| 변수 | 값 | 설명 |
|---|---|---|
| `ROS_DOMAIN_ID` | 관제 PC `100`, pinky1 `10`, pinky2 `20`, pinky3 `30` | 장비별 도메인 (도메인 간 중계는 `domain_bridge`) |
| `ROS_DOMAIN_ID=77` + `ROS_LOCALHOST_ONLY=1` | 시험용 | 통합 테스트 전용 격리 값 (아니면 통합 테스트 skip) |
| `RMW_IMPLEMENTATION`, `CYCLONEDDS_URI`, `ROS_AUTOMATIC_DISCOVERY_RANGE` | `rmw_cyclonedds_cpp`, `file:///home/pinky/.ros/cyclonedds_robot.xml`, `SUBNET` | 로봇 DDS 설정. 웹 GUI가 SSH로 켤 때 주입 (직접 실행 시 로봇 터미널 값 사용) |

노드 파라미터 `robot_id`(기본: pinky1 노드 `pinky1`, pinky2 노드 `pinky2`, pinky3 노드 `pinky3`)는 환경변수가 아닙니다. 재시도 횟수는 노드 파일의 클래스 상수(`NAV_RETRIES`)라 코드를 수정해야 바뀝니다. 유휴 복귀 시간 `idle_return_sec` 은 YAML 파라미터입니다. **지점 좌표와 홈 지점(`home_name`)은 `config/pinkyN.yaml` 의 파라미터**이며, 맵이 바뀌면 이 YAML 만 고치면 됩니다(좌표는 `[x, y]` 또는 `[x, y, yaw]`, m·rad, 소수점으로 작성). 값이 빠지거나 형식이 틀리면 노드가 오류 로그를 남기고 시작하지 않습니다. `W<구역>` 는 `cobot_zone_traffic_control/config/zone_params.yaml` 의 `zone_<구역>.queue_anchor` 와 같아야 합니다(테스트가 검사). 구역 이름(`zone_names`)과 소속 지점(`zone_points`)도 이 YAML 의 파라미터이며, 값이 빠지거나 소속이 모순(중복 소속·홈이 구역 안 등)이면 노드가 시작을 거부합니다.

## 위치 재설정 (`pinky_pose_recovery_node`)

충돌로 라이다 위치가 틀어졌거나 AMCL이 위치를 잡지 못할 때 씁니다. **사람이 로봇을 waypoint 좌표에 놓고 그 이름을 보내면**, 노드가 그 좌표로 AMCL 초기 위치(`/initialpose`)를 다시 잡고 제자리 스캔으로 방향을 맞춥니다. 자동으로 동작하지 않고, 이 명령을 받을 때만 동작합니다. patrol 노드와 별개로 로봇마다 하나씩 띄웁니다. 설계는 [`docs/prd/[진행] pose_reset_by_waypoint_prd.md`](docs/prd/)를 봅니다.

### 사용 방법
1. **patrol 이동이 멈춘 것을 확인**하고, 로봇 주변에 장애물이 없는지 봅니다. 스캔 중에 로봇이 제자리에서 돌며, 노드는 patrol 상태를 검사하지 않습니다.
2. 로봇을 지정 waypoint 좌표에 놓고, 그 waypoint 의 yaw 방향을 대략 보게 합니다.
3. 노드 실행 (로봇에서, `robot` 은 필수 — 다른 로봇의 좌표로 조용히 동작하지 않게 기본값이 없습니다)

   ~~~bash
   export ROS_DOMAIN_ID=20     # pinky1=10, pinky2=20, pinky3=30
   ros2 launch cobot_pinky_patrol pose_recovery.launch.xml robot:=pinky2
   ~~~

4. 명령 전송 (waypoint 이름은 `config/pinkyN.yaml` 의 `points` 에 있는 것, 대소문자 무시)

   ~~~bash
   ros2 topic pub --once /pose_reset_cmd std_msgs/msg/String "{data: 'P3'}"
   ~~~

5. 결과 확인

   ~~~bash
   ros2 topic echo /pose_recovery_status      # CONVERGED 면 완료
   ros2 topic echo /amcl_pose --once          # 위치가 waypoint 근처인지
   ~~~

   `FAILED` 면 RViz 의 2D Pose Estimate 로 직접 지정합니다.

### 동작 순서
| 단계 | 동작 | 상태 |
|---|---|---|
| 검증 | 이름이 `points` 에 있는지, 다른 재설정이 동작 중인지 확인. 아니면 로봇을 움직이지 않고 종료 | `FAILED` |
| 위치 지정 | `/initialpose` 구독자(AMCL)를 `reset_amcl_wait_sec` 까지 기다린 뒤 waypoint `(x, y, yaw)` 를 `initialpose_repeat` 번 발행 | `RESETTING` |
| 1차 수렴 확인 | `converge_timeout_sec` 동안 `/amcl_pose` 공분산이 `max_cov_xy`·`max_cov_yaw` 이하가 되는지 확인. 되면 끝 | `CONVERGED` |
| 좌우 스캔 | 수렴하지 않으면 왼쪽 `scan_half_angle_rad` → 오른쪽 `2×` → 정면 복귀 순으로 `scan_angular_speed` 로 회전. **회전량은 오도메트리(`odom`)로 재고, 수렴하는 즉시 정지** | `SCANNING_LR` |
| 한 바퀴 스캔 | 좌우로도 안 되면 `scan_full_turn_fallback: true` 일 때 오도메트리 기준 한 바퀴(2π) 회전 | `SCANNING` |
| 실패 | 그래도 수렴하지 않으면 정지하고 알림 | `FAILED` |

- 상태 토픽: `pose_recovery_status`(String JSON `{"state": ..., "detail": ...}`) — `RESETTING` `SCANNING_LR` `SCANNING` `CONVERGED` `FAILED`
- `FAILED` 의 detail: `unknown waypoint` `busy`(이미 동작 중) `points_file: ...` `no amcl` `no odom` `odom lost` `scan timeout` `not converged`
- **안전 감시**: odom 이 없으면 회전을 시작하지 않고, 스캔 중 odom 이 `scan_odom_stale_sec` 이상 끊기거나 한 구간이 계획 시간×`scan_timeout_factor` 안에 목표 각도에 닿지 못하면(바퀴 걸림 등) 즉시 정지하고 `FAILED` 로 끝납니다 (이 경우는 한 바퀴 스캔을 하지 않음)
- 종료(Ctrl+C·SIGTERM)나 예외에도 회전 중이었다면 `cmd_vel` 0 을 내고 멈춥니다
- 재설정은 한 번에 하나만 동작합니다

### 주요 파라미터 (`config/pose_recovery.yaml`)
| 이름 | 기본 | 설명 |
|---|---|---|
| `points_file` | launch 의 `robot` 이 정함 | waypoint 를 읽을 `config/pinkyN.yaml`. 명령을 받을 때마다 읽으므로 좌표를 고쳐도 노드를 다시 켤 필요가 없음 |
| `reset_topic` | `pose_reset_cmd` | 명령 토픽 |
| `initial_cov_xy`, `initial_cov_yaw` | 0.25, 0.3 | `/initialpose` 로 보낼 분산. 놓은 위치·방향이 부정확하면 키움 |
| `max_cov_xy`, `max_cov_yaw` | 0.05, 0.1 | 수렴 기준 |
| `scan_angular_speed`, `scan_half_angle_rad` | 0.3 rad/s, 1.5 rad | 스캔 속도와 한쪽 각도(약 86°). 벽에 가까운 waypoint 에서는 줄임 |
| `odom_topic` | `odom` | 회전량을 재는 오도메트리 |
| `scan_angle_tolerance_rad`, `scan_odom_stale_sec`, `scan_timeout_factor` | 0.05, 1.0, 2.0 | 도달 허용 오차, odom 끊김 허용 시간, 구간 시간 초과 배수. **추정치이며 실기에서 확인해 조정** |

값은 소수점이 필요한 항목은 `0.0` 형태로 씁니다. 스캔 파라미터가 잘못되면(0 이하, 허용 오차가 반각 이상 등) 노드가 시작하지 않습니다.

### 한계와 주의
- patrol 이동 중에 쓰지 마세요. 스캔이 `cmd_vel` 을 직접 냅니다.
- odom 이 끊긴 순간부터 정지 판단까지는 회전 명령이 계속 나갑니다 (기본 속도에서 최대 약 0.3 rad). 줄이려면 `scan_odom_stale_sec` 을 낮춥니다.
- 오도메트리는 바퀴 미끄러짐 오차가 있을 수 있어, 구간 시간 초과 감시를 함께 둡니다.
- 관제 PC(도메인 100)에서 보내려면 `domain_bridge` 에 `/pinkyN/pose_reset_cmd` 항목이 필요하며, 아직 없습니다 (후속 작업). 지금은 로봇에서 직접 보냅니다.
- patrol 노드의 `~/.pinky_last_pose.json` 복원(`restore_last_pose`)과는 별개이며 코드도 분리되어 있습니다.

## 프로젝트 구조

```
cobot_pinky_patrol/
├── README.md, package.xml, setup.py, setup.cfg
├── config/pinky{1,2,3}.yaml                # 로봇별 지점 좌표·home_name 파라미터
├── config/pose_recovery.yaml               # 위치 재설정 노드 파라미터
├── launch/pinky{1,2,3}_patrol.launch.xml  # 노드 + 좌표 YAML 실행
├── launch/pose_recovery.launch.xml         # 위치 재설정 노드 실행 (robot:=pinkyN 필수)
├── PinkyPatrolNode.html                    # 순찰 노드 흐름도
├── docs/pinky_patrol_flow.svg              # 시스템 구성도
├── docs/prd/                               # 위험구역 대기열 단계별 PRD, 위치 재설정 PRD
├── test/test_patrol_queue.py            # 대기열 진입 테스트
├── test/test_patrol_commands.py         # 명령 처리 테스트
├── test/test_patrol_points_utils.py     # 좌표 파싱·검증 단위 테스트
├── test/test_pose_recovery_utils.py     # 위치 재설정 판정·스캔 계획 단위 테스트
└── cobot_pinky_patrol/
    ├── patrol_points_utils.py              # 좌표 파싱·검증 (ROS 비의존)
    ├── pose_recovery_utils.py              # 위치 재설정 판정·waypoint 읽기·스캔 계획 (ROS 비의존)
    ├── pinky_pose_recovery_node.py         # 위치 재설정 노드
    └── pinky_patrol_node_pinky{1,2,3}.py   # 대기열 방식 순찰 노드
```
