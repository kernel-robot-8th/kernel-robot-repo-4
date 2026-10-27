# cobot_pinky_patrol

Pinky 로봇에서 실행하는 Nav2 순찰 노드 패키지. (`pinky_patrol_node_pinky1`, `pinky_patrol_node_pinky2`, `pinky_patrol_node_pinky3`)는 위험 구역에 **한 대만** 들어가도록 `cobot_zone_traffic_control`의 대기열 슬롯 방식과 연동합니다.

## 주요 기능

- **명령 수신**: `patrol_cmd`(String)로 `stop` / `goto:<P>[,<P>,...]`. `start`(전체 순회)는 v1.1.0 에서 **비활성**이며 받으면 `FAILED`(detail `start disabled`)로 응답합니다 (순회 코드는 노드 파일에 주석으로 보관)
- **상태 발행**: `patrol_status`에 JSON 발행 — `{"state": "MOVING", "waypoint": 2, "detail": "ZB", "time": ...}`
  `IDLE` `STARTING` `MOVING` `QUEUEING` `WAITING_ZONE` `ARRIVED` `LEAVING_ZONE` `RETURNING` `DONE` `STOPPED` `FAILED` `RETRY`
- **대기열 진입**: 구역 진입 전에 먼저 요청을 보냅니다.
  - 구역이 비어 있으면 바로 허가를 받아 목적지로 직행
  - 점유 중이면 매니저가 준 슬롯으로 이동해 `QUEUEING` 대기, 슬롯이 바뀌면 새 슬롯으로 재이동
  - 대기열이 가득 차면 `FAILED`(`queue_full`), `stop`/이동 실패 시 대기열에서 빠지고 허가를 받았다면 락 반납
- **위치 복원**: 마지막 위치를 `~/.pinky_last_pose.json`에 저장하고, 노드 실행 후 첫 작업에서만 AMCL 초기 위치로 보낸 뒤 제자리 회전으로 방향 보정
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

- 로봇 코드에는 슬롯 좌표가 없습니다. 구역마다 진입 앵커 `W<구역>`와 출구 `Z<구역>_EXIT`만 있고(좌표는 `config/pinkyN.yaml`), 슬롯은 매니저가 구역별 `queue_anchor` 로 계산해 `queue_slot`으로 줍니다. 앵커(대기 위치) / 출구는 구역 A `(0.0, 0.6, 0.7)` / `(0.5, 0.0, 0.7)`, 구역 B `(0.0, 0.6, 0.7)`(A 와 같은 대기 위치) / `(0.55, -0.6, 0.7)`, 구역 C `(-0.7, -0.08, 0.7)` / `(-0.3, -0.4, 0.7)` 입니다 (2026-10-27 확정). 앵커는 구역 소속 지점과 좌표가 달라야 합니다(같으면 대기자가 점유자 자리로 갑니다). 대기줄은 세 구역 모두 +y 방향입니다.
- **같은 구역의 로봇은 모두 같은 대기열 방식으로 맞추세요.** 이전 세대(`v2-final` 태그)와 섞으면 두 대가 동시에 구역에 들어갈 수 있습니다.
- `robot_id`는 `zone_params.yaml`의 `robot_ids`와 같아야 합니다.

### 경로와 규칙

| 로봇 | `start` 경로 (v1.1.0 비활성, 주석 보관) | goto 홈 |
|---|---|---|
| pinky1 | (구역 2개 이전 순회 경로, 주석 보관) | `I1` (0, 0) |
| pinky2 | (구역 2개 이전 순회 경로, 주석 보관) | `I2` (0, -0.2) |
| pinky3 | (구역 2개 이전 순회 경로, 주석 보관) | `I3` (0, -0.4) |

