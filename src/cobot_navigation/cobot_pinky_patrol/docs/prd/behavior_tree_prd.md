# 순찰 노드 비헤이비어 트리(BT) 전환 PRD

| 항목 | 내용 |
|---|---|
| 패키지 | `cobot_pinky_patrol` |
| 대상 파일 | `pinky_patrol_node_pinky1.py`, `pinky_patrol_node_pinky2.py`, `pinky_patrol_node_pinky3.py` (각 965줄) |
| 작성일 | 2026-10-31 |
| 상태 | 초안 (분석 완료, 방식 결정 대기) |
| 담당 | 주행 (`cobot_navigation`) |
| 관련 문서 | [`patrol_independent_move_prd.md`](patrol_independent_move_prd.md) (명령 체계·F1~F8), [`patrol_param_prd.md`](patrol_param_prd.md) (좌표 파라미터화) |

## 1. 배경 · 목적 · 비목표

### 배경
순찰 노드는 `goto / zone / leave / home / stop / emergency_stop` 명령과 유휴 복귀, 위험구역 토큰(대기열) 절차를 한 클래스(`PinkyPatrolNode`)에서 스레드와 불리언 플래그로 처리한다. 기능이 늘어날수록 중단·복구 처리가 곳곳에 퍼졌다.

### 목적
- 순찰 동작을 **비헤이비어 트리(BT)** 로 표현해 "무엇을 어떤 순서로, 실패하면 어떻게" 를 구조로 드러낸다.
- stop / emergency_stop 처리를 한곳(트리 루트)으로 모은다.
- 새 작업(예: 충전, 대기 구역 추가)을 코드 수정이 아닌 **서브트리 추가**로 넣을 수 있게 한다.

### 비목표
- 외부 인터페이스 변경 (토픽 `patrol_cmd` / `patrol_status`, 파라미터 YAML 형식, `ZoneGateClient` API). **100% 호환 유지.**
- Nav2 자체의 BT Navigator 교체. 여기서 말하는 BT 는 로봇 위 "작업 지시" 계층이다.
- 위치 복원 노드(`pinky_pose_recovery_node`)의 변경. 별개 프로세스로 유지한다.
- 순회(`start`) 부활. 비활성(`FAILED: start disabled`) 응답만 유지한다.

## 2. 현행 구조 분석

### 2-1. 실행 흐름

```
patrol_cmd (String)
   └─ _cmd_cb  (executor 스레드, 검증만 하고 즉시 리턴)
        ├─ goto / zone / leave / home ─> _start_task ─> 작업 스레드
        │                                   ├─ _run_goto(names)
        │                                   ├─ _run_zone(name)
        │                                   ├─ _run_leave()
        │                                   └─ _run_idle_return()   (home 명령 · 유휴 타이머 공용)
        └─ stop / emergency_stop ─> 플래그(_stop_requested, _emergency_requested)만 세움
                                      └─ 작업 스레드가 0.1초마다 폴링해서 반응
   _idle_tick (1초 타이머) ─> 유휴 시간 경과 시 _run_idle_return 시작
```

각 `_run_*` 는 `_prepare_nav`(STARTING 발행, Nav2 활성 대기) → 본 동작 → `finally: _finish_task`(stop 이면 EXIT 후퇴, LED 복귀, `_running=False`) 순서다.

### 2-2. 공유 상태 (흩어져 있음)

| 변수 | 의미 | 쓰는 곳 |
|---|---|---|
| `_running` | 작업 수행 중 (명령 중복 방지) | `_start_task`, `_finish_task`, `_cmd_cb`, `_idle_tick` |
| `_stop_requested` | stop 또는 emergency 수신 | `_navigate`, `_queue_and_enter`, `_wait_interruptible`, `_finish_task` 등 |
| `_emergency_requested` | emergency 수신 (후퇴·반납 생략) | `_retreat_after_stop`, `_finish_task` |
| `_held_zone` | 토큰 보유 구역 (명령 사이에도 유지) | `_run_*`, `_exit_held_zone`, `_arm_idle` |
| `_last_point` | 마지막 도착 지점 (홈 판단) | `_run_*`, `_arm_idle` |
| `_idle_deadline` | 유휴 복귀 시각 | `_arm_idle`, `_idle_tick`, `_start_task` |
| `_pose_initialized` | 초기 위치 보정 1회 여부 | `_init_pose_once` (현재 호출 안 함) |

