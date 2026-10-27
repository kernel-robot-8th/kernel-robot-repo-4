# 독립 지점 이동 · 3구역 · 유휴 복귀 PRD

- 대상: `cobot_pinky_patrol` (노드 `pinky_patrol_node_pinky1/2/3`), `cobot_zone_traffic_control`, `cobot_pinky_patrol_cmd`
- 작성일: 2026-10-27
- 상태: 초안 (구현 전). 이 문서는 코드를 바꾸지 않는다.
- 관련 문서: [`patrol_param_prd.md`](patrol_param_prd.md) (좌표 파라미터화), [`Pinky 위험구역 대기열 — 단계별 PRD.md`](Pinky%20위험구역%20대기열%20—%20단계별%20PRD.md) (대기열)

## 1. 배경 · 문제

실기 시험에서 `goto P2 P3` 를 연속으로 보냈더니 `ZONE_A_ENTRY` 까지만 이동한 뒤 홈으로 복귀했다. (당시 구역 A = P2, P3)
같은 구역이면 토큰을 유지한 채 P3 로 가야 하는데 그렇게 되지 않았다. **원인은 아직 확정하지 못했다 (R0).**

원인과 별개로 구조에 문제가 있다.

| # | 문제 | 위치 |
|---|---|---|
| 1 | 명령 1개가 끝나면 무조건 홈으로 복귀한다 | `_run_route` F 단계 (`pinky_patrol_node_pinky*.py` 약 823행) |
| 2 | 구역 지점과 구역 밖 지점이 한 `goto` 안에 섞여 있어 지점을 하나씩 독립해서 보낼 수 없다 | `_cmd_cb` goto 분기 |
| 3 | 구역 토큰 보유 상태(`held`)가 `_run_route` 의 지역변수라 명령 사이에 유지되지 않는다 | `_run_route` |

**R0 (재현 로그 확보)**: 구현 전에 `goto P2 P3` 를 다시 보내 아래를 수집해 원인을 확정한다.
- 노드 로그 전체 (`Navigating to goal` 줄과 그 앞뒤)
- `ros2 topic echo /pinky1/patrol_status` (state 순서)
- `ros2 topic echo /zone_manager/status`
- `ros2 node list --no-daemon`, 실행 중인 코드가 최신 빌드인지 (`ros2 pkg prefix cobot_pinky_patrol`)

## 2. 요구사항

사용자 조건 1~7 을 아래 F1~F8 로 옮겼다.

| ID | 요구사항 |
|---|---|
| F1 | 각 지점은 독립적으로 이동한다. 명령 1개는 목표 지점까지만 이동하고 **자동으로 홈 복귀하지 않는다**. |
| F2 | 이동 후 `idle_return_sec` 동안 다음 이동 명령이 없으면 홈으로 복귀한다. 파라미터로 수정할 수 있다 (기본 **120.0** 초, 0 이하는 자동 복귀 끔). 새 명령이 오면 타이머를 취소한다. 이 타이머 외에는 임의로 홈으로 복귀하지 않는다 (stop 이후에도 복귀하지 않는다). |
| F3 | 위험구역 지점 경유 이동은 **별도 명령** `zone:<P>` 로 지정한다. `goto:<P>` 는 구역 밖 지점 전용이며, 구역 지점이면 `FAILED` (`use zone`) 로 응답한다. |
| F4 | 구역 지점 이동 후 토큰을 **유지**한다. 이후 이동 명령(`goto`, 다른 구역 `zone`) 또는 `leave` 가 오면 먼저 해당 구역 EXIT 까지 이동하고, 도착한 뒤 `notify_exit` 로 토큰을 반납한 다음 그 명령을 실행한다. 같은 구역 `zone:` 연속 명령은 토큰을 다시 요청하지 않고 이동한다. |
| F5 | 위험구역은 **3개**다. `A` = [P2], `B` = [P3], `C` = [P4]. 구역마다 `ZONE_<Z>_ENTRY` / `ZONE_<Z>_EXIT` 한 쌍을 둔다. 매니저에 `zone_C` 와 `queue_anchor` (= `ZONE_C_ENTRY`) 를 추가한다. 홈 P1 은 구역 밖이다. |
| F6 | 토큰은 구역 진입 **전** zone_manager 에게서 발급받는다. `request_entry` 를 보내고 `grant_entry` 를 받기 전에는 구역 지점으로 출발하지 않는다 (ENTRY 또는 대기열 슬롯까지만 간다). 한 번에 1개 구역 토큰만 보유한다. |
| F7 | 토큰 반납은 EXIT 에 **SUCCEEDED 로 도착한 뒤에만** 한다. 이동이 실패하면 `NAV_RETRIES` 만큼 재시도하고, 끝내 실패하면 토큰을 유지하고 (매니저 `max_hold_sec` 뒤 자동 해제) `FAILED` 로 알린다. 명령·타이머 어느 경로로 나가든 같은 `_leave_zone` 을 쓴다. `emergency_stop` 은 현재처럼 토큰을 유지한다. |
| F8 | 구역 안(토큰 보유)에서 유휴 타이머가 만료되면 EXIT → 반납 → 홈 순서로 복귀한다. |

