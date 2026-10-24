# FMS 웹 화면 골격 — 팀 레포로 옮기는 에이전트용 안내

> **이 폴더(`handoff/`)는 팀 레포로 가져가지 않는다.** 개인 레포 이름과 진행 메모가 들어 있다.
> 작성: 2026-10-23, 관제/GUI 담당의 지시 "개인 프라이빗 레포에 먼저 반영하고, 다른 에이전트가 복사해서 팀 레포에 올린다".
> 팀 레포 규칙(CLAUDE.md §10-1): Plan 승인 뒤 작업, 푸시와 머지는 사용자 확인마다. **이 안내는 승인이 아니다.**

## 1. 무엇이 있나

개인 레포 `rkd1rjs2/robot_mini_project_pinky` 의 브랜치 두 개다.

| 개인 레포 브랜치 | 팀 레포에서의 자리 | 내용 |
|---|---|---|
| `claude/fms-web-shell` | 새 브랜치 `feature/gui-common-web-shell` (기준: `feature/gui-registry-s1-decisions`, 팀 `da639af`) | 아래 커밋 4개 |
| `claude/fms-map-contract` | PR #3 `feature/common-map-contract` 에 커밋 1개 추가 | 지도 문서·주석의 SR-08 ±5 cm 표기 정정 (`41265ed`) |

`claude/fms-web-shell` 의 커밋 (팀 `da639af` 위에 쌓였다):

1. `ca410ec` 3.7 = 팀원 녹화 앱 채택, 레지스트리 `impl`(구현도) 칸 추가, 로드맵 §6 구현 현황. → **팀 PR #6 에 추가할 커밋**이다. 웹 골격과 별개다.
2. `c43e840` D8 문구: 웹 빌드(Node/npm)와 `web/dist` 설치 포함.
3. `feb4aa6` 웹 골격 (`src/cobot_gui/web/`), 생성기, 시험, CI, 문서.
4. `2572bf7` 루트 `.gitignore` 의 `lib/` 규칙이 `web/src/lib` 를 가리지 않게 함.

## 2. 가져가는 방법

**가) git 으로 (권장)** — 이력이 남는다.

```bash
cd <팀 레포 클론>
git remote add personal https://github.com/rkd1rjs2/robot_mini_project_pinky.git   # 비공개 레포. 인증이 필요하다
git fetch personal claude/fms-web-shell claude/fms-map-contract
git switch -c feature/gui-common-web-shell origin/feature/gui-registry-s1-decisions
git cherry-pick ca410ec c43e840 feb4aa6 2572bf7
git remote remove personal        # 개인 레포 주소를 팀 레포 설정에 남기지 않는다
```

`ca410ec` 는 PR #6 브랜치(`feature/gui-registry-s1-decisions`)에도 필요하다. 사용자가 PR #6 에 따로 올리라고 하면 그 브랜치에서 `git cherry-pick ca410ec` 를 한 뒤, 웹 골격 브랜치를 그 위로 다시 만든다.

**나) 파일 복사로** — 아래 목록을 같은 경로에 복사한다. 목록은 `git diff --name-status da639af claude/fms-web-shell -- . ':!handoff'` 로 뽑는다. 바꾼 기존 파일은 덮어쓰지 말고 이 브랜치의 diff 를 적용한다 (`.gitattributes`, `.github/workflows/fms-contract.yml`, `docs/fms_decisions.md`, `docs/fms_menu_tree.md`, `src/cobot_gui/config/menu_tree.yaml`, `src/cobot_gui/setup.py`, 시험 파일).

## 3. 팀 레포에서 해야 할 일 (이 브랜치로는 못 하는 것)

