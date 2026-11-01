# cobot_patrol_interfaces

관제 ↔ 핑키 순찰 **규격 v2** 메시지입니다. 메시지 양식만 있고 실행 코드는 없습니다.

- **v1** (지금 주행 코드): `std_msgs/String` 명령·JSON 상태. 그대로 둡니다.
- **v2** (이 패키지): 작업 ID 를 붙인 타입 메시지. **v1 과 다른 토픽 이름**이라 함께 돌려도 겹치지 않습니다.
- 지금 v2 를 내는 것은 가짜 핑키(`cobot_mock`)뿐입니다. 실물 순찰 노드는 아직 v1 만 씁니다.

담당: 김지혜 · 상태: 제안 (팀 합의 전)

## 왜 v2 인가

v1 에는 관제가 다루기 어려운 점이 세 가지 있습니다. v1 규칙은 [`cobot_pinky_patrol/README.md`](../cobot_navigation/cobot_pinky_patrol/README.md) 와 순찰 노드 코드가 기준입니다.

| v1 문제 | v2 에서 |
|---|---|
| 작업 중에 온 명령은 **아무 응답 없이 무시** | `PatrolCommandAck` 로 받음/거절과 이유가 온다 |
| 상태가 어느 명령의 결과인지 **짝지을 값이 없음** | `task_id` 가 명령·ack·상태에 모두 실린다 |
| 상태가 **바뀔 때만** 와서 끊김을 알 수 없음 | `PatrolState` 를 1초마다도 보낸다 |

같은 방식(작업 ID + 주기 상태 메시지)을 Open-RMF·VDA 5050 같은 관제 표준과
허지석 님 `refactor/control-server-bt-mqtt-db` 브랜치(JSON `command_id`·`task_finished`)가 씁니다.
관제↔로봇은 와이파이·도메인 브릿지를 지나므로 액션 대신 토픽 메시지로 했습니다.

## v1 ↔ v2 (관제 PC 쪽 이름)

| 할 일 | v1 | v2 |
|---|---|---|
| 명령 | `/pinkyN/patrol_cmd` String `goto:P1,P2` | `/pinkyN/patrol_command` `PatrolCommand` |
| 받음/거절 | 없음 | `/pinkyN/patrol_command_ack` `PatrolCommandAck` |
| 상태 | `/pinkyN/patrol_status` JSON (바뀔 때만) | `/pinkyN/patrol_state` `PatrolState` (바뀔 때 + 1초마다) |

- 바뀌지 않는 것: `state` 14종, 명령 6종(`goto`·`zone`·`leave`·`home`·`stop`·`emergency_stop`), 지점 이름, 실패 문구(`unknown point: ['P99']` 등), 로봇 동작 규칙.
- 시험(`test/test_generated_types.py`)이 v2 상수와 v1 목록이 같은지 봅니다.

## 메시지

- `PatrolCommand`: `task_id`, `operation`(`OP_*`), `points[]`
- `PatrolCommandAck`: `header`, `robot_id`, `task_id`, `accepted`, `reason`
  - 받음은 '시작했다' 는 뜻이지 성공이 아닙니다.
  - 거절 이유: `busy`, `not running`, `bad task_id`, `unknown operation`, 또는 v1 FAILED 문구
- `PatrolState`: `header`, `robot_id`, `state`(`STATE_*`), `waypoint`, `detail`, `task_id`, `task_finished`, `held_zone`
  - `task_id` 는 진행 중 작업, 없으면 마지막 작업의 ID 입니다. 로봇이 스스로 시작한 유휴 복귀는 `""` 입니다.

필드 설명은 각 `.msg` 파일 주석에 있습니다. `ros2 interface show cobot_patrol_interfaces/msg/PatrolState`

## 써 보기 (가짜 핑키, 격리 도메인)

```bash
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_mock mock_fleet.launch.xml auto_patrol:=false
ros2 topic echo /pinky1/patrol_command_ack                      # 다른 터미널
ros2 topic echo /pinky1/patrol_state                            # 다른 터미널
ros2 topic pub --once /pinky1/patrol_command cobot_patrol_interfaces/msg/PatrolCommand \
  "{task_id: t1, operation: goto, points: [P1, P3]}"
```

## 합치는 절차 (팀이 v2 를 받아들이면)

1. 김진호 님 순찰 노드가 v2 3개 토픽을 구현한다. 한동안 v1 과 함께 둔다.
2. 브릿지 설정 `cobot_domain_bridge/config/pinky_bridge_pinkyN.yaml` 에 v2 토픽 3개를 더한다.
   - 명령: 100 → 10/20/30
   - ack·상태: 10/20/30 → 100
3. `msg/` 파일을 `cobot_interfaces` 로 옮기고, 쓰는 패키지의 import 를 바꾼다. 이 패키지는 지운다.
   - `cobot_interfaces` 변경이므로 팀 공지·리뷰가 필요하다 (CLAUDE.md §3-4).
4. 관제가 v2 로 옮긴 뒤 v1 토픽(`patrol_cmd`, `patrol_status`)을 없앤다.

## 빼는 법

v2 를 쓰지 않기로 하면 이 폴더를 지우고 다음을 함께 정리합니다.
- `cobot_mock` 의 v2 코드와 `package.xml` 의존
- `CLAUDE.md` §2 의 `cobot_patrol_interfaces` 줄