### 2-3. 명령 → 동작 매핑 (BT 서브트리 후보)

| 명령 | 절차 | 실패·중단 시 |
|---|---|---|
| `goto:<P>[,...]` | (토큰 보유 시 EXIT 반납) → 지점 순차 `_navigate` → ARRIVED/DONE → 유휴 타이머 | `FAILED`/`STOPPED`, 타이머 걸지 않음 |
| `zone:<Z>` | (다른 구역 토큰이면 EXIT 반납) → `_queue_and_enter`(요청 → 슬롯 대기 → 허가) → 구역 지점 이동 → 토큰 유지 | 이동 실패 시 EXIT 후퇴 시도, `FAILED`/`STOPPED` |
| `leave` | 보유 구역 EXIT 이동 → 도착 후 `notify_exit` | 도달 실패 시 토큰 유지(`max_hold_sec` 후 매니저 해제) |
| `home` / 유휴 만료 | (EXIT 반납) → 홈 `_navigate` | 위와 동일 |
| `stop` | 현재 goal 취소 → 토큰 보유 시 EXIT 후퇴·반납 → `STOPPED` | 후퇴 실패 시 토큰 유지 |
| `emergency_stop` | 즉시 정지, 토큰 유지(상태 기억은 버림) | - |
| `start` | `FAILED: start disabled` 응답 | - |

### 2-4. 외부 연동 (전환 후에도 유지)

| 대상 | 내용 |
|---|---|
| 입력 | 토픽 `patrol_cmd` (String, `parse_command` 로 해석) |
| 출력 | 토픽 `patrol_status` (JSON: state, waypoint, detail, time). 상태: IDLE / STARTING / MOVING / QUEUEING / WAITING_ZONE / ARRIVED / LEAVING_ZONE / RETURNING / RETREATING / DONE / HOLDING_ZONE / IDLE_WAIT / STOPPED / FAILED / RETRY |
| Nav2 | `BasicNavigator` (`goToPose`, `isTaskComplete`, `cancelTask`, `waitUntilNav2Active`) |
| 구역 토큰 | `cobot_zone_traffic_control.zone_gate_client.ZoneGateClient` (`send_request`, `granted`, `current_slot`, `cancel_entry`, `notify_exit`) |
| LED | 서비스 `set_led` (`pinky_interfaces`), led_server 서브프로세스 |
| 설정 | `config/pinkyN.yaml` (`points`, `zone_names`, `zone_points`, `home_name`, `idle_return_sec`, `restore_last_pose`) |
| 순수 로직 (재사용) | `patrol_points_utils.py` (파싱·검증, ROS 비의존) |
| 테스트 | `test/` pytest (현재 104 passed, 65 skipped) |

## 3. 문제 정의

| # | 문제 | 근거 |
|---|---|---|
| P1 | 중단 처리 중복. `_stop_requested` 를 0.1초 `while`/`sleep` 로 폴링하는 구간이 `_navigate`, `_retreat_after_stop`, `_queue_and_enter`, `_wait_interruptible` 에 따로 있다 | 같은 패턴 4곳 |
| P2 | executor 제약 우회. 콜백에서 `cancelTask` 를 부르면 `Executor is already spinning` 으로 죽어서 플래그 + 스레드 구조가 강제된다 | `_cmd_cb` 주석 |
| P3 | 3개 파일이 사본. 차이는 `robot_id` 기본값과 주석뿐이라 수정할 때마다 3곳을 고쳐야 한다 | `diff` 결과 |
| P4 | 복구 로직이 if 중첩. 재시도, 후퇴, 락 반납, emergency 분기가 함수마다 비슷하게 흩어져 있다 | `_run_zone`, `_finish_task` |
| P5 | 상태 발행·LED 호출이 절차 코드 사이에 섞여 있어 동작 흐름을 읽기 어렵다 | `publish_status` 호출이 `_run_*` 전반에 분포 |
| P6 | 작업 추가 비용. 새 작업은 `_cmd_cb` 분기 + `_run_*` + `_finish_task` 영향 확인이 모두 필요하다 | 구조 |
| P7 | 단위 테스트가 어렵다. 작업 로직이 Nav2 / 스레드와 얽혀 있어 skip 테스트 65개가 남아 있다 | `test_patrol_queue.py` |

