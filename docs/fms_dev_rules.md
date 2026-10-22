# FMS 개발 공통 규칙 (R1~R10)

- 상태: 초안 (2026-10-22). 팀 리뷰 전이다.
- 대상: FMS 관제 대시보드와 거기에 붙는 모든 작업. 사람과 AI 에이전트 모두 따른다.
- 팀 공통 규칙의 정본은 [`CLAUDE.md`](../CLAUDE.md) 다. 이 문서는 그 위에 FMS 작업 규칙만 더한다. 겹치는 내용은 CLAUDE.md 를 따른다.
- 메뉴 목록: [`docs/fms_menu_tree.md`](fms_menu_tree.md) (자동 생성). 정본은 `src/cobot_gui/config/menu_tree.yaml` 이다.
- 단계와 순서: [`docs/fms_roadmap.md`](fms_roadmap.md)

## 왜 필요한가

여러 사람이 동시에 작업하면 이런 일이 생길 수 있다.

- 같은 기능이 여러 브랜치에서 따로 만들어진다.
- 한 브랜치에 여러 서브시스템이 섞인다.
- 합의 전의 메뉴가 문서에 들어가고, 문서마다 메뉴 수가 달라진다.

그래서 모든 작업을 메뉴 ID 나 인터페이스 하나에 붙인다. 메뉴마다 담당·단계·상태를 레지스트리에 미리 적어 둔다.

## 규칙 요약

| # | 규칙 | 한 줄 요약 |
|---|---|---|
| R1 | 작업 단위 | 메뉴 ID 또는 인터페이스 하나. 레지스트리에 없는 화면·도구는 만들지 않는다. |
| R2 | 담당 분리 | 화면은 GUI 담당, 데이터 계약은 도메인 담당. |
| R3 | 인터페이스 먼저 | 새 데이터는 `cobot_interfaces` PR 이 머지된 뒤 구현한다. |
| R4 | 위치 | 레포 루트에 독립 도구·소스 폴더를 만들지 않는다. |
| R5 | 브랜치·PR | `feature/<역할>-<메뉴ID>-<내용>`, 한 브랜치 = 한 메뉴. 레지스트리·공용 PR 은 `registry`·`common`. |
| R6 | SR 인용 | SR 의 뜻을 바꾸지 않는다. |
| R7 | 안전 | 장치를 여는 코드는 장치 담당 패키지에만. 웹·도구는 로봇 토픽을 발행하지 않는다. |
| R8 | AI 에이전트 | 같은 규칙. 계획 승인, 자기 브랜치, 검사 로그. |
| R9 | 비밀값 | 비밀값·실IP·개인 경로를 커밋하지 않는다. |
| R10 | 문서 | 문서 위치는 CLAUDE.md §4. 메뉴 표는 생성 문서만 쓴다. |

## R1. 작업 단위 = 메뉴 ID 또는 인터페이스 하나

- 규칙: 모든 작업은 레지스트리의 메뉴 ID 하나, 또는 `cobot_interfaces` 의 인터페이스 하나에 붙는다. 레지스트리에 없는 화면·도구는 만들지 않는다. 새 메뉴가 필요하면 레지스트리 PR 을 먼저 낸다. 이 PR 은 관제·GUI 담당이 리뷰한다.
- 이유: 같은 기능이 두 브랜치에 따로 생길 수 있다. 레지스트리에 먼저 올리면 리뷰에서 겹침이 보인다.
- 예시: '전체 로봇 현황 카드' 작업은 메뉴 1.1 이다. '녹화 도우미 화면' 을 새로 만들고 싶으면 먼저 레지스트리 PR 로 메뉴를 제안한다.

## R2. 화면 담당과 데이터 담당을 나눈다

- 규칙: 메뉴마다 화면 담당(`screen_owner`)과 데이터 담당(`data_owner`)이 있다. 도메인 담당(주행·팔·비전)은 토픽·메시지 계약을 낸다. 화면은 GUI 담당이 만든다. 도메인 담당이 따로 웹 화면이나 대시보드를 만들지 않는다.
- 이유: 도메인 담당이 각자 화면을 만들면 같은 화면이 둘 생긴다.
- 예시: 2.2 로봇별 주행 상태. 주행 담당은 RobotStatus 에 필요한 필드를 계약으로 낸다. GUI 담당은 그 계약을 읽는 인스펙터 패널을 만든다.

## R3. 인터페이스 먼저

