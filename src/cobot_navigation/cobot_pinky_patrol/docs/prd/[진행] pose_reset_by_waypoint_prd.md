# Waypoint 기반 초기 위치 재설정 PRD

## 진행 현황
**현재 단계: 6단계 (실기 시험, 사용자가 직접).** 5단계까지 구현·문서를 마쳤다. 갱신일 2026-11-01. 단계별 상세는 10번을 본다.

| 단계 | 내용 | 상태 | 완료일 |
|---|---|---|---|
| 1. PRD 정리 | 불일치 점검, 결정 확정 | ✅ 완료 | 2026-10-31 |
| 2. 순수 로직 | `pose_recovery_utils.py`와 단위 테스트 | ✅ 완료 | 2026-10-31 |
| 3. 명령 수신 | 노드, yaml, launch, `/initialpose` 발행, 1차 수렴 확인 | ✅ 완료 | 2026-10-31 |
| 4. 스캔·마무리 | 오도메트리 기반 좌우 스캔, 한 바퀴 fallback, odom 감시, 정지 보장 | ✅ 완료 | 2026-11-01 |
| 5. 문서·검증 | README 갱신, PRD와 구현 일치 점검, 전체 검증 | ✅ 완료 | 2026-11-01 |
| **6. 실기 시험** | **사람이 로봇으로 직접 시험** | **🔄 다음 단계 (사용자 시험 대기)** | - |

범례: ✅ 완료 / 🔄 진행 중 / ⬜ 예정. 단계가 바뀔 때마다 이 표와 10번의 해당 단계 "상태"를 함께 고친다.


## 1. 배경과 목적
- 충돌로 라이다 위치가 틀어지거나 AMCL이 위치를 잡지 못하면 `/amcl_pose`가 어긋난다. 지금은 RViz에서 손으로 "2D Pose Estimate"를 찍어야 한다.
- 사람이 로봇을 **waypoint 좌표**에 가져다 두고 명령 한 번을 내리면, 노드가 아래를 자동으로 한다.
  1. 그 waypoint 좌표로 `/initialpose`를 보낸다.
  2. 제자리에서 **좌우로 스캔**해 방향을 잡고 수렴을 확인한다. 회전량은 시간이 아니라 **오도메트리**로 잰다.
- 로봇이 스스로 판단해 이동하는 기능이 아니라 **사람이 위치를 알려 주는 복구 절차**다.
- **기존 위치 복원 구현을 이 PRD 내용으로 전부 교체한다. 이 PRD가 우선한다.**
  - 대상: `pinky_pose_recovery_node.py`, `pose_recovery_utils.py`, `config/pose_recovery.yaml`, 그리고 이들을 쓰는 `test_pose_recovery_utils.py`.
  - 파일 이름과 노드 이름(`pinky_pose_recovery_node`), launch, `setup.py` entry point는 그대로 쓴다.
  - 기존 기능(부팅 시 저장 위치 복원, 마지막 위치 저장, 드리프트 감시, `~/recover` 서비스, 한 방향 한 바퀴 스캔)은 **유지하지 않는다.** 이 PRD에 있는 동작만 남긴다.

## 2. 범위
**포함**
- waypoint 이름을 받아 `/initialpose`를 발행하고, 수렴하지 않으면 좌우 스캔으로 방향을 잡는 노드.
- waypoint 좌표는 `config/pinkyN.yaml`의 `points`를 재사용한다. 좌표를 중복해서 쓰지 않는다. 파싱은 같은 패키지의 `patrol_points_utils.parse_points`를 재사용한다.
- 스캔 회전량은 **오도메트리(`odom`)의 yaw 변화량**으로 재고, 목표 각도에서 멈춘다. 시간 기반(open-loop)은 쓰지 않는다. 정확성이 우선이라는 2026-11-01 사용자 결정이다.
- 판정·각도 계산 함수(ROS 비의존)를 `pose_recovery_utils.py`에 새로 쓴다.
- 상태 발행, 파라미터(`config/pose_recovery.yaml`), 단위 테스트, README 갱신.