## 4. 요구사항

### 기능 (F)

| ID | 요구사항 |
|---|---|
| F1 | `patrol_cmd` 명령 체계와 `patrol_status` 상태 이름·발행 순서가 현행과 같다 (관제 GUI, `cobot_pinky_patrol_cmd` 무수정). |
| F2 | 명령은 한 번에 하나만 수행한다. 작업 중 새 이동 명령은 현행처럼 경고 후 무시한다. |
| F3 | `stop` 은 어느 단계에서든 한 tick(≤ 0.1초) 안에 Nav2 goal 을 취소하고, 구역 안이면 EXIT 로 후퇴해 토큰을 반납한다 (현행 F7 규칙). |
| F4 | `emergency_stop` 은 후퇴·반납 없이 즉시 정지하고 토큰을 유지한다. |
| F5 | 토큰 반납은 EXIT 에 SUCCEEDED 로 도착한 뒤에만 한다. 이동 실패는 `NAV_RETRIES`(3)회 재시도, 끝내 실패하면 토큰 유지 + `FAILED`. |
| F6 | `zone` 은 `grant` 를 받기 전에는 구역 지점으로 출발하지 않는다. 슬롯이 바뀌면 현재 goal 을 취소하고 새 슬롯으로 간다. 1초 간격 재전송을 유지한다. |
| F7 | 유휴 복귀(`idle_return_sec`), `HOLDING_ZONE`, `IDLE_WAIT` 동작을 유지한다. stop/실패 뒤에는 임의로 홈으로 가지 않는다. |
| F8 | `start` 는 `FAILED: start disabled` 로 응답한다. |
| F9 | 위치 보정 코드는 이번 범위에서 되살리지 않는다 (`restore_last_pose` 호출은 꺼진 상태 유지). |

### 비기능 (N)

| ID | 요구사항 |
|---|---|
| N1 | 로봇 3대가 **코드 한 벌**을 쓴다. 차이는 `robot_id` 와 YAML 뿐이다. 기존 `pinky_patrol_node_pinkyN` 실행 이름은 이행 기간 동안 유지한다. |
| N2 | 트리 구성·tick 로직은 ROS 객체와 분리해 ROS 없이 pytest 로 돌릴 수 있다 (`<기능>_utils.py` 규칙). |
| N3 | 매직 넘버는 파라미터로 둔다 (tick 주기, 재시도 횟수, 재전송 주기). |
| N4 | 새 의존성은 팀 허락 후에만 추가한다 (CLAUDE.md 9). |
| N5 | 린트(`ament_flake8`, `ament_pep257`)를 신규 파일에서 통과한다. |

## 5. 목표 BT 설계안

### 5-1. 원칙
- **tick 기반**: 주기 타이머(기본 10 Hz)가 트리를 tick 한다. 작업 스레드와 `time.sleep` 폴링을 없앤다.
- **Nav2 호출은 tick 안에서만**: `goToPose` / `isTaskComplete` / `cancelTask` 모두 한 스레드(tick)에서 호출해 P2 를 구조로 해결한다. 콜백은 명령을 큐에 넣기만 한다.
- **중단은 트리 최상단 가드**: stop/emergency 가 오면 진행 중인 서브트리를 취소(halt)하고 중단 서브트리로 전환한다.
- **Action 노드는 비블로킹**: `RUNNING` 을 반환하며 다음 tick 에 이어간다.

### 5-2. 루트 구조 (스케치)

```
Root (Selector)
├─ [Cond] 긴급정지 요청?  ──> Seq: 정지 + 상태 STOPPED (토큰 유지)
├─ [Cond] stop 요청?      ──> Seq: goal 취소 → (구역 보유?) EXIT 후퇴 → 반납 → STOPPED
├─ [Cond] 활성 명령 있음? ──> Selector: 명령 종류별 서브트리 (5-3)
└─ 유휴 Seq: IDLE 상태 유지 → 유휴 타이머 만료? → 유휴복귀 서브트리
```

