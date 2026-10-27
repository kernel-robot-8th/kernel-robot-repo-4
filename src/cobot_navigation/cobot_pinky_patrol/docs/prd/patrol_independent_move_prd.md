# 독립 지점 이동 · 3구역 · 유휴 복귀 PRD

- 대상: `cobot_pinky_patrol` (노드 `pinky_patrol_node_pinky1/2/3`), `cobot_zone_traffic_control`, `cobot_pinky_patrol_cmd`
- 작성일: 2026-10-27
- 상태: 구현 완료 (①~⑤, 2026-10-27). 실기 시험은 7절 절차로 진행한다.
- 관련 문서: [`patrol_param_prd.md`](patrol_param_prd.md) (좌표 파라미터화), [`Pinky 위험구역 대기열 — 단계별 PRD.md`](Pinky%20위험구역%20대기열%20—%20단계별%20PRD.md) (대기열)

## 1. 배경 · 문제

실기 시험에서 `goto ZA ZB` 를 연속으로 보냈더니 `WA` 까지만 이동한 뒤 홈으로 복귀했다. (당시 구역 A = ZA, ZB)
같은 구역이면 토큰을 유지한 채 ZB 로 가야 하는데 그렇게 되지 않았다. **원인은 아직 확정하지 못했다 (R0).**

원인과 별개로 구조에 문제가 있다.

| # | 문제 | 위치 |
|---|---|---|
| 1 | 명령 1개가 끝나면 무조건 홈으로 복귀한다 | `_run_route` F 단계 (`pinky_patrol_node_pinky*.py` 약 823행) |
| 2 | 구역 지점과 구역 밖 지점이 한 `goto` 안에 섞여 있어 지점을 하나씩 독립해서 보낼 수 없다 | `_cmd_cb` goto 분기 |
| 3 | 구역 토큰 보유 상태(`held`)가 `_run_route` 의 지역변수라 명령 사이에 유지되지 않는다 | `_run_route` |

**R0 (재현 로그 확보)**: 구현 전에 `goto ZA ZB` 를 다시 보내 아래를 수집해 원인을 확정한다.
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
| F5 | 위험구역은 **3개**다. `A` = [ZA], `B` = [ZB], `C` = [ZC]. 구역마다 `W<Z>` / `Z<Z>_EXIT` 한 쌍을 둔다. 매니저에 `zone_C` 와 `queue_anchor` (= `WC`) 를 추가한다. 홈 P1 은 구역 밖이다. |
| F6 | 토큰은 구역 진입 **전** zone_manager 에게서 발급받는다. `request_entry` 를 보내고 `grant_entry` 를 받기 전에는 구역 지점으로 출발하지 않는다 (ENTRY 또는 대기열 슬롯까지만 간다). 한 번에 1개 구역 토큰만 보유한다. |
| F7 | 토큰 반납은 EXIT 에 **SUCCEEDED 로 도착한 뒤에만** 한다. 이동이 실패하면 `NAV_RETRIES` 만큼 재시도하고, 끝내 실패하면 토큰을 유지하고 (매니저 `max_hold_sec` 뒤 자동 해제) `FAILED` 로 알린다. 명령·타이머 어느 경로로 나가든 같은 `_leave_zone` 을 쓴다. `emergency_stop` 은 현재처럼 토큰을 유지한다. |
| F8 | 구역 안(토큰 보유)에서 유휴 타이머가 만료되면 EXIT → 반납 → 홈 순서로 복귀한다. |

### 명령 체계 (제안)

| 명령 | 의미 | 홈 복귀 |
|---|---|---|
| `goto:<P>[,<P>...]` | 구역 밖 지점 이동 (여러 개면 순서대로) | 안 함 (F2 타이머만) |
| `zone:<P>` | 구역 지점 이동. 대기 위치(W) → 토큰 → 지점. 토큰 유지 | 안 함 |
| `leave` | 현재 구역의 EXIT 로 이동 → 토큰 반납 | 안 함 |
| `stop` / `emergency_stop` | 기존과 같음 (stop = EXIT 후퇴 후 반납, emergency = 토큰 유지) | 안 함 |
| `start` | 비활성 유지 (`FAILED: start disabled`) | - |

