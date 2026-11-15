# 팔 노드 한 장 안내 (팀원용)

2026-11-15 기준. 자세한 규격은 [`prd.md`](prd.md), 실행기는 `tool/omx-dashboard` 브랜치 `omx_fleet/README.md`.
**실제 팔로는 아직 시험하지 않았다.** 가짜 로봇으로만 확인했다.

## 한 줄 요약

관제가 Station PC 에 가지 않고 **팔을 켜고(START), 일을 시키고(작업 요청), 끈다(RESET)**. 팔은 학습한 ACT 모델로 움직인다.

```text
관제 PC                                Station PC
fleet_control ── 작업 요청·결과 ──▶  팔 어댑터 노드 ──▶ 팔 실행기 ──▶ 실제 팔
관제 코어     ── 켜기·끄기 ──────▶  (cobot_manipulation)  (omx_fleet, lerobot 0.4.4)
              ◀─ 응답·상태 ───────
```

| 부분 | 어디 | 하는 일 |
|---|---|---|
| 팔 어댑터 노드 | `cobot_manipulation` (ROS 노드) | 관제와 대화. 주문 검사, 켜기·끄기, 상태 발행 |
| 팔 실행기 | `tool/omx-dashboard` 브랜치 `omx_fleet/` | 팔에 연결해 토크를 붙잡고, 모델을 돌려 실제로 움직임 |

실행기를 따로 두는 이유: 작업마다 lerobot 을 새로 켜면 연결·해제 때 토크가 꺼져 **팔이 떨어지고 물건을 놓친다**.
실행기는 한 번 연결해 토크를 유지한 채 계속 일을 받는다.

## 하루 흐름

| 순서 | 누가 | 무엇을 | 팔 |
|---|---|---|---|
| 1 | Station PC | 노드를 켜 둔다 | 꺼짐. 연결·토크 없음 |
| 2 | 관제 | `CMD_START` | 팔에 연결, 모델 불러옴 (약 10초). 토크가 잠깐 꺼졌다 켜진다 → **쉬는 자세에서 켤 것** |
| 3 | 관제 | 작업 요청 `pick`·`load` | 시작 자세 → 정책 실행 → 안전 자세 → 결과 보고 |
| 4 | 관제 | `CMD_RESET` | 쉬는 자세면 토크를 끔. 아니면 **거절** ("현장에서 팔을 내려 주세요") |

- 끄기는 팔을 옮기지 않는다. 관제는 팔 모션을 시작하지 않는다는 팀 규칙(`ArmCommand.msg`) 때문이다.
- 급할 때는 **팔 12 V 전원 차단**이 가장 빠르다. 팔이 떨어지니 받칠 것.

## 주고받는 것

| 토픽 | 타입 | 방향 | 내용 |
|---|---|---|---|
| `/fleet/work_request` | String(JSON) | 관제 → 팔 | 작업 요청 (기존 fleet_control 계약 그대로) |
| `/fleet/work_result` | String(JSON) | 팔 → 관제 | 실측 결과 |
| `/control_center/omx_1/command` | `ArmCommand` | 관제 → 팔 | 켜기·끄기·정지 |
| `/manipulation/omx_1/command_ack` | `CommandAck` | 팔 → 관제 | 명령을 받았는지·거절 이유 |
| `/manipulation/omx_1/status` | `ArmStatus` | 팔 → 관제, 10 Hz | 토크, 관절 값, 퇴피 실측, 정지 상태 |

모두 `cobot_interfaces` 에 이미 있는 메시지다. **인터페이스는 바꾸지 않았다.**

## 명령 (`ArmCommand`)

| 명령 | 언제 되나 | 결과 |
|---|---|---|
| `CMD_START` (3) | 꺼짐일 때, 새 epoch 로 | 켜짐 |
| `CMD_RESET` (2) | 켜짐·소프트 정지, 작업 중 아님 | 쉬는 자세면 꺼짐, 아니면 거절 |
| `CMD_SOFT_LATCH` (4) | 언제나 | 작업을 멈추고 토크 유지. RESET 으로만 풀림 |
| `CMD_HOLD` (0) / `CMD_RELEASE_HOLD` (1) | 언제나 | 정지 / 정지 해제. 꺼지면(RESET) 정지도 풀림 |

- 정지 명령은 검사에 걸려도 **무조건 멈춘다**.
- HOLD 는 꺼질 때(DISARMED) 지워진다. 꺼진 팔은 `hold_active=false` 이고, 다시 켠 뒤에도 멈춰야 하면 관제가 HOLD 를 다시 보낸다.
- 헤더 검사: 대상 `omx_1`, 유효 시간 5 s, START 는 새 epoch, 그 밖은 같은 epoch + seq 증가. **서명(sig)은 아직 안 본다** (D13).

## 결과를 읽는 법

| 결과 | 뜻 | 관제가 할 일 |
|---|---|---|
| `success=true` | 성공 판단 OK + 안전 자세 확인 | 다음 단계 |
| `success=false` + `retry_safe=true` | 팔이 **움직이기 전에** 거절 (꺼짐, 작업 중, 만료 등) | 다시 보내도 됨 |
| `success=false`, `retry_safe` 없음 | 움직인 뒤 실패·정지·고장 | 주문 보류, 사람 확인 |

**지금은 성공이 나오지 않는다.** 카메라 성공 판단(YOLO) 모델이 아직 없어 항상 "확인 못 함 = 실패" 로 보낸다.

## 상태 (`ArmStatus`) 보는 법

| 보고 싶은 것 | 필드 |
|---|---|
| 켜졌나 | `torque_enabled` |
| 팔이 물러났나 | `retract_safe` 와 `retract_safe_measured` 가 **둘 다** true |
| 멈춰 있나 | `hold_active`, `hold_reason` (`HOLD`·`SOFT_LATCH`) |
| 관절 값이 최신인가 | `header.stamp` (작업 중에는 갱신 안 됨) |

`ArmStatus` 에는 "고장" 칸이 없다. 고장은 CommandAck 거절 사유와 노드 로그로 본다.

## 시험해 보기 (팔 없이)

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_manipulation arm_station.launch.xml backend:=fake
ros2 topic echo /manipulation/omx_1/status    # 다른 터미널
```

fake 도 꺼짐으로 시작한다. `CMD_START` 를 보내야 켜지는데, 아직 `ArmCommand` 를 보내는 관제 코드가 없어 지금은 시험 스크립트로 보낸다.
`backend:=worker` 는 실제 팔을 쓴다. 팔 옆에 사람이 있을 때만.

## 아직 안 된 것

| 할 일 | 담당 (제안) |
|---|---|
| 관제 화면의 켜기·끄기 버튼, HTTP → `ArmCommand` 중계 | 로봇 수행 관제 |
| 실제 팔 시험 (보드가 omx1 이 맞는지, 캘리브레이션) | 로봇팔 + 관제 |
| 쉬는 자세 실측 (지금은 임시로 shoebox_d 시작 자세) | 로봇팔 |
| 성공 판단 YOLO 모델 | 로봇팔·비전 |
| omx2·omx3 등록 | 로봇팔 |

## 팀이 정해 줄 것

1. **팔 이름**: 명세는 `omx_1`, 관제 시나리오는 `omx1`. 지금은 자동으로 이어 붙인다.
2. **`retract_safe` 기준**: 명세는 "Z ≥ 280 mm", 여기서는 관절 오차 5° 이내.
3. **`ArmStatus` 에 전원 상태 칸**을 넣을지 (켜짐·꺼짐·고장).
4. **서명 키** (D13).
