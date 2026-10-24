# <신발 매장 픽업 자동화 시스템>

<신발 운반 자동화를 통해 직원은 고객 맞춤 서비스에 집중>

- 환경: Ubuntu 24.04 / ROS2 Jazzy / Python 3.12
- 로봇: <예: 모바일 베이스 + 매니퓰레이터>
- 시뮬레이터: MuJoCo OMX 검증 실험 (장면 실측·접촉 보정 진행 중)
- 팀 규칙은 [`CLAUDE.md`](CLAUDE.md)를 참고하세요. (코딩 규칙, 패키지 구조, Git 규칙)

## 팀 구성
| 역할 | 담당 패키지 | 담당자 |
|---|---|---|
| 주행 | `cobot_navigation` | 김진호 |
| 로봇팔 | `cobot_manipulation`, `cobot_moveit_config` | 강민석, 김성아, 허지석 |
| 비전 | `cobot_vision` | 손선아, 강건한 |
| 로봇 수행 관제 | `cobot_gui`, `cobot_control_center` | 김지혜 |
| 이상 감지 관제 | `cobot_gui`, `cobot_control_center` | 강건한 |

담당 기준은 [2026-10-24 사용자 지정](docs/team_roles.md)이다. 두 관제는 공통 GUI·관제 코어를 재사용하며 로봇 기능 개발과 구분한다.

## 워크스페이스 구조
```
<ws>/
├── src/
│   ├── <proj>_interfaces/      # 공용 msg / srv / action (코드 없음)
│   ├── <proj>_bringup/         # 전체 launch, 통합 파라미터 YAML
│   ├── <proj>_description/     # URDF/xacro, 메시 (모바일 베이스 + 팔)
│   ├── <proj>_vision/          # [비전] 카메라, 검출/인식, 좌표 변환
│   ├── <proj>_navigation/      # [주행] Nav2 설정, 주행 시퀀스, localization
│   ├── <proj>_manipulation/    # [매니퓰레이터] 팔/그리퍼 제어, pick&place
│   ├── <proj>_moveit_config/   # [매니퓰레이터] MoveIt2 설정
│   ├── cobot_mujoco/          # [매니퓰레이터] OMX MuJoCo·독립 학습 검증 실험
│   ├── <proj>_control_center/  # [관제] 상태 수집, 작업 할당, 로그
│   └── <proj>_gui/             # [GUI] 사용자/관제 화면
├── docs/                       # 팀 공통 문서 (전체 PRD, 토픽·TF·인터페이스 명세) → 4번 참고
├── scripts/                    # 환경 설정, 보조 스크립트
└── CLAUDE.md
```

## 처음 설치하기

### OMX 학습·MuJoCo 검증 실험

`src/cobot_mujoco`는 저장된 실제 카메라 영상을 기준으로 OMX-F, 작업대, 상자, 흰 원형 수신 로봇을 재현하고
상태 BC·시각 CNN BC·ACT 학습을 녹화 단위로 비교합니다. 실제 장치에 연결하지 않는 독립 실험 패키지입니다.
설치·최대 12시간 실행·중단·검증 절차는 [검증 문서](src/cobot_mujoco/docs/validation.md),
결과는 [HTML 보고서](docs/mujoco_validation/report.html)를 보세요. 물리 환경은 아직 현장 검증을 통과하지 않았습니다.

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
- 실물 로봇의 도메인은 D2 설계 제안으로 `10`(실물 구동)과 `12`(Nav2)를 씁니다. 개발·시뮬레이션 노드를 10·12에서 띄우지 마세요. SR_v2는 번호를 지정하지 않으며 D2 결정 전에는 실물 설정에 적용하지 않습니다. 자세한 제안은 [`docs/fms_interfaces.md`](docs/fms_interfaces.md)를 보세요.

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
- 확정: `담당 분야에서 작업 → submaster에서 함께 시험 → main 반영`. 기존 분야 브랜치는 유지하고 새 분야 브랜치는 최신 submaster에서 만듭니다. PR은 submaster로 보냅니다. [팀원 공지](docs/github_team_notice.md)와 [핵심 규칙](docs/fms_branch_workflow.md)을 확인하세요.
- PR 전에 빌드, 테스트, 린트가 통과하는지 확인합니다.
- 자세한 내용은 `CLAUDE.md`를 확인하세요.