## 3. 설계

- **명령 파싱 분리**: `patrol_points_utils.py` 에 순수 함수 `parse_command(raw)` → `(kind, points)` 를 추가한다 (`goto | zone | leave | stop | emergency_stop`). ROS 의존 없이 단독 테스트한다.
- **노드 상태**: 멤버 `self._held_zone` (None = 구역 밖), `self._idle_deadline`, 현재 지점 이름을 둔다. `_run_route` 를 `_run_goto(names)`, `_run_zone(name)`, `_run_leave()` 로 나누고 홈 복귀 단계를 제거한다. `_leave_zone`, `_queue_and_enter`, `_navigate` 는 그대로 재사용한다.
- **유휴 타이머**: `create_timer(1.0)` 콜백이 `_running` 이 아니고 deadline 이 지났을 때 작업 스레드 `_run_idle_return` 을 시작한다. 콜백에서 Nav2 를 직접 부르지 않는다 (작업 스레드가 같은 executor 를 spin 하므로 `Executor is already spinning` 이 난다. stop 처리와 같은 이유).
- **상태 발행**: 신규 `IDLE_WAIT` (detail = 남은 초), `HOLDING_ZONE` (detail = 구역명). 기존 `LEAVING_ZONE`, `ARRIVED`, `DONE` 은 재사용하고, `DONE` 은 "명령 완료"를 뜻한다 (홈 도착이 아님).
- **파라미터 (YAML + `declare_parameter`)**: `idle_return_sec: 120.0`, `zone_names: [A, B, C]`, `zone_points: {A: [ZA], B: [ZB], C: [ZC]}`, `points.WC` / `ZC_EXIT`.
- **zone_manager** (`cobot_zone_traffic_control/config/zone_params.yaml`): `zone_names` 에 C, `zone_C.queue_anchor`, `queue_back_dir` 추가. **`max_hold_sec` 120 → 240 상향 제안**: 유휴 타이머(120초)와 EXIT 이동 시간 동안 매니저가 토큰을 먼저 강제 회수하지 않게 한다.
- **관제 클라이언트** (`cobot_pinky_patrol_cmd/pinky_control_client.py`): `zone`, `leave` 서브커맨드 추가, `goto` 안내 문구 수정.
- 3개 로봇 노드 파일은 구조가 같으므로 같은 수정을 3벌 적용한다 (좌표·홈만 YAML 이 다르다).

### 영향 범위
- goto 허용 = YAML 에 좌표가 있는 일반 지점(P1~P10, P1·P2 필수 / P3~P10 선택) + 자기 홈(`home_name`, I1/I2/I3). 구역 지점(ZA/ZB/ZC)은 포함하지 않는다.
- msg/srv/action, 의존성, `ROS_DOMAIN_ID`, 네트워크 설정 변경 없음.
- 도메인 브릿지 토픽 목록 변경 없음 (구역 이름과 무관한 메시지).

## 4. 수용 기준 · 검증

| # | 시나리오 | 기대 결과 |
|---|---|---|
| 1 | `goto P1` | P1 도착 후 홈 복귀하지 않고 대기. `idle_return_sec` 뒤 홈 복귀 (테스트는 짧은 값 사용) |
| 2 | 대기 중 새 명령 | 타이머 취소 |
| 3 | `zone ZA` | request → grant → ZA. 토큰 유지 (`A:occupied_by:pinky1`), 홈 복귀 안 함 |
| 4 | `zone ZA` 후 `goto P1` | ZA_EXIT 도착 → `A:free` → P1 |
| 5 | `zone ZA` 후 `zone ZB` | ZA_EXIT 반납 → WB 요청 → ZB (동시 보유 없음) |
| 6 | `zone ZA` 후 `leave` | ZA_EXIT → 반납, 홈 복귀 안 함 |
| 7 | 구역 안에서 유휴 만료 | EXIT → 반납 → 홈 |
| 8 | EXIT 이동 실패 / `emergency_stop` | 토큰 유지, `FAILED` / 현재 위치 유지 |
| 9 | 구역이 점유 중일 때 `zone` | 대기 위치(슬롯)에서 대기, grant 전에 구역 지점으로 출발하지 않음 |
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

