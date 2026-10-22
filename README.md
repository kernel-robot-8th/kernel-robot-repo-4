# <신발 매장 픽업 자동화 시스템>

<신발 운반 자동화를 통해 직원은 고객 맞춤 서비스에 집중>

- 환경: Ubuntu 24.04 / ROS2 Jazzy / Python 3.12
- 로봇: <예: 모바일 베이스 + 매니퓰레이터>
- 시뮬레이터: <예: Gazebo Harmonic, 사용 안 함>
- 팀 규칙은 [`CLAUDE.md`](CLAUDE.md)를 참고하세요. (코딩 규칙, 패키지 구조, Git 규칙)

## 팀 구성
| 역할 | 담당 패키지 | 담당자 |
|---|---|---|
| 비전 | `cobot_vision` | 강건한, 손선아 |
| 주행 | `cobot_navigation` | 김지호, 김성아 |
| 매니퓰레이터 | `cobot_manipulation`, `cobot_moveit_config` | 강민석, 김성아, 손선아, 허지혁 |
| 관제 | `cobot_control_center` | 강건한 |
| GUI | `cobot_gui` | 강건한, 김지혜 |

## 처음 설치하기
도커로 하려면 [`docs/dev_docker_guide.md`](docs/dev_docker_guide.md)를 보세요. (도커를 처음 써도 이 문서부터 따라 하면 됩니다)

### 1. ROS2 Jazzy 설치
[공식 설치 문서](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)를 따라 설치한 뒤, 개발 도구를 설치합니다.
```bash
sudo apt install ros-jazzy-desktop ros-dev-tools python3-venv
```

### 2. 저장소 받기
```bash
git clone <저장소 주소> <ws>
cd <ws>
```

### 3. 파이썬 가상환경 만들기
```bash
python3 -m venv --system-site-packages .venv
touch .venv/COLCON_IGNORE      # colcon이 .venv 안을 탐색하지 않도록 함
```
- conda를 쓰고 있다면 `conda deactivate`로 끈 상태에서 진행하세요.
- 시스템 파이썬에 `pip install` 하지 마세요. 필요한 패키지는 `.venv`를 켠 상태에서 설치합니다.

### 4. 환경 설정
`~/.bashrc`에 아래를 추가하면 터미널을 열 때마다 적용됩니다. (개발·시뮬레이션 전용 값)
```bash
export ROS_DOMAIN_ID=100
```
- 실물 로봇은 100을 쓰지 않고 SR-19 대로 `10`(실물 구동)과 `12`(Nav2)를 씁니다. 개발·시뮬레이션 노드를 10·12에서 띄우지 마세요. 자세한 값은 [`docs/fms_interfaces.md`](docs/fms_interfaces.md)를 보세요.

### 5. 의존 패키지 설치 (처음 한 번)
```bash
source /opt/ros/jazzy/setup.bash
sudo rosdep init        # 이미 한 적이 있으면 생략
rosdep update
rosdep install --from-paths src --ignore-src -r -y
```

## 빌드와 실행
순서는 **ROS2 source → .venv 활성화 → 빌드**입니다.
```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
colcon build --symlink-install
source install/setup.bash
ros2 launch <proj>_bringup bringup.launch.xml
```

## 테스트
```bash
colcon test --packages-select <pkg>
colcon test-result --verbose
```

## 문서
- 팀 공통 문서: [`docs/`](docs/)
- 패키지별 문서(PRD 등): `src/<proj>_<역할>/docs/`

## 협업 규칙 요약
- `main`에는 직접 push하지 않고, 브랜치에서 작업한 뒤 PR + 리뷰 1명 이상으로 합칩니다.
- PR 전에 빌드, 테스트, 린트가 통과하는지 확인합니다.
- 자세한 내용은 `CLAUDE.md`를 확인하세요.
