# pinky_fleet_sim (3D Gazebo Simulation Package)

팀 신발 매장 아레나와 핑키 로봇을 Gazebo Sim(Ignition/Harmonic) 상에서 3D로 시뮬레이션하는 선택형(Optional) 정밀 시뮬레이터입니다.

## 1. 시뮬레이터 2-Track 선택 가이드
* **경량 표준 시뮬레이터 (`cobot_simulation`) [팀 기본 권장]**:
  * FMS, Web GUI, 자율주행 알고리즘 결합 테스트용 (1초 빌드, 저부하, 순수 ROS 2 Jazzy)
  * 실행: `ros2 launch cobot_simulation bringup_sim.launch.py`
* **3D 가제보 시뮬레이터 (`pinky_fleet_sim`) [정밀 3D 선택]**:
  * 3D 시각화, 라이다 광선 충돌, 센서 노이즈 검증용 (Gazebo Sim 필요)
  * 실행: `ros2 launch pinky_fleet_sim gz_fleet.launch.xml`

## 2. 필수 의존성 설치 (Ubuntu 24.04 / ROS 2 Jazzy)
```bash
sudo apt update && sudo apt install -y \
  ros-jazzy-ros-gz \
  ros-jazzy-ros-gz-sim \
  ros-jazzy-ros-gz-bridge \
  ros-jazzy-xacro \
  ros-jazzy-joint-state-publisher \
  ros-jazzy-robot-state-publisher
```

## 3. 빌드 및 실행
```bash
# 가제보 패키지만 선택 빌드
colcon build --packages-select pinky_fleet_sim
source install/setup.bash

# 3D 가제보 아레나 및 핑키 기동
ros2 launch pinky_fleet_sim gz_fleet.launch.xml
```
