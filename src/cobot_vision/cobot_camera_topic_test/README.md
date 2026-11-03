# ROS 2 카메라 토픽 통신 테스트

`refactor/control-server-bt-mqtt-db`에서 분기한 `feature/vision-camera-topic-besteffort` 브랜치의 독립 테스트 패키지다. Ubuntu 24.04 / ROS 2 Jazzy를 기준으로 한다.

카메라 영상 또는 움직이는 테스트 영상을 JPEG로 발행하고, 수신 노드에서 디코딩한 프레임 수·수신 FPS·전송량을 확인한다. 기본 실행은 카메라 장치와 화면 없이 동작한다. 기존 `pinky_camera.zip`을 풀거나 설치할 필요가 없다.

## 토픽과 QoS

| 항목 | 값 |
|---|---|
| 패키지 | `cobot_camera_topic_test` |
| 기본 토픽 | `/vision/camera/image_raw/compressed` |
| 메시지 | `sensor_msgs/msg/CompressedImage` |
| 이미지 | JPEG, 기본 640×480 / 10 FPS / 품질 75 |
| 양쪽 QoS | `BEST_EFFORT`, `VOLATILE`, `KEEP_LAST`, depth 1 |
| 기본 frame_id | `camera_optical_frame` |

Best Effort는 손실된 프레임을 재전송하지 않는다. 통신 확인은 수신 노드의 `received` 증가와 정상 디코딩으로 판단한다. 수신 FPS는 발행 FPS보다 낮을 수 있으며, 로그는 종단 지연이나 정확한 손실률을 측정하지 않는다. 이 패키지는 TF·카메라 보정 정보(`CameraInfo`)를 발행하지 않는다.

## 처음 설치하기

발행 장비와 수신 PC 모두 Ubuntu 24.04와 ROS 2 Jazzy가 필요하다. USB/UVC 등 OpenCV의 V4L2 입력으로 읽을 수 있는 카메라를 대상으로 한다. CSI 전용 카메라는 장비 드라이버가 필요할 수 있다. 합성 영상 시험에는 카메라가 필요 없다. 설치 단계에는 인터넷과 sudo 권한이 필요하며, 설치 후 영상 통신에는 인터넷이 필요 없다.

### 1. ROS 2 Jazzy가 없을 때만 설치

이미 `/opt/ros/jazzy/setup.bash`가 있으면 다음 단계로 간다. Ubuntu 버전은 `cat /etc/os-release`로 확인한다. 아래 명령은 Ubuntu 24.04 전용이다.

```bash
sudo apt update
sudo apt install -y locales curl software-properties-common python3

# locale 출력에 UTF-8이 없을 때만 실행
sudo locale-gen en_US.UTF-8
export LANG=en_US.UTF-8

sudo add-apt-repository -y universe

# ROS 공식 apt 저장소와 서명 키 등록
camera_ros_source_version=$(curl -fsSL \
  https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
curl -fL -o /tmp/camera-test-ros2-apt-source.deb \
  "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${camera_ros_source_version}/ros2-apt-source_${camera_ros_source_version}.noble_all.deb"
sudo dpkg -i /tmp/camera-test-ros2-apt-source.deb
sudo apt update
sudo apt install -y ros-jazzy-ros-base
source /opt/ros/jazzy/setup.bash
```

ROS Desktop이 이미 설치돼 있어도 그대로 사용할 수 있다. ROS 설치 기준은 [공식 Jazzy Ubuntu 설치 안내](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)와 [공식 저장소 등록 절차](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Installation/_Apt-Repositories.rst)다.

### 2. 빌드·시험 도구 설치

```bash
sudo apt update
sudo apt install -y git python3-colcon-common-extensions python3-rosdep python3-pytest
source /opt/ros/jazzy/setup.bash

# rosdep을 처음 사용하는 PC에서만 실행
sudo rosdep init
rosdep update
```

`rosdep init`에서 이미 초기화됐다는 메시지가 나오면 `rosdep update`로 넘어간다. rosdep과 apt 설치가 끝나기 전에는 빌드를 시작하지 않는다.

### 3. 별도 작업 디렉터리로 받기

기존 작업과 분리하려면 새 경로에 복제한다. 아래 예시 경로가 이미 있으면 비어 있는 다른 경로를 선택한다.

```bash
git clone --single-branch --branch feature/vision-camera-topic-besteffort \
  https://github.com/kernel-robot-8th/kernel-robot-repo-4.git ~/kernel-robot-camera-test
cd ~/kernel-robot-camera-test
```

기존 복제본을 사용할 경우에는 변경 중인 파일을 먼저 정리한 뒤 `git fetch origin`과 `git switch --track origin/feature/vision-camera-topic-besteffort`를 실행한다. 로컬 브랜치가 이미 있으면 `git switch feature/vision-camera-topic-besteffort`만 실행한다.

### 4. 패키지 의존성 설치와 빌드

저장소 루트에서 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src/cobot_vision/cobot_camera_topic_test \
  --ignore-src --rosdistro jazzy -r -y