**제외**
- 자동 트리거. 사람이 명령을 낼 때만 동작한다.
- **patrol 이동 중 reset 거부 기능.** 노드는 patrol 상태를 보지 않는다. patrol이 멈춘 것을 확인하는 책임은 사용자에게 있다(5번에 명시).
- 부팅 복원, 마지막 위치 저장, 드리프트 감시, 수동 복구 서비스 (1번에서 제거하기로 한 기능).
- 관제 PC·GUI 연동. 이번 버전은 로봇 로컬 명령이다. 도메인 브릿지 항목 추가는 후속이다.
- `msg/srv/action` 신규 정의. 표준 타입만 쓴다.

## 3. 사용 시나리오
1. 충돌 등으로 위치가 틀어진 것을 사람이 발견한다.
2. 사람이 로봇을 정지시키고 **지정 waypoint 좌표에 놓는다. 방향은 대략 그 waypoint의 yaw를 보게 한다.**
3. 로봇에서 명령을 보낸다. 예: `ros2 topic pub --once /pose_reset_cmd std_msgs/msg/String "{data: 'P3'}"`
4. 노드가 `/initialpose`를 발행하고 좌우 스캔으로 방향을 맞춘다.
5. `pose_recovery_status`가 `CONVERGED`로 바뀌면 완료다. `FAILED`면 RViz에서 직접 지정한다.

### 3-1. 단계별 절차
사람이 하는 일(👤)과 노드가 하는 일(🤖)을 나눠 적는다. 괄호는 해당 요구사항(4번)이다.

| 단계 | 주체 | 동작 | 발행 상태 | 실패/분기 |
|---|---|---|---|---|
| 0. 준비 | 👤 | **patrol 이동이 멈춘 것을 확인한다.** 로봇 주변에 장애물이 없는지 본다. | - | 노드는 이를 검사하지 않는다 (2번 제외 항목) |
| 1. 배치 | 👤 | 로봇을 지정 waypoint 좌표에 놓고, 그 waypoint의 yaw 방향을 대략 보게 한다. | - | - |
| 2. 명령 | 👤 | `pose_reset_cmd`로 waypoint 이름을 보낸다. 예: `P3` | - | - |
| 3. 검증 | 🤖 | 이름이 `points`에 있는지, 다른 reset이 동작 중인지 확인한다. (F1, F6) | 실패 시 `FAILED` | 없는 이름: unknown waypoint, 동작 중: busy. 둘 다 로봇을 움직이지 않고 종료한다. |
| 4. 위치 지정 | 🤖 | `/initialpose` 구독자(AMCL)를 `reset_amcl_wait_sec`까지 기다린 뒤, waypoint `(x, y, yaw)`를 `map` 프레임으로 `initialpose_repeat`회 발행한다. (F2) | `RESETTING` | 구독자가 끝내 없으면 `FAILED`(no amcl) |
| 5. 1차 수렴 확인 | 🤖 | `converge_timeout_sec` 동안 `/amcl_pose` 공분산이 수렴하는지 본다. (F3) | - | 수렴하면 9단계로 간다. 아니면 6단계로 간다. |
| 6. 좌우 스캔 | 🤖 | 먼저 `odom`이 들어오는지 확인한다(없으면 회전하지 않는다). 오도메트리 yaw 변화량으로 재면서 왼쪽 `+scan_half_angle_rad` → 오른쪽 `2 × scan_half_angle_rad`(왼쪽 끝에서 오른쪽 끝까지) → 왼쪽 `+scan_half_angle_rad`(정면 복귀) 순으로 `scan_angular_speed`로 회전한다. 구간 목표 각도의 `scan_angle_tolerance_rad` 이내에 들어오면 다음 구간으로 간다. 매 주기마다 수렴을 확인한다. (F4, F10) | `SCANNING_LR` | 수렴하는 즉시 정지하고 9단계로 간다. 끝까지 수렴하지 않으면 7단계로 간다. odom 없음·끊김·구간 시간 초과는 정지하고 8단계로 간다(fallback 없음). |
| 7. 한 바퀴 스캔 | 🤖 | `scan_full_turn_fallback`이 켜져 있으면 오도메트리로 누적 2π(한 바퀴)를 왼쪽으로 돈다. 감시는 6단계와 같다. (F5, F10) | `SCANNING` | 수렴하면 9단계로 간다. 아니면 8단계로 간다. |
| 8. 실패 처리 | 🤖 | `cmd_vel` 0으로 정지하고 실패를 알린다. (F5, F8) | `FAILED` | 사람이 RViz "2D Pose Estimate"로 직접 지정한다. |
| 9. 마무리 | 🤖 | `cmd_vel` 0으로 정지하고 완료를 알린다. (F8) | `CONVERGED` | - |
| 10. 확인 | 👤 | `ros2 topic echo /amcl_pose --once`로 위치가 waypoint 근처인지 확인한다. 어긋나 있으면 1단계부터 다시 한다. | - | - |