### 5-3. 작업 서브트리

| 서브트리 | 구성 (Sequence 기준) |
|---|---|
| `Goto(names)` | 상태 STARTING → Nav2 활성 → `ReleaseZoneIfHeld` → 지점마다 [상태 MOVING → `NavigateTo`(재시도 3회) → 상태 ARRIVED] → DONE → `ArmIdle` |
| `Zone(name)` | STARTING → `ReleaseZoneIfOther` → `Selector[ 이미 보유 / EnterZone ]` → `NavigateTo(name)` → ARRIVED/DONE → `ArmIdle`. 이동 실패 시 Fallback: `LeaveZone` |
| `EnterZone(zone)` | `SendRequest` → Parallel[ `FollowSlot`(슬롯 변경 시 goal 교체), `ResendRequest`(1초), `WaitGrant` ] → 허가 시 goal 취소. `queue_full` 이면 FAILED |
| `Leave` | LEAVING_ZONE → `NavigateTo(EXIT)` → `NotifyExit` → DONE |
| `IdleReturn` | `ReleaseZoneIfHeld` → (홈 아니면) RETURNING → `NavigateTo(home)` → DONE |
| `Retreat`(stop 용) | RETREATING → `NavigateTo(EXIT)` 재시도 → `NotifyExit`. emergency 가 오면 즉시 중단 |

공통 데코레이터: `PublishState(state, detail)` (상태 발행), `LedScope(drive/idle/queue)` (LED 복귀 보장), `Retry(n)`.

### 5-4. Blackboard 키

| 키 | 대응하는 현행 변수 |
|---|---|
| `held_zone` | `_held_zone` |
| `last_point` | `_last_point` |
| `stop_requested`, `emergency_requested` | `_stop_requested`, `_emergency_requested` |
| `active_cmd` | `_running` + 현재 명령 (`kind`, `names`) |
| `idle_deadline` | `_idle_deadline` |
| `current_goal` | 진행 중 Nav2 goal 핸들 (취소·교체용) |

### 5-5. 코드 배치 (`ament_python` 규칙)

```
cobot_pinky_patrol/
├── patrol_bt_nodes.py      # Action/Condition/Decorator 클래스 (Nav2·Gate 는 주입받음)
├── patrol_bt_trees.py      # 명령 종류 → 서브트리 조립 (순수 로직)
├── pinky_patrol_bt_node.py # ROS 노드(얇게): 토픽/타이머/Nav2/Gate 연결, 단일 진입점
├── patrol_points_utils.py  # 기존 재사용
config/pinkyN.yaml          # 기존 그대로 + tick_hz 등 신규 파라미터
```

## 6. 방식 비교와 권고

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. `py_trees` (Python) | 같은 패키지에서 BT 구성 | 언어 유지, Blackboard·halt·RUNNING 내장, 트리 출력/테스트 쉬움 | **새 의존성 → 팀 허락 필요**. 현재 환경에 설치되어 있지 않음 |
| B. BehaviorTree.CPP + Nav2 BT 플러그인 | `ament_cmake` 패키지 신설 | Nav2 생태계, Groot2 시각화 | 한 패키지 한 언어 규칙 때문에 새 패키지 필요. 현 코드·`ZoneGateClient`(Python) 재작성 비용 큼 |
| C. 자체 최소 BT (Python) | Sequence / Selector / Decorator / Action 을 직접 구현 (약 200줄) | 의존성 0, 즉시 시작 | 유지보수 책임, 시각화 도구 없음 |

**권고**: A 를 1순위로 하고, 허락이 안 되면 C 로 진행한다. B 는 이번 범위에서 제외한다 (`ZoneGateClient` 와 `BasicNavigator` 가 Python 이므로). 노드 클래스를 얇은 인터페이스(`tick()` / `halt()` / 상태 반환)로 만들어 A↔C 교체 비용을 낮춘다.

> 결정 필요: 방식 A/C 선택 (7절 R1 착수 전에 확정).