- 위험구역은 **3개(`A`, `B`, `C`)** 이고 구역마다 토큰(락)·대기열이 따로입니다. 구역 소속 지점은 `config/pinkyN.yaml` 의 `zone_points` 로 정하며 현재 A = `ZA`, B = `ZB`, C = `ZC` 입니다 (`P1` `P5` `P6` `P7` 은 구역 밖).
- 구역 대기 위치(W*) 뒤쪽 대기 슬롯(`queue_back_dir`: 세 구역 모두 +y)과 pinky1~3 의 구역 지점·일반 지점 좌표는 같은 값이며 실측 확인이 남아 있습니다. 확인 전에는 구역 지점으로 이동하지 마세요. A·B 가 같은 대기 위치를 쓰므로 A 대기자와 B 대기자가 동시에 생기면 같은 슬롯으로 가 충돌할 수 있고, 구역 C 슬롯 1 이 ZC 와 약 0.2 m 인 점도 현장에서 확인해야 합니다.

### 명령과 동작 (지점 단위 독립 이동)

| 명령 | 동작 |
|---|---|
| `goto:<P>[,<P>...]` | **구역 밖** 일반 지점(`P1`~`P10` 중 YAML 에 있는 것. `P1`·`P2` 필수, `P3`~`P10` 선택. **현재 P1~P10 은 모두 (0,0,0) 자리표시자라 goto 하면 원점으로 갑니다**)과 자기 홈(`I<n>`)만 순서대로 이동. 도착 후 홈으로 가지 않고 대기. 구역 지점을 주면 `FAILED: use zone`, W*/Z*_EXIT 는 `not allowed` |
| `zone:<P>` | 구역 지점 **1개**로 이동. 구역 대기 위치(`W*`)에서 토큰(`request_entry` → `grant_entry`)을 받은 **뒤에만** 출발하고, 도착 후 토큰을 **유지**(`HOLDING_ZONE`) |
| `leave` | 보유 중인 구역의 `EXIT` 로 이동해 **도착한 뒤에** 토큰 반납. 보유 구역이 없으면 `FAILED: no zone held` |
| `stop` | 현재 작업 중단. 구역 안이면 `EXIT` 로 나와 락 반납 |
| `emergency_stop` | 그 자리 정지 + 락 유지(`max_hold_sec` 후 매니저가 강제 해제). 노드는 구역을 쥔 것으로 기억하지 않아 다음 `zone` 이 토큰을 다시 요청 |
| `start` | 비활성 (`FAILED: start disabled`) |

- 같은 구역 `zone` 재명령은 토큰을 다시 요청하지 않고 바로 이동합니다. 다른 구역 `zone` 이나 `goto` 는 먼저 **현재 구역 `EXIT` 에 도착해 토큰을 반납한 뒤** 출발합니다 (한 번에 한 구역 토큰만 쥐므로 교착이 없습니다).
- `EXIT` 에 도달하지 못하면 토큰을 반납하지 않고 `FAILED` 로 응답합니다(`max_hold_sec` 뒤 매니저가 해제). 다시 `leave` 로 재시도할 수 있습니다.
- **자동 홈 복귀는 없습니다.** 마지막 명령을 마친 뒤 `idle_return_sec`(`config/pinkyN.yaml`, 기본 `120.0`초, 0 이하이면 끔) 동안 새 명령이 없을 때만 홈으로 복귀합니다. 구역 안이면 `EXIT` 반납 후 홈으로 갑니다. 새 명령이 오면 타이머가 취소되고, `stop`/실패 뒤에는 타이머를 걸지 않습니다.
- 상태 토픽(`patrol_status`): `HOLDING_ZONE`(detail = 구역), `IDLE_WAIT`(detail = 복귀까지 초)가 추가되었습니다. 작업 중 온 명령은 무시됩니다.
- `max_hold_sec`(`zone_params.yaml`, 240초)는 유휴 복귀 120초와 `EXIT` 이동 시간보다 길어야 합니다.

## 설치 방법

로봇에는 Nav2, `pinky_interfaces`(`SetLed`), `pinky_led`가 이미 있어야 합니다 (이 저장소에 없음). 환경: Ubuntu 24.04, ROS 2 `jazzy`.

