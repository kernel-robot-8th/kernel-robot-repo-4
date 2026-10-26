# FMS 웹 화면 골격

- 상태: 초안 (2026-10-23). 결정 D8(웹 화면 소스·빌드 결과 위치)과 Node/npm 사용 허락이 `proposed`/미결이다. 팀 허락 전에는 머지하지 않는다.
- 위치: `src/cobot_gui/web/` (CLAUDE.md §3-7). 단계: 로드맵 S2 앞의 화면 골격(W0~W2). 규칙은 `docs/fms_dev_rules.md` 를 따른다.
- 이 앱은 **읽기 전용**이다. 로봇에 아무것도 보내지 않는다. 명령이 있는 메뉴 9개(1.4, 1.5, 2.4, 4.2, 4.4, 5.1, 5.2, 5.3, 5.4)의 틀 페이지에는 "게이트웨이 연결 전에는 비활성" 안내가 뜬다.

## 1. 무엇이 되는가

메뉴 트리 34개가 모두 클릭되는 웹 화면이다. 메뉴 이름·순서·화면(①~⑧)·단계·SR·결정·담당·구현도는 레지스트리(`src/cobot_gui/config/menu_tree.yaml`)에서 가져온다. 화면이 아직 없는 메뉴는 **틀 페이지**가 대신 열리고, 담당자가 자기 메뉴 폴더에 `Page.tsx` 를 만들면 그 화면이 틀을 대신한다.

| 주소 | 내용 |
|---|---|
| `/` | 개요: 메뉴 34개와 구현도(레지스트리 `impl`, 웹 화면 유무), 결정 현황 |
| `/menus/<메뉴 ID>` | 메뉴 하나. 예: `/menus/1.1`, `/menus/3.7` |

## 2. 폴더

```
src/cobot_gui/
  cobot_gui/gen_web_menus.py      레지스트리 → web/src/generated/menus.ts (--check)
  web/
    package.json  package-lock.json  vite.config.ts  tsconfig*.json  eslint.config.js
    scripts/dist-check.mjs        빌드 결과에 외부 참조가 없는지 본다
    scripts/gen-dependencies.mjs  package-lock.json → docs/fms_web_dependencies.md
    src/
      components/ui/              공용 부품 10개 (홈랩 관리자 화면과 같은 모양)
      components/layout/          Layout, Sidebar (메뉴 트리 사이드바, 모바일은 Sheet)
      lib/                        utils, api(fetchAPI), dataSource(useResource·useMessages), registry, contracts, format, tones
      shell/                      types, 틀 페이지, 라우트 연결(pages.ts), 개요, MenuHeader, ResourceSection, Pill, Measured
      generated/menus.ts          생성 파일(레지스트리). 직접 고치지 않는다
      generated/messages.ts       생성 파일(cobot_interfaces 의 msg·srv·action). 직접 고치지 않는다
      mock/<메시지 이름>.json     메시지마다 모의 데이터 배열 하나 (정의와 맞는지 시험이 본다)
      menus/<ID의 . 를 _ 로>/     메뉴 하나가 폴더 하나 (Page.tsx)
      menus/_template/            복사용 틀
```

## 3. 규칙

1. **레지스트리가 정본이다.** 메뉴 이름·순서·화면·단계는 `menu_tree.yaml` 만 고친다. 고친 뒤에는 `python3 -m cobot_gui.gen_web_menus` 로 `menus.ts` 를 다시 만든다. CI 가 `--check` 로 어긋남을 잡는다.
2. **메뉴 하나가 폴더 하나다.** 메뉴 폴더는 `components/ui`, `lib`, `shell/types`, `shell/MenuHeader` 만 가져다 쓴다. 다른 메뉴 폴더를 가져다 쓰지 않는다.
3. **라우터와 사이드바를 고치지 않는다.** `menus/<ID>/Page.tsx` 가 생기면 `shell/pages.ts` 가 찾아서 틀 페이지 대신 쓴다. 담당자끼리 같은 파일을 고치지 않는다 (규칙 R1·R2).
4. **데이터는 `useMessages('<메시지 이름>')` 한 가지 길로 읽는다.** 타입은 `generated/messages.ts` 에서 오고, 값은 대상 하나(로봇·팔·카메라)마다 하나씩 든 배열이다. 기본은 모의 데이터(`VITE_DATA=mock`)다. 서버가 붙으면(S2) `VITE_DATA=gateway` 로 바뀌어 `/api/fms/<이름>` 을 읽는다. 서버를 직접 부르는 코드를 메뉴 폴더에 쓰지 않는다. 인터페이스 정의가 없는 값(예: `DatasetSummary`)만 `useResource` 와 화면 안의 임시 모의 값을 쓰고, 그렇다고 화면에 적는다.
5. **명령 버튼은 만들지 않는다.** 게이트웨이(S2)와 안전 검토 전까지 팔·핑키에 무언가를 보내는 화면은 없다.
6. **외부 주소를 쓰지 않는다** (CLAUDE.md §3-7). 글꼴·아이콘은 번들에 넣는다. 소스 시험(`offline.test.ts`)과 빌드 결과 검사(`npm run check:dist`)가 막는다.
7. **색은 `index.css` 의 토큰으로만 쓴다.** 토큰 이름은 홈랩 관리자 화면과 같고(`--color-background` 등) 값은 팀 것이다.
8. **새 npm 패키지는 허락을 받는다** (CLAUDE.md §9). 허락 목록은 `docs/fms_web_dependencies.md` 에 자동 생성된다.

## 4. 메뉴 화면 만들기