## 5. 확정 값 · 남은 확인 (2026-10-27)

확정(사용자 지정, YAML 반영 완료):

| 구역 | 소속 | 대기 위치 W (= queue_anchor) | 출구 Z_EXIT | queue_back_dir |
|---|---|---|---|---|
| A | ZA | [0.0, 0.6, 0.0] | [0.5, 0.0, -1.5] | [0, 1] |
| B | ZB | [0.0, 0.6, -1.5] (A 와 위치 공유·yaw 만 다름, 토큰은 따로) | [0.55, -0.6, -1.5] | [0, 1] |
| C | ZC | [-0.7, -0.08, 1.5] | [-0.3, -0.4, 1.5] | [0, 1] |

※ 대기 위치(W*)를 구역 지점(ZB/ZC)과 같은 좌표로 두면 `zone` 을 동시에 받은 두 번째 로봇이 점유자 자리로 가므로 분리했다 (2026-10-27).

- `max_hold_sec` 120 → 240 상향 승인됨. `idle_return_sec` ≤ 0 은 자동 복귀 끔.

남은 확인:
- A·B 가 같은 대기 위치를 공유하므로 A 대기자와 B 대기자가 동시에 생기면 같은 슬롯으로 가 충돌한다 (해결하려면 매니저의 대기열 공유 구현 또는 A+B 토큰 통합 필요). C 슬롯 1 (-0.7,0.22) 은 ZC 와 약 0.2 m. A·B 줄(+y)은 (0,0.6)~(0,1.2) 이 맵 안인지 확인.
- 구역 지점·일반 지점 좌표는 pinky1~3 이 같은 값(실측 확인 남음). 홈은 I1 (0,0) / I2 (0,-0.2) / I3 (0,-0.4) 로 확정(2026-10-27).
- R0: `goto ZA ZB` 가 대기 위치 후 홈으로 간 원인은 코드상 재현되지 않는다(최신 코드는 같은 구역이면 토큰을 유지). 로봇이 옛 코드/YAML 로 돌았는지 확인하고, 재현되면 `patrol_status`·노드 로그를 확보한다.

## 6. Claude Code 실행 프롬프트

```
docs/prd/patrol_independent_move_prd.md 를 읽고 CLAUDE.md 규칙대로 Plan 모드에서 계획을 세운 뒤 승인 받고 구현해줘.
범위: cobot_pinky_patrol(노드 3개·patrol_points_utils·config/pinkyN.yaml·test·README), cobot_zone_traffic_control/config/zone_params.yaml,
cobot_pinky_patrol_cmd/pinky_control_client.py. 그 외 패키지·msg/srv/action·의존성·ROS_DOMAIN_ID 는 건드리지 마.
순서: ① R0 재현 로그로 `goto ZA ZB` 원인 확정 ② parse_command + 단위 테스트 ③ 노드 3벌에 _held_zone/_idle_deadline, _run_goto/_run_zone/_run_leave, 유휴 타이머(idle_return_sec) ④ 3구역 YAML·매니저 설정 ⑤ 클라이언트 zone/leave ⑥ README·PRD 갱신.
검증: colcon build --symlink-install → pytest(격리 ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1) → colcon test 린트. 실제 로봇 구동은 하지 말고, 실기 시험이 필요하면 실행 직전에 나에게 다시 확인해.
ZONE_C 좌표처럼 모르는 값은 추측하지 말고 물어봐. 커밋은 요청할 때만.
```

## 7. 시험 절차

1. **PC 자동 시험** (로봇 불필요)
   ```bash
   source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --packages-select cobot_pinky_patrol cobot_zone_traffic_control
   source install/setup.bash
   ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest -q src/cobot_navigation/cobot_zone_traffic_control/test src/cobot_navigation/cobot_pinky_patrol/test
   colcon test --packages-select cobot_pinky_patrol cobot_zone_traffic_control && colcon test-result --verbose
   ```