- 규칙: 새 데이터가 필요하면 `cobot_interfaces` PR(또는 `docs/` 의 계약 초안)이 머지된 뒤 구현한다. msg/srv/action 변경은 CLAUDE.md §3-4·§9 를 따른다 (PR, 팀 공지, 1명 리뷰).
- 이유: 인터페이스 초안(미병합 브랜치의 fleet_msgs)의 명령 메시지에는 epoch·TTL 이 없다. 그래서 SR-20 명령 유효성 검증 및 구 권한 차단 기능을 표현하지 못한다.
- 예시: 5.6 이 CommandAck 를 써야 한다. 먼저 CommandAck.msg PR 을 내고, 머지된 뒤 5.6 을 만든다.

## R4. 위치

- 규칙: 레포 루트에 독립 도구·소스 폴더를 만들지 않는다. 코드와 도구는 `src/cobot_*` 패키지 안에, 문서는 CLAUDE.md §4 의 자리에 둔다. 새 자리가 필요하면 CLAUDE.md 구조도 개정 PR 을 먼저 낸다 (CLAUDE.md §2, §9).
- 예외: `.github/`(PR 템플릿, CLAUDE.md §8 의 CODEOWNERS)와 `.gitattributes` 같은 저장소 설정은 루트에 둔다.
- 참고: S0 PR 은 CLAUDE.md §2 구조도·담당표를 고치지 않았다. `cobot_gui` 는 §2 의 `<proj>_gui` 자리이고, 접두사 `cobot_` 확정(D1) 뒤에 §2 를 고친다.
- 이유: 루트에 도구 폴더가 생기면 CLAUDE.md §2 구조와 어긋나고 담당과 리뷰가 흐려진다.
- 예시: 화면 정적 파일(HTML/JS)을 둘 자리는 아직 정하지 않았다 (D8). 정해지기 전에는 만들지 않는다.

## R5. 브랜치·PR

- 규칙:
  - 브랜치 이름은 `feature/<역할 키>-<메뉴 ID>-<내용>` 이다. 버그는 `fix/<역할 키>-<메뉴 ID>-<내용>`. 역할 키는 레지스트리 `roles` 의 키다 (`vision`, `navigation`, `manipulation`, `control_center`, `gui`, `common`). CLAUDE.md §8 의 `feature/<역할>-<내용>` 에 메뉴 ID 를 더한 것이다.
  - main 에 직접 push 하지 않는다. 남의 브랜치에 push 하지 않는다.
  - PR 은 1명 이상 리뷰 + 그 메뉴의 화면·데이터 담당 리뷰를 받는다.
  - 한 브랜치에는 한 메뉴 또는 한 인터페이스만 담는다.
  - 예외: 레지스트리·규칙 문서 PR 은 메뉴 ID 자리에 `registry` 를, 여러 메뉴가 같이 쓰는 틀 PR 은 `common` 을 쓴다. 이런 PR 은 여러 메뉴를 함께 다뤄도 된다.
  - 커밋은 CLAUDE.md §8 (Conventional Commits) 을 따른다. 메시지에 메뉴 ID 와 SR ID 를 적기를 권한다 (Git 규칙 단일화 D16 전까지 권고).
- 이유: 한 브랜치에 여러 서브시스템이 섞이면 리뷰와 되돌리기가 어렵다.
- 예시: 브랜치 `feature/gui-1.1-robot-cards`, 커밋 `feat(gui): 1.1 로봇 카드 틀 추가 (SR-06)`. 인터페이스는 `feature/common-command-ack-msg`. 레지스트리는 `feature/gui-registry-menu-tree`.

## R6. SR 은 인용만 한다

- 규칙: SR ID 의 뜻을 바꾸지 않는다. 레지스트리 `sr` 에는 SR v5.0 의 ID 만 쓴다. SR v5.0 에 없는 ID 는 `sr_unconfirmed` 에 둔다. 메뉴 트리 원문과 매핑이 다르면 `sr_original` 에 원문 값을, 메모에 이유를 적는다. 뜻을 바꿔야 하면 SR 개정 PR 을 낸다.
- 검사: 검사기(`menu_registry.py`)와 시험이 SR 사본의 ID·이름·우선순위·순서를 고정 사본과 대조한다. YAML 만 고쳐서 SR 을 늘리거나 이름을 바꾸면 실패한다.
- 이유: SR ID 가 다른 뜻으로 쓰이면 추적이 깨진다. 예를 들어 브라우저 콘솔 잠금은 SR-19 네트워크 분리 및 단일 제어권 관리 기능의 단일 기록자가 아니다.
- 예시: 6.5 의 'SR-22' 는 SR v5.0 에 없어서 `sr_unconfirmed` 에 있다 (D17).