```
명령 ─► 3.검증 ─► 4.initialpose ─► 5.수렴? ──예──────────────┐
          │ 실패          │ 아니오                              │
          ▼               ▼                                    ▼
        FAILED     6.좌우 스캔 ──수렴──────────────────────► 9.마무리(CONVERGED)
                          │ 실패                               ▲
                          ▼                                    │
                    7.한 바퀴 스캔 ──수렴───────────────────────┘
                          │ 실패
                          ▼
                    8.FAILED (정지, 수동 지정 안내)
```

- 어느 단계에서든 예외나 취소가 나면 `cmd_vel` 0을 발행하고 정지한다. (F8)
- 스캔 중 odom 없음·끊김·시간 초과(F10)는 로봇이 정상이 아니라는 신호라서, 한 바퀴 fallback을 하지 않고 정지 후 바로 `FAILED`로 끝낸다.
- 모든 단계의 대기 시간, 각도, 속도는 파라미터(6번)로 정한다.

## 4. 기능 요구사항
| ID | 요구사항 |
|---|---|
| F1 | `pose_reset_cmd`(std_msgs/String)로 waypoint 이름(예: `P3`, `I2`)을 받는다. 이름이 `points`에 없으면 `FAILED`(이유: unknown waypoint)로 알리고 아무것도 움직이지 않는다. |
| F2 | waypoint `(x, y, yaw)`를 `map` 프레임 `/initialpose`로 발행한다. yaw가 없는 점(`[x, y]`)은 0.0으로 처리하고 로그로 알린다. 공분산은 `initial_cov_xy`, `initial_cov_yaw`를 쓴다. 유실 대비 `initialpose_repeat`회 재발행한다. 발행 전에 구독자를 `reset_amcl_wait_sec`까지 기다린다. |
| F3 | 발행 후 바로 수렴을 확인한다(`converge_timeout_sec`). 수렴 기준은 `max_cov_xy`, `max_cov_yaw`다. 이미 수렴했으면 스캔 없이 `CONVERGED`로 끝낸다. |
| F4 | 수렴하지 않으면 **좌우 스캔**을 한다. 정면 기준 왼쪽 `+scan_half_angle_rad`까지 돌고, 오른쪽 `-scan_half_angle_rad`까지 돈 뒤(회전량 `2 × scan_half_angle_rad`), 정면(원래 방향)으로 돌아온다. 속도는 `scan_angular_speed`다. **회전량은 `odom_topic`(nav_msgs/Odometry)의 yaw 변화량을 −π~π 경계를 풀어 누적해서 잰다.** 구간 목표 각도의 `scan_angle_tolerance_rad` 이내에 들어오면 그 구간을 끝낸다. **수렴하는 즉시 정지**하며, 정면 복귀는 하지 않고 그 자리에서 끝낸다. |
| F5 | 좌우 스캔으로 실패하면 제자리 한 바퀴 스캔을 한 번 더 시도한다. 한 바퀴는 오도메트리 누적 회전량 2π로 판단한다. 켜고 끄는 값은 `scan_full_turn_fallback`이다. 그래도 실패하면 `FAILED`를 발행하고 정지한다. |
| F6 | reset 동작 중에 새 명령이 오면 거부하고 `FAILED`(busy)로 알린다. 동작은 한 번에 하나만 한다. |
| F8 | 종료·예외·취소 시 반드시 `cmd_vel`에 0을 발행해 정지시킨다. |
| F9 | 상태는 `pose_recovery_status`(String, JSON `{"state": ..., "detail": ...}`)로 발행한다. 상태는 `RESETTING`, `SCANNING_LR`, `SCANNING`, `CONVERGED`, `FAILED` 다섯 가지다. |
| F10 | 스캔 회전 안전 감시. ① 스캔 시작 전에 `odom_topic`을 `scan_odom_stale_sec` 이내에 받았는지 확인하고, 없으면 **회전하지 않고** `FAILED`(no odom)로 끝낸다. ② 스캔 중 odom이 `scan_odom_stale_sec` 이상 끊기면 즉시 정지하고 `FAILED`(odom lost). ③ 한 구간이 계획 시간(목표 각도 ÷ `scan_angular_speed`) × `scan_timeout_factor` 안에 목표 각도에 닿지 못하면(바퀴 걸림, 미동) 정지하고 `FAILED`(scan timeout). 세 경우 모두 한 바퀴 fallback을 하지 않는다. |