2. **설정 점검** (로봇 3대): 최신 코드·YAML 이 반영되었는지(`zone_points` 가 A=[ZA] B=[ZB] C=[ZC], `idle_return_sec: 120.0`), 홈 좌표가 (0,0,0) 이 아닌지, 값이 (0,0,0) 인 빈 일반 지점(pinky1 의 P1·P2)으로 이동하지 않는지. 재배포 순서: 매니저 → 로봇 3대.
3. **통신 점검**: 도메인 브릿지 기동, `ros2 topic echo /zone_manager/status` 에 A/B/C 가 보이는지, `pinky_control_client.py pinky1 monitor` 로 `patrol_status` 확인.
4. **단독 시험 (pinky1만, 주변 확보 후 사용자가 직접 실행)** — 실행 직전 재확인
   - `goto P1` → 도착 후 홈으로 가지 않고 `IDLE_WAIT`, 120초 뒤 홈 복귀. 대기 중 새 명령을 보내면 복귀하지 않음.
   - `zone ZA` → `A:occupied_by:pinky1`, 홈으로 가지 않음(`HOLDING_ZONE`). 다시 `zone ZA` → 대기 위치를 거치지 않음.
   - `zone ZB` → A `EXIT` 도착 → `A:free` → B 요청 → ZB.
   - `leave` → EXIT 도착 후 `B:free`, 홈으로 가지 않음. 구역 안에서 120초 방치 → EXIT 반납 후 홈.
   - `stop`(EXIT 로 나와 반납), `emergency_stop`(그 자리 정지·락 유지).
5. **2대 간섭 시험**: 같은 구역 `zone` 을 동시에 → 늦은 쪽 `QUEUEING` 후 순차 진입, 서로 다른 구역은 대기 없음, 대기 중 `stop`.
6. **현장 위험 확인**: 위 5절의 좌표 겹침, pinky2/3 옛 Z* 좌표.
7. **가짜 점유자로 대기열 시험 (로봇 1대, 구역 A 먼저 → 구역 B)** — 실행 직전 재확인
   - 사전: 매니저를 `max_hold_sec` 를 올려 띄운다. 가짜 점유자 `manual` 은 `notify_exit` 을 보내지 않으므로, 기본 240초가 지나면 매니저가 강제 해제하고 대기 중인 로봇이 정상적으로 점유를 넘겨받는다 (시험 중 "점유를 갑자기 가져간다"로 보이는 현상의 원인).
     ```bash
     export ROS_DOMAIN_ID=100
     ros2 run cobot_zone_traffic_control zone_manager_node --ros-args \
       --params-file src/cobot_navigation/cobot_zone_traffic_control/config/zone_params.yaml -p max_hold_sec:=1800.0
     ```
   - **구역 A**
     1. `ros2 topic pub --times 3 --rate 1 /zone_manager/request_entry std_msgs/msg/String "{data: 'A:manual:1'}"` → `status` 에 `A:occupied_by:manual`.
     2. `pinky_control_client.py pinky1 zone ZA` → 기대: `QUEUEING`(slot0), 대기 위치 WA (0.0, 0.6) 에서 정지, 점유는 `manual` 유지.
     3. `ros2 topic pub --once /zone_manager/notify_exit std_msgs/msg/String "{data: 'A:manual'}"` → pinky1 이 허가를 받고 ZA 로 이동, `HOLDING_ZONE`.
     4. `pinky_control_client.py pinky1 leave` → ZA_EXIT 도착 후 `A:free`.
   - **구역 B**: 같은 순서를 `B:manual:1` / `zone ZB` / `notify_exit B:manual` / `leave` 로 반복한다. WA 와 WB 는 같은 좌표이므로 A·B 대기자를 동시에 만들지 않는다.
   - 시험 후 매니저를 `ros2 launch cobot_zone_traffic_control zone_manager.launch.xml` (기본 240초) 로 되돌린다.
   - 실패하면 매니저 로그(`강제 해제`, `대기열 등록`, `진입 허가` 줄)와 `patrol_status` 를 함께 확보한다.
