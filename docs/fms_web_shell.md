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
      lib/                        utils, api(fetchAPI), dataSource(useResource), registry
      shell/                      types, 틀 페이지, 라우트 연결(pages.ts), 개요, MenuHeader
      generated/menus.ts          생성 파일. 직접 고치지 않는다
      menus/<ID의 . 를 _ 로>/     메뉴 하나가 폴더 하나 (Page.tsx)
      menus/_template/            복사용 틀
```

## 3. 규칙

1. **레지스트리가 정본이다.** 메뉴 이름·순서·화면·단계는 `menu_tree.yaml` 만 고친다. 고친 뒤에는 `python3 -m cobot_gui.gen_web_menus` 로 `menus.ts` 를 다시 만든다. CI 가 `--check` 로 어긋남을 잡는다.
2. **메뉴 하나가 폴더 하나다.** 메뉴 폴더는 `components/ui`, `lib`, `shell/types`, `shell/MenuHeader` 만 가져다 쓴다. 다른 메뉴 폴더를 가져다 쓰지 않는다.
3. **라우터와 사이드바를 고치지 않는다.** `menus/<ID>/Page.tsx` 가 생기면 `shell/pages.ts` 가 찾아서 틀 페이지 대신 쓴다. 담당자끼리 같은 파일을 고치지 않는다 (규칙 R1·R2).
4. **데이터는 `useResource('<메시지 이름>', 모의 값)` 한 가지 길로 읽는다.** 기본은 모의 데이터(`VITE_DATA=mock`)다. 서버가 붙으면(S2) `VITE_DATA=gateway` 로 바뀐다. 서버를 직접 부르는 코드를 메뉴 폴더에 쓰지 않는다.
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
- 메시지 정의에서 TS 타입을 만드는 생성기 (W2).
- 팀원 앱(3.7)의 웹 포팅. 3.7 화면은 안내와 모의 상태만 보인다.
- 화면 ⑦ 같은 "화면 단위" 합성(여러 메뉴를 탭으로 묶는 것). 지금은 메뉴 트리 기준으로만 연다.