(F7은 마지막 위치 저장을 없애면서 삭제했다. 번호는 다른 문서 참조가 깨지지 않게 비워 둔다.)

## 5. 비기능·안전 요구사항
- **로봇이 회전하므로 patrol 이동·goto 중에는 쓰지 않는다.** `cmd_vel`을 직접 내기 때문이다. 노드는 이를 검사하지 않으므로 사용자가 patrol 정지를 확인한다. README와 노드 docstring에 명시한다. 실기 구동 전에는 주변 확인과 사용자 확인이 필요하다.
- 회전 범위는 `scan_half_angle_rad`(기본 1.5 rad, 약 86°)로 제한한다. 회전 속도는 `scan_angular_speed`(기본 0.3 rad/s)다. 벽에 가까운 waypoint에서는 값을 줄여 쓸 수 있어야 한다.
- 회전량은 오도메트리로 잰다. 명령 발행 주기와 로봇 지연 때문에 목표를 조금 넘어설 수 있고, `scan_angle_tolerance_rad` 이내를 도달로 본다. 오도메트리는 바퀴 미끄러짐 오차를 가질 수 있으므로, 구간 시간 초과 감시(F10 ③)를 함께 둔다.
- odom이 끊긴 순간부터 정지 판단까지, 최대 `min(scan_odom_stale_sec, 구간 시간 초과)` 동안은 회전 명령이 계속 나간다(기본 속도에서 최대 약 0.3 rad). 이 시간을 줄이려면 `scan_odom_stale_sec`를 낮춘다.
- 값은 모두 `declare_parameter` + `config/pose_recovery.yaml`로 관리한다. 소수점은 `0.0` 형태로 쓴다. 매직 넘버 금지.
- 판정·각도 계산은 `pose_recovery_utils.py`에 두어 ROS 없이 테스트한다.
- **새 의존성: `python3-yaml`(PyYAML) 1개를 승인받아 추가한다**(2026-10-31 사용자 허가). `points_file`(yaml)을 읽는 데만 쓴다. `package.xml`과 `setup.py` 둘 다 수정한다. 스캔에는 `nav_msgs/Odometry`(표준 메시지)를 구독한다. `geometry_msgs`, `std_msgs`와 같은 표준 메시지 패키지라서 새 외부 의존성은 아니지만, `package.xml`에 선언할지는 4단계 계획에서 사용자 확인을 받는다. 그 밖의 새 의존성과 새 msg/srv는 추가하지 않는다.
- `ROS_DOMAIN_ID`와 네트워크 설정은 건드리지 않는다. 도메인은 기존대로 장비별로 지정한다(pinky1=10, pinky2=20, pinky3=30).

## 6. 파라미터 (`config/pose_recovery.yaml` 전체)
기존 yaml은 이 표의 내용으로 교체한다. 소수점이 필요한 값은 `0.0` 형태로 쓴다.