## R7. 안전

- 규칙:
  - 모터·시리얼·카메라를 여는 코드는 그 장치 담당 패키지 안에서만 쓰고 담당 리뷰를 받는다.
  - 웹·도구는 로봇 토픽을 발행하지 않는다. 로봇 명령은 관제 코어 한 곳에서만 나간다.
  - 실물 로봇을 움직이는 실행은 CLAUDE.md §9·§10-1 대로 실행 직전에 사용자 확인을 받는다.
- 이유: 장치 제어 코드가 리뷰 경로 밖에 있거나 인증 없이 열려 있으면 사람이 다칠 수 있다.
- 예시: 화면의 정지 버튼은 관제 코어에 요청만 보낸다. 실제로 멈추는 것은 로봇 쪽 가드와 HW 릴레이다.

## R8. AI 에이전트도 같은 규칙을 따른다

- 규칙: 아래 'AI 에이전트 작업 규칙' 을 따른다.
- 이유: 검사 로그가 없는 '호환된다' 보고는 아무도 확인할 수 없다.

## R9. 비밀값·실IP·개인 경로를 커밋하지 않는다

- 규칙: 토큰·비밀번호·키, 실제 IP 주소, 개인 PC 경로를 커밋하지 않는다 (CLAUDE.md §9 재확인). 예시 설정에는 자리표시자를 쓴다.
- 이유: 개발용 기본 키라도 커밋하면 공개 이력에 남는다.
- 예시: `api_key: <레포 밖 설정 파일에서 읽는다>` 는 된다. 실제 키 값이나 실제 주소는 안 된다.

## R10. 문서 위치·이름

- 규칙: 문서 위치와 이름은 CLAUDE.md §4 를 따른다. 메뉴 표는 생성 문서(`docs/fms_menu_tree.md`)만 쓴다. 다른 문서에 메뉴 표를 손으로 베끼지 않고 링크를 건다.
- 이유: 메뉴 수가 문서마다 33·34 로 어긋났다.

## 새 메뉴·기능을 시작하는 순서

레지스트리 PR → 계약 → 구현 순서로 한다.

1. 레지스트리를 읽는다. 메뉴가 있는지, 단계(`phase`)·담당·기다리는 결정(`decisions`)을 본다.
2. 앞 단계 출구 검사가 통과했는지, 기다리는 결정이 정해졌는지 본다 (`docs/fms_roadmap.md`).
3. 레지스트리 PR 을 낸다.
   - 새 메뉴면 메뉴를 추가한다. 관제·GUI 담당이 리뷰한다.
   - 있는 메뉴면 `status: in_progress` 와 `branch` 를 적어 선점한다.
   - 생성기를 돌려 생성 문서도 같은 PR 에 넣는다.
4. 계약 PR 을 낸다. 새 데이터가 필요하면 `cobot_interfaces` PR(또는 `docs/` 의 계약 초안)을 내고 데이터 담당·팀 리뷰 뒤 머지한다.
5. 구현 PR 을 낸다. 브랜치는 `feature/<역할>-<메뉴ID>-<내용>`. 빌드·시험·린트가 통과해야 한다.
6. 마무리로 `status: done` 을 적고 검사 로그를 붙인다. 구현 PR 에 같이 넣어도 된다.

## PR 체크리스트

PR 템플릿 `.github/pull_request_template.md` 와 같다. CLAUDE.md §8 의 체크리스트(빌드·시험·린트·문서)를 포함한다.

- [ ] 메뉴 ID 또는 인터페이스 하나
- [ ] 레지스트리 상태 갱신, 생성 문서 재생성 (`--check` 결과 0)
- [ ] 레지스트리를 고쳤다면 `check_menu_tree` 오류 0, `test_menu_registry.py` 통과
- [ ] 인터페이스 변경 여부, 변경했다면 팀 공지
- [ ] SR 은 ID 와 이름을 그대로 인용
- [ ] 안전: 모터·시리얼·카메라를 여는지, 로봇 토픽을 발행하는지
- [ ] 빌드·시험·린트 결과 (실제 출력)
- [ ] 관련 문서 갱신
- [ ] 비밀값·실IP·개인 경로 없음