1. `menus/_template/` 를 `menus/<ID의 . 를 _ 로>/` 로 복사한다 (예: 메뉴 1.1 → `menus/1_1/Page.tsx`).
2. `useResource` 와 모의 값으로 화면을 만든다. `MenuHeader` 를 맨 위에 둔다.
3. 시험을 같은 폴더에 둔다 (`Page.test.tsx`). 브랜치 이름은 `feature/<역할>-<메뉴 ID>-<설명>` 이다 (R5).

## 5. 개발·시험·빌드

Node 22 가 필요하다. ROS 개발 이미지에는 넣지 않는다. 노트북에 Node 가 없으면 컨테이너로 한다.

```bash
cd src/cobot_gui/web
npm ci                  # 처음 한 번. package-lock.json 대로만 설치한다
npm run dev             # 개발 서버
npm run lint && npm test
npm run build && npm run check:dist   # web/dist 만들기 (커밋하지 않는다)
```

```bash
docker run --rm -v "$PWD":/repo -w /repo/src/cobot_gui/web node:22.14.0-bookworm \
  sh -c "npm ci && npm run lint && npm test && npm run build && npm run check:dist"
```

`web/dist` 는 `setup.py` 의 `data_files` 가 `share/cobot_gui/web/dist` 로 install 한다. 빌드하지 않았으면 비어 있는 목록이라 `colcon build` 는 그대로 통과한다. 게이트웨이(S2)는 dist 가 없으면 "웹 빌드 필요" 를 알려야 한다.

## 6. 아직 없는 것

- 서버(관제 코어, 게이트웨이)와의 연결. `useResource` 의 `gateway` 모드는 `/api/fms/<이름>` 을 부르도록만 되어 있고 받아 주는 서버가 없다.
- `DatasetSummary` 같은 아직 정의되지 않은 메시지 (D12). 3.3·3.4 화면은 정의가 생긴 뒤에 만든다.
- 팀원 앱(3.7)의 웹 포팅. 3.7 화면은 안내와 모의 상태만 보인다.
- 화면 ⑦ 같은 "화면 단위" 합성(여러 메뉴를 탭으로 묶는 것). 지금은 메뉴 트리 기준으로만 연다.

## 7. 타입과 모의 데이터 (W2)

`cobot_interfaces` 의 메시지 정의가 웹 화면의 타입과 모의 데이터의 정본이다. 정의를 고치면 아래 순서로 맞춘다.

```bash
PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_types            # generated/messages.ts 다시 만들기
PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_types --check    # 파일과 모의 데이터가 정의와 맞는지 (CI)
PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_types --init-mocks   # 없는 모의 데이터 파일만 영 값으로 만든다
```

- **타입 규칙.** 정수는 `number`, float 는 `Float`(`number | null`), 시각은 `Time`, 헤더는 `Header`. float 의 NaN(미측정)은 JSON 에서 null 이 되므로 null 을 허용한다. 화면은 null 을 0 으로 바꿔 보이지 않고 '미측정' 으로 보인다(`Measured`).
- **상수.** 메시지의 상수는 `<메시지 이름>Const` 객체로 나온다 (예: `RobotStatusConst.STATE_HOLD`).
- **모의 데이터 검사.** `--check` 는 모든 모의 데이터가 정의와 같은 키를 갖는지, 값 종류와 정수 범위가 맞는지, `위 STATE_* 중 하나` 주석이 있는 필드가 그 상수 값인지 본다. 어긋나면 종료 코드 1 이다.
- **모의 데이터 시나리오.** 핑키 3대(이동 중·대기·정지), 팔 3대(ROS 관리·LeRobot 전용·오프라인), 알림 5건, 카메라 4대, 통신 진단 한 벌. `RobotStatus`·`ArmStatus`·`ArmMode`·`AlarmEvent`·`MapInfo`·`DiagSnapshot`·`CameraHealth`·`MediaHealth` 만 사람이 쓴 값이고 나머지는 영 값이다. 화면을 만들 때 필요하면 그 메시지의 JSON 을 현실적인 값으로 채워 PR 에 넣는다.
- **기준 레포 순서.** 이 도구는 `src/cobot_interfaces` 가 같은 트리에 있어야 돈다. 인터페이스 PR(#2)이 먼저 들어간 브랜치 위에서 쓴다.

### 참고 화면 (모의 데이터, 읽기 전용)

| 메뉴 | 보이는 것 | 데이터 |
|---|---|---|
| 1.1 | 핑키·팔 카드, 미측정 배터리·퇴피, 맵 지문 일치 | RobotStatus, ArmStatus, ArmMode, MapInfo |
| 1.4 | 알림 표, 심각도 순, 진행/해제 거르기 | AlarmEvent |
| 2.1 | 지점(작업점·정차점)과 로봇 위치를 맵 좌표로 그린 SVG | MapInfo, RobotStatus |
| 4.1 | 카메라 건강(멈춘 화면, 오래된 프레임, 시뮬레이션)과 미디어 서버 경로 | CameraHealth, MediaHealth |
| 6.2 | 토픽(유일 기록자 상태)과 노드(생존·왕복) | DiagSnapshot |
| 3.7 | 팀원 앱 원격 뷰(noVNC), 검수 스튜디오(8088), 팔 상태(ArmMode) 3대 탭 통합 | ArmMode, DatasetSummary |

나머지 메뉴의 화면은 담당자가 `menus/<ID>/Page.tsx` 로 만든다. 위 화면들이 모양을 보여 주는 예다. 각 화면은 같은 폴더에 시험(`Page.test.tsx`)을 둔다.