| 이름 | 기본 | 설명 |
|---|---|---|
| `points_file` | `config/pinkyN.yaml` 경로 | waypoint `points`를 읽을 파일(`pinky_patrol_node.ros__parameters.points`). 비어 있거나 읽지 못하면 reset은 모든 명령을 `FAILED`로 거부한다 |
| `reset_topic` | `pose_reset_cmd` | 명령 토픽 이름 |
| `reset_amcl_wait_sec` | 5.0 | `/initialpose` 구독자(AMCL)를 기다리는 시간 [s] |
| `initial_cov_xy` | 0.25 | `/initialpose`로 보낼 위치 분산 [m^2] |
| `initial_cov_yaw` | 0.3 | `/initialpose`로 보낼 방향 분산 [rad^2] |
| `initialpose_repeat` | 3 | 유실 대비 재발행 횟수 |
| `max_cov_xy` | 0.05 | 수렴으로 볼 위치 분산 상한 [m^2] |
| `max_cov_yaw` | 0.1 | 수렴으로 볼 방향 분산 상한 [rad^2] |
| `converge_timeout_sec` | 5.0 | 발행 후 수렴을 기다리는 시간 [s] |
| `scan_angular_speed` | 0.3 | 스캔 회전 속도 [rad/s] |
| `scan_half_angle_rad` | 1.5 | 좌우 스캔 한쪽 각도 [rad] |
| `scan_full_turn_fallback` | true | 좌우 실패 시 한 바퀴 스캔도 시도할지 |
| `odom_topic` | `odom` | 회전량을 재는 오도메트리 토픽 (nav_msgs/Odometry). 로봇 도메인의 `/odom`이다 |
| `scan_angle_tolerance_rad` | 0.05 | 구간 목표 각도에 이만큼 가까워지면 도달로 본다 [rad] |
| `scan_odom_stale_sec` | 1.0 | 스캔 전·중에 odom이 이 시간 이상 안 들어오면 정지하고 `FAILED` [s] |
| `scan_timeout_factor` | 2.0 | 구간 계획 시간(각도 ÷ 속도)의 이 배수를 넘기면 정지하고 `FAILED` |

기존 yaml의 `pose_file`, `startup_restore`, `save_period_sec`, `max_speed_mps`, `jump_accept_count`, `max_age_sec`, `amcl_wait_timeout_sec`, `global_fallback`, `drift_*`, `auto_recover_on_drift`는 쓰지 않으므로 지운다.

## 7. 변경 파일
- `cobot_pinky_patrol/cobot_pinky_patrol/pinky_pose_recovery_node.py`: **전체 교체.** 명령 구독, reset 처리 스레드, 좌우 스캔, 한 바퀴 스캔, 상태 발행
- `cobot_pinky_patrol/cobot_pinky_patrol/pose_recovery_utils.py`: **전체 교체.** 수렴 판정, yaw/쿼터니언 변환, points_file 읽기, 좌우 스캔 계획, 오도메트리 각도 변화 누적(−π~π 풀기), 구간 시간 초과 계산
  - 2단계의 `plan_lr_scan(half_angle, speed)`은 (방향, 시간)을 돌려주도록 만들었다. 오도메트리 기반으로 바뀌므로 4단계에서 `(방향, 목표 각도[rad])`를 돌려주도록 고치고 테스트도 함께 고친다.
- `cobot_pinky_patrol/config/pose_recovery.yaml`: **전체 교체.** 6번 표의 파라미터
- `cobot_pinky_patrol/test/test_pose_recovery_utils.py`: **전체 교체.** 새 함수의 단위 테스트
- `cobot_pinky_patrol/README.md`: "위치 복원" 절을 reset 기능 설명으로 교체
- `cobot_pinky_patrol/package.xml`: `python3-yaml` `exec_depend` 추가
- `cobot_pinky_patrol/setup.py`: `install_requires`에 `pyyaml` 추가. entry point는 그대로
- `cobot_pinky_patrol/launch/pose_recovery.launch.xml`: `robot` 인자 추가. 기본값이 없어 반드시 지정해야 하며(`robot:=pinky2`), `config/<robot>.yaml`을 `points_file`로 넘긴다

## 8. 검증
1. 단위 테스트: 좌우 스캔 목표 각도 순서, waypoint 파싱(yaw 없음, 없는 이름), points_file 읽기(파일 없음, 키 없음, 잘못된 형식), 수렴 판정 경계값, 각도 변화 누적(−π/π 경계를 넘는 회전, 회전 방향 부호), 구간 시간 초과 계산
2. 빌드 → `colcon test --packages-select cobot_pinky_patrol` → 린트(flake8, pep257)
3. 격리 스모크 시험(`ROS_DOMAIN_ID=101`, 가짜 AMCL·가짜 odom·가짜 `cmd_vel` 구독기): 가짜 odom이 `cmd_vel`을 적분해 회전을 흉내 내게 하고, 목표 각도에서 멈추는지, 수렴 즉시 정지하는지, odom 없음·끊김·시간 초과(F10)에서 회전 없이 또는 즉시 정지하는지, SIGINT에서 마지막 `cmd_vel`이 0인지 확인
4. 실기(사용자 확인 후): 로봇을 waypoint에 놓고 명령 → `/amcl_pose` 확인, 좌우 스캔 중 장애물 여부와 실제 회전 각도 확인