### 명령 체계 (제안)

| 명령 | 의미 | 홈 복귀 |
|---|---|---|
| `goto:<P>[,<P>...]` | 구역 밖 지점 이동 (여러 개면 순서대로) | 안 함 (F2 타이머만) |
| `zone:<P>` | 구역 지점 이동. ENTRY → 토큰 → 지점. 토큰 유지 | 안 함 |
| `leave` | 현재 구역의 EXIT 로 이동 → 토큰 반납 | 안 함 |
| `stop` / `emergency_stop` | 기존과 같음 (stop = EXIT 후퇴 후 반납, emergency = 토큰 유지) | 안 함 |
| `start` | 비활성 유지 (`FAILED: start disabled`) | - |

## 3. 설계

- **명령 파싱 분리**: `patrol_points_utils.py` 에 순수 함수 `parse_command(raw)` → `(kind, points)` 를 추가한다 (`goto | zone | leave | stop | emergency_stop`). ROS 의존 없이 단독 테스트한다.
- **노드 상태**: 멤버 `self._held_zone` (None = 구역 밖), `self._idle_deadline`, 현재 지점 이름을 둔다. `_run_route` 를 `_run_goto(names)`, `_run_zone(name)`, `_run_leave()` 로 나누고 홈 복귀 단계를 제거한다. `_leave_zone`, `_queue_and_enter`, `_navigate` 는 그대로 재사용한다.
- **유휴 타이머**: `create_timer(1.0)` 콜백이 `_running` 이 아니고 deadline 이 지났을 때 작업 스레드 `_run_idle_return` 을 시작한다. 콜백에서 Nav2 를 직접 부르지 않는다 (작업 스레드가 같은 executor 를 spin 하므로 `Executor is already spinning` 이 난다. stop 처리와 같은 이유).
- **상태 발행**: 신규 `IDLE_WAIT` (detail = 남은 초), `HOLDING_ZONE` (detail = 구역명). 기존 `LEAVING_ZONE`, `ARRIVED`, `DONE` 은 재사용하고, `DONE` 은 "명령 완료"를 뜻한다 (홈 도착이 아님).
- **파라미터 (YAML + `declare_parameter`)**: `idle_return_sec: 120.0`, `zone_names: [A, B, C]`, `zone_points: {A: [P2], B: [P3], C: [P4]}`, `points.ZONE_C_ENTRY` / `ZONE_C_EXIT`.
- **zone_manager** (`cobot_zone_traffic_control/config/zone_params.yaml`): `zone_names` 에 C, `zone_C.queue_anchor`, `queue_back_dir` 추가. **`max_hold_sec` 120 → 240 상향 제안**: 유휴 타이머(120초)와 EXIT 이동 시간 동안 매니저가 토큰을 먼저 강제 회수하지 않게 한다.
- **관제 클라이언트** (`cobot_pinky_patrol_cmd/pinky_control_client.py`): `zone`, `leave` 서브커맨드 추가, `goto` 안내 문구 수정.
- 3개 로봇 노드 파일은 구조가 같으므로 같은 수정을 3벌 적용한다 (좌표·홈만 YAML 이 다르다).

### 영향 범위
- `GOTO_BASE` = {P1, P2, P7} 에서 P2 를 제거한다 (P2 는 구역 A 소속).
- msg/srv/action, 의존성, `ROS_DOMAIN_ID`, 네트워크 설정 변경 없음.
- 도메인 브릿지 토픽 목록 변경 없음 (구역 이름과 무관한 메시지).

