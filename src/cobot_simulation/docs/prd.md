# cobot_simulation PRD: 경량 전체 시뮬레이션 환경 (Lightweight Full Simulation)

> **문서 상태**: 공식 승인 배포안 (v0.1.0)  
> **기준 일시**: 2026-10-28 22:30 KST  
> **적용 브랜치**: `feature/cobot-simulation`  
> **핵심 원칙**: **무거운 인공신경망 학습(PyTorch/LeRobot/CUDA) 배제**, **순수 ROS 2 Jazzy & 경량 키네마틱스/MuJoCo 3.x 기반 고속 다중 로봇 시뮬레이션 환경 제공**

---

## 1. 개발 배경 및 목적

1. **기존 시뮬레이션의 한계 극복**:
   - 기존 매니퓰레이션 시뮬레이션 브랜치는 수 기가바이트(GB)에 달하는 LeRobot 0.4.4, PyTorch, 가중치 체크포인트 및 오프라인 BC 데이터셋에 강결합되어 일반 팀원이 자신의 PC나 CI 환경에서 실행하기 불가능했습니다.
2. **팀 전체를 위한 가상 아레나 통합 테스트베드 제공**:
   - 주행(Navigation), 관제(Control Center/FMS), 매니퓰레이터(Manipulation), 비전(Vision), 웹 GUI 팀원이 실물 로봇 없이도 즉시 전체 시스템을 결합 검증할 수 있는 단일 launch 환경을 제공합니다.
3. **공식 계약 및 도면 100% 준수**:
   - `map_shoe_store_1021_gate67.yaml` 맵 규격(2.5m × 2.4m, 67cm 중앙 게이트, 8대 정본 웨이포인트)과 100% 일치합니다.

---

## 2. 시뮬레이션 시스템 구성

### 2-1. 하드웨어 에이전트
- **Pinky 이동 로봇 3대 (`pinky1`, `pinky2`, `pinky3`)**:
  - 차동 구동(Differential Drive) 기구학 및 가감속 스무딩
  - 360° 2D 라이다 레이캐스팅 (`sensor_msgs/msg/LaserScan`)
  - 실시간 오도메트리 (`nav_msgs/msg/Odometry`) 및 TF 트리 브로드캐스팅 (`map` $\to$ `odom` $\to$ `base_footprint`)
  - `cmd_vel` 수동 주행 및 폐루프 웨이포인트 자율주행 모드 지원
- **OpenManipulator-X 5축 로봇팔 3대 (`omx_1`, `omx_2`, `omx_3`)**:
  - `omx_1`: 창고 1번 상차대 (`WP_LOAD_1`: X=2.015, Y=2.105)
  - `omx_2`: 창고 2번 상차대 (`WP_LOAD_2`: X=2.015, Y=1.5375)
  - `omx_3`: 매장 하차대 (`WP_UNLOAD`: X=0.415, Y=1.85)
  - 관절각 5-DOF + 2-jaw 그리퍼 JointState 발행
  - Temporal Ensembling ($\alpha=0.01\sim0.05$) 관절 모션 스무딩 및 표준 픽앤플레이스(Z=200mm 수직 상승) 시퀀스 내장

---

## 3. ROS 2 인터페이스 명세

### 3-1. 발행 토픽 (Publishers)
| 토픽명 | 메시지 타입 | 발행 주기 | 설명 |
| :--- | :--- | :---: | :--- |
| `/{ns}/odom` | `nav_msgs/msg/Odometry` | 50 Hz | 핑키 로봇별 위치 및 속도 오도메트리 |
| `/{ns}/scan` | `sensor_msgs/msg/LaserScan` | 50 Hz | 아레나 벽체 및 타 로봇 360° 2D 라이다 스캔 |
| `/{ns}/joint_states` | `sensor_msgs/msg/JointState` | 50 Hz | 핑키 좌/우 구동 휠 회전각 |
| `/{ns}/robot_status` | `cobot_interfaces/msg/RobotStatus` | 10 Hz | 배터리, 통신 상태, 현재 위치 |
| `/{arm_id}/joint_states` | `sensor_msgs/msg/JointState` | 50 Hz | 로봇팔 5개 관절 + 그리퍼 조인트 각도 |
| `/{arm_id}/arm_status` | `cobot_interfaces/msg/ArmStatus` | 10 Hz | 로봇팔 동작 중(busy), 화물 파지 여부 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 50 Hz | `map` $\to$ `pinky{N}/odom` $\to$ `pinky{N}/base_footprint`, `map` $\to$ `omx_{N}/base_link` |

### 3-2. 수신 토픽 (Subscribers)
| 토픽명 | 메시지 타입 | 설명 |
| :--- | :--- | :--- |
| `/{ns}/cmd_vel` | `geometry_msgs/msg/Twist` | 핑키 속도 제어 명령 (선속도 최대 0.25 m/s, 각속도 최대 1.2 rad/s) |
| `/{ns}/goal_pose` | `geometry_msgs/msg/PoseStamped` | 핑키 목표 목적지 좌표 (자율 폐루프 제어로 즉시 이동) |
| `/fms/fleet_command` | `cobot_interfaces/msg/FleetCommand` | FMS 고레벨 웨이포인트 지시 (`WP_LOAD_1`, `WP_GATE_TRANSIT` 등) |
| `/fms/string_command` | `std_msgs/msg/String` | 문자열 기반 빠른 디스패치 (`goto:pinky1,WP_LOAD_1`) |
| `/{arm_id}/arm_command` | `cobot_interfaces/msg/ArmCommand` | 로봇팔 상차/하차 트리거 (`action="pick"`) |

---

## 4. 팀 역할별 활용 가이드

1. **주행 담당 (Navigation)**:
   - `/{ns}/scan`과 `/{ns}/odom` 및 TF 트리를 입력받아 Nav2 경로 계획 및 67cm 좁은 게이트 통과 알고리즘을 즉시 검증할 수 있습니다.
2. **관제 코어 담당 (Control Center / FMS)**:
   - 3대 로봇의 동시 주문 할당, 충돌 방지 차간거리(0.65m), 게이트 토큰 대기열 주행 시나리오를 가상 공간에서 실시간 테스트할 수 있습니다.
3. **매니퓰레이션 담당 (Manipulation)**:
   - Z=200mm 수평 상차 및 정밀 하차 시퀀스를 핑키 상차대 트레이 좌표와 정합하여 검증할 수 있습니다.
4. **웹 GUI 담당 (GUI)**:
   - Mosquitto 브로커와 연동하여 3대 로봇의 위치 좌표 및 팔 상태를 2D/3D 웹 대시보드에서 렌더링 검증할 수 있습니다.

---

## 5. 빌드 및 실행 방법

```bash
# 1. 빌드 (워크스페이스 루트)
colcon build --packages-select cobot_simulation cobot_interfaces

# 2. 환경 로드
source install/setup.bash

# 3. 전체 시뮬레이션 기동 (기본 3대 핑키 + 3대 로봇팔)
ros2 launch cobot_simulation bringup_sim.launch.py

# (선택) MuJoCo 네이티브 3D 뷰어 함께 실행
# pip install mujoco
python3 -c "import cobot_simulation.mujoco_runner as mr; mr.launch_mujoco_viewer()"
```