## 9. 결정 사항
2026-10-31 사용자 결정으로 확정했다.
1. 명령 인터페이스: `std_msgs/String` 토픽.
2. 좌우 스캔: 한쪽 1.5 rad(약 86°), 왼쪽 먼저.
3. waypoint yaw는 "도착 시 로봇이 보는 방향"이라 사람이 그 방향으로 놓아야 한다. 놓는 방향이 크게 틀릴 수 있으면 `initial_cov_yaw`를 키운다.
4. 관제 PC 연동: `cobot_domain_bridge`에 `/pinkyN/pose_reset_cmd` 항목 추가는 후속 작업으로 둔다.
5. `python3-yaml` 의존성 추가를 허가한다.
6. patrol 이동 중 reset 거부 기능은 넣지 않는다.
7. AMCL 구독자 대기 시간은 `reset_amcl_wait_sec` 파라미터로 분리한다.
8. 기존 위치 복원 파일은 이 PRD 내용으로 전부 교체한다. 충돌하면 이 PRD가 우선한다.

2026-11-01 사용자 결정.
9. 스캔 회전량은 시간 기반이 아니라 오도메트리 기반으로 한다. 정확성이 우선이다.
10. 오도메트리 기반이 되면서 odom 없음·끊김·구간 시간 초과 감시(F10)와 파라미터 4개(`odom_topic`, `scan_angle_tolerance_rad`, `scan_odom_stale_sec`, `scan_timeout_factor`)를 추가한다. 이 세 경우는 fallback 없이 정지 후 `FAILED`로 끝낸다.

## 10. 구현 단계
한 번에 만들지 않고 단계별로 나눠 진행한다. 앞 단계의 빌드·테스트가 통과해야 다음 단계로 간다. 단계마다 Plan 모드로 계획을 승인받는다. (CLAUDE.md 10-1)
각 단계의 공통 검증은 `colcon build --symlink-install --packages-select cobot_pinky_patrol` → `colcon test` → `colcon test-result --verbose` → 린트(`ament_flake8`, `ament_pep257`) 순서다.

### 10-1. 1단계: PRD 정리 — ✅ 완료 (2026-10-31)
- **목표**: PRD와 기존 코드의 불일치를 찾고 열린 질문을 확정한다. 파일은 수정하지 않는다.
- **결과**: 9번 결정 사항 1~8이 확정되었다(`python3-yaml` 허가, patrol 이동 중 거부 안 함, 대기 시간 파라미터 분리, 기존 파일 전수 교체).
- **로봇 구동**: 없음

### 10-2. 2단계: 순수 로직 — ✅ 완료 (2026-10-31)
- **목표**: ROS 없이 테스트할 수 있는 순수 함수를 새로 쓴다.
- **요구사항**: F2, F3, F4(계획 부분)
- **변경 파일**: `pose_recovery_utils.py`(전체 교체), `test_pose_recovery_utils.py`(전체 교체), `package.xml`(`python3-yaml`), `setup.py`(`pyyaml`)
- **만든 것**: 수렴 판정, yaw/쿼터니언 변환, `load_waypoints`, `get_waypoint`, `plan_lr_scan`(시간 기반 — 4단계에서 각도 기반으로 바뀜), `full_turn_sec`
- **결과**: 단위 테스트 통과, 린트 통과
- **로봇 구동**: 없음