## 7. 이행 계획

신규 노드와 기존 노드를 **병행 유지**하고, 같은 `patrol_cmd`/`patrol_status` 를 쓰므로 한 로봇에서는 둘 중 하나만 실행한다.

| 단계 | 내용 | 출구 기준 |
|---|---|---|
| R0 | 현행 동작 특성화. 명령별 상태 발행 순서를 표로 기록하고 skip 중인 큐 테스트 65개의 대체 가능 여부를 정리 | 상태 순서 표 + 가짜 Nav2/Gate 로 현행 시나리오를 재현하는 기준 테스트 |
| R1 | 방식 결정, BT 골격(루트 가드, Blackboard, 상태 발행)과 `Goto` 서브트리 | `goto` 단일/다중/실패/stop 이 가짜 Nav2 에서 현행과 같은 상태 순서 |
| R2 | `Zone` / `EnterZone` / `Leave` | 슬롯 변경·허가·queue_full·EXIT 반납 시나리오 통과 |
| R3 | `stop` / `emergency_stop` / 유휴 복귀 / `home` | 모든 단계에서 stop 이 1 tick 내 반응, emergency 시 토큰 유지 |
| R4 | 단일 노드화(N1), 실기 시험(사용자 수행), 구 노드 3개 제거, README·PRD 갱신 | 로봇 3대 실기 통과 후 제거 (제거는 별도 승인) |

각 단계는 빌드 → pytest → 린트를 통과해야 다음으로 간다.

## 8. 테스트 · 검증 계획

- 기존 pytest(104 passed) 유지. 새 로직은 `test/test_patrol_bt_*.py` 로 추가.
- 가짜 Nav2(`goToPose` / `isTaskComplete` / `getResult` 스크립트 응답)와 가짜 Gate 를 주입해 tick 단위로 검증한다. 시간 경과는 가짜 시계로 처리한다.
- 비교 기준: R0 의 "현행 상태 발행 순서 표".
- 실기 검증(주행, stop, 구역 진입/대기열)은 **사용자가 로봇에서** 수행한다. Claude 는 로봇을 구동하지 않는다.
- ROS_DOMAIN_ID, 네트워크 설정은 변경하지 않는다.

## 9. 위험 · 결정 필요

| 항목 | 내용 | 대응 |
|---|---|---|
| D-1 | 라이브러리 방식 A/C | 팀 허락 후 확정 (6절) |
| D-2 | executor/스레딩. tick 이 Nav2·Gate 콜백과 같은 executor 에서 돌 때 `spin_until_future_complete` 중첩 금지 | 모든 Nav2 호출을 tick 한 곳에서, 비동기 API 만 사용. R1 에서 검증 |
| D-3 | `ZoneGateClient` 가 `navigator` 노드에 붙어 있고 `spin_once` 에 의존하는 부분(`wait_for_entry`) | tick 방식에서는 `wait_for_entry` 대신 `granted()` 폴링만 사용 |
| D-4 | `BasicNavigator.isTaskComplete` 가 내부에서 spin 하는 점 | 단일 스레드 tick 에서만 호출 |
| D-5 | LED 호출이 블로킹(`spin_until_future_complete`) | 비동기 호출로 바꾸거나 별도 스레드 유지 (R1 에서 결정) |
| D-6 | 실로봇 안전. stop 지연, 토큰 미반납으로 다른 로봇 대기 | R3 출구 기준에 stop 1 tick 반응, `max_hold_sec` 안전망 유지 |
| D-7 | 이행 중 구·신 노드 동시 실행 | 실행 스크립트/launch 에서 상호 배타 구성 (한 로봇 한 노드) |

## 10. 영향 범위

| 대상 | 영향 |
|---|---|
| `cobot_pinky_patrol` | 신규 파일 추가, 기존 노드는 R4 까지 유지 |
| `cobot_zone_traffic_control` | 변경 없음 (`ZoneGateClient` 는 그대로 사용). D-3 로 비동기 사용 방식만 확인 |
| `cobot_pinky_patrol_cmd`, 관제 GUI | 토픽 호환이라 변경 없음 |
| `pinky_pose_recovery_node` | 변경 없음. `cmd_vel`·`initialpose` 공유 주의는 기존과 동일 |
| 의존성 | 방식 A 선택 시 `py_trees` 추가 (`package.xml` + `setup.py`, 팀 허락 필요) |
| 문서 | README 구조·실행법, `patrol_independent_move_prd.md` 에 이 PRD 링크 추가 (R1 시점) |

