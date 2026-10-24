# cobot_navigation PRD

## 1. 목적
- 주행(Nav2 설정, 주행 시퀀스, localization)을 담당한다.

## 2. 담당자
- 김지호, 김성아

## 3. 범위
- 포함: <작성 예정>
- 제외: <작성 예정>

## 4. 인터페이스
- 토픽/서비스/액션은 `/navigation/...` 접두사를 쓴다. (CLAUDE.md 7번)
- 사용하는 msg/srv/action: `cobot_interfaces` 기준. <작성 예정>
- TF frame 이름은 최상위 `docs/`의 정의만 쓴다.

## 5. 의존성
- `cobot_interfaces` 만 참고한다. 다른 기능 패키지는 import 하지 않는다.

## 6. 검증
- 빌드 → 테스트 → 린트 순서로 확인한다. (CLAUDE.md 5번)
- 실제 로봇 구동 여부: <작성 예정>
