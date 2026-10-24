<!--
규칙: docs/fms_dev_rules.md (R1~R10), 팀 공통 규칙: CLAUDE.md §8.
해당 없는 칸은 지우지 말고 '해당 없음' 이라고 적는다.
-->

## 무엇을 하나

- 메뉴 ID (하나): <!-- 예: 1.1. src/cobot_gui/config/menu_tree.yaml 에 있는 ID 만 -->
- 또는 인터페이스 (하나): <!-- 예: cobot_interfaces/msg/CommandAck.msg -->
- 단계: <!-- S0~S6 (docs/fms_roadmap.md) -->
- 요약:

## 레지스트리

- [ ] 메뉴 상태를 고쳤다 (`in_progress` + `branch`, 또는 `done`)
- [ ] `check_menu_tree` 오류 0, `pytest src/cobot_gui/test/test_menu_registry.py` 통과
- [ ] 생성 문서를 다시 만들었고 `gen_menu_doc --check` 가 0 이다
- [ ] 해당 없음

## 인터페이스 변경 (msg/srv/action)

- [ ] 없음
- [ ] 있음 — `cobot_interfaces` PR: <!-- 링크 -->, 팀 공지: <!-- 링크 --> (CLAUDE.md §3-4, §9)

## SR 인용

<!-- SR_v2 v13 의 ID 와 이름을 그대로 적는다. 뜻을 바꾸지 않는다. 예: SR-06 로봇 상태 모니터링 기능 -->

-

## 안전

- [ ] 모터·시리얼·카메라를 열지 않는다
- [ ] 연다면 그 장치 담당 패키지 안이고, 장치 담당 리뷰를 받았다
- [ ] 웹·도구 코드가 로봇 토픽을 발행하지 않는다
- [ ] 실물 로봇 구동이 없다 / 있다면 실행 직전 사용자 확인 기록:

## 빌드·시험·린트

<!-- 실제로 돌린 명령과 출력 요약을 붙인다. skip 은 통과가 아니다. -->

```text
colcon build --symlink-install --packages-select <pkg>
colcon test --packages-select <pkg>
colcon test-result --verbose
```

- [ ] 빌드 성공
- [ ] 시험 통과
- [ ] 린트 통과 (Python: ament_flake8·ament_pep257 / C++: ament_cpplint·ament_uncrustify)
- [ ] 관련 문서 갱신

## 비밀값 점검

- [ ] 토큰·비밀번호·키가 없다
- [ ] 실제 IP 주소·개인 PC 경로가 없다
- [ ] 대용량 파일(모델 가중치, rosbag, 데이터셋)이 없다

## 리뷰

- [ ] 1명 이상 리뷰
- [ ] 이 메뉴의 화면 담당·데이터 담당 리뷰 (레지스트리 `screen_owner`·`data_owner`)

## AI 에이전트를 썼다면

- [ ] 승인받은 계획(CLAUDE.md §10-1)의 링크 또는 요약
- [ ] 위 검사 결과는 실제로 돌린 출력이다
