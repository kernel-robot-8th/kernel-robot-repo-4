# cobot_simulation

신발 매장(PRD_3) 2.5m × 2.4m 아레나와 이동 로봇 3대, 5축 다관절 로봇팔 3대를 시뮬레이션하는 **경량 통합 ROS 2 Jazzy 시뮬레이션 패키지**입니다.

## 🚀 주요 특징
- **인공신경망/대용량 가중치(PyTorch/LeRobot/CUDA) 완전 배제**: 일반 노트북 및 CI 환경에서도 1초 만에 빌드 및 즉시 실행
- **공식 맵 규격 정합**: `map_shoe_store_1021_gate67.yaml` (2.5m × 2.4m, 67cm 중앙 통과 게이트, 8개 정본 웨이포인트) 100% 반영
- **다중 로봇 플릿 지원**:
  - Pinky 1~3호기: 차동 구동 기구학, 360° 2D 라이다 레이캐스팅(`LaserScan`), 오도메트리(`Odometry`), TF 브로드캐스팅(`map` $\to$ `odom` $\to$ `base_footprint`), 폐루프 웨이포인트 자율주행
  - OpenManipulator-X 1~3호기: 5-DOF + 그리퍼 관절, Temporal Ensembling($\alpha=0.01$) 관절 제어 스무딩, 표준 픽앤플레이스(Z=200mm 수직 상승) 시퀀스

## 📦 빌드 및 실행
```bash
# 워크스페이스 빌드
colcon build --packages-select cobot_interfaces cobot_simulation
source install/setup.bash

# 시뮬레이션 실행 (기본 3대 핑키 + 3대 로봇팔 기동)
ros2 launch cobot_simulation bringup_sim.launch.py
# 또는 XML launch
ros2 launch cobot_simulation bringup_sim.launch.xml

# 단위 테스트 실행
pytest src/cobot_simulation/test/test_sim_smoke.py -v
```

## 📡 주요 토픽 명세
- `/{pinky1..3}/odom`: `nav_msgs/msg/Odometry`
- `/{pinky1..3}/scan`: `sensor_msgs/msg/LaserScan`
- `/{pinky1..3}/cmd_vel`: `geometry_msgs/msg/Twist`
- `/{pinky1..3}/goal_pose`: `geometry_msgs/msg/PoseStamped`
- `/{pinky1..3}/robot_status`: `cobot_interfaces/msg/RobotStatus`
- `/{omx_1..3}/joint_states`: `sensor_msgs/msg/JointState`
- `/{omx_1..3}/arm_status`: `cobot_interfaces/msg/ArmStatus`
- `/tf`: `tf2_msgs/msg/TFMessage`