## 11. 일정 · 담당

| 단계 | 담당 | 예정 |
|---|---|---|
| R0~R4 | 김진호 (주행) | 미정 |

## 12. 단계별 Claude Code 프롬프트

각 단계는 앞 단계의 출구 기준(빌드 → pytest → 린트 → 상태 순서 대조)을 통과한 뒤 시작한다. 모든 프롬프트는 CLAUDE.md 10-1에 따라 Plan 모드 계획부터 받는다. 단계마다 커밋을 따로 하고 메시지는 `feat(navigation): ...` 형식을 쓴다.

### 사전: D-1 방식 확정

```
cobot_pinky_patrol 의 BT 전환 방식을 확정하려고 해.
docs/prd/behavior_tree_prd.md 6절을 읽고, 아래 두 안을 현재 환경 기준으로 다시 비교해줘.
  A. py_trees (새 의존성)  /  C. 자체 최소 BT
확인할 것: py_trees 설치 가능 여부(pip 말고 apt/rosdep 경로), 오프라인 현장 설치 가능성
(docs/fms_offline_bundle.md), 자체 BT 로 구현할 때 필요한 노드 종류와 예상 코드량.
코드는 수정하지 말고 비교표와 권고만 줘. sudo/apt install 은 실행하지 마.
```

### R0. 현행 동작 특성화

```
docs/prd/behavior_tree_prd.md 의 R0 를 진행해줘. 목표는 현행 순찰 노드의 동작을 BT 전환 전에 고정하는 것이야.

범위
- pinky_patrol_node_pinky1.py 만 대상 (2, 3 은 사본)
- 명령별(goto 단일/다중, zone, leave, home, stop, emergency_stop, 유휴 복귀, start)
  patrol_status 상태 발행 순서와 detail/waypoint 값을 표로 정리
- 정상 / 이동 실패(재시도 3회) / stop / emergency / queue_full / 슬롯 변경 시나리오 포함
- 가짜 Nav2(BasicNavigator 대체)와 가짜 ZoneGateClient 를 만들어
  현행 노드가 위 시나리오에서 내는 상태 순서를 pytest 로 고정하는 기준 테스트 작성
  (test/test_patrol_baseline.py). 현행 코드는 수정하지 마
- 현재 skip 중인 65개 테스트가 이 기준 테스트로 대체 가능한지 정리

산출물: 상태 순서 표(PRD 부록 또는 docs/ 하위 문서), 기준 테스트
검증: colcon build --symlink-install --packages-select cobot_pinky_patrol →
      python3 -m pytest test -q (기존 104 passed 유지) → 신규 파일 flake8
금지: 로봇 구동, ROS_DOMAIN_ID 변경, 새 의존성 추가
Plan 모드로 계획부터 보여줘.
```

### R1. BT 골격 + Goto

```
docs/prd/behavior_tree_prd.md 의 R1 을 진행해줘. 방식은 [A: py_trees / C: 자체 BT] 로 확정했어.
(A 인 경우 py_trees 의존성 추가는 팀 허락 받았음. package.xml 과 setup.py 에 같이 반영)

범위
- 신규: patrol_bt_nodes.py, patrol_bt_trees.py, pinky_patrol_bt_node.py (PRD 5-5 배치)
- 루트 가드(emergency → stop → 활성 명령 → 유휴), Blackboard 키, PublishState 데코레이터
- Goto 서브트리: 단일/다중 지점, NavigateTo 재시도 3회, stop 시 goal 취소
- 모든 Nav2 호출은 tick 한 곳에서만. 작업 스레드와 time.sleep 폴링 금지 (PRD 문제 P1, P2)
- 기존 pinky_patrol_node_pinky1~3.py 는 수정하지 마. 이 노드와 한 로봇에서 동시에 실행하지 않게
  README 에 명시
- 파라미터는 declare_parameter + config YAML (tick_hz 등), 기존 키는 그대로
- D-2, D-4, D-5 (executor, isTaskComplete 의 spin, LED 블로킹) 를 코드로 확인해서
  결론을 PRD 9절에 갱신

검증: R0 기준 테스트와 같은 시나리오(goto 정상/실패/stop)에서 상태 발행 순서 동일.
      신규 BT 단위 테스트(ROS 없이 실행) 추가. 빌드 → pytest → flake8/pep257.
금지: 로봇 구동, 기존 노드 변경, 인터페이스(msg/srv/action) 변경
Plan 모드로 계획부터 보여줘.
```