```bash
# 로봇 (저장소 루트에서)
git clone https://github.com/cdwlsgh1-source/pinky_slam_nav.git
cd pinky_slam_nav
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
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 stop             # 중지

# 대기열 확인: 두 로봇에 같은 구역 zone 을 거의 동시에 보내면 늦은 쪽이 QUEUEING으로 대기
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky1 zone ZA
python3 src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py pinky2 zone ZA
ros2 topic echo /zone_manager/status      # <구역>:free | <구역>:occupied_by:<robot_id>
# 로봇 한 대로 대기열을 시험하려면 가짜 robot_id 로 구역을 먼저 잡는다: ../cobot_zone_traffic_control/README.md 의 "구역 수동 점유 / 해제"
```

테스트(가짜 navigator + 실제 매니저, 격리 도메인에서만 통합 테스트 실행). 이 문서 작성 환경에는 ROS가 없어 실행해 보지 못했습니다.

```bash
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest cobot_pinky_patrol/test/test_patrol_queue.py -q
```

## 환경변수

| 변수 | 값 | 설명 |
|---|---|---|
| `ROS_DOMAIN_ID` | 관제 PC `100`, pinky1 `10`, pinky2 `20`, pinky3 `30` | 장비별 도메인 (도메인 간 중계는 `domain_bridge`) |
| `ROS_DOMAIN_ID=77` + `ROS_LOCALHOST_ONLY=1` | 시험용 | 통합 테스트 전용 격리 값 (아니면 통합 테스트 skip) |
| `RMW_IMPLEMENTATION`, `CYCLONEDDS_URI`, `ROS_AUTOMATIC_DISCOVERY_RANGE` | `rmw_cyclonedds_cpp`, `file:///home/pinky/.ros/cyclonedds_robot.xml`, `SUBNET` | 로봇 DDS 설정. 웹 GUI가 SSH로 켤 때 주입 (직접 실행 시 로봇 터미널 값 사용) |

노드 파라미터 `robot_id`(기본: pinky1 노드 `pinky1`, pinky2 노드 `pinky2`)는 환경변수가 아닙니다. 재시도 횟수는 노드 파일의 클래스 상수(`NAV_RETRIES`)라 코드를 수정해야 바뀝니다. 유휴 복귀 시간 `idle_return_sec` 은 YAML 파라미터입니다. **지점 좌표와 홈 지점(`home_name`)은 `config/pinkyN.yaml` 의 파라미터**이며, 맵이 바뀌면 이 YAML 만 고치면 됩니다(좌표는 `[x, y]` 또는 `[x, y, yaw]`, m·rad, 소수점으로 작성). 값이 빠지거나 형식이 틀리면 노드가 오류 로그를 남기고 시작하지 않습니다. `W<구역>` 는 `cobot_zone_traffic_control/config/zone_params.yaml` 의 `zone_<구역>.queue_anchor` 와 같아야 합니다(테스트가 검사). 구역 이름(`zone_names`)과 소속 지점(`zone_points`)도 이 YAML 의 파라미터이며, 값이 빠지거나 소속이 모순(중복 소속·홈이 구역 안 등)이면 노드가 시작을 거부합니다.

## 프로젝트 구조

```
cobot_pinky_patrol/
├── README.md, package.xml, setup.py, setup.cfg
├── config/pinky{1,2,3}.yaml                # 로봇별 지점 좌표·home_name 파라미터
├── launch/pinky{1,2,3}_patrol.launch.xml  # 노드 + 좌표 YAML 실행
├── PinkyPatrolNode.html                    # 순찰 노드 흐름도
├── docs/prd/                               # 위험구역 대기열 단계별 PRD
├── test/test_patrol_queue.py            # 대기열 진입 테스트
├── test/test_patrol_points_utils.py     # 좌표 파싱·검증 단위 테스트
└── cobot_pinky_patrol/
    ├── patrol_points_utils.py              # 좌표 파싱·검증 (ROS 비의존)
    └── pinky_patrol_node_pinky{1,2,3}.py   # 대기열 방식 순찰 노드
```