## AI 에이전트 작업 규칙

CLAUDE.md §10 (Plan 모드 필수, 승인 범위 안에서만 작업) 을 먼저 따른다. 여기에 아래를 더한다.

1. 작업 전에 이 문서, 레지스트리(`src/cobot_gui/config/menu_tree.yaml`), 로드맵을 읽는다.
2. 계획에 메뉴 ID(또는 인터페이스)와 단계를 적는다. 레지스트리에 없는 메뉴나 다른 브랜치가 `in_progress` 로 잡은 메뉴는 시작하지 않고 사용자에게 묻는다.
3. 자기 브랜치에만 쓴다. main 이나 남의 브랜치에 push 하지 않는다.
4. 토큰·비밀번호·키를 다루지 않는다. 필요하면 사람에게 넘긴다.
5. 실물 로봇·장비에 접속하거나 구동하는 일은 실행 직전에 사용자 확인을 받는다 (CLAUDE.md §9, §10-1).
6. `docs/fms_menu_tree.md` 를 손으로 고치지 않는다. 레지스트리를 고치고 생성기를 돌린다.
7. '완료'·'호환' 을 말할 때는 실제로 돌린 명령과 출력(빌드·시험·린트 로그)을 붙인다. skip 된 시험은 통과로 치지 않는다.
8. SR 의 뜻을 바꾸지 않는다. 판단이 들어간 값에는 '초안' 이라고 적는다.

## 레지스트리 수정 방법

레포 루트(또는 그 아래 폴더)에서 한다. 도구가 레지스트리를 `src/cobot_gui/config/` 에서 찾고 문서를 `docs/` 에 쓰기 때문이다. 다른 곳에서는 `--registry`·`--root` 를 준다.

1. `src/cobot_gui/config/menu_tree.yaml` 을 고친다. 필드 설명은 파일 머리 주석에 있다. 메뉴 ID 는 따옴표로 감싼다 (`'1.1'`). 파일은 UTF-8 로 저장한다.
2. 검사한다. 오류가 0 이어야 한다. 빈 담당 칸은 경고만 나온다. 메뉴 목록과 SR 사본은 고정 사본과도 대조한다.

   ```bash
   PYTHONPATH=src/cobot_gui python3 -m cobot_gui.menu_registry
   ```

3. 생성 문서를 다시 만든다.

   ```bash
   PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_menu_doc
   PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_menu_doc --check   # 0 이어야 한다
   ```

4. 시험을 돌린다.

   ```bash
   PYTHONPATH=src/cobot_gui python3 -m pytest src/cobot_gui/test/test_menu_registry.py
   ```

5. ROS 환경에서는 이렇게 한다 (CLAUDE.md §5).

   ```bash
   source /opt/ros/jazzy/setup.bash
   colcon build --symlink-install --packages-select cobot_gui
   source install/setup.bash
   ros2 run cobot_gui check_menu_tree
   ros2 run cobot_gui gen_menu_doc
   colcon test --packages-select cobot_gui
   colcon test-result --verbose
   ```

6. YAML 과 생성 문서를 같은 PR 에 넣는다.

주의:

- 메뉴를 더하거나 빼거나 이름을 바꾸면 `src/cobot_gui/cobot_gui/menu_registry.py` 의 `AGREED_MENUS` 와 `src/cobot_gui/test/test_menu_registry.py` 의 `AGREED_MENUS`·`ORIGINAL_SR` 도 같은 PR 에서 고친다. 원문 메뉴 트리 개정과 함께 한다.
- SR 이 개정되면 `menu_registry.py` 의 `SR_V5`, YAML 의 `sr_catalog`, 시험의 `AGREED_SR` 를 같은 PR 에서 고친다.
- 메뉴의 단계나 단계 이름을 바꾸면 `docs/fms_roadmap.md` 의 단계 제목과 '포함 메뉴' 줄도 고친다. 시험이 둘을 대조한다.
- 두 레지스트리 PR 이 충돌하면 생성 문서는 손으로 합치지 않는다. YAML 만 합친 뒤 생성기를 다시 돌린다.
- 생성 문서의 줄 끝은 LF 다. `.gitattributes` 가 이 파일만 LF 로 고정한다. 그래서 Windows 의 `core.autocrlf=true` 에서도 CRLF 로 바뀌지 않는다. 레포 전체의 줄 끝 규칙은 팀이 정한다.