### R2. Zone / EnterZone / Leave

```
R1 이 끝났어. PRD 의 R2 를 진행해줘.

범위
- Zone, EnterZone, Leave 서브트리 추가 (PRD 5-3)
- EnterZone: send_request → 허가 대기, 슬롯 변경 시 goal 교체, 1초 재전송, queue_full 처리
- 한 번에 1개 구역 토큰만 보유, 다른 구역이면 EXIT 도착 후 반납, 같은 구역이면 재요청 없이 이동
- 토큰 반납은 EXIT 에 SUCCEEDED 로 도착한 뒤에만. 실패 시 토큰 유지
- D-3: ZoneGateClient 의 wait_for_entry/spin_once 의존을 tick 방식에서 어떻게 쓸지 확인.
  cobot_zone_traffic_control 을 수정해야 한다면 수정하지 말고 이유와 대안만 보고해줘

검증: R0 의 zone/leave 시나리오와 상태 순서 동일. 슬롯 변경, 허가 즉시, queue_full, 이동 실패 후 EXIT 후퇴 테스트.
빌드 → pytest → 린트.
금지: 로봇 구동, cobot_zone_traffic_control 수정, 인터페이스 변경
Plan 모드로 계획부터 보여줘.
```

### R3. stop / emergency / 유휴 복귀 / home

```
R2 가 끝났어. PRD 의 R3 를 진행해줘.

범위
- stop: 어느 단계에서든 1 tick 안에 goal 취소 → 구역 안이면 EXIT 후퇴 → 반납 → STOPPED
- emergency_stop: 즉시 정지, 후퇴/반납 없이 토큰 유지(노드는 보유 상태를 버림), 후퇴 중 emergency 도 처리
- 유휴 복귀: idle_return_sec, HOLDING_ZONE, IDLE_WAIT, 새 명령 시 타이머 취소, stop/실패 뒤 임의 복귀 금지
- home 명령, start 는 FAILED: start disabled
- 작업 중 새 이동 명령은 경고 후 무시 (현행과 동일)

검증: 모든 서브트리 실행 중 stop 을 넣는 테스트를 파라미터화해서 반응 tick 수를 확인.
R0 상태 순서 표와 대조. 빌드 → pytest → 린트.
금지: 로봇 구동, restore_last_pose 호출 되살리기
Plan 모드로 계획부터 보여줘.
```

### R4. 단일화 + 이행

```
R3 가 끝났어. PRD 의 R4 중 코드 정리 부분만 진행해줘. 실기 시험은 내가 로봇에서 해.

범위
- BT 노드를 pinkyN.yaml 의 robot_id 로 구분하는 단일 진입점으로 정리 (N1)
- launch/pinky{1,2,3}_patrol.launch.xml 이 새 노드를 쓰는 대안 launch 추가
  (기존 launch 는 유지, 한 로봇에서 구·신 노드가 동시에 안 뜨게 구성)
- README, patrol_independent_move_prd.md 에 PRD 링크, behavior_tree_prd.md 상태 갱신
- 구 노드 3개 삭제는 하지 마. 내가 실기 확인 뒤에 따로 요청할게

검증: 빌드 → pytest → 린트. 실기 시험 체크리스트(goto, zone 진입/대기열, stop, emergency, 유휴 복귀)를 문서로 작성
금지: 로봇 구동, 구 노드 삭제, ROS_DOMAIN_ID 변경
Plan 모드로 계획부터 보여줘.
```
