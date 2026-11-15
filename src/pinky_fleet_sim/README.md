# pinky_fleet_sim (3D Gazebo Simulation Package)

팀 신발 매장 아레나와 핑키 로봇을 Gazebo Sim(Ignition/Harmonic) 상에서 3D로 시뮬레이션하는 선택형(Optional) 정밀 시뮬레이터 패키지입니다.

## 1. 시뮬레이터 2-Track 선택 가이드
* **경량 표준 시뮬레이터 (`cobot_simulation`) [팀 기본 권장 / SSOT]**:
  * FMS, Web GUI, 자율주행 알고리즘 결합 테스트용 (1초 빌드, 저부하, 순수 ROS 2 Jazzy)
  * 컨플루언스 SR_v2 정본 명세 100% 준수: 핑키 3대 + OpenManipulator-X 3대 + 67cm 통로
  * 실행: `ros2 launch cobot_simulation bringup_sim.launch.py`
* **3D 가제보 시뮬레이터 (`pinky_fleet_sim`) [정밀 3D 센서 시각화]**:
  * 3D 시각화, 라이다 광선 충돌, 센서 노이즈 검증용 (Gazebo Sim 환경)
  * 로봇 외형 메시(`pinky_description`) 및 가제보 리소스(`pinky_gz_sim`) 내장 완료
  * 실행: `ros2 launch pinky_fleet_sim gz_world.launch.xml` 또는 `ros2 launch pinky_fleet_sim gz_spawn.launch.xml`

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

## 3. 빌드 및 단계별 실행
```bash
# 가제보 및 로봇 3D 외형 패키지 일괄 빌드
colcon build --packages-select pinky_description pinky_gz_sim pinky_fleet_sim
source install/setup.bash

# 1단계: 3D 가제보 아레나 월드 기동
ros2 launch pinky_fleet_sim gz_world.launch.xml

# 2단계: 핑키 로봇 3D 모델 및 센서 브리지 스폰 (다른 터미널)
ros2 launch pinky_fleet_sim gz_spawn.launch.xml namespace:=pinky1 x:=0.0 y:=0.0
```