colcon build --symlink-install --packages-select cobot_camera_topic_test
source install/setup.bash
ros2 pkg executables cobot_camera_topic_test
```

마지막 명령에 `camera_publisher`, `camera_subscriber`가 나오면 설치 등록이 완료된 것이다. 런타임 의존성은 `rclpy`, `sensor_msgs`, `launch_ros`, `launch_xml`, `python3-opencv`, `python3-numpy`다. 시험에는 `python3-pytest`, `python3-yaml`과 ament 린트 패키지가 필요하며 `package.xml`을 통해 rosdep이 설치한다. 별도의 pip 설치나 기존 zip 설치는 필요 없다.

conda가 활성화돼 있으면 `conda deactivate` 후 진행한다. 가상환경을 사용한다면 시스템 ROS 패키지를 볼 수 있도록 `--system-site-packages`로 만든 환경을 사용한다.

## 새 터미널에서 공통으로 실행할 명령

아래의 발행·수신·토픽 확인 명령을 실행할 때마다 먼저 실행한다. 복제한 경로가 다르면 `cd` 경로를 바꾼다.

```bash
cd ~/kernel-robot-camera-test
source /opt/ros/jazzy/setup.bash
source install/setup.bash
```

## 1. 카메라 없이 한 PC에서 확인

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_camera_topic_test camera_test.launch.xml
```

발행기와 수신기가 함께 실행된다. 수신기에 아래 형식의 로그가 반복되고 `received`가 증가하면 정상이다. 수치는 실행 환경에 따라 달라진다. 종료는 Ctrl+C다.

```text
received=..., fps=..., KiB/s=..., size=640x480, invalid=0
```

## 2. 실제 카메라에서 발행하고 다른 PC에서 수신

양쪽 장비에서 같은 브랜치의 패키지를 빌드하고 ROS와 `install/setup.bash`를 source한다. 같은 네트워크와 도메인을 사용해야 한다. 아래 환경변수는 각 테스트 터미널에만 적용한다.

카메라가 연결된 장비:

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  source:=camera device:=/dev/video0 subscriber:=false
```

수신 PC:

```bash
export ROS_DOMAIN_ID=100
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
unset ROS_LOCALHOST_ONLY
ros2 launch cobot_camera_topic_test camera_test.launch.xml publisher:=false
```

GUI가 있는 수신 PC에서는 `display:=true`를 추가하면 영상을 볼 수 있다. SSH·화면 없는 환경에서는 기본값 `false`를 유지한다. 카메라 대신 두 장비 간 테스트 영상으로 먼저 확인하려면 발행 쪽에서 `source:=synthetic`을 사용한다.

카메라 경로는 `device:=/dev/video2`처럼 바꾼다. 다른 드라이버가 같은 장치를 사용 중이면 중복으로 열지 않는다. 장치를 열지 못하거나 연속 읽기 실패가 `max_read_failures`에 도달하면 발행 프로세스가 오류로 종료된다.

### 카메라 경로와 권한 확인

실제 카메라를 연결한 장비에서만 필요하다.

```bash
sudo apt install -y v4l-utils
v4l2-ctl --list-devices
ls -l /dev/video*
id -nG
```

카메라가 여러 `/dev/videoN`을 제공하면 `v4l2-ctl --device=/dev/video0 --list-formats-ext`로 영상 캡처가 가능한 노드를 찾는다. 출력의 소유 그룹이 `video`이고 현재 계정에 접근 권한이 없을 때만 아래 명령을 실행한다. 로그아웃 후 다시 로그인해야 그룹이 적용된다.

```bash
sudo usermod -aG video "$(id -un)"
```

WSL·컨테이너에서는 카메라 장치를 별도로 전달해야 한다. 처음 시험은 Ubuntu 호스트에서 진행하는 편이 쉽다.

## 3. ros2 topic으로 확인

실행 중인 노드와 같은 ROS 환경·도메인을 사용하는 별도 터미널에서 실행한다.

```bash
ros2 topic list -t
ros2 topic info /vision/camera/image_raw/compressed --verbose
ros2 topic echo /vision/camera/image_raw/compressed \
  sensor_msgs/msg/CompressedImage \
  --qos-reliability best_effort --qos-durability volatile --qos-depth 1 \
  --field header --once --timeout 10
```

`topic info`에서 양쪽 Reliability가 `BEST_EFFORT`인지 확인한다. `echo`는 이미지 바이트 대신 헤더를 출력한다. JPEG 디코딩과 수신 FPS는 패키지의 수신기로 확인한다. Best Effort 발행기에 `RELIABLE` 구독기를 연결하면 수신하지 못할 수 있다. [ROS 2 Jazzy QoS 구현](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/qos.py)과 [topic echo 옵션](https://github.com/ros2/ros2cli/blob/jazzy/ros2topic/ros2topic/verb/echo.py)을 참고한다.

기존 드라이버가 `CompressedImage`를 발행하고 있으면 수신기만 실행해 해당 토픽을 확인할 수 있다.

```bash
ros2 launch cobot_camera_topic_test camera_test.launch.xml \
  publisher:=false topic:=/camera/image_raw/compressed
