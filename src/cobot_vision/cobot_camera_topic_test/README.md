# Pinky Pro 카메라 ROS 2 토픽 테스트

JiHyeok의 제조사 API 버전에 JPEG 압축 전송을 추가한 구현이다. 실물 카메라는 기존 `pinkylib.Camera`의 `Camera() → start() → get_frame() → close()` 경로를 유지한다. `Picamera2`나 `/dev/video0`을 직접 열지 않으며 제조사 드라이버를 교체하지 않는다.

API 기준은 [pinky_pro](https://github.com/pinklab-art/pinky_pro)에서 연결한 [공식 카메라 가이드](https://github.com/pinklab-art/pinky_study/wiki/2.1-Pinky-Pro%28part1%29)이다. 기존 확인 기준 커밋은 `014a09f289e6988894fbffde2624fdb1e257815b`이다. 이 launch는 카메라 발행기·수신기와 선택적인 RViz2만 실행하며 모터·Nav2·전체 bringup을 실행하지 않는다.

## 통신 구조

| 위치 | 실행 | 역할 |
|---|---|---|
| 핑키 | `camera_publisher`, `source:=pinky` | 제조사 프레임 획득 → JPEG 인코딩 또는 원본 발행 |
| 수신 PC | `camera_subscriber` | JPEG 디코딩 또는 원본 검사 → 수신 FPS·전송량 출력 |
| 수신 PC, 선택 | RViz2 | 영상 표시 |

| 항목 | 기본값 |
|---|---|
| 기본 이미지 토픽 | `/camera/image_raw` |
| 실제 JPEG 토픽 | `/camera/image_raw/compressed` |
| JPEG 메시지 | `sensor_msgs/msg/CompressedImage` |
| 비압축 모드 | 양쪽 `transport:=raw`: `/camera/image_raw`, `sensor_msgs/msg/Image` |
| JPEG 품질 | 85 (1~100 정수, 높은 값이 높은 품질이며 압축률 %가 아님) |
| 목표 FPS | 10.0, launch에서 변경 가능 |
| frame_id | `front_camera_link` |
| 양쪽 QoS | `BEST_EFFORT`, `VOLATILE`, `KEEP_LAST`, depth 1 |
| 기본 실행 | 수신기만 실행. 실물 발행은 `publisher:=true` 지정 |

JPEG 토픽은 표준 image_transport 규칙대로 기본 토픽에 `/compressed`를 붙인다. `topic` 인자에는 `/compressed`가 없는 기본 이미지 토픽을 지정한다.

## 준비와 빌드

Ubuntu 24.04 / ROS 2 Jazzy와 핑키 제조사 Python 환경을 기준으로 한다. ROS가 없다면 [Jazzy 공식 설치 안내](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)를 따른다.

핑키에서 제조사 환경을 확인한다. 아래 명령은 카메라를 열지 않는다.

```bash
source /opt/ros/jazzy/setup.bash
python3 -c 'from pinkylib import Camera; print(Camera.__module__)'
```

`pinkylib`가 없으면 제조사 Python 환경을 확인한다. 임의의 동명 패키지를 pip로 설치하거나 제조사 라이브러리를 교체하지 않는다. PC 시험에는 제조사 라이브러리가 필요 없다. 별도 conda·venv를 사용하면 ROS나 제조사 모듈이 보이지 않을 수 있다.

양쪽에서 빌드·런타임 도구를 준비한다. 이미 준비된 항목은 다시 설치할 필요 없다.

```bash
sudo apt install -y git python3-colcon-common-extensions \
  ros-jazzy-rclpy ros-jazzy-sensor-msgs ros-jazzy-launch-ros ros-jazzy-launch-xml \
  python3-opencv python3-numpy
# 영상 창이 필요한 수신 PC에서만 설치
sudo apt install -y ros-jazzy-rviz2 ros-jazzy-compressed-image-transport
```

JPEG 인코딩·디코딩은 OpenCV·NumPy를 사용한다. `cv_bridge`는 필요 없다. 핑키에는 RViz2가 필요 없다.

기존 저장소를 사용하는 경우 양쪽에서 브랜치를 갱신하고 빌드한다. 로컬 변경이 있으면 먼저 보존한다. 새로 받는 경우 아래 브랜치를 clone한다.

```bash
# 새 경로에 받을 때만 실행
# git clone --single-branch --branch feature/vision-camera-topic-besteffort \
#   https://github.com/kernel-robot-8th/kernel-robot-repo-4.git ~/ws/kernel-robot-repo-4
cd ~/ws/kernel-robot-repo-4
git pull --ff-only origin feature/vision-camera-topic-besteffort
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_camera_topic_test
source install/setup.bash
ros2 pkg prefix cobot_camera_topic_test
```

`ros2 pkg prefix`가 방금 빌드한 작업 공간을 가리키는지 확인한다. 새 터미널마다 ROS와 해당 `install/setup.bash`를 source한다. Git 파일을 갱신한 뒤에도 실행 중인 노드는 재시작해야 하며, launch·YAML·패키지 설정을 갱신하면 재빌드한다.

## 실제 핑키에서 JPEG 발행

같은 네트워크와 ROS 도메인을 사용하는 별도 터미널에서 실행한다. 예시 도메인 100은 이 시험 프로세스에만 적용한다. Jupyter 등에서 같은 카메라를 사용 중이면 먼저 `cam.close()`로 반환한다.

핑키:

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  publisher:=true subscriber:=false source:=pinky \
  fps:=30.0 transport:=compressed jpeg_quality:=85
```

수신 PC:

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml transport:=compressed
```

PC에서 `display:=true`를 추가하면 RViz2를 실행한다. 기본값은 화면 없이 로그만 출력한다. 발행 시작 로그에는 실제 topic·source·transport·목표 FPS·JPEG 품질이 표시된다. `source=pinky`는 제조사 카메라를 열며 시작 실패를 테스트 패턴으로 대체하지 않는다. 종료 시 `Camera.close()`로 자원을 반환한다.

수신 로그 예:

```text
received=..., fps=..., KiB/s=..., size=..., invalid=0
```

`fps`는 실제 시간 동안 받은 정상 메시지 수이고 `KiB/s`는 JPEG 또는 원본 픽셀 페이로드의 전송량이다. ROS·네트워크 헤더는 제외한다. `invalid=0`은 JPEG 디코딩 또는 원본 크기 검사를 통과했다는 의미이며 장면·색상은 실제 영상으로 확인한다.

### FPS·품질·색상·해상도

- `fps:=30.0`은 발행 타이머를 약 33.3 ms로 설정한다. 제조사 센서 캡처 FPS를 바꾸지 않는다. 프레임 읽기·JPEG 인코딩·발행 속도와 네트워크에 따라 실제 수신 FPS가 낮아질 수 있다. 메시지 수는 센서의 고유 프레임 수를 보장하지 않는다.
- `jpeg_quality:=85`는 JPEG 품질이다. 1~100의 정수이며 낮을수록 보통 파일이 작아지고 손실이 커진다. 고정 압축률이 아니므로 수신 로그로 전송량을 비교한다.
- `encoding:=bgr8`은 제조사 배열의 실제 픽셀 순서를 지정한다. RGB 배열이면 `encoding:=rgb8`로 실행한다. JPEG 모드는 지정한 순서에서 BGR 또는 흑백으로 변환해 인코딩하며 알파 채널은 보존하지 않는다. 비압축 모드는 원래 픽셀 순서 그대로 전송한다.
- 실물 영상의 반환 해상도를 유지하며 확대·축소하지 않는다. `width`·`height`는 합성 영상에만 적용한다.

같은 제조사 API로 비압축과 비교하려면 핑키와 PC **양쪽** 명령을 `transport:=raw`로 실행한다. 실제 토픽은 `/camera/image_raw`이고 RViz 설정도 raw로 선택된다. 비압축 640×480 컬러는 픽셀만 10 FPS에서 약 74 Mbps, 30 FPS에서 약 221 Mbps이다. JPEG는 대역폭을 줄이지만 핑키의 인코딩 시간을 사용하므로 실물 30 FPS를 보장하지 않는다.

직접 실행하는 예:

```bash
ros2 run cobot_camera_topic_test camera_publisher --ros-args \
  -p source:=pinky -p fps:=30.0 -p transport:=compressed -p jpeg_quality:=85
```

## 토픽·QoS 확인

PC에서 같은 도메인과 환경을 설정한 뒤 실행한다.

```bash
ros2 topic list -t
ros2 topic info /camera/image_raw/compressed --verbose
ros2 topic echo /camera/image_raw/compressed sensor_msgs/msg/CompressedImage \
  --qos-reliability best_effort --qos-durability volatile --qos-depth 1 \
  --field header --once --timeout 10
```

양쪽 Reliability는 `BEST_EFFORT`이다. 손실 프레임은 재전송하지 않으며 로그는 정확한 손실률이나 종단 지연을 계산하지 않는다. 원본 `Image`를 발행하는 기존 노드·공식 MuJoCo 시뮬레이터에 연결할 때는 `transport:=raw` 수신기만 실행한다. 발행기를 중복 실행하지 않는다.

## 하드웨어 없이 시험

기존 영상과 분리한 토픽에서 합성 영상을 보낸다. 제조사 라이브러리나 카메라 장치를 열지 않는다.

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  publisher:=true source:=synthetic topic:=/camera_test/image_raw fps:=30.0
```

두 PC 사이 합성 시험에서는 양쪽 discovery를 `SUBNET`으로 맞추고 발행 쪽만 `publisher:=true source:=synthetic`으로 실행한다. 양쪽 topic·transport를 맞춘다.

## 실행 인자

| 인자 | 기본값 | 의미 |
|---|---|---|
| `publisher` | `false` | 발행기 실행 |
| `subscriber` | `true` | 수신기 실행 |
| `source` | `pinky` | 제조사 API. `synthetic`은 테스트 패턴. `camera`는 지원하지 않음 |
| `transport` | `compressed` | JPEG. `raw`는 기존 비압축 모드. 양쪽 동일하게 설정 |
| `jpeg_quality` | `85` | JPEG 품질 1~100 정수 |
| `fps` | `10.0` | 발행 목표 FPS |
| `encoding` | `bgr8` | 제조사 배열 순서: mono8, bgr8, rgb8, bgra8, rgba8 |
| `topic` | `/camera/image_raw` | 기본 이미지 토픽. `/compressed`를 포함하지 않음 |
| `namespace` | 빈 값 | 노드 네임스페이스 |
| `display` | `false` | 수신 PC의 RViz2 실행 |

`config/camera.yaml`에는 frame_id, 연속 빈 프레임 허용 횟수 `max_read_failures`, 수신 로그 주기 `report_interval`도 있다. launch 인자가 YAML보다 우선한다. FPS·품질·transport 변경은 노드를 재시작해 적용한다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| 패키지를 찾을 수 없음 | 패키지를 빌드하고 올바른 `install/setup.bash`를 source한 뒤 `ros2 pkg prefix` 확인 |
| `jpeg_quality` 속성 오류 | 발행기·설정 파일 버전을 함께 갱신하고 재빌드·source·노드 재시작 |
| `pinkylib.Camera is unavailable` | 제조사 Python 환경 확인. PC 시험은 synthetic 또는 수신 전용 |
| 카메라를 열지 못함 | Jupyter·다른 카메라 프로그램에서 장치 반환. 제조사 예제 확인 |
| 수신 안 됨 | 양쪽 transport·topic·도메인·SUBNET·방화벽 확인. 환경 변경 후 `ros2 daemon stop` |
| `invalid` 증가 | JPEG 데이터 손상 또는 원본 width·height·step·data 길이 확인 |
| 빨강·파랑 뒤바뀜 | 제조사 배열 순서에 맞는 encoding 지정 |
| RViz2 영상 안 나옴 | PC의 compressed-image-transport 설치, 실제 topic·QoS·디스플레이 환경 확인 |

## 개발 검증

```bash
sudo apt install -y python3-pytest python3-yaml \
  ros-jazzy-ament-flake8 ros-jazzy-ament-pep257 ros-jazzy-ament-copyright
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 -m unittest discover -s src/cobot_vision/cobot_camera_topic_test/test -v
# ROS DDS 시험은 명시적인 격리 환경에서 실행
CAMERA_TOPIC_TEST_ROS=1 ROS_DOMAIN_ID=100 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  colcon test --packages-select cobot_camera_topic_test
colcon test-result --verbose
```

단위 시험은 제조사 API 호출·정리, 설정 검증, 픽셀 배열 포장, JPEG 품질·색상·해상도, 손상 데이터와 통계를 검사한다. ROS 시험은 합성 영상과 모의 제조사 프레임을 사용해 JPEG·비압축 DDS 왕복을 확인하며 실물 장치를 열지 않는다. 실물 `pinkylib` 연동, 핑키의 실제 처리 FPS와 두 장비 사이 전송 성능은 장비에서 별도로 확인해야 한다.