1. **CLAUDE.md §3-7 개정** (PR #5 `feature/common-team-rules-s1`). 지금 초안은 "따로 빌드하지 않는다·빌드 산출물은 커밋하지 않는다·프론트 라이브러리는 vendoring" 이라 웹 골격과 부딪힌다. 이렇게 고친다:
   - "`web/` 폴더는 웹 화면 **소스**를 둔다 (React·Vite). `cobot_gui`(`ament_python`) 안에만 둔다."
   - "빌드 결과 `web/dist` 만 `setup.py` 의 `data_files` 로 install 한다. `web/dist`, `node_modules/` 는 커밋하지 않는다."
   - "`web/` 의 TypeScript 는 브라우저 화면 소스이고 ROS 실행 코드가 아니다. 실행 코드의 언어는 패키지 언어(Python) 하나다."
   - "설치는 `package-lock.json` 으로 고정하고 `npm ci` 로만 한다. 새 npm 패키지는 팀 허락을 받고 `docs/fms_web_dependencies.md`(자동 생성)에 오른다."
   - "외부 CDN 주소를 쓰지 않는다 (유지)."
   - §5 에 웹 빌드 명령(`docs/fms_web_shell.md` §5)을 한 줄 더한다.
2. **Node/npm 사용 허락.** 사용자(관제 담당)가 팀을 설득한다. 허락 전에는 머지하지 않는다.
3. **S1 공지 전에 D8 문구 확인.** 공지 초안의 D8 줄은 이 브랜치의 `docs/fms_decisions.md` 와 맞춰져 있다.
4. 3.7 앱 소스 이동은 **팀원이 자기 브랜치에서** 한다 (`git mv omx_recoder src/cobot_manipulation/omx_recorder`). 우리가 하지 않는다. 3.7 화면은 소스가 옮겨지기 전에도 정상이다.

## 4. 올리기 전 확인

팀 레포 클론에서, 이 순서로 모두 통과해야 한다. 실패하면 올리지 말고 사용자에게 보고한다.

```bash
cd src/cobot_gui/web
npm ci && npm run lint && npm test && npm run build && npm run check:dist && npm run check:deps
cd ../../..
PYTHONPATH=src/cobot_gui python3 -m pytest -q -p no:cacheprovider \
  src/cobot_gui/test/test_menu_registry.py src/cobot_gui/test/test_rule_boundaries.py src/cobot_gui/test/test_gen_web_menus.py
PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_menus --check
PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_menu_doc --check
```

그리고 **Jazzy 컨테이너에서 `colcon build --packages-select cobot_gui` 와 `colcon test --packages-select cobot_gui`** 를 돌린다 (ament flake8·pep257·copyright 시험은 ROS 환경에서만 돈다). 개인 환경에서는 flake8·pydocstyle 근사 검사만 했고 이 시험은 돌리지 못했다.

이 브랜치에서 이미 확인한 것 (2026-10-23, 새로 clone 한 곳에서 `npm ci` 부터):

| 항목 | 결과 |
|---|---|
| `npm ci` | 401개 패키지 설치 (실행 번들 61, 도구 340) |
| `npm run lint` | 오류 없음 |
| `npm test` | 3개 파일 47개 통과 (메뉴 34개 전부 열림, 3.7 화면, 오프라인 검사, 음성 대조) |
| `npm run build`, `check:dist` | 통과, 번들 약 345 kB (gzip 110 kB), 외부 참조 없음 |
| Python 시험 | 59개 통과 (레지스트리, 규칙 경계, 생성기) |
| 브라우저 | 데스크톱·폰 폭(375 px)에서 개요, 3.7, 명령 메뉴(1.4) 확인 |

아직 안 한 것: ROS 컨테이너의 `colcon test`, GitHub Actions 실행(`fms-web` 작업은 `docker run node:22.14.0-bookworm` 으로 처음 돌려 보는 것이다), 팀원 환경에서의 `npm ci`.

## 5. 하지 말 것

- `main`·다른 사람의 브랜치를 바꾸지 않는다. 머지하지 않는다 (사용자 확인마다).
- `node_modules/`, `web/dist/` 를 커밋하지 않는다.
- 이 `handoff/` 폴더, 개인 레포 이름·주소, 홈랩 내부 주소를 팀 레포에 넣지 않는다.
- 홈랩 소스를 더 가져오지 않는다. 가져온 것은 공용 부품 10개와 `cn` 유틸뿐이고, 업무 페이지는 하나도 없다.
- Draft PR 로 올린다. PR 본문에 위 §4 결과를 그대로 옮긴다.

## 6. 알아 둘 문제

- 노트북의 npm 11.3 은 `package-lock.json` 없이 `npm install` 하면 `Cannot read properties of null (reading 'edgesOut')` 로 실패했다 (jsdom 피어 해석 버그). **항상 `npm ci`** 를 쓴다. lock 파일은 커밋돼 있다.
- Windows(`core.autocrlf=true`)에서 생성 파일 비교가 어긋나지 않도록 `.gitattributes` 에 `menus.ts`, `fms_web_dependencies.md`, `package-lock.json` 의 LF 고정을 넣었다.
- 루트 `.gitignore` 의 `lib/` 규칙이 `web/src/lib` 를 가렸던 것이 새 clone 검증에서 드러났다. 고쳤다 (`2572bf7`).
- 이 골격은 읽기 전용이다. 명령을 보내는 화면과 서버(게이트웨이) 연결은 S2 이후다.

## 7. W2 (타입·모의 데이터·참고 화면) — 개인 레포 브랜치 `claude/fms-web-w2`

W0 위에 쌓은 브랜치다 (기준: `claude/fms-web-shell` `6e637f6`).

| 커밋 | 내용 | 가져가나 |
|---|---|---|
| `c288c4b` | **개발용 병합.** `cobot_interfaces`(PR #2) 파일을 이 브랜치에 들여온 병합 커밋 | **가져가지 않는다** |
| `df02f00` | `gen_web_types.py`(+시험 13개), `generated/messages.ts`, `mock/*.json` 30개, setup.py 진입점, CI 단계 | 가져간다 |
| `a85ef69` | `useMessages` 훅, 참고 화면 1.1·1.4·2.1·4.1·6.2, 3.7 타입 적용, 개요의 데이터 계약 열, 시험, 문서 | 가져간다 |
| `3cd222e` | `messages.ts` 를 LF 로 고정(.gitattributes) | 가져간다 |

**순서 조건.** W2 는 `src/cobot_interfaces`(PR #2)가 같은 트리에 있어야 돈다. 팀 레포에서는 PR #2 가 들어간 브랜치 위에 W0 커밋 → W2 커밋 순으로 쌓는다. `cherry-pick df02f00 a85ef69 3cd222e` 만 한다 (`c288c4b` 제외).

**W2 가 한 일**
- 메시지 정의 → TS 타입: float 는 `Float = number | null`(NaN 은 JSON 에서 null). 미측정 값을 0 으로 보이지 않는다.
- 모의 데이터 30개가 정의와 맞는지 `--check` 가 본다 (키 이름, 값 종류, 정수 범위, `위 X_* 중 하나` 주석의 상수 값). 어긋나면 종료 1.
- 사람이 쓴 시나리오: `RobotStatus`·`ArmStatus`·`ArmMode`·`AlarmEvent`·`MapInfo`·`DiagSnapshot`·`CameraHealth`·`MediaHealth`. `MapInfo` 의 지점은 `approach_poses.yaml` 의 실제 값이다. 나머지 22개는 영 값이다.
- `DiagSnapshot` 의 장비 주소는 문서용 주소(192.0.2.x, RFC 5737)다. 실제 주소가 아니다.

**확인한 것 (2026-10-23, 새 clone `feature/gui-web-w2` 에서 `npm ci` 부터)**

| 항목 | 결과 |
|---|---|
| `npm ci` / lint / tsc | 401개 설치, 오류 없음 |
| `npm test` | 11개 파일 75개 통과 |
| 일부러 망가뜨림 | 배터리 모의 값을 0 으로 바꾸면, 퇴피 측정 여부를 무시하면 시험이 실패한다 |
| `npm run build`, `check:dist`, `check:deps` | 통과 (번들 약 348 kB, 외부 참조 없음) |
| Python 시험 | 72개 통과 (레지스트리, 규칙 경계, 메뉴 생성기, 타입 생성기) |
| `gen_web_menus --check`, `gen_web_types --check` | 일치 (모의 데이터 30개 통과) |
| flake8 근사(google import 순서, 작은따옴표, 99자) | 새 파이썬 파일 깨끗함 |
| 브라우저 | 2.1(지도), 1.1(카드) 눈으로 확인 |

**아직 안 한 것:** ROS 컨테이너 `colcon test`(ament lint), Actions 의 `fms-web` 첫 실행, 팀 CI 에서 `gen_web_types --check` (PR #2 가 있어야 돈다), 팀원의 화면 작성.