```

`sensor_msgs/msg/Image` 원본 토픽은 이 수신기로 읽을 수 없다. 기존 드라이버의 JPEG 압축 토픽을 선택한다.

## 설정

| launch 인자 | 기본값 | 용도 |
|---|---|---|
| `source` | `synthetic` | `synthetic` 테스트 영상 또는 `camera` 실제 장치 |
| `device` | `/dev/video0` | 카메라 경로 또는 `0` 같은 장치 번호 |
| `publisher` | `true` | 발행 노드 실행 여부 |
| `subscriber` | `true` | 수신 노드 실행 여부 |
| `display` | `false` | 수신 영상 창 표시 여부 |
| `namespace` | `vision` | 양쪽 노드와 상대 토픽의 네임스페이스 |
| `topic` | `camera/image_raw/compressed` | 양쪽 토픽 이름 |

`config/camera.yaml`에서 해상도·FPS·JPEG 품질·frame_id·연속 읽기 실패 한도·로그 주기를 바꾼다. 변경 후 노드를 재시작한다. `source`, `device`, `topic`, `display`는 launch 인자로 지정하며 YAML보다 우선한다. `namespace:=pinky1/vision`처럼 네임스페이스도 바꿀 수 있다. `topic`을 `/`로 시작하면 네임스페이스를 붙이지 않는다.

발행기만 직접 실행하며 FPS를 바꾸는 예:

```bash
ros2 run cobot_camera_topic_test camera_publisher --ros-args \
  -r __ns:=/vision -p source:=synthetic -p fps:=5.0 -p jpeg_quality:=60
```

수신이 없으면 도메인·토픽 이름·메시지 타입·QoS와 양쪽 discovery 설정을 확인한다. 다른 PC와 통신할 때는 `LOCALHOST` 설정을 해제하고 방화벽의 DDS 통신 허용 여부를 확인한다. 기존 관제 도메인 브릿지는 이 테스트 토픽을 자동 중계하지 않으므로, 먼저 같은 도메인에서 직접 시험한다. `invalid`가 증가하면 발행 데이터가 정상 JPEG인지 확인한다.

## 자주 발생하는 문제

| 증상 | 확인·해결 |
|---|---|
| `ros2` 또는 패키지를 찾지 못함 | Jazzy 설치와 두 `setup.bash` source 여부를 확인한다. 새 패키지를 추가했으면 다시 빌드한다. |
| `No module named cv2/numpy/rclpy` | rosdep을 다시 실행한다. 시스템 ROS와 다른 Python·conda 환경인지 확인한다. `python3 -c 'import cv2, numpy, rclpy'`로 확인한다. |
| 카메라 열기 실패 | 실제 장치 경로, 캡처 포맷, 계정 권한과 다른 드라이버의 장치 점유를 확인한다. |
| 토픽은 보이지만 수신 로그가 없음 | `topic info --verbose`에서 타입과 Best Effort QoS를 확인한다. 합성 영상으로 먼저 분리 시험한다. |
| 다른 PC의 토픽이 안 보임 | 양쪽 도메인 100, discovery `SUBNET`, `ROS_LOCALHOST_ONLY` 해제, 방화벽과 무선 AP의 장비 간 통신 허용 여부를 확인한다. 환경을 바꾼 뒤에는 `ros2 daemon stop` 후 토픽 명령을 다시 실행한다. |
| Qt·display 오류 | SSH·화면 없는 환경에서는 `display:=false`로 실행한다. 영상 창은 데스크톱 세션에서 사용한다. |
| FPS가 낮거나 끊김 | 해상도·`fps`·`jpeg_quality`를 낮추고 다른 영상 전송을 줄인다. 수신 FPS는 보장값이 아니다. |

## 파일 구성

```text
cobot_camera_topic_test/
├── cobot_camera_topic_test/
│   ├── camera_publisher_node.py
│   ├── camera_subscriber_node.py
│   ├── camera_runtime.py
│   └── camera_utils.py
├── config/camera.yaml
├── launch/camera_test.launch.xml
├── test/
├── package.xml
├── setup.py
└── README.md
```

## 검증

```bash
# 저장소 루트: ROS 없이 실행 가능한 단위 시험
PYTHONPATH=src/cobot_vision/cobot_camera_topic_test \
  python3 -m unittest discover -s src/cobot_vision/cobot_camera_topic_test/test -v

# ROS와 의존성이 설치된 PC: 실제 DDS/JPEG 왕복 및 ament 검사
CAMERA_TOPIC_TEST_ROS=1 ROS_DOMAIN_ID=100 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  colcon test --packages-select cobot_camera_topic_test
colcon test-result --verbose
```

ROS 통합 시험은 명시적인 격리 설정이 있을 때만 실행한다. 카메라 하드웨어는 열지 않으며 합성 영상 왕복·QoS·잘못된 이미지·네임스페이스 설정·카메라 열기 실패 정리를 검사한다. ROS가 없는 환경에서는 해당 시험을 건너뛴다. 실제 카메라와 두 PC 간 통신은 별도 실측이 필요하다.
