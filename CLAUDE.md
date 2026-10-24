# CLAUDE.md

이 파일은 팀 공통 규칙입니다. 개인 설정은 `CLAUDE.local.md`(gitignore)에 작성하세요.

## 1. 프로젝트 개요
- 프로젝트명: <프로젝트 이름> (패키지 접두사: `cobot`, 결정 D1 → [`docs/fms_decisions.md`](docs/fms_decisions.md#d1))
- 목적: <한두 문장으로 프로젝트 목적 작성>
- 대상 하드웨어/로봇: <예: 모바일 베이스 + 매니퓰레이터>
- 환경: Ubuntu 24.04 / ROS2 Jazzy / Python 3.12 / C++17 (C++ 패키지 사용 시)
- 시뮬레이터: <예: Gazebo Harmonic, 사용 안 함>
- 팀 역할: 주행 / 로봇팔 / 비전 / 로봇 수행 관제 / 이상 감지 관제

## 2. 워크스페이스 구조
```
<ws>/
├── src/
│   ├── cobot_interfaces/       # 공용 msg / srv / action (코드 없음)
│   ├── cobot_bringup/          # 전체 launch, 통합 파라미터 YAML
│   ├── cobot_description/      # URDF/xacro, 메시 (모바일 베이스 + 팔)
│   ├── cobot_vision/           # [비전] 카메라, 검출/인식, 좌표 변환
│   ├── cobot_navigation/       # [주행] Nav2 설정, 주행 시퀀스, localization
│   ├── cobot_manipulation/     # [매니퓰레이터] 팔/그리퍼 제어, pick&place
│   ├── cobot_moveit_config/    # [매니퓰레이터] MoveIt2 설정
│   ├── cobot_control_center/   # [관제] 상태 수집, 작업 할당, 로그
│   └── cobot_gui/              # [GUI] 사용자/관제 화면 (웹 화면 자원은 web/ → 3-7 참고)
├── docs/                       # 팀 공통 문서 (전체 PRD, 토픽·TF·인터페이스 명세) → 4번 참고
│   ├── dev_docker_guide.md     # 도커로 빌드·시험하는 방법 (도커를 처음 쓰는 사람용 설명 포함)
│   ├── fms_decisions.md        # FMS 결정 기록 (D1~D5·D8, 추천안 → 공지 → decided 절차)
│   ├── fms_dev_rules.md        # FMS(관제 대시보드) 작업 공통 규칙 R1~R10
│   ├── fms_interfaces.md       # 토픽·QoS·ROS_DOMAIN_ID·네임스페이스·TF frame 표
│   ├── fms_map_contract.md     # 맵 정본, map_hash, 작업점·정차점
│   ├── fms_menu_tree.md        # FMS 메뉴 표 (레지스트리에서 자동 생성, 손으로 고치지 않음)
│   ├── fms_offline_bundle.md   # 인터넷 없는 현장 PC 에 설치할 오프라인 번들 목록
│   └── fms_roadmap.md          # FMS 단계 계획 S0~S6 과 단계별 출구 검사
├── scripts/                    # 환경 설정, 보조 스크립트
│   ├── docker/                 # 개발용 도커 스크립트 (dev_docker_guide.md 참고)
│   └── spikes/                 # 한 번 확인하고 끝나는 검증 스크립트 (결과는 docs/ 에 기록)
└── CLAUDE.md
```
- `build/`, `install/`, `log/`는 colcon 산출물이므로 수정·커밋하지 않습니다. (`.gitignore` 등록)
- `scripts/`는 colcon 패키지가 아니라서 `colcon test`의 린트가 검사하지 않습니다. 여기 파이썬 파일을 고쳤다면 `ament_flake8 scripts/`, `ament_pep257 scripts/`, `ament_copyright scripts/`를 직접 돌립니다.
- 새 패키지를 추가하면 이 구조도와 아래 담당 표를 함께 갱신합니다.

### 역할별 담당 패키지
| 역할 | 담당 패키지 | 담당자 |
|---|---|---|
| 주행 | `cobot_navigation` | 김진호 |
| 로봇팔 | `cobot_manipulation`, `cobot_moveit_config` | 강민석, 김성아, 허지석 |
| 비전 | `cobot_vision` | 손선아, 강건한 |
| 로봇 수행 관제 | `cobot_gui`, `cobot_control_center` | 김지혜 |
| 이상 감지 관제 | `cobot_gui`, `cobot_control_center` | 강건한 |
| 공통 | `cobot_interfaces`, `cobot_bringup`, `cobot_description` | 팀 전체 (관련 담당 리뷰) |

담당 기준은 [2026-10-24 사용자 지정](docs/team_roles.md)이다. 두 관제는 공통 GUI·관제 코어를 재사용하며 로봇 기능 개발과 구분한다.

## 3. 패키지 · 폴더 작성 규칙

### 3-1. 공통 규칙
- 패키지명은 `<proj>_<역할>` 형태의 소문자 `snake_case`로 통일합니다.
- 한 패키지는 **한 가지 언어만** 사용합니다. (Python → `ament_python`, C++ → `ament_cmake`)
- 모든 패키지는 `package.xml`에 `description`, `maintainer`(담당자), `license`를 채웁니다.
- 폴더명은 아래 표준 이름만 사용합니다: `launch/`, `config/`, `test/`, `docs/`, `rviz/`, `urdf/`, `meshes/`, `msg/`, `srv/`, `action/`, `web/`(`cobot_gui`만, 3-7 참고)
- 파일 종류별 위치를 지킵니다.
  - 패키지 개별 문서(PRD 등): `docs/prd.md` (자세한 규칙은 4번)
  - launch 파일: `launch/<이름>.launch.xml`
  - 노드 파라미터: `config/<노드명>.yaml`
  - 테스트: `test/test_<대상>.py` 또는 `test/test_<대상>.cpp`
- 패키지에는 소스와 설정만 둡니다. 대용량 파일(모델 가중치, rosbag, 데이터셋)은 커밋하지 않고 `docs/`에 받는 방법만 기록합니다.

### 3-2. Python 패키지 구조 (`ament_python`)
```
<proj>_vision/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/<proj>_vision      # 빈 마커 파일 (필수)
├── <proj>_vision/              # 소스 폴더명 = 패키지명
│   ├── __init__.py
│   ├── <기능>_node.py          # 노드 진입점 (얇게 유지)
│   └── <기능>_utils.py         # 순수 로직 (ROS 의존 최소화)
├── config/
├── docs/                       # 패키지 PRD 등 개별 문서
├── launch/
└── test/
```
- 노드 파일명은 `<기능>_node.py`, 클래스명은 `<Feature>Node`로 합니다.
- 새 노드는 `setup.py`의 `entry_points`(`console_scripts`)에 등록해야 `ros2 run`으로 실행됩니다.
- `launch/`, `config/` 폴더는 `setup.py`의 `data_files`에 등록해야 install 됩니다.
- 알고리즘 로직은 ROS 객체와 분리해 단독 테스트가 가능하게 작성합니다.

### 3-3. C++ 패키지 구조 (`ament_cmake`)
```
<proj>_control/
├── package.xml
├── CMakeLists.txt
├── include/<proj>_control/     # 헤더는 패키지명 하위 폴더에 둠
│   └── <기능>_node.hpp
├── src/
│   ├── <기능>_node.cpp
│   └── main.cpp                # 실행 파일 진입점
├── config/
├── docs/                       # 패키지 PRD 등 개별 문서
├── launch/
└── test/
```
- 헤더는 `include/<패키지명>/` 안에 두고 include guard는 `#pragma once`를 씁니다.
- 파일명은 `snake_case`, 클래스명은 `PascalCase`입니다.
- 새 실행 파일·라이브러리·`launch`/`config` install 규칙을 `CMakeLists.txt`에 등록합니다.

### 3-4. interfaces 패키지 (`<proj>_interfaces`)
팀이 함께 쓰는 **메시지 양식(약속)만 모아 두는 패키지**입니다. 
비전이 보낸 메시지를 주행이 알아들으려면 형식을 미리 정해 두어야 하기 때문입니다.

- `msg/`, `srv/`, `action/`, `docs/`와 스키마·생성 타입 검사를 위한 `test/`를 둘 수 있습니다. 실행 노드·장치 제어 코드는 넣지 않습니다. ament_cmake_pytest의 Python 시험은 런타임 언어 혼용으로 보지 않습니다.
- 파일명은 `PascalCase`입니다. (예: `DetectedObject.msg`, `MoveToPose.action`)
- 필드명은 `snake_case`로 쓰고, 단위를 주석으로 적습니다. (예: `float32 distance  # [m]`)
- 양식을 바꾸거나 지우면 이를 쓰는 모든 패키지가 영향을 받습니다. PR에 변경 내용을 적고, 팀에 알린 뒤 머지합니다.

### 3-5. bringup 패키지 (`<proj>_bringup`)
**전체 시스템을 한 번에 켜는 스위치** 역할을 하는 패키지입니다.

- 전체 실행은 `launch/bringup.launch.xml`, 시뮬레이션용은 `launch/sim.launch.xml`로 둡니다.
- 각 패키지의 launch 파일을 `<include>` 태그로 불러와 묶기만 합니다.
- 기능 코드(노드 로직)는 bringup 안에 넣지 않습니다.
- 팀 공통 설정값(네임스페이스, 공통 파라미터)은 `config/` 한곳에서 관리합니다.

### 3-6. 패키지 간 의존 규칙
**패키지끼리는 코드를 직접 가져다 쓰지 않고, 메시지로만 대화합니다.** 한 패키지를 수정해도 다른 패키지가 같이 고장 나지 않게 하기 위해서입니다.

- 모든 패키지는 `interfaces`를 참고할 수 있습니다. (`interfaces ← 각 기능 패키지`)
- 기능 패키지끼리는 서로 import하지 않고, **토픽·서비스·액션으로만** 통신합니다.
- `gui`와 `control_center`는 `interfaces`만 의존합니다. 로봇 내부 코드를 몰라도 메시지만 주고받으면 되기 때문입니다.
- A가 B를 쓰고 B도 A를 쓰는 순환 의존이 생기면, 둘이 같이 쓰는 부분을 `interfaces`로 옮깁니다.

### 3-7. 웹 화면 자원 (`cobot_gui`의 `web/`)
**브라우저로 보는 화면의 HTML·JS·CSS 파일을 두는 자리**입니다. 자리를 한곳으로 정해 두어야 화면 파일이 여러 패키지에 흩어지지 않습니다. (결정 D8 → [`docs/fms_decisions.md`](docs/fms_decisions.md#d8))

- `web/` 폴더는 `cobot_gui`(`ament_python`) 안에만 둡니다. 다른 패키지나 워크스페이스 최상위에는 만들지 않습니다.
- `web/`도 `launch/`, `config/`처럼 `setup.py`의 `data_files`에 등록해야 install 됩니다.
- `web/`의 파일은 install 때 복사만 되는 정적 파일입니다. 따로 빌드하지 않으므로 3-1의 '한 패키지 한 언어' 규칙은 그대로 지킵니다.
- 빌드 산출물(번들, 압축된 JS 등)은 커밋하지 않고 원본 파일만 커밋합니다.
- 외부 CDN 주소를 쓰지 않습니다. 현장은 인터넷 없이도 화면이 떠야 하기 때문입니다.
- 프론트엔드 라이브러리는 팀 허락을 받은 뒤에만, 버전을 고정해 `web/` 안에 복사(vendoring)해 둡니다. (9번의 새 의존성 규칙)
- 웹 서버용 파이썬 패키지(예: `fastapi`, `uvicorn`)도 새 의존성이므로 허락을 받은 뒤에 추가합니다.

## 4. 문서 관리
개발 과정에서 생기는 문서는 `docs/` 폴더에 저장하고, 범위에 따라 위치를 나눕니다.

### 4-1. 문서 위치
| 구분 | 위치 | 예시 |
|---|---|---|
| 패키지(역할)별 문서 | `src/<proj>_<역할>/docs/` | `src/<proj>_vision/docs/prd.md` |
| 팀 공통 문서 | 워크스페이스 최상위 `docs/` | `docs/prd_<proj>.md`, 토픽·TF·인터페이스 명세 |

- **개별 PRD는 해당 패키지 안에 `docs/prd.md`로 작성**하며, 담당자가 관리합니다.
- 프로젝트 전체 PRD와 여러 패키지에 걸친 문서(토픽·TF·`ROS_DOMAIN_ID` 등 명세)는 최상위 `docs/`에 둡니다.
- 그 외 패키지별 문서(설계, 실험 기록 등)는 `docs/<주제>.md`로 작성합니다.

### 4-2. 문서 작성 규칙
- 파일명은 소문자와 밑줄(`prd_vision.md`), 형식은 Markdown(`.md`)으로 통일합니다.
  - 이유: 형식이 같아야 누구나 열어 보고 Git에서 변경 내용을 비교할 수 있습니다.
- 코드나 인터페이스를 바꾸면 관련 문서도 같은 PR에서 함께 고칩니다.
  - 이유: 문서를 나중으로 미루면 실제 코드와 달라집니다.
- 패키지 PRD가 최상위 `docs/`의 공통 명세와 다르면 공통 명세를 따릅니다.
  - 이유: 패키지마다 기준이 다르면 서로 연결이 어긋납니다.
- 큰 파일(이미지, 데이터)은 커밋하지 않고 받는 방법만 적습니다.
  - 이유: 큰 파일이 쌓이면 저장소가 무거워집니다.
- Claude는 4-1에서 정한 위치에만 문서를 만들고, 만들기 전에 중복 문서가 있는지 확인합니다.
  - 이유: 문서가 여기저기 흩어지거나 같은 내용이 여러 개 생기는 것을 막습니다.

## 5. 빌드 · 실행 · 테스트
```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install                          # 전체 빌드
colcon build --symlink-install --packages-select <pkg>  # 특정 패키지만
colcon build --symlink-install --packages-up-to <pkg>   # 의존 패키지 포함
source install/setup.bash
colcon test --packages-select <pkg>
colcon test-result --verbose
ros2 launch <proj>_bringup bringup.launch.xml
```
- 코드 수정 후에는 반드시 해당 패키지를 빌드하고 테스트를 실행해 검증합니다.
- 린트: `ament_flake8`, `ament_pep257`, `ament_cpplint`, `ament_uncrustify` 모두 통과해야 합니다.
  - 린트는 코드를 실행하기 전에 스타일 규칙(들여쓰기, 줄 길이, 안 쓰는 import 등)을 자동으로 검사하는 도구입니다.
  - Python은 `ament_flake8`·`ament_pep257`, C++은 `ament_cpplint`·`ament_uncrustify`가 검사하며, `colcon test`를 실행하면 함께 돌아갑니다.
  - 오류는 `colcon test-result --verbose`로 확인하고, 고친 뒤 PR을 올립니다.
- 인터페이스(`interfaces`)를 수정했다면 의존하는 패키지까지 다시 빌드합니다.
- 도커로 빌드·시험하는 방법은 `docs/dev_docker_guide.md`를 봅니다. (도커를 처음 쓰는 사람도 이 문서부터 따라 하면 됩니다)

### `--symlink-install` 옵션
- `install/`에 파일을 복사하지 않고 원본(`src/`)을 가리키는 **바로가기(symlink)**를 만드는 옵션입니다.
- Python 코드, launch 파일, YAML 설정을 고치면 다시 빌드하지 않아도 바로 반영됩니다.
- 평소 개발은 이 옵션으로 빌드하고, 시연·배포용 빌드는 옵션 없이 합니다.
- 아래 경우에는 옵션을 써도 다시 빌드해야 합니다.
  - 새 파일이나 새 노드를 추가했을 때
  - `setup.py`, `package.xml`, `CMakeLists.txt`를 수정했을 때
  - C++ 코드를 수정했을 때 (컴파일이 필요하므로 옵션 효과 없음)
- 수정했는데 반영되지 않으면 `build/`, `install/`, `log/`를 지우고 다시 빌드합니다. (`rm -rf`는 사용자 확인 후 실행)

### 파이썬 환경
- 파이썬 패키지가 필요하면 `python3 -m venv --system-site-packages .venv`로 만든 가상환경을 사용합니다.
- 작업 전 `source .venv/bin/activate`, `colcon build`도 같은 환경에서 실행합니다.
- conda는 `rclpy`와 충돌할 수 있으므로 ROS2 작업 중에는 비활성화합니다.
- 시스템 파이썬에 `pip install` 하지 않습니다. (PEP 668)
  - PEP 668은 OS가 관리하는 파이썬에 pip로 마음대로 설치하지 못하게 막는 파이썬의 규칙

## 6. 코딩 컨벤션
- Python: PEP8 준수, 노드는 `rclpy.node.Node`를 상속한 클래스로 작성
  - PEP 8은 파이썬 코드를 어떻게 쓸지 정해 둔 공식 스타일 가이드
- C++: ROS2 스타일 가이드, `rclcpp::Node` 상속 클래스로 작성
- 네이밍: 패키지·노드·토픽·파일은 `snake_case`, 클래스는 `PascalCase`, 상수는 `UPPER_SNAKE_CASE`
- 로깅은 `self.get_logger()` / `RCLCPP_*` 매크로를 사용하고 `print`, `std::cout`은 쓰지 않습니다.
- 매직 넘버·하드코딩 금지: 값은 파라미터로 선언(`declare_parameter`)하고 YAML로 관리합니다.
- 주석은 <한국어/영어>로 작성하고, "무엇"보다 "왜"를 설명합니다.

## 7. ROS2 설계 규칙
- 토픽·서비스·액션 이름은 `/<namespace>/<name>` 형태의 소문자 `snake_case`
- 역할별 토픽 접두사 예: `/vision/...`, `/navigation/...`, `/manipulation/...`, `/control_center/...`
- GUI·관제가 별도 PC에서 실행되면 `ROS_DOMAIN_ID`와 네임스페이스 규칙을 `docs/`에 명시합니다.
- `ROS_DOMAIN_ID`: 실물 로봇 환경은 D2 설계 제안으로 `10`(실물 구동)과 `12`(Nav2)를 씁니다. 개발·시뮬레이션(가짜 발행기 포함)은 `100`을 쓰고 10·12에서 띄우지 않습니다. SR_v2 SR-19는 번호를 지정하지 않습니다. D2가 decided가 된 뒤 노드별 값은 `docs/fms_interfaces.md`를 따릅니다. 장치 없는 격리 스파이크는 100·101을 기본으로 쓰며, 10·12 시험은 네트워크·실물 장치와 격리한 명시적 검증으로만 허용합니다. (결정 D2 → [`docs/fms_decisions.md`](docs/fms_decisions.md#d2))
- QoS: 센서 데이터는 `SensorDataQoS`, 상태/설정성 데이터는 필요 시 `transient_local`을 명시
- launch 파일은 XML(`*.launch.xml`)로 통일합니다.
- 의존성 추가 시 `package.xml`과 `CMakeLists.txt`(또는 `setup.py`)를 **모두** 수정합니다.
- 좌표계(frame)는 REP-103/105를 따르고, TF frame 이름은 `docs/`에 정의된 것만 사용합니다.

## 8. Git · 협업 규칙
- 브랜치: 기준선 `main`, 통합 확인 `submaster`, 분야별 작업 `feature/<역할>` 또는 필요 시 `feature/<역할>-<내용>`, 버그는 `fix/<역할>-<내용>`. 기존 분야 브랜치를 유지하며 메뉴 번호를 팀 전체에 강제하지 않습니다. FMS 개별 메뉴 예약 형식은 R5를 따릅니다.
- 확정 흐름은 `담당 분야에서 작업 → submaster에서 함께 시험 → main 반영`입니다. 기존 분야 브랜치를 계속 사용하고 새 분야 브랜치는 최신 submaster에서 시작합니다. PR 대상은 submaster이며 기존 PR은 작성자가 확인 후 전환합니다. [핵심 규칙](docs/fms_branch_workflow.md)을 확인합니다.
- 브랜치 보호·필수 리뷰 설정은 아직 미완입니다. [관리자 적용 확인](docs/fms_repository_governance.md) 전까지 D16 전체 완료로 기록하지 않습니다.
- `main`에 직접 push 금지, 반드시 PR + 최소 1명 리뷰
- 커밋 메시지: Conventional Commits, scope에 패키지명 사용 (예: `feat(vision): 객체 검출 노드 추가`)
- `CODEOWNERS`로 패키지별 담당자를 지정하고, 담당 패키지 변경 시 담당자가 리뷰합니다.
- PR 전 체크리스트: 빌드 성공 / 테스트 통과 / 린트 통과 / 관련 문서 갱신

## 9. 금지 · 주의 사항
- 실제 로봇을 구동하는 코드·명령은 사용자 확인 없이 실행하지 않습니다.
- `sudo`, `rm -rf`, `apt install`, 시스템 전역 설정 변경은 사용자 확인 없이 하지 않습니다.
- 허락 없이 새 의존성을 추가하거나 msg/srv/action 인터페이스를 변경하지 않습니다. (팀 전체에 영향)
- `ROS_DOMAIN_ID`, 네트워크 설정, 비밀키/토큰은 임의로 변경하거나 커밋하지 않습니다.
- `build/`, `install/`, `log/` 및 담당 외 패키지는 요청 없이 수정하지 않습니다.
- 3번의 폴더·파일 배치 규칙을 벗어나는 새 폴더나 구조를 임의로 만들지 않습니다.

## 10. Claude 작업 방식

### 10-1. Plan 모드 (필수)
- 모든 작업은 **Plan 모드에서 계획을 먼저 작성하고, 사용자가 검토·승인한 뒤에** 진행합니다.
  - 대상: 코드 작성·수정, 파일 생성·삭제·이동, 설정 변경, 문서 작성, 빌드·실행 등
- 승인 전에는 읽기·조회(파일 읽기, 검색, 구조 파악)만 하고, 파일 수정·생성이나 명령 실행은 하지 않습니다.
- 계획에는 아래 내용을 포함합니다.
  1. 작업 목적과 범위
  2. 변경·생성할 파일 목록 (패키지 경로 포함)
  3. 영향받는 패키지와 인터페이스(msg/srv/action), 의존성 변경 여부
  4. 등록 절차 (`setup.py`/`CMakeLists.txt`, `package.xml`, `launch`/`config` install)
  5. 검증 방법 (빌드 → 테스트 → 린트)
  6. 실제 로봇 구동 여부와 위험 요소
- 승인된 범위를 벗어나는 변경이 필요하면 작업을 멈추고 계획을 수정해 다시 승인받습니다.
- **Plan 승인과 별개로 `sudo`, `rm -rf`, 로봇 구동(9번의 확인 대상 포함)은 실행 직전에 다시 확인받습니다.**
- 단순 질문이나 코드 설명처럼 파일을 바꾸지 않는 요청은 Plan 없이 답변합니다.
- 팀 공통 `.claude/settings.json`에 `"permissions": { "defaultMode": "plan" }`을 설정해 기본 모드를 Plan으로 합니다.

### 10-2. 작업 원칙
- 새 패키지·노드를 만들 때는 3번 구조와 등록 절차(`setup.py`/`CMakeLists.txt`, `package.xml`)를 빠짐없이 따릅니다.
- 변경 범위는 요청한 것에 한정하고, 관련 없는 리팩터링은 하지 않습니다.
- 수정 후에는 빌드 → 테스트 → 린트 순으로 검증하고 결과를 보고합니다.
- 응답과 설명은 한국어로 합니다.
- 불확실한 요구사항은 추측하지 말고 먼저 질문합니다.

## 규칙의 근거와 적용 상태

- SR 정본은 Confluence 5406727의 SR_v2 version 13입니다. `docs/fms_sr_reconciliation.md`에서 정본·설계 제안·실측을 구분합니다. 도메인 10/12·워치독 200 ms·시계 ±50 ms·팔 Z=280 mm는 정본의 고정값으로 인용하지 않습니다.
- main 보호·필수 리뷰·CODEOWNERS·CI는 선언과 활성화를 구분합니다. `docs/fms_repository_governance.md`에 관리자 적용 조건과 현재 미적용 상태를 적습니다.
- FMS 규칙은 팀 리뷰·결정·병합 뒤 적용합니다. 기존 브랜치의 독립 도구는 채택/이전/예외 결정을 먼저 하고, 이번 문서만으로 소급 삭제하거나 타인 브랜치를 수정하지 않습니다.
