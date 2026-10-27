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

**신규 1026 v2 데이터 학습은 LeRobot 0.4.4입니다.** 성공 9개 에피소드로
일반형·경량형, 전류 미포함·포함, 배치 8·16, chunk 32·64·100을 비교하고
배치32 1개를 추가합니다. 신규 25개 학습에서 5k·10k·15k 저장본 75개를 비교합니다. 기존 완료 3개도 포함해
총 28개 실험·84개 저장본을 비교하며 시간 제한은 없습니다. 신규 학습은 BF16 AMP를 적용합니다.
[신규 학습 기준·실행 방법](src/cobot_mujoco/docs/actv2.md) ·
[신규 진행·비교 보고서](docs/mujoco_validation/lerobot044_v2_15k/report.html).

아래는 이전 1024 데이터의 0.4.4 학습입니다. 로컬 `il_ws/src/lerobot` 원본 train으로
ACT 일반형·경량형(모두 ResNet18+Transformer)의 chunk·step·학습률·감쇠를 비교합니다.
12개 학습 경로·44개 검증 시점을 계획했으며, 독립 CNN·MuJoCo·실물 실행은 포함하지 않습니다.
[0.4.4 진행·비교 보고서](docs/mujoco_validation/lerobot044/report.html) ·
[실험 기준·재현 방법](src/cobot_mujoco/docs/act044.md).
오늘 모델의 실물 추론 실행기는 `~/il_ws/run_act044.sh`, 설정은 `~/il_ws/act044_inference.env`입니다.
[모델 번호 1~12·실행 명령·추론 설정 안내](src/cobot_mujoco/docs/act044_inference.md)를 확인하세요.
아래의 이전 학습·MuJoCo·박스 외형 비교는 0.6.1 기반 보관 결과입니다.

**박스 외형 개선:** 실제 하트 인쇄 텍스처·카메라·조명을 기본 장면에 반영했습니다.
[수정 전후 박스 정합·모델 반응·물리 비교](docs/mujoco_validation/appearance_report.html)와
[변경 범위·재현 방법](src/cobot_mujoco/docs/appearance.md)을 확인하세요.
무늬 정합은 개선됐지만 안정 배치는 아직 재현하지 못했습니다.

**재학습·추가 비교:** 사용자 지정 기본 시연 0~10번과 보완 시연 11~14번의 역할을 반영했습니다.
경량 CNN·ACT 비교 48건, **원본 해상도·기본 구조의 공식 `lerobot-train` ACT 비교 8건**,
전체 15개 녹화를 반영한 마지막 경량·공식 ACT 모델 2건을 완료했습니다.
추가 MuJoCo 비교는 새 학습 모델 66회·관절 유지 대조군 6회·기록 명령 재생 6회를 실제 실행했습니다.
보고서에서 목표·종료·선택 스텝, 조기 종료 이유, 학습 곡선, 신규 시뮬레이션 영상과 진단 수치를 구분해서 확인할 수 있습니다.
현재 장면의 안정 배치는 재현하지 못했으며, 보정 전 물리 결과를 실제 로봇 성공률로 해석하지 않습니다.
[재학습 절차·실제 파라미터](src/cobot_mujoco/docs/retraining.md)와 [현재 HTML 보고서](docs/mujoco_validation/report.html)를 확인하세요.
실행은 `scripts/mujoco/run_retraining.sh`입니다. [1차 보고서](docs/mujoco_validation/round1_report.html)는 보관 기록입니다.

`src/cobot_mujoco`는 저장된 실제 카메라 영상을 기준으로 OMX-F, 작업대, 상자, 흰 원형 수신 로봇을 재현하고
상태 BC·시각 CNN BC·ACT 학습을 녹화 단위로 비교합니다. 실제 장치에 연결하지 않는 독립 실험 패키지입니다.
설치·최대 12시간 실행·중단·검증 절차는 [검증 문서](src/cobot_mujoco/docs/validation.md),
결과는 [HTML 보고서](docs/mujoco_validation/report.html)를 보세요. 물리 환경은 아직 현장 검증을 통과하지 않았습니다.
1차 학습 설정의 기능·실제 변경값은 [기존 파라미터 설명서](src/cobot_mujoco/docs/parameters.md)를 참고하세요.
기존 기본 장면의 박스 3개 설정 오류를 2개로 정정했으며, 원래 0/108회는 동일 장면의 모델 성공률로 해석할 수 없습니다.

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
