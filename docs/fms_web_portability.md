# FMS 웹 화면을 홈랩 관리자 화면으로 옮기는 방법

- 상태: 초안 (2026-10-23). 홈랩 쪽 소스는 이 문서로 바꾸지 않는다.
- 목적: 팀 프로젝트가 끝난 뒤 필요한 메뉴 화면만 홈랩 관리자 화면(React 19, react-router 7, Vite, Tailwind 4, Radix)으로 옮긴다.

## 1. 같게 맞춘 것

| 항목 | 팀 웹 앱 | 홈랩 관리자 화면 |
|---|---|---|
| 스택 | React 19, react-router-dom 7, Vite 7, Tailwind 4, Radix, vitest | 같음 (같은 버전 대) |
| 경로 별칭 | `@/` → `src/` | 같음 |
| 공용 부품 | `src/components/ui/*` | `src/components/ui/*` (같은 파일을 복사했다) |
| 토큰 이름 | `--color-background` 등 | 같음. 값만 다르다 |
| 서버 호출 | `fetchAPI(endpoint, options)` | 같은 서명 |
| 시험 | vitest, jsdom, Testing Library | 같음 |

## 2. 옮길 때 지키는 규칙 (팀 쪽에서 미리 지킨다)

1. 메뉴 폴더는 `@/components/ui/*`, `@/lib/*`, `@/shell/types`, `@/shell/MenuHeader` 만 가져다 쓴다. 다른 메뉴 폴더를 가져다 쓰지 않는다.
2. 서버 데이터는 `useResource('<메시지 이름>', 모의 값)` 으로만 읽는다. 홈랩에서는 `lib/dataSource.ts` 의 `gateway` 모드가 `/api/fms/<이름>` 을 부르므로, 홈랩 프록시가 그 주소를 받아 주면 된다.
3. 앱 안 링크는 상대 경로를 쓴다. 홈랩에서는 `/admin/robot/` 같은 아래에 붙인다.
4. 홈랩 전용 값(내부 주소, 호스트 이름, 인증 방식)을 메뉴 폴더에 쓰지 않는다.

## 3. 옮기는 순서

1. 옮길 메뉴 ID 를 고른다 (예: 1.1, 2.1, 5.5).
2. 홈랩 `src/pages/robot/` 아래에 `menus/<ID>` 폴더를 폴더째 복사한다. `shell/types.ts`, `shell/MenuHeader.tsx`, `lib/dataSource.ts`, `lib/registry.ts`, `generated/menus.ts` 도 함께 필요하다.
3. 홈랩 `App.tsx` 의 `AdminChildRoutes` 에 라우트를 더하고, `Navigation.tsx` 의 로봇 그룹에 줄을 더한다. 홈랩에는 이미 "ROS 모니터링" 페이지가 있어 겹치는 부분을 먼저 정리한다.
4. 홈랩 `lib/api.ts` 의 기준 주소와 프록시를 맞춘다.
5. 홈랩 시험(`npm test`)과 빌드를 돌린다.

## 4. 조심할 것

- **저작권·사용 동의.** 팀 레포 `main` 에는 LICENSE 파일이 없다. 팀원이 만든 화면을 홈랩으로 옮기려면 동의와 라이선스를 먼저 정한다. 이 골격(생성기, 틀 페이지, 3.7 안내 화면)은 관제 담당이 만들었다.
- **공개 레포.** 홈랩 소스를 팀 레포로 옮기면 공개된다. 복사 범위는 공용 부품(`components/ui` 10개), 유틸, 빌드 설정 모양뿐이다. 업무 페이지·`api.ts`·로고·브랜드 색은 가져오지 않았다.
- **빌드 환경.** 홈랩은 자체 Dockerfile 과 nginx 로 서빙한다. 팀 쪽 `web/dist` 는 ROS 패키지에 install 되어 게이트웨이가 서빙한다. 서빙 방식은 옮기지 않는다.