## 4. 수용 기준 · 검증

| # | 시나리오 | 기대 결과 |
|---|---|---|
| 1 | `goto P1` | P1 도착 후 홈 복귀하지 않고 대기. `idle_return_sec` 뒤 홈 복귀 (테스트는 짧은 값 사용) |
| 2 | 대기 중 새 명령 | 타이머 취소 |
| 3 | `zone P2` | request → grant → P2. 토큰 유지 (`A:occupied_by:pinky1`), 홈 복귀 안 함 |
| 4 | `zone P2` 후 `goto P1` | A_EXIT 도착 → `A:free` → P1 |
| 5 | `zone P2` 후 `zone P3` | A_EXIT 반납 → B_ENTRY 요청 → P3 (동시 보유 없음) |
| 6 | `zone P2` 후 `leave` | A_EXIT → 반납, 홈 복귀 안 함 |
| 7 | 구역 안에서 유휴 만료 | EXIT → 반납 → 홈 |
| 8 | EXIT 이동 실패 / `emergency_stop` | 토큰 유지, `FAILED` / 현재 위치 유지 |
| 9 | 구역이 점유 중일 때 `zone` | ENTRY/슬롯에서 대기, grant 전에 구역 지점으로 출발하지 않음 |
| 10 | 한 지점을 두 구역에 지정 | 노드 시작 거부 (`validate_zones`) |

검증 순서는 **빌드 → 테스트 → 린트** 다.
```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_zone_traffic_control cobot_pinky_patrol
source install/setup.bash
python3 -m pytest src/cobot_navigation/cobot_zone_traffic_control/test -q
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest src/cobot_navigation/cobot_pinky_patrol/test -q
colcon test --packages-select cobot_zone_traffic_control cobot_pinky_patrol && colcon test-result --verbose
```
- 자동 테스트: 신규 `test_patrol_commands.py` (`parse_command`), `test_patrol_queue.py` 에 위 시나리오 추가 (격리 도메인 77), zone 패키지 3구역 테스트.
- 실기 시험: 별도 승인과 실행 직전 재확인 후 pinky1 단독 → 2대 간섭 순서로 진행한다.

## 5. 미결 (사용자 확인 필요)

- `ZONE_C_ENTRY` / `ZONE_C_EXIT` 와 `zone_C.queue_anchor` 실측 좌표. 값이 없으면 구동하지 않고, 0,0,0 이 들어가지 않도록 검증을 추가하는 것을 제안한다.
- P3·P4 가 구역 B → B/C 로 갈라진다. P3(구역 B), P4(구역 C) 에 맞는 ENTRY/EXIT 와 기존 구역 B 좌표의 재배치.
- pinky2/3 의 P 좌표 (옛 값), pinky3 전용 홈.
- `max_hold_sec` 240 상향, `idle_return_sec` 0 의 의미 (자동 복귀 끔) 승인.
- R0 재현 로그 (`goto P2 P3` 가 ENTRY 후 홈으로 간 원인).

## 6. Claude Code 실행 프롬프트

```
docs/prd/patrol_independent_move_prd.md 를 읽고 CLAUDE.md 규칙대로 Plan 모드에서 계획을 세운 뒤 승인 받고 구현해줘.
범위: cobot_pinky_patrol(노드 3개·patrol_points_utils·config/pinkyN.yaml·test·README), cobot_zone_traffic_control/config/zone_params.yaml,
cobot_pinky_patrol_cmd/pinky_control_client.py. 그 외 패키지·msg/srv/action·의존성·ROS_DOMAIN_ID 는 건드리지 마.
순서: ① R0 재현 로그로 `goto P2 P3` 원인 확정 ② parse_command + 단위 테스트 ③ 노드 3벌에 _held_zone/_idle_deadline, _run_goto/_run_zone/_run_leave, 유휴 타이머(idle_return_sec) ④ 3구역 YAML·매니저 설정 ⑤ 클라이언트 zone/leave ⑥ README·PRD 갱신.
검증: colcon build --symlink-install → pytest(격리 ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1) → colcon test 린트. 실제 로봇 구동은 하지 말고, 실기 시험이 필요하면 실행 직전에 나에게 다시 확인해.
ZONE_C 좌표처럼 모르는 값은 추측하지 말고 물어봐. 커밋은 요청할 때만.
```
