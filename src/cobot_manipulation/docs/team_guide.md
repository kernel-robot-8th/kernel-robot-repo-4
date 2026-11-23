# 팔 노드 한 장 안내 (팀원용)

2026-11-15 기준. 정본은 [`prd.md`](prd.md) 이다. **실제 팔로는 아직 시험하지 않았다** (가짜 로봇만).

관제가 Station PC 에 가지 않고 **팔을 켜고(START), 일을 시키고(pick·load), 끈다(RESET)**. 팔은 학습한 ACT 모델로 움직인다.
구성도는 [prd.md 0절](prd.md#0-하는-일), 상태도는 [5절](prd.md#전원-상태-흐름).

## 하루 흐름

| 순서 | 누가 | 무엇을 | 팔 |
|---|---|---|---|
| 1 | Station PC | 노드를 켜 둔다 | 꺼짐. 연결·토크 없음 |
| 2 | 관제 | `CMD_START` | 연결·모델 로드 약 10 s. 토크가 잠깐 꺼졌다 켜진다 → **쉬는 자세에서 켤 것** |
| 3 | 관제 | 작업 `pick`·`load` | 시작 자세 → 정책 실행 → 안전 자세 → 결과 |
| - | 관제 | 비상정지 `CMD_SOFT_LATCH` → 현장 확인 → 잠금 해제 `CMD_UNLATCH` | 토크 유지한 채 멈춤 → 잠금만 풀림, 움직이지 않음. 다음 작업부터 받음 |
| 4 | 관제 | `CMD_RESET` | 쉬는 자세면 끔, 아니면 거절. 현장 설정 `release_move` 면 쉬는 자세로 옮긴 뒤 끔 ([끄기 순서](prd.md#끄기-순서-cmd_reset)) |

## 결과 읽는 법

| 결과 | 뜻 | 관제가 할 일 |
|---|---|---|
| `success=true` | 성공 판단 OK + 안전 자세 확인 | 다음 단계 |
| `success=false` + `retry_safe=true` | 팔이 **움직이기 전에** 거절 | 다시 보내도 됨 |
| `success=false`, `retry_safe` 없음 | 움직인 뒤 실패·정지·고장 | 주문 보류, 사람 확인 |

## 시험해 보기 (팔 없이)

```bash
scripts/run_arm_adapter.sh --domain 101 --localhost --backend fake
# 다른 터미널
source /opt/ros/jazzy/setup.bash && source install/setup.bash
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
/usr/bin/python3 scripts/arm_console.py     # start, pick, s, saverest, reset, q
```

관제 웹 로봇팔 패널(`feature/control-center`)로도 켜기·끄기·정지를 보낼 수 있다. pick 은 웹에 버튼이 없어 콘솔로 보낸다.

## 주의

- 급할 때는 **팔 12 V 전원 차단**이 가장 빠르다. 팔이 떨어지니 받칠 것.
- `--backend fake` 를 빼면 실제 팔을 쓴다. 팔 옆에 사람이 없으면 노드를 끈다 (관제 웹에 로그인이 없다).
- **지금은 성공이 나오지 않는다.** 성공 판단 YOLO 모델이 없어 늘 "확인 못 함 = 실패".

토픽·명령·상태 필드는 [prd.md 5절](prd.md#5-관제-켜기끄기-armcommand--commandackarmstatus), 남은 일·팀 결정은 [6절](prd.md#6-남은-일과-팀-결정).