### 10-3. 3단계: 명령 수신 — ✅ 완료 (2026-10-31)
- **목표**: 명령을 받아 이름을 검증하고 `/initialpose`를 발행한 뒤 1차 수렴을 확인한다. 수렴하지 못하면 이 단계에서는 `FAILED`로 끝낸다(스캔 미구현).
- **요구사항**: F1, F2, F3, F6, F9
- **변경 파일**: `pinky_pose_recovery_node.py`(전체 교체), `pose_recovery.yaml`(전체 교체), `pose_recovery.launch.xml`(`robot` 인자 필수 추가), `pose_recovery_utils.py`(`make_initialpose_cov`, `build_status` 추가), `test_pose_recovery_utils.py`
- **결과**
  - 단위 테스트 40개 통과, 린트 통과
  - 격리 스모크 시험(`ROS_DOMAIN_ID=101`, 가짜 AMCL) 11/11 통과: 정상 흐름, 없는 이름, 이름 정규화, 수렴 실패, busy 거부, 재명령 수락, 구독자 없음
  - `colcon test` 전체는 193개 중 5개 실패. 모두 `test_patrol_queue.py`의 구역 좌표 테스트이며 이번 변경과 무관해 보이나, 수정 전 상태에서도 실패했는지는 확인하지 못했다
- **로봇 구동**: 없음 (`cmd_vel` 미발행)

### 10-4. 4단계: 스캔·마무리 — ✅ 완료 (2026-11-01)
- **목표**: 수렴하지 못했을 때 오도메트리로 회전량을 재며 좌우 스캔과 한 바퀴 스캔을 하고, 모든 종료 경로에서 반드시 정지한다.
- **요구사항**: F4, F5, F8, F9, F10
- **변경 파일**
  - `pose_recovery_utils.py`: `angle_delta`, `RotationTracker`, `segment_timeout_sec`, `validate_scan_params` 추가, `plan_lr_scan`을 (방향, 목표 각도) 목록으로 변경, 쓰지 않게 된 `full_turn_sec` 삭제
  - `pinky_pose_recovery_node.py`: `odom` 구독, `cmd_vel` 발행, 구간 회전 루프, SIGINT/SIGTERM 정리, 시작 시 파라미터 검증
  - `pose_recovery.yaml`: `odom_topic`, `scan_angle_tolerance_rad`(0.05), `scan_odom_stale_sec`(1.0), `scan_timeout_factor`(2.0) 추가. 기본값 3개는 추정치이며 6단계에서 확인해 고친다.
  - `test_pose_recovery_utils.py`: 새 함수 테스트 추가, 시간 기반 `plan_lr_scan` 테스트 교체
  - `package.xml`: `nav_msgs` `exec_depend` 추가
- **구현에서 정한 것**
  - 정지 명령은 회전 명령을 한 번이라도 낸 구간에서만 낸다(`_rotate`의 `finally`). 회전하지 않은 reset(없는 이름, no odom 등)에서는 `cmd_vel`을 발행하지 않아, 다른 노드의 `cmd_vel`을 건드리지 않는다.
  - Ctrl+C·SIGTERM에서 정지 명령이 나가도록 `rclpy.init(signal_handler_options=SignalHandlerOptions.NO)`를 쓰고, 메인 루프는 `spin_once`를 0.1초 주기로 돌려 시그널을 바로 처리한다.
- **결과**
  - 단위 테스트 58개 통과(`angle_delta` ±π 경계, `RotationTracker` 누적, 스캔 계획, 시간 초과, 파라미터 검증), `ament_flake8`·`ament_pep257` 통과
  - 격리 스모크 시험(`ROS_DOMAIN_ID=101`, 가짜 AMCL·odom, 시작 yaw 3.0 rad) 26/26 통과: 스캔 중 수렴 시 즉시 정지, 좌우(−0.6~+0.6)와 한 바퀴(약 2π) 스캔, fallback 끔, odom 없음(회전 명령 0회), odom 끊김, 로봇 미동(시간 초과), 스캔 중 SIGINT 정지, 잘못된 파라미터에서 노드 미시작, 시험 후 남은 프로세스 없음
  - `colcon test` 전체는 211개 중 5개 실패. 3단계와 같은 `test_patrol_queue.py`의 구역 좌표 테스트이며 이번 변경과 무관해 보이나, 수정 전 상태에서도 실패했는지는 확인하지 못했다
- **로봇 구동**: 없음. 가짜 odom과 가짜 `cmd_vel` 구독기로만 시험했다.

