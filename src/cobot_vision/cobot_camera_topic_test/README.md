# Pinky Pro 카메라 ROS 2 토픽 테스트

[pinklab-art/pinky_pro](https://github.com/pinklab-art/pinky_pro)와 그 저장소가 연결한 [공식 Pinky Pro 카메라 가이드](https://github.com/pinklab-art/pinky_study/wiki/2.1-Pinky-Pro%28part1%29)를 기준으로 한다. 코드 확인 기준은 `pinky_pro`의 `014a09f289e6988894fbffde2624fdb1e257815b`이다.

실물 카메라는 핑키에 제공된 `pinkylib.Camera`를 사용한다. 공식 가이드의 `Camera() → start() → get_frame() → close()`를 ROS 2 발행기로 감싼다. 카메라 드라이버와 `pinkylib`는 기존 핑키 환경을 사용한다. 이 패키지는 OpenCV·NumPy·cv_bridge 설치를 요구하지 않으며 `/dev/video0`을 직접 열지 않는다. `pinkylib` 내부 의존성은 제조사 환경에서 관리한다.

## 통신 구조

| 위치 | 실행 | 역할 |
|---|---|---|
| 핑키 | `camera_publisher`, `source:=pinky` | 기존 `pinkylib.Camera` 프레임을 토픽으로 발행 |
| 수신 PC | `camera_subscriber` | 이미지 크기·데이터 길이 검사, 수신 FPS·전송량 출력 |
| 수신 PC, 선택 | RViz2 | 수신 영상 표시 |

| 항목 | 값 |
|---|---|
| 패키지 | `cobot_camera_topic_test` |
| 토픽 | `/camera/image_raw` |
| 메시지 | `sensor_msgs/msg/Image` (압축하지 않은 원본 픽셀) |
| 기본 frame_id | `front_camera_link` |
| 발행기·수신기 QoS | `BEST_EFFORT`, `VOLATILE`, `KEEP_LAST`, depth 1 |
| 기본 발행 목표 | 10 FPS |
| 기본 실행 | 수신기만 실행. 카메라를 열려면 `publisher:=true` 지정 |

토픽·메시지·frame 이름은 `pinky_pro`의 [카메라 설정](https://github.com/pinklab-art/pinky_pro/blob/014a09f289e6988894fbffde2624fdb1e257815b/pinky_mujoco/config/mujoco.yaml)과 맞췄다. 실물 `bringup_robot.launch.xml`에는 카메라 발행기가 포함돼 있지 않아 이 어댑터를 별도로 실행한다. 이 패키지의 launch는 모터·Nav2·전체 bringup을 실행하지 않는다.

## 1. 준비와 빌드

### 핑키: 기존 ROS·카메라 환경 확인

Ubuntu 24.04 / ROS 2 Jazzy 기준이다. 핑키의 제조사 환경을 사용하는 터미널에서 확인한다. 아래 Python 명령은 클래스를 가져오기만 하며 카메라를 열지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
python3 -c 'from pinkylib import Camera; print(Camera.__module__)'
python3 -c 'import rclpy; from sensor_msgs.msg import Image'
command -v colcon
```

`pinkylib`를 찾지 못하면 제조사가 제공한 Python 환경을 먼저 확인한다. 임의의 `pinky`·`pinkylib` 패키지를 pip로 설치하거나 핑키의 카메라 라이브러리를 교체하지 않는다. PC에서 하드웨어 없이 시험할 때는 `source:=synthetic`을 쓴다.

### 수신 PC: ROS 2와 빌드 도구 준비

ROS 2 Jazzy가 이미 있으면 도구 설치부터 진행한다. ROS가 없는 Ubuntu 24.04 PC에서는 아래 명령으로 설치한다. 다른 Ubuntu 버전에 그대로 적용하지 않는다. [공식 설치 안내](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)를 기준으로 한다.

```bash
sudo apt update
sudo apt install -y locales curl software-properties-common python3
# UTF-8 locale이 없을 때만 실행
sudo locale-gen en_US.UTF-8
export LANG=en_US.UTF-8
sudo add-apt-repository -y universe
camera_ros_source_version=$(curl -fsSL \
  https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
curl -fL -o /tmp/camera-test-ros2-apt-source.deb \
  "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${camera_ros_source_version}/ros2-apt-source_${camera_ros_source_version}.noble_all.deb"
sudo dpkg -i /tmp/camera-test-ros2-apt-source.deb
sudo apt update
sudo apt install -y ros-jazzy-ros-base
```

수신 PC의 빌드·실행 도구:

```bash
sudo apt install -y git python3-colcon-common-extensions \
  ros-jazzy-rclpy ros-jazzy-sensor-msgs ros-jazzy-launch-ros ros-jazzy-launch-xml
# 영상 창이 필요한 수신 PC에서만 설치
sudo apt install -y ros-jazzy-rviz2
```

런타임 ROS 의존성은 `rclpy`, `sensor_msgs`, `launch_ros`, `launch_xml`이다. RViz2는 영상 표시를 선택할 때만 필요하다. 핑키에는 RViz2를 설치할 필요가 없다. 핑키에 Git·colcon이 없다면 기존 제조사 ROS 개발 환경을 확인하거나 필요한 도구만 준비한다.

### 양쪽: 테스트 패키지 받기와 빌드

기존 작업과 분리한 새 경로에서 실행한다. 예시 경로가 이미 있으면 다른 경로를 선택한다.

```bash
git clone --single-branch --branch feature/vision-camera-topic-besteffort \
  https://github.com/kernel-robot-8th/kernel-robot-repo-4.git ~/kernel-robot-camera-test
cd ~/kernel-robot-camera-test
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_camera_topic_test
source install/setup.bash
ros2 pkg executables cobot_camera_topic_test
```

이미 이 기능 브랜치를 사용 중이면 변경 파일을 정리한 뒤 `git pull --ff-only origin feature/vision-camera-topic-besteffort`로 갱신하고 다시 빌드한다. 다른 패키지를 함께 빌드하거나 기존 카메라 zip을 풀 필요가 없다.

새 터미널을 열 때마다 양쪽에서 먼저 실행한다.

```bash
cd ~/kernel-robot-camera-test
source /opt/ros/jazzy/setup.bash
source install/setup.bash
```

conda나 별도 Python을 쓰면 제조사 `pinkylib`와 ROS 모듈이 보이지 않을 수 있다. 핑키의 원래 Python 환경에서 실행한다.

## 2. 실제 핑키 카메라에서 발행하고 PC에서 수신

같은 네트워크와 ROS 도메인을 사용하는 별도 터미널에서 실행한다. 예시 도메인 100은 이 테스트 프로세스에만 적용하며 기존 로봇 설정 파일은 바꾸지 않는다. Jupyter 등에서 같은 카메라를 사용 중이면 해당 프로그램의 `cam.close()`를 먼저 호출한다.

핑키:

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  publisher:=true subscriber:=false source:=pinky fps:=5.0
```

수신 PC:

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml
```

영상 창을 보려면 PC의 마지막 명령에 `display:=true`를 추가한다. 이 옵션은 RViz2를 실행한다. SSH·화면 없는 환경에서는 기본값 `false`로 로그만 확인한다. 종료는 Ctrl+C이며 핑키 발행기는 `Camera.close()`로 자원을 반환한다.

수신 로그에서 `received`가 증가하고 `invalid=0`이면 메시지의 크기와 데이터 길이 검사를 통과한 것이다. 실제 색상·장면은 RViz2로 확인한다.

```text
received=..., fps=..., KiB/s=..., size=..., invalid=0
```

### FPS와 색상 설정

`fps:=5.0`은 발행 타이머를 0.2초로 만든다. `pinkylib`의 내부 센서 캡처 FPS를 바꾸는 옵션은 아니며, 처리 속도에 따라 실제 수신 FPS는 낮을 수 있다. 값을 바꾸려면 핑키 발행기를 재시작한다.

이미지는 `get_frame()`이 반환한 크기와 픽셀 순서 그대로 보낸다. `encoding`은 그 순서를 설명하는 ROS 메타데이터이며 픽셀을 변환하지 않는다. 기본값은 `bgr8`이다. 설치된 제조사 라이브러리가 RGB 배열을 반환하면 `encoding:=rgb8`로 실행한다. 색상 순서는 실물 영상으로 확인한다.

원본 영상은 JPEG보다 대역폭이 크다. 640×480의 3채널 영상을 10 FPS로 보내면 픽셀만 약 74 Mbit/s다. 먼저 낮은 FPS로 확인한다. 해상도는 실물 카메라에서는 제조사 설정을 사용하며, 이 패키지는 이미지를 확대·축소하지 않는다.

## 3. ros2 topic과 QoS 확인

PC에서 위와 같은 ROS 환경·도메인을 설정한 뒤 실행한다.

```bash
ros2 topic list -t
ros2 topic info /camera/image_raw --verbose
ros2 topic echo /camera/image_raw sensor_msgs/msg/Image \
  --qos-reliability best_effort --qos-durability volatile --qos-depth 1 \
  --field header --once --timeout 10
```

이 패키지의 발행·수신 Reliability는 둘 다 `BEST_EFFORT`여야 한다. 수신 FPS는 패키지 로그로 확인한다. Best Effort는 손실된 프레임을 재전송하지 않으며 로그는 정확한 손실률이나 종단 지연을 계산하지 않는다.

기존 카메라 노드가 이미 `sensor_msgs/msg/Image`를 발행하고 있다면 발행기를 중복 실행하지 않고 PC에서 수신기만 실행한다. 이름이 다르면 `topic:=/실제_토픽_이름`을 지정한다. `CompressedImage` 토픽은 이 원본 이미지 수신기로 읽을 수 없다.

## 4. 하드웨어 없이 통신 확인

PC 한 대에서 기존 카메라 토픽과 분리한 시험 이름을 사용한다. 합성 영상은 Python 표준 라이브러리로 만들며 `pinkylib`, OpenCV, NumPy가 필요 없다.

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  publisher:=true source:=synthetic topic:=/camera_test/image_raw fps:=5.0
```

두 PC 사이에서 합성 영상으로 시험하려면 양쪽 discovery를 `SUBNET`으로 맞추고 발행 쪽만 `publisher:=true source:=synthetic`으로 실행한다. 수신 쪽은 같은 `topic`을 지정한다.

`pinky_pro` 시뮬레이터가 `/camera/image_raw`를 발행 중이면 이 패키지의 수신기만 실행해 확인할 수 있다. 확인한 공식 MuJoCo 코드는 `RELIABLE` 발행기를 사용하며 Best Effort 구독기와 호환된다. 이 경우 양쪽이 모두 Best Effort인 시험과는 구분한다. [공식 발행 코드](https://github.com/pinklab-art/pinky_pro/blob/014a09f289e6988894fbffde2624fdb1e257815b/pinky_mujoco/pinky_mujoco/bridge.py)

## 실행 인자

| 인자 | 기본값 | 용도 |
|---|---|---|
| `publisher` | `false` | 핑키 카메라 또는 합성 영상 발행기 실행 |
| `subscriber` | `true` | 수신 검사기 실행 |
| `source` | `pinky` | `pinky`: 제조사 Camera API, `synthetic`: 장치 없는 패턴 |
| `fps` | `10.0` | 발행 목표 FPS |
| `encoding` | `bgr8` | `mono8`, `bgr8`, `rgb8`, `bgra8`, `rgba8` |
| `topic` | `/camera/image_raw` | 양쪽 토픽. `/`로 시작하면 namespace와 무관한 절대 이름 |
| `namespace` | 빈 값 | 노드 네임스페이스 |
| `display` | `false` | PC의 RViz2 영상 창 실행 |

`config/camera.yaml`에는 `frame_id`, 연속 빈 프레임 허용 횟수 `max_read_failures`, 수신 로그 주기 `report_interval`도 있다. `width`·`height`는 합성 영상에서만 사용한다. 설정 수정 후 재빌드하고 노드를 재시작한다. launch 인자로 전달하는 값은 YAML보다 우선한다.

발행기만 직접 실행하는 동일한 예:

```bash
ros2 run cobot_camera_topic_test camera_publisher --ros-args \
  -p source:=pinky -p fps:=5.0 -p topic:=/camera/image_raw
```

## 문제 해결

| 증상 | 확인 |
|---|---|
| `pinkylib.Camera is unavailable` | 핑키의 제조사 Python 환경인지 확인한다. PC는 `source:=synthetic` 또는 수신 전용으로 실행한다. |
| 카메라가 열리지 않음 | 다른 Jupyter·카메라 프로그램을 종료하고 자원을 반환한다. 제조사 Camera 예제가 동작하는지 확인한다. |
| 프레임 dtype·shape 오류 | `get_frame()` 반환값이 8비트 배열인지, 실제 채널 수와 `encoding`이 일치하는지 확인한다. |
| 다른 PC에서 수신 안 됨 | 양쪽 도메인·topic·`SUBNET`·방화벽·AP 장비 간 통신 허용을 확인한다. 환경 변경 후 `ros2 daemon stop`으로 CLI 캐시를 갱신한다. |
| `invalid` 증가 | 토픽 타입이 `Image`인지, width·height·step·data 길이가 일치하는지 확인한다. |
| 영상의 빨강·파랑이 바뀜 | 제조사 배열의 실제 채널 순서를 확인하고 발행기의 `encoding`을 맞춘다. |
| RViz2 실행 실패 | 수신 PC에 RViz2와 데스크톱 세션이 있는지 확인한다. 로그 시험은 `display:=false`로 실행한다. |

## 개발 검증

아래 설치는 개발·시험 PC에서만 필요하다.

```bash
sudo apt install -y python3-pytest python3-yaml \
  ros-jazzy-ament-flake8 ros-jazzy-ament-pep257 ros-jazzy-ament-copyright
# 저장소 루트: 표준 Python만으로 실행할 수 있는 검사
PYTHONPATH=src/cobot_vision/cobot_camera_topic_test \
  python3 -m unittest discover -s src/cobot_vision/cobot_camera_topic_test/test -v
# ROS DDS 왕복과 ament 검사는 명시적인 격리 환경에서 실행
CAMERA_TOPIC_TEST_ROS=1 ROS_DOMAIN_ID=100 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  colcon test --packages-select cobot_camera_topic_test
colcon test-result --verbose
```

단위 시험은 Camera API 호출·자원 정리·원본 픽셀 배열 포장·잘못된 이미지·통계 계산을 검사한다. ROS 시험은 합성 영상으로 수행하며 실물 카메라를 열지 않는다. 실물 `pinkylib` 연동과 두 장비 사이 영상 통신은 장비 환경에서 별도 검증해야 한다.
