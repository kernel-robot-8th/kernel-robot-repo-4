# cobot_gui/web

FMS 관제 대시보드 웹 화면. 설명서는 [`docs/fms_web_shell.md`](../../../docs/fms_web_shell.md) 에 있다.

```bash
npm ci                          # package-lock.json 대로만 설치
npm run dev                     # 개발 서버 (기본은 모의 데이터)
npm run lint && npm test        # 검사
npm run build && npm run check:dist
```

- 메뉴 화면 만들기: `src/menus/_template/` 를 `src/menus/<ID의 . 를 _ 로>/` 로 복사한다.
- 메뉴 목록은 `src/cobot_gui/config/menu_tree.yaml`, 메시지 타입은 `src/cobot_interfaces` 정의가 정본이다. `src/generated/*` 는 직접 고치지 않는다.
- 데이터는 `useMessages('RobotStatus')` 처럼 읽는다. 기본은 모의 데이터(`src/mock/*.json`)다.
- 이 앱은 읽기 전용이다. 로봇에 명령을 보내는 화면은 만들지 않는다.