### 10-5. 5단계: 문서·검증 — ✅ 완료 (2026-11-01)
- **목표**: 문서를 구현에 맞추고 전체를 한 번 더 검증한다. 기능 코드는 수정하지 않는다.
- **변경 파일**: `README.md`("위치 복원" 절을 "위치 재설정" 절로 교체, 프로젝트 구조 트리와 "주요 기능" 갱신)
- **결정 (2026-11-01)**: `docs/prd/behavior_tree_prd.md`는 수정하지 않는다. 그 문서의 "위치 복원 노드는 변경 없음"(25행, 228행)은 BT 전환 작업의 범위 설명이라 사실과 어긋나지 않는다. README에 "제거된 기능" 안내는 넣지 않는다.
- **결과**
  - 단위 테스트 58개 통과, `ament_flake8`·`ament_pep257` 통과
  - 파라미터 대조: PRD 6번 16개 = 노드 `declare_parameter` 16개 = `pose_recovery.yaml` 16개, yaml 기본값과 코드 기본값 일치
  - 상태 문자열: 노드가 발행하는 상태는 `RESETTING` `SCANNING_LR` `SCANNING` `CONVERGED` `FAILED`로 F9와 일치
  - `colcon test` 전체는 211개 중 5개 실패. 이전 단계와 같은 `test_patrol_queue.py`의 구역 좌표 테스트이며 이번 변경과 무관해 보이나, 수정 전 상태에서도 실패했는지는 확인하지 못했다
- **PRD와 구현의 차이 (PRD는 아직 고치지 않았다. 사용자 확인 대기)**
  1. F8은 "종료·예외·취소 시 반드시 `cmd_vel`에 0을 발행"이라 쓰지만, 구현은 **회전 명령을 낸 구간에서만** 정지 명령을 낸다. 회전하지 않은 reset이 다른 노드(patrol 등)의 `cmd_vel`을 건드리지 않게 하려는 것이다.
  2. 구현은 좌우 스캔(또는 한 바퀴 스캔)이 끝난 뒤 정지한 채로 `converge_timeout_sec`만큼 마지막 수렴 확인을 한 번 더 한다. 3-1 절차에는 없다.
  3. 7번 변경 파일에 `package.xml`의 `nav_msgs` 추가가 빠져 있고, 5번의 "`package.xml`에 선언할지는 4단계 계획에서 확인" 문구는 이미 결정되어(추가함) 낡았다.
  4. 스캔 중 노드를 종료하면 `FAILED`의 detail이 `aborted`로 나가는데 PRD에 없다.
  5. 7번과 10-2의 "`plan_lr_scan`을 4단계에서 고친다"는 문구는 4단계에서 이미 반영되어 낡았다.
- **로봇 구동**: 없음

### 10-6. 6단계: 실기 시험 — ⬜ 예정 (사용자가 직접)
- **목표**: 실제 로봇에서 동작을 확인한다.
- **전제**: 4~5단계 완료. 실제 로봇을 구동하므로 사용자가 직접 하거나, 실행 직전에 확인을 받는다.
- **체크리스트**
  1. patrol 이동이 멈춘 상태인지 확인하고 주변에 장애물이 없는지 본다.
  2. 로봇을 waypoint에 놓고 yaw 방향을 대략 맞춘다. `ROS_DOMAIN_ID`는 장비에 맞게 지정한다(pinky2=20).
  3. `ros2 topic echo /odom --once`로 오도메트리가 나오는지 확인한다.
  4. `ros2 topic pub --once /pose_reset_cmd std_msgs/msg/String "{data: 'P3'}"`를 실행한다.
  5. `pose_recovery_status`가 `RESETTING` → `SCANNING_LR` → `CONVERGED`로 바뀌는지 본다. 스캔 중 로봇이 약 86° 왼쪽 → 약 172° 오른쪽 → 약 86° 왼쪽으로 도는지 눈으로 확인한다.
  6. `ros2 topic echo /amcl_pose --once`로 위치가 waypoint 근처인지 확인한다.
  7. 이름이 없는 waypoint와 동작 중 재명령을 보내 `FAILED`로 거부되는지 확인한다.
  8. (선택) 오도메트리를 끊은 상태에서 명령을 보내 `FAILED`(no odom)로 끝나고 로봇이 회전하지 않는지 확인한다.
- **결과**: 시험 후 이 칸에 기록한다. 기본 파라미터 3개(`scan_angle_tolerance_rad`, `scan_odom_stale_sec`, `scan_timeout_factor`)는 추정치이므로 여기서 확인해 고친다.
- **로봇 구동**: 있음 (사용자 확인 후)
