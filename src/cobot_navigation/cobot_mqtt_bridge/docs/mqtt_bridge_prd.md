# mqtt_bridge_prd — MQTT 브릿지 PRD

담당: 주행 (`cobot_navigation`)
작성일: 2026-11-07 / 상태: A·B·C(PC 쪽)·**D(실물 없이 가능한 부분)·E(가짜 모드)·F-0/F-0b/F-1·G-2·G-3 완료**, F-2~F-4 보류. 서비스는 설치되어 켜져 있음. 실물 pinky1 시험(A, C 로봇 쪽, D 터널 끊김)은 모두 보류

## 1. 목적
- 관제 PC와 로봇 사이의 통신 방식으로 DDS `cobot_domain_bridge` 말고 **MQTT 브릿지(launch 한 개)도 쓸 수 있게** 한다. 기능은 도메인 브릿지와 같아야 한다.
- **`cobot_domain_bridge`는 유지한다.** 삭제·수정하지 않고, 두 브릿지를 **상황에 맞게 골라 쓴다**(한 번에 하나만 켠다).
- **기존 `cobot_navigation` 코드는 수정 없이 호환되어야 한다.** 노드·launch·파라미터 코드는 그대로 두고 관제↔로봇 사이의 통신 방식만 바꾼다. 그러려면 관제 PC(도메인 100)에서는 지금과 같은 토픽 이름(`/pinky1/...`)·타입·QoS·주기로 보이고, 로봇(도메인 10)에서는 원래 이름(`/cmd_vel`, `/amcl_pose`...)으로 보여야 한다.
- 대체 범위의 정본은 `src/cobot_navigation/cobot_domain_bridge/config/pinky_bridge_pinky{1,2,3}.yaml`이다. 토픽을 따로 적지 않고 이 YAML을 읽어서 쓴다.

## 2. 현재까지 된 것 / 안 된 것
| 항목 | 상태 | 근거 |
|---|---|---|
| 로봇→관제(up) 중계, YAML 기반, 로봇당 1프로세스 | 가짜 모드(도메인 101→102)에서 완료 | `colcon test` 27개 통과, 가짜 모드 유실 0 |
| 실물 pinky1 10분 시험 | **보류** (실물 없는 환경) | pinky1 `/tmp` 임시 복사·열린 터널 사용은 승인됨 |
| 관제→로봇(명령) 중계 | **미구현** | B단계 |
| 한 번에 켜는 launch | **없음** | C단계 |
| 끊김 복구, 상태 표시, 자동 시작 | 없음 | D·G단계 |
| pinky2·pinky3 | 미시험 | E단계 |
| 실제 도메인 100 적용 | 안 함 | 다른 팀이 DDS 브릿지를 켜 둠. F단계 |

## 3. 범위
| 포함 | 제외 |
|---|---|
| YAML 기반 양방향 중계 노드(프로세스 1개/로봇) | `cobot_domain_bridge` 코드 삭제·수정 (**유지**, 병행 사용) |
| 두 브릿지를 고르는 launch 인자·문서 | `cobot_navigation` 노드·launch·파라미터 코드 수정 |
| `mqtt_bridge.launch.xml` (pinky1~3 선택 실행) | msg/srv/action 인터페이스 변경 |
| 명령 방향 안전장치(워치독, 속도 상한, 격리 시험) | 서비스·액션의 MQTT 변환 (YAML에 없음) |
| 끊김 복구, 상태 토픽, 로그 | 팀 결정 문서(`fms_decisions.md`) 직접 수정 (제안만) |
| 로봇 쪽 자동 시작(systemd) 설계 | sudo 없는 환경 변경 (sudo는 매번 확인) |

## 4. 설계 원칙
1. **YAML이 정본**: 토픽 목록·방향·remap·타입은 YAML에서 읽는다. 하드코딩 금지(CLAUDE.md 6).
2. **MQTT 주제 규칙**: `mqtt_bridge/<robot>/<방향>/<원래 로봇쪽 토픽>`  (방향 = `up` 로봇→관제, `down` 관제→로봇). 방향이 주제에 들어 있어 되돌아오는 루프가 생기지 않는다.
3. **로봇 프로세스는 1개**: 지금은 토픽당 1개(15개)라 pinky1에 부담이다. 한 프로세스가 여러 토픽을 맡는다.
4. **래치 토픽**(`/tf_static`, `/amcl_pose`)은 `transient_local` + MQTT retain.
5. **안전 우선**: 명령 방향은 시험 도메인(101/102)에서만 개발한다. 실제 도메인 100·10 적용은 단계마다 사용자 확인.
6. **DDS 브릿지와 동시에 켜지 않는다**: 같은 도메인 100에서 토픽이 이중 발행된다. 켜기 전 기존 발행자 검사를 한다(노드에 구현됨).
7. **기존 코드 무수정 호환**: 관제 쪽 토픽 이름·타입·QoS(구독 노드가 쓰는 reliable/best_effort/transient_local)가 DDS 브릿지 때와 같아야 한다. 호환이 깨지는 변경(이름·타입 변경, 주기 변경)은 하지 않는다.
8. **두 브릿지 공존**: 도메인 브릿지와 MQTT 브릿지를 상황에 맞게 고른다. 한 도메인에서는 한 번에 하나만 켠다(이중 발행 방지).
9. launch는 XML(`*.launch.xml`), 값은 launch 인자·YAML 파라미터로 둔다.

## 5. 산출물과 위치
정식 패키지 `src/cobot_navigation/cobot_mqtt_bridge/`(ament_python, 2026-11-07 사용자 승인).

| 산출물 | 위치 | 상태 |
|---|---|---|
| 노드 `mqtt_bridge_node.py` (로봇당 1프로세스) | `cobot_mqtt_bridge/cobot_mqtt_bridge/` | A단계 완료 |
| 순수 로직 `bridge_config.py`, `relay_utils.py` | 같은 폴더 | A단계 완료 |
| 설정 `mqtt_bridge.yaml` (브로커·상한·워치독) | `cobot_mqtt_bridge/config/` | A단계 완료 |
| launch `mqtt_bridge.launch.xml` | `cobot_mqtt_bridge/launch/` | C단계 |
| 단위·린트 시험 | `cobot_mqtt_bridge/test/` | A단계 완료 |
| 이 PRD | `cobot_mqtt_bridge/docs/mqtt_bridge_prd.md` | |

## 6. 단계 개요
| 단계 | 내용 | 실제 로봇 | 도메인 |
|---|---|---|---|
| A | YAML 파서 + 매니저(로봇→관제, 로봇 1프로세스) | 구독만 | 102 |
| B | 명령 방향(관제→로봇) 격리 구현 | 없음(가짜) | 101/102 |
| C | `mqtt_bridge.launch.xml` 통합(pinky1) | 구독만 | 102 |
| D | 안정성(재연결, 상태 토픽, 워치독, 오래 돌리기) | 구독만 | 102 |
| E | pinky2·pinky3 확장 + 동시 실행 | 구독만 | 102 |
| F | 실제 도메인 적용(그림자 → 전환 → 되돌리기) | **명령 시 구동 있음** | 100/10 |
| G | 자동 시작·문서·팀 결정 제안 | 설정 변경 | — |

각 단계는 **앞 단계의 시험이 모두 통과해야** 시작한다. 단계마다 사용자 승인 후 진행한다.

---

## 7. 단계별 상세

### A단계: 매니저 (로봇→관제, YAML 기반)
**목표**: YAML을 읽어 `from_domain` 이 로봇인 토픽(15개)을 한 번에 올린다.
**작업**
- `mqtt_bridge_node.py`: `--robot pinky1 --config <yaml> --side {robot,pc}` 로 실행. 로봇 쪽은 프로세스 1개가 토픽 15개를 구독해 MQTT로 발행, PC 쪽은 MQTT를 받아 `remap` 이름으로 발행.
- 기존 `mqtt_ros_relay.py`의 QoS·rate 상한·래치 로직을 함수로 재사용(복사 금지).
- 느린 토픽 상한 없음, `/odom`·`/scan`·`/tf`는 원래 주기 옵션.
**산출물**: `cobot_mqtt_bridge/mqtt_bridge_node.py`, 린트 통과.
**완료 기준**
- 15개 토픽 이름·타입이 YAML의 `remap` 결과와 일치한다.
- pinky1 프로세스 수가 15 → 1개로 줄고 load가 이전 이하(≤ 1.2)다.
- 10분 유실 0(원래 주기).
**시험 절차**
1. 린트: `colcon test --packages-select cobot_mqtt_bridge` (flake8·pep257·copyright 포함)
2. 단위(ROS·MQTT 없이): YAML 파싱 결과 표를 출력해 `grep -c from_domain` 개수·remap과 대조.
3. 가짜 모드: 기존 `--role run --mode fake` 방식으로 15개 토픽 값 일치 확인.
4. 실물 읽기(도메인 102, 터널 확인 후):
   ```bash
   ps -eo pid,cmd | grep "ssh.*-R 127.0.0.1:1883" | grep -v grep
   python3 cobot_mqtt_bridge/cobot_mqtt_bridge/mqtt_bridge_node.py --robot pinky1 --config src/cobot_navigation/cobot_domain_bridge/config/pinky_bridge_pinky1.yaml --duration 600
   ssh pinky@192.168.45.21 'pgrep -fc mqtt_bridge_manager; uptime'
   ROS_DOMAIN_ID=102 CYCLONEDDS_URI="$LO" ros2 topic list
   ```
5. 종료 뒤 pinky1·PC에 남은 프로세스 0개.

**Claude Code 프롬프트**
```
[A단계] cobot_mqtt_bridge/docs/mqtt_bridge_prd.md 의 A단계를 진행한다.
먼저 plan으로 변경 파일 목록과 검증 방법을 보여주고 승인받은 뒤 작업해.
- cobot_mqtt_bridge/cobot_mqtt_bridge/mqtt_bridge_node.py 를 새로 만든다. 기존 mqtt_ros_relay.py 의 QoS/rate/래치 로직은 함수로 import 해서 쓴다(복사 금지).
- pinky_bridge_pinky1.yaml 의 from_domain=10 토픽 15개를 YAML에서 읽어 한 프로세스가 중계한다. 토픽 하드코딩 금지.
- 안전: 로봇(도메인 10)에서는 구독만, 시험은 도메인 102, 기존 발행자 사전 검사와 load 3.0 중단 유지. 로봇 구동 명령 금지.
- 끝나면 린트 3종, 가짜 모드 시험, 실물 읽기 10분 시험 결과를 표로 보고하고 이 PRD 의 단계별 결과 표에 기록해.
- 터널 열기/삭제/sudo 는 실행 직전에 물어봐.
```

---

### B단계: 명령 방향 (관제→로봇) — 격리 구현
**목표**: `patrol_cmd`, `cmd_vel`, `initialpose`, `goal_pose`, `zone_manager/grant_entry`, `zone_manager/queue_slot` 6개를 반대 방향으로 전달한다. **로봇을 움직이지 않는다.**
**작업**
- 매니저에 `down` 방향 추가(PC가 구독→MQTT 발행, 로봇 쪽이 받아 로봇 도메인으로 발행).
- QoS는 명령이라 reliable. `cmd_vel`만 별도 규칙: 마지막 수신 후 `watchdog_ms`(설정값, 기본 [TODO] 팀 합의) 지나면 0 속도를 1회 발행, 속도 상한 클램프, 오래된 메시지(타임스탬프 지연) 폐기.
- 시험 도메인에서는 로봇 쪽 목적지도 101(pinky1 쪽)로 둔다. 도메인 10으로 발행하는 코드 경로는 `--confirm-real-domain` 없이는 거부.
**완료 기준**
- 6개 토픽 값(문자열, Twist, PoseStamped 필드) 일치 0 불일치.
- `cmd_vel` 워치독: 입력 중단 후 `watchdog_ms`+여유 안에 0 속도가 나온다.
- 상한 초과 값은 클램프되어 나온다.
- 지연 평균·p95 기록(기준: DDS 대비 +수 ms).
**시험 절차**
1. 린트 3종.
2. 가짜 모드: PC 도메인 102에 `ros2 topic pub`, pinky1 격리 도메인 101에서 수신 값 비교 (`ros2 topic echo` 대신 중계 카운터·로그로 확인).
3. 워치독: 10 Hz로 5초 발행 후 중단 → 수신 쪽 로그의 마지막 메시지 시각과 0 속도 시각 차이 측정.
4. 상한: 상한보다 큰 속도 1회 발행 → 클램프 확인.
5. 도메인 10 발행 시도 → 거부 메시지 확인(음성 시험).
6. 사후: 로봇 바퀴·`/cmd_vel` 실제 변화 없음 확인(`ros2 topic info /cmd_vel` 구독자만, 발행자 0).

**Claude Code 프롬프트**
```
[B단계] PRD 의 B단계를 진행한다. A단계 시험이 모두 통과한 상태에서만 시작해.
plan 먼저. 로봇을 움직이는 어떤 것도 실행하지 마. 시험 도메인 101/102 와 가짜 메시지만 쓴다.
- mqtt_bridge_node.py 에 down 방향(YAML 에서 to_domain=10 인 6개)을 추가.
- cmd_vel 은 워치독(설정값, 기본값은 내가 정하게 인자로), 속도 상한 클램프, 오래된 메시지 폐기를 넣는다.
- 도메인 10 으로 발행하는 경로는 --confirm-real-domain 없으면 거부하게 하고, 거부 시험도 포함해.
- 완료 후 PRD B단계 시험 절차 6개를 실제로 돌리고 결과 표를 보고해.
```

---

**B단계 결과 (2026-11-07, 가짜 모드 — 관제 역할 도메인 102 → MQTT → 로봇 역할 도메인 101, 로봇·도메인 10 사용 없음)**
| 시험 | 결과 |
|---|---|
| 1. 빌드·린트·단위 | `colcon test` 44개 통과 (워치독·클램프·도메인 가드 단위 시험 17개 추가) |
| 2. 6개 값 일치 | 6/6 중계 유실 0. 문자열 3개 일치, goal_pose(map, 1.0/2.0, w=1.0)·initialpose(map, 0.5/0.25)·cmd_vel 필드 일치 |
| 3. 워치독 (500 ms 설정) | 입력 중단 뒤 0 속도까지 525~595 ms (설정 500 ms + 확인 주기 100 ms 이내), 0 속도는 1회만 발행 |
| 4. 속도 상한 (0.2 m/s, 1.0 rad/s) | 입력 (0.6, 0.8) m/s·3.0 rad/s → 출력 (0.12, 0.16) = 0.200 m/s·1.0 rad/s, 방향 유지, 9개 모두 줄임 |
| 5. 거부 | 로봇 역할: 도메인 10(확인 없음), 10(확인만, 보호 없음), 10(워치독만), 77, 100 → 모두 종료 코드 2 + 사유. 도메인 101은 보호 없으면 경고만 하고 시작 |
| 6. 사후 | 도메인 10 발행 없음(도메인 10은 거부 시험에서 시작 전에 막힘), 남은 프로세스 0, MQTT 보관 메시지 0 |
| 호환(QoS) | 관제 쪽 `/pinky1/cmd_vel` 구독 QoS = RELIABLE (기존 노드가 reliable로 발행하는 경우 호환. 기존 노드의 실제 발행 QoS는 F단계 전에 `ros2 topic info -v`로 확인 필요) |
| A단계 회귀 | up 토픽 `/battery/percent` 169/169, `/patrol_status` 34/34, 값 77.5 일치 |

참고: 명령 방향은 기본으로 꺼져 있다(`enable_down:=false`). `max_age_ms`(오래된 메시지 폐기)는 단위 시험만 했고, 두 장비 시계를 맞춘 뒤 실물에서 확인한다. `confirm_real_domain:=10`처럼 숫자로 넣어도 받는다.

### C단계: `mqtt_bridge.launch.xml` 통합
**목표**: 한 명령으로 pinky1의 양방향 중계가 켜지고, Ctrl+C 한 번에 PC·pinky1 프로세스가 모두 정리된다.
**작업**
- launch 인자: `pinky1/pinky2/pinky3`(기존 `bridges.launch.xml`과 동일 이름·기본값), `domain`(기본 시험 102), `config_dir`, `include_cmd`(기본 false), `fast_rate_hz`.
- 실행 항목: (1) 사전 검사(터널·브로커·기존 발행자), (2) PC 쪽 매니저, (3) ssh로 로봇 쪽 매니저 기동, (4) 종료 시 원격 정리.
- 기존 `bridges.launch.xml`과 인자 호환 → 호출하는 쪽만 launch 이름을 바꾸면 되게 한다.
**완료 기준**
- `ros2 launch`로 켜지고 Ctrl+C 후 양쪽 잔여 프로세스 0.
- 사전 검사 실패 시 이유를 출력하고 시작하지 않는다.
**시험 절차**
1. `xmllint --noout src/cobot_navigation/cobot_mqtt_bridge/launch/mqtt_bridge.launch.xml`
2. `ros2 launch src/cobot_navigation/cobot_mqtt_bridge/launch/mqtt_bridge.launch.xml pinky1:=true pinky2:=false pinky3:=false`
3. 다른 터미널(도메인 102): `ros2 topic list`로 15개 확인, 값 몇 개 echo.
4. Ctrl+C 후:
   ```bash
   pgrep -fc mqtt_bridge_manager
   ssh pinky@192.168.45.21 'pgrep -fc mqtt_bridge_manager'
   ```
   둘 다 0.
5. 음성 시험: 터널 닫고 실행 → 시작 거부, 브로커 정지 상태 → 시작 거부.
6. 비정상 종료 시험: launch 프로세스를 kill → 원격 프로세스가 `N`초 안에 스스로 종료되는지.

**Claude Code 프롬프트**
```
[C단계] PRD 의 C단계를 진행한다. B단계 시험이 통과했는지 이 PRD 의 결과 표에서 먼저 확인해.
plan 먼저(새 폴더 launch/, config/ 생성 승인 포함).
- src/cobot_navigation/cobot_mqtt_bridge/launch/mqtt_bridge.launch.xml 을 만든다. XML 만 사용. 인자 이름은 bridges.launch.xml 과 같게(pinky1/2/3).
- 시작 전 사전 검사(터널 상태, 브로커, 도메인 100 기존 발행자) 후 PC 매니저와 ssh 원격 매니저를 띄우고, 종료·비정상 종료 시 원격까지 정리한다.
- 실제 도메인 100 은 건드리지 않는다(기본 102). 터널을 열거나 닫는 것은 실행 직전에 물어봐.
- PRD C단계 시험 6개를 돌리고 결과를 보고해.
```

---

**C단계 결과 — PC 쪽 (2026-11-08, 가짜 모드 도메인 102 loopback, 로봇·pinky1·터널·sudo 사용 없음)**
`launch/mqtt_bridge.launch.xml`: 인자 `pinky1/2/3`(기존 `bridges.launch.xml`과 같은 이름·기본값), `params_file`, `host`, `port`, `enable_down`(false), `duration_sec`, `confirm_real_domain`. 로봇별로 노드 이름 `mqtt_bridge_<robot>`을 붙이고 파라미터 YAML 최상위 키는 `/**`로 바꿨다.
| 시험 | 결과 |
|---|---|
| XML 문법·인자 일치·린트 | `xmllint` 통과, `colcon test` 48개 통과 (launch 시험 4개 추가: 인자 이름·기본값이 `bridges.launch.xml`과 같음, 로봇당 pc 노드 1개, 노드 이름 중복 없음, 명령 방향 기본 꺼짐) |
| 기동 (pinky1) | 노드 `/mqtt_bridge_pinky1`, 관제 도메인 토픽 12개 확인, 프로세스 = launch 1 + 노드 1 |
| 종료 | SIGINT·SIGTERM 모두 정상 종료, 남은 프로세스 0 |
| 3대 동시 (시험 도메인) | 노드 3개(`pinky1~3`) 기동, SIGINT 뒤 남은 프로세스 0 |
| 음성 | 도메인 100(확인 없음), 도메인 10, 잘못된 포트(1884) → 노드가 이유를 출력하고 종료 코드 2, launch도 함께 종료 |
| launch만 `kill -9` | **자식 노드가 남는다**(launch가 죽어도 노드는 계속 실행). 수동 정리 필요 |
| 사후 | 남은 프로세스 0, MQTT 보관 메시지 0 |

한계와 후속:
- `kill -9`로 launch가 죽으면 pc 노드가 고아로 남는다. 부모 프로세스가 사라지면 스스로 종료하는 처리를 D단계 후보로 둔다.
- 실제 도메인에서 3대를 동시에 켜면 공용 토픽(`/zone_manager/*`)의 기존 발행자 검사가 서로를 막을 수 있다 → E단계 설계 항목.
- 로봇 쪽 기동(ssh), 원격 정리, 비정상 종료 시 원격 자동 종료는 실물이 필요해 보류.

### D단계: 안정성
**목표**: 끊겨도 스스로 복구하고, 상태를 볼 수 있고, 오래 돌려도 안정적이다.
**작업**
- MQTT 재연결(백오프), 재연결 뒤 구독 복구, 래치 토픽 재발행.
- LWT(마지막 유언)와 하트비트 주제 `mqtt_bridge/<robot>/status` → PC에서 로봇 쪽 생사 확인, 로그에 끊김 시각 기록.
- `cmd_vel` 워치독이 **연결 끊김** 때도 동작(로봇 쪽에서 입력이 사라진 것과 동일하게 처리).
- 1시간 연속 시험(tmux).
**완료 기준**
- 터널을 끊었다 복구하면 `N`초 안에 중계가 재개되고 래치 토픽이 다시 나온다.
- 1시간 유실 < 0.1 %, 메모리 증가 없음, pinky1 load ≤ 1.2.
**시험 절차**
1. 린트 3종.
2. 끊김 시험(사용자 확인 후): `kill <터널 PID>` → 로그에서 끊김 감지 → 터널 재개 → 재연결·카운터 재개 확인. 끊김 구간 시간 기록.
3. 브로커 재시작(`sudo systemctl restart mosquitto` — **sudo는 사용자가 `!`로 실행**) 후 복구 확인.
4. LWT: 로봇 쪽 프로세스를 `kill -9` → PC 쪽 status가 offline이 되는 시간.
5. 1시간 시험: `serve` 요약과 `ps -o rss`를 10분 간격으로 기록.

**Claude Code 프롬프트**
```
[D단계] PRD 의 D단계를 진행한다. plan 먼저.
- 재연결(지수 백오프), 구독/래치 복구, LWT+하트비트 status 주제, 연결 끊김 시 cmd_vel 워치독 동작을 매니저에 추가해.
- 터널 kill, 브로커 restart(sudo 는 내가 직접 실행), kill -9 시험은 각각 실행 직전에 나에게 확인받아.
- 1시간 시험은 tmux 로 돌리고 10분마다 유실률/RSS/pinky1 load 를 표로 남겨. 로봇 구동은 하지 않는다.
```

---

**D단계 결과 — 실물 없이 가능한 부분 (2026-11-08, 가짜 모드: 로봇 역할 101, 관제 역할 102, 사용자 권한 임시 브로커 포트 1884. 시스템 브로커·pinky1·도메인 10 사용 없음)**
구현: 접속 뒤 자동 재접속(`reconnect_min_sec`~`reconnect_max_sec`), 재접속 때 구독·래치 값 재발행, 끊긴 동안 명령 버림, 연결 끊김 즉시 `cmd_vel` 0 속도, 상태 주제와 LWT(`mqtt_bridge/<로봇>/status/<robot|pc>`), 부모 종료 감지(`exit_on_parent_loss`, launch가 켬).
| 시험 | 결과 |
|---|---|
| 린트·단위 | `colcon test` 50개 통과 |
| 브로커 `kill -9` → 6초 뒤 재시작 | 끊김 감지 1~2 ms, 재접속 재시작 뒤 1.0 s (양쪽 노드), 배터리 수신 재개 |
| 끊김 중 `cmd_vel` | 끊김 뒤 0 속도 30 ms (워치독 3000 ms보다 빠름). 끊긴 동안 로봇 도메인에 수신된 명령 0개, 재시작 직후 1초 0개, 안정 뒤 2초 20개 |
| 래치 재발행 | 발행기 종료 뒤 브로커 재시작 → 보관된 `/tf_static` 마지막 값이 다시 올라옴 |
| 상태·LWT | 정상 종료 `offline (cause: exit)`, `kill -9` 즉시 `offline (cause: will)`, 상대 쪽 로그에 online/offline 기록 |
| 고아 방지 | launch만 `kill -9` → 노드 0.4 s 안에 종료 |
| **30분 연속** (가짜 `/odom` 30 Hz, `/scan` 10 Hz, `/tf` 50 Hz→상한 30, 배터리 1 Hz) | 발행 수 = 로봇 역할 수신 수 = 관제 역할 수신 수: odom 53850, scan 17949, battery 1794×2, tf 89749 중 44863 중계(상한으로 의도적 버림 44886). **유실 0, 오류 0**. 노드 RSS 69.1 → 69.6 MB (30분 +0.5 MB, 누수 없음) |
| CPU (30분, 이 PC) | 로봇 역할 평균 약 21 % (코어 1개 기준), 관제 역할 약 6 % |
| 사후 | 임시 브로커·노드 모두 종료, 남은 프로세스 0, 시스템 브로커 보관 메시지 0 |

시험 중 발견·수정: rclpy 로거는 같은 호출 위치에서 로그 수준을 바꿀 수 없어 상대 상태 로그가 예외를 일으켰다 → 호출 분리.

한계(실물에서 확인 필요):
- CPU 21 %는 x86 PC에서 가짜 발행기와 함께 잰 값이다. pinky1(ARM)에서는 더 높을 수 있어 실물에서 load 감시(3.0)와 함께 확인해야 한다. 로봇 역할의 Python JSON 직렬화(`/scan` 360개, `/odom`)가 주된 비용이다.
- 실제 와이파이 지연·끊김, 터널(SSH) 끊김, 시스템 브로커 재시작(sudo)은 하지 않았다.
- 끊김 중 버린 상태(up) 메시지는 복구하지 않는다(최신 값만 의미가 있어서). 래치 토픽만 재발행한다.

### E단계: pinky2·pinky3 확장
**목표**: 3대를 한 launch로 동시에 중계한다.
**작업**
- 로봇별 MQTT 주제 분리(`mqtt_bridge/pinky2/...`), 로봇 쪽 도메인은 3대 모두 10(아래 "로봇 도메인 10 통일" 참고). `zone_manager/*` 처럼 remap이 없는 토픽은 로봇별 MQTT 주제로 올리고 PC 쪽에서 **같은 이름 하나로 합쳐서** 발행(메시지 안 `robot_id`로 구분되는 기존 동작 유지).
- 브로커 연결 수·초당 메시지 수 측정.
**완료 기준**
- 3대 동시 10분, 유실 < 0.1 %, PC CPU·브로커 CPU 기록.
- 한 대를 끄거나 끊어도 나머지 영향 없음.
**시험 절차**
1. 린트 3종.
2. 가짜 모드로 3대분 토픽 값 일치(토픽 수 = pinky1 21, pinky2 18, pinky3 18 개 중 방향별 분리 집계).
3. 실물이 한 대뿐이면 pinky2·3은 가짜 발행기로 대체하고 그 사실을 기록.
4. 한 대 끊기 시험(해당 로봇만 상태 offline, 다른 로봇 카운터 유지).
5. pinky2·3 실물 도메인 접속은 **사용자 승인 후**에만.

**Claude Code 프롬프트**
```
[E단계] PRD 의 E단계를 진행한다. plan 먼저.
- pinky2/pinky3 YAML 도 같은 매니저로 읽어 MQTT 주제를 로봇별로 분리해.
- zone_manager 처럼 remap 없는 공용 토픽은 PC 쪽에서 한 이름으로 합쳐 발행하는 방식을 제안해서 확인받아.
- pinky2/3 실물 접속은 내가 허락하기 전에는 하지 말고, 가짜 발행기로 먼저 시험해.
- 3대 동시 10분 시험과 1대 끊김 시험 결과를 표로 보고해.
```

#### E단계 결과 (가짜 모드, 2026-11-09)
설계: **코드 변경 없이** 로봇당 프로세스 방식(A안)을 그대로 쓴다. `cobot_zone_traffic_control` 의 `zone_gate_client.py` 가 메시지 안의 `robot_id` 로 자기 것만 골라 쓰므로(`_on_grant`, `_on_slot`) 공용 토픽을 한 이름으로 합칠 필요가 없고, 동작은 DDS 브릿지와 같다. 시험은 임시 브로커(포트 1884)와 도메인 101·102·103·104(루프백 전용)에서만 했다. 로봇 역할은 up 만 쓸 때 ROS 에 발행하지 않으므로, 로봇 3대의 토픽 이름이 겹치지 않게 pinky1 은 101, pinky2 는 103, pinky3 은 104 에 가짜 발행기를 따로 두었다.

| 시험 | 결과 |
|---|---|
| 3대 동시 10분(`mqtt_bridge.launch.xml`) | pinky1·3 은 odom 17,760 / scan 5,919 / 배터리 591 / request_entry 1,183 **발행 수와 수신 수가 같음**(유실 0). `/tf` 는 상한 30 Hz 로 의도적으로 절반 중계. 값에 로봇 번호를 심어 확인했고 **다른 로봇 값이 섞인 것은 0**. |
| 1대 끊김(pinky2 로봇 역할 `kill -9`, 60초 뒤 재시작) | pinky2 만 약 61초 분량(odom 1,830)이 비었고 pinky1·3 은 영향 없음. 관제 쪽 pinky2 로그에만 `offline` 이 올라왔고 재시작 뒤 복구. |
| 공용 `request_entry` | 로봇 3대 분량이 중복 없이 도착(1,183 / 1,183 / 로봇 2 는 끊긴 만큼 감소 1,061). |
| 명령 방향 라우팅 | 관제에서 `/pinky1·2·3/cmd_vel` 을 각각 100개 보내자 로봇 쪽에서 x=0.1·0.2·0.3 이 정확히 100개씩 도착(엉뚱한 로봇으로 간 것 0). 워치독 0 속도는 로봇당 1회. |
| 공용 `grant_entry`·`queue_slot` | 관제가 5개·3개를 보내면 로봇 3대 쪽에 각각 도착해 15개·9개. **모든 로봇에 내려가고 로봇 쪽이 `robot_id` 로 거른다**(DDS 브릿지와 같은 동작). |
| 1대만 켜기(`pinky1:=false pinky3:=false`) | 노드 목록에 `/mqtt_bridge_pinky2` 하나만 있음. |
| 로봇 역할 CPU(이 PC, 가짜 발행기와 함께) | 로봇 1대당 평균 약 15 % (코어 1개 기준, 약 480초 동안 누적 72초). 관제 쪽 프로세스와 브로커 CPU 는 따로 재지 않았다. |

시험 중 알게 된 것: 로봇 역할 3개와 가짜 발행기 3개를 한 PC 에서 돌리자 1분 load 가 3.62 가 되어 로봇 역할의 부하 보호(`load_abort` 3.0)가 설계대로 스스로 멈췄다. 한 PC 에 모아 돌리는 시험에서만 `load_abort:=50.0` 으로 올렸고, 설정 파일 기본값은 그대로다. 실제 로봇은 한 대에 한 프로세스라 해당하지 않는다.

남은 것(실물 필요): pinky2·3 실물 도메인 접속, 공용 토픽의 실제 QoS 확인, 실제 도메인 100 에서 `/zone_manager/*` 를 3개 프로세스가 같이 발행할 때 기존 발행자 사전 검사가 두 번째·세 번째 프로세스를 막는지(F단계 설계 항목).

---

### F단계: 실제 도메인 적용

**진행 상태 (2026-11-09)**: F-0·F-0b 완료. F-1 은 PC 쪽 관제 노드를 루프백 전용으로 격리해 DDS 브릿지를 끄지 않고 진행한다. **F-2~F-4 는 보류** — 도메인 100 을 쓰는 다른 팀의 DDS 브릿지를 지금은 끌 수 없다. 끌 수 있는 시간이 정해지면 F-2 plan 을 새로 만들어 승인받는다.
**목표**: DDS 브릿지를 끄고 MQTT 브릿지로 실제 시스템을 구동한다. **가장 위험한 단계.**
**선행 조건**: A~E 통과, 팀(다른 DDS 브릿지 사용자) 합의, 일정 확보, 롤백 방법 확인.
**하위 단계**
- F-1 그림자: DDS 브릿지가 켜진 채 MQTT는 `mqtt_test/` 이름으로만 병행 발행 → 값 비교(이미 가능).
- F-2 읽기 전환: DDS 브릿지를 로봇→관제 항목만 끄고 MQTT가 원래 이름으로 발행(도메인 100). 기존 노드(GUI·zone manager)가 정상 동작하는지 확인.
- F-3 명령 전환: 관제→로봇 항목을 MQTT로. **저속·바퀴 들어올린 상태**(또는 사용자가 지켜보며)에서 `patrol_cmd`, `goal_pose`, `cmd_vel` 순.
- F-4 되돌리기 시험: MQTT 정지 → DDS 브릿지 재기동으로 복귀하는 시간 측정.
**완료 기준**
- 기존 노드 코드 수정 없이 순찰 1회(왕복)·구역 진입 허가 1회가 DDS 브릿지 때와 같은 결과.
- 복귀 시간 기록, 비상정지(`cmd_vel` 0) 지연이 기준 이하.
**시험 절차**
1. 시작 전: 기존 발행자 검사, DDS 브릿지 상태 확인(누가 쓰는지 사용자에게 확인).
2. F-2: `ros2 topic list`(도메인 100)가 이전과 같은 이름·타입이어야 한다(`ros2 topic info -v`로 비교). GUI 화면에서 배터리·위치·도착 판정이 정상인지 사용자가 눈으로 확인.
3. F-3: 사용자가 로봇 옆에서 비상 정지 준비 상태로 단계별 확인. `cmd_vel` 한 번에 한 축·저속.
4. 브릿지 하나만 켜졌는지(MQTT와 DDS 중복 발행 없음) 매 단계 확인.
5. F-4 복귀 훈련.

**Claude Code 프롬프트**
```
[F단계] PRD 의 F단계를 진행한다. 이 단계는 실제 도메인 100/10 과 로봇 구동이 포함된다.
- 시작 전에 DDS 브릿지를 누가 쓰는지, 로봇이 안전한 상태인지, 비상정지 준비가 됐는지를 나에게 물어보고 답을 받은 뒤에만 진행해.
- 하위 단계(F-1~F-4)마다 plan 을 보여주고 승인받고, 로봇이 움직이는 명령은 실행 직전에 다시 확인해.
- 도메인 100 에는 이전 단계에서 승인한 토픽만 올리고, DDS 브릿지와 동시에 같은 이름을 발행하지 마.
- 각 하위 단계 결과(이름/타입 비교, 지연, 복귀 시간)를 이 PRD 의 단계별 결과 표에 기록해.
```

#### F-0 결과: pinky1 실물 읽기 10분 (2026-11-09)
조건: pinky1 은 `bringup_robot.launch.xml` 만 켠 상태(센서·주행·배터리, **AMCL/Nav2 는 꺼짐**), 순찰 없음. 로봇 쪽 노드는 도메인 10 에서 **구독 전용**(`enable_down` 꺼짐)으로 `/tmp/mqtt_f0` 임시 복사본을 실행했고, 관제 쪽은 도메인 102. 경로는 pinky1 → SSH 역방향 터널 → PC 시스템 브로커(127.0.0.1:1883).

| 항목 | 결과 |
|---|---|
| 유실 | **0**. pinky1 이 받은 수 = 관제 쪽이 받은 수: scan 5,918 / odom 17,732 / 배터리 118×2. `/tf` 는 상한 30 Hz 로 33,278 중 13,566 만 중계(의도). 오류 0 |
| pinky1 중계 노드 CPU | 코어 1개의 약 18 % (10분 누적 99초), 메모리 67 → 68 MB, 증가 없음 |
| pinky1 load(1분) | 시험 전 0.45, 시험 중 0.33~1.14, 종료 뒤 0.48. bringup 만 켠 상태의 값이며 PRD 기준 ≤ 1.2 안. `load_abort` 3.0 은 작동하지 않음 |
| bringup 쪽 CPU | 시험 전 12.1 % → 시험 중 12.2~12.6 % (중계 노드가 bringup 에 준 영향은 이 지표에서 거의 없음) |
| 종료 | 로봇 쪽 종료 코드 0. 종료 뒤 pinky1 프로세스 0개, `/tmp/mqtt_f0` 삭제, 터널 닫힘, 시스템 브로커의 `mqtt_bridge/pinky1/#` retain 삭제 |

시험 중 알게 된 것
- 예행 첫 시도는 내가 `PYTHONPATH` 를 덮어써서 `ament_index_python` 을 못 찾아 실패했다(로봇에는 영향 없음). 로봇에서 직접 실행할 때는 ROS 환경을 먼저 source 하고 기존 `PYTHONPATH` 뒤에 붙인다.
- 관제 쪽 `/pinky1/tf_static` 이 2건 받은 것은 앞선 예행의 retain 값이 남아 있었기 때문이다(래치 토픽의 의도된 동작).
- 값 종류별 수집기는 빈 `/tf` 메시지(변환 목록이 빔)에서 시험 도구가 예외를 내 비어 나왔다. 중계 수는 양쪽 노드 요약으로 확인했다.

이번에 확인하지 못한 것: `/amcl_pose`(AMCL 꺼짐), Nav2 가 켜진 상태의 pinky1 부하, 터널 끊김, 시스템 브로커 재시작.

#### F-0b 결과: pinky1 실물 터널 끊김·재접속 (2026-11-09)
조건은 F-0 과 같다(bringup 만 켠 pinky1, 구독 전용, 관제 쪽 도메인 102). 시험 진행 중 제가 연 SSH 터널 프로세스만 닫았다 다시 열었다. 총 약 3분 30초.

| 구간 | 터널 닫음 → 열림 | 관제가 `offline` 을 본 시각 | 열린 뒤 `online` 까지 | 데이터가 비어 있던 구간 |
|---|---|---|---|---|
| 끊김① | 21 초 | 닫는 즉시(0초) | **9.9 초** | 약 31 초 |
| 끊김② | 46 초 | 닫는 즉시(0초) | **15.0 초** | 약 61 초 |

- 로봇 쪽 노드는 두 번 모두 `예기치 않게 끊김 rc=7` 로 끊김을 감지하고 **죽지 않고** 스스로 재접속했다. 종료 코드 0, 오류 0.
- 복구 뒤 `/scan` 은 5초에 약 50개(10 Hz)로 바로 정상이 됐다. 끊긴 동안 로봇이 받은 것(`버림` 923 등)은 설계대로 버렸고 쌓아 두었다가 한꺼번에 내보내지 않았다.
- 터널을 닫으면 브로커가 즉시 `offline`(will)을 올린다. 그래서 끊김 감지는 사실상 즉시다.
- 재접속이 터널이 다시 열린 뒤 약 10~15 초 늦은 이유는 재접속 대기가 1초에서 두 배씩 늘어나기 때문이다(`reconnect_max_sec` 30). 끊긴 시간이 길수록 늦어지고 최대 30초까지 걸릴 수 있다.
- [TODO] 현장 와이파이·터널이 자주 끊긴다면 `reconnect_max_sec` 를 5~10 초로 낮추는 것을 검토한다(팀이 정함, 이번에 바꾸지 않았다).
- 정리: pinky1 `/tmp/mqtt_f0` 삭제, 프로세스 0개, 터널 닫힘, 시스템 브로커의 `mqtt_bridge/pinky1/#` retain 삭제.

이번에 확인하지 못한 것: 시스템 브로커 재시작(sudo 필요), AMCL 이 켜진 상태, 와이파이 자체가 끊기는 경우(터널을 닫은 것과 다를 수 있다).

#### F-1 결과: 그림자 병행 비교 (2026-11-09)
방법: PC 쪽 관제 노드를 **도메인 100 루프백 전용**(`CYCLONEDDS_URI` 에 `lo` 만 허용)으로 띄워 다른 팀 도메인 100 에 보이지 않게 했다. 그래서 `mqtt_test/` 같은 이름 변경 없이 원래 이름(`/pinky1/...`)을 그대로 썼다. `confirm_real_domain:=100` 으로 안전장치 확인은 통과시켰다. 다른 팀 DDS 브릿지는 끄지 않았다. 5분, pinky1 은 bringup 만 켠 상태(구독 전용).

| 항목 | 결과 |
|---|---|
| 격리 확인(발행 전) | 루프백 프로브 노드는 네트워크 쪽 도메인 100 노드 목록에 **안 보였고**, 루프백 쪽에서는 프로브만 보였다 |
| 시험 중 격리 | 네트워크 쪽 `/pinky1/battery/percent` 의 발행자는 `relay_patch_d100` 1개뿐(우리 노드 없음). 종료 뒤 도메인 100 노드 목록에 우리 흔적 0 |
| `/pinky1/battery/percent` | 타입 `std_msgs/msg/Float32` 같음(해시도 같음), QoS RELIABLE·VOLATILE 같음, 5분 동안 **DDS 56건 = MQTT 56건**, 값 100.0 동일 |
| `/pinky1/patrol_status` | 타입 `std_msgs/msg/String`·QoS 같음. 순찰이 없어 두 쪽 모두 0건 |
| odom / scan / tf / battery voltage | 도메인 100 에 비교 대상이 **없음**(현재 pinky1 은 정식 DDS 브릿지가 아니라 `relay_patch_d100` 이 일부만 올림). MQTT 쪽 주기: odom 29.7 Hz, scan 10.0 Hz, tf 22.9 Hz(상한 30 Hz), voltage 0.2 Hz. 타입·QoS 는 YAML 대로(RELIABLE·VOLATILE) |
| 로봇 쪽 | 종료 코드 0, 오류 0, 중계 수 = 수신 수. 로봇은 움직이지 않았고 도메인 10 에는 발행하지 않았다 |

**F-2 협의 안건 (이번에 알게 된 것)**
1. 도메인 100 의 pinky1 은 `relay_patch_d100` 이 `battery/percent`, `amcl_pose`, `patrol_status`, `fleet_heartbeat` 만 올린다. pinky2 는 정식 브릿지(`pinky_bridge_pinky2_only_100`)가 전체를 올린다. `/pinky1/odom`·`scan`·`tf`·`battery/voltage` 는 지금 도메인 100 에 없다.
2. 현재 시스템은 브릿지 YAML 밖의 토픽도 쓴다: `/pinky1/fleet_heartbeat`(`fleet_control` 이 발행하고 `relay_patch_d100` 이 받음), `/pinky1/camera/image_raw/compressed`. MQTT 브릿지가 이를 대체하려면 YAML 추가 또는 별도 설정 방식을 팀과 정해야 한다.
3. 시험 중 관제 쪽 구독자(`fleet_control`, `fleet_status_node`)의 QoS 는 `RELIABLE` 과 `BEST_EFFORT` 가 섞여 있다. MQTT 쪽 발행은 RELIABLE 이라 둘 다 받을 수 있다.
4. F-2~F-4 는 DDS 브릿지를 끌 수 있을 때까지 보류.

---

### G단계: 자동 시작 · 문서 · 결정
**목표**: 사람이 안 만져도 켜지고, 팀이 판단할 수 있는 문서를 만든다.
**작업**
- pinky1 로봇 쪽 매니저 systemd 서비스 초안(설치는 sudo → 사용자 실행). 터널은 `autossh` 또는 서비스로(새 의존성이므로 **허락 필요**).
- 패키지화 제안(`cobot_mqtt_bridge`, ament_python, `launch/`·`config/` install) — 구조도·담당 표 갱신 포함.
- 팀 결정 제안서: DDS 유지 vs MQTT 전환(성능은 MQTT가 불리, 구조적 이점은 별도). **`fms_decisions.md`는 직접 고치지 않고 제안만.**
**완료 기준**
- 재부팅 후 사람 개입 없이 중계 재개(시험 전 사용자 확인).
- 문서·README·가이드가 코드와 일치, 린트 통과.
**시험 절차**
1. 서비스 파일 `systemd-analyze verify`.
2. 사용자 승인 후 pinky1에서 `systemctl --user` 또는 시스템 서비스 설치 → `reboot` 뒤 상태 확인(재부팅은 사용자 확인).
3. 문서 경로·명령을 README 예시와 대조 실행.

**Claude Code 프롬프트**
```
[G단계] PRD 의 G단계를 진행한다. plan 먼저.
- systemd 서비스 초안과 autossh 사용 여부는 새 의존성/시스템 설정이라 먼저 제안만 하고 내 허락을 받아. sudo 는 내가 직접 실행한다.
- 패키지화 제안서(구조, setup.py/package.xml 등록 목록, CLAUDE.md 구조도 갱신안)를 문서로 만들어 보여줘. 실제 패키지 생성은 승인 뒤에.
- fms_decisions.md 는 수정하지 말고 결정 제안 문안만 docs 에 따로 작성해.
```

#### G-2 결과: 서비스 초안 (2026-11-09)
G-1(결정 제안서)은 사용자가 건너뛰기로 했다. 서비스 파일 2개를 `config/`에 작성했다(새 폴더 없음, `setup.py` `data_files` 에 `*.service` 등록). 터널은 **autossh 없이** systemd `Restart=always` + `ExitOnForwardFailure`/`ServerAlive*` 로 복구한다(새 의존성 없음).

| 항목 | 결과 |
|---|---|
| `systemd-analyze verify` | 터널·로봇 서비스 PC 에서 통과, 로봇 서비스 pinky1 에서도 통과 (시스템에 설치하지 않음) |
| 시험 | `test_service_files.py` 3개 추가(로봇 서비스에 `enable_down`·`confirm_real_domain` 없음, 재시작 정책, 터널에 autossh 없음). 전체 53개 통과, 린트 포함 |
| 문서 정리 | `package.xml`·`setup.py` 설명의 "대체" 표현을 "병행"으로 수정 |
| SSH 키 | 서비스가 쓸 `~/.ssh/id_ed25519` 로 에이전트 없이 pinky1 접속 가능함을 확인 |

미설치 상태다. 설치(sudo)와 재부팅 시험은 G-3 에서 사용자와 함께 한다.

#### G-3 결과: 설치와 재부팅 시험 (2026-11-09)
PC 터널 서비스와 pinky1 로봇 서비스를 설치(사용자가 `sudo` 로 실행)하고 `enable --now` 했다. 로봇은 움직이지 않았고 도메인 10 에는 구독만 한다.

| 시험 | 결과 |
|---|---|
| 설치 직후 | 두 서비스 `active`·`enabled`. 관제 쪽에 `status/robot online`, 로봇 노드 메모리 약 67 MB |
| 터널 끊김 복구(터널 프로세스 `kill -9`) | 브로커가 즉시 `offline`(will), systemd 가 **6초 뒤** 터널을 다시 열고 **약 7초 만에** 같은 프로세스가 `online` 으로 재접속 |
| **pinky1 재부팅** | 사람 개입 없이 로봇 서비스가 자동 시작해 `MQTT 접속 성공`, `status/robot online`. 부팅 직후 첫 시도는 터널이 아직 없어 `브로커에 닿지 않음`(종료 코드 2)으로 끝났고, 설계대로 systemd 가 30초 뒤 다시 시도해 성공 |
| 재부팅 뒤 PC 터널 | 계속 `active` |

알게 된 것: pinky1 은 부팅 직후 시계가 며칠 전(11/07)으로 틀려 있다가 NTP 로 맞춰진다(저널 시각이 점프). `max_age_ms` 로 오래된 명령을 버리는 기능은 두 장비 시계가 맞은 뒤에만 켜야 한다. 서비스는 현재 `enable` 상태이며, 켜 둔 동안 pinky1 CPU 를 코어 1개의 약 18 % 쓴다. DDS 브릿지만 쓰는 때는 README 의 "끄기" 명령으로 `disable` 한다.

#### 토픽 목록 분리 결과: MQTT 전용 YAML (2026-11-09)
요청: "DDS 와 별개로 MQTT 용도로 따로 빼 달라". 토픽 목록을 `cobot_domain_bridge` 의 YAML 대신 이 패키지의 `config/mqtt_topics_pinkyN.yaml` 로 옮겼다.

| 항목 | 내용 |
|---|---|
| 시작 내용 | DDS 쪽 `pinky_bridge_pinkyN.yaml` 항목을 그대로 복사(pinky1 21개, pinky2·3 18개). 복사본과 원본의 내용이 같음을 확인했고 `cobot_domain_bridge` 는 수정하지 않았다(git 변경 0) |
| 기본 경로 | `bridge_config` 를 비우면 설치본(`share/cobot_mqtt_bridge/config`), 없으면(pinky1 처럼 코드만 복사한 경우) 코드 옆 `config/`. 파일이 없으면 DDS YAML 로 몰래 대신하지 않고 오류로 알린다 |
| 서비스 파일 | pinky1 의 YAML 경로를 `~/mqtt_bridge/cobot_mqtt_bridge/config/mqtt_topics_pinky1.yaml` 로 변경. 예전 설치(`~/mqtt_bridge/cobot_domain_bridge/`)는 새 서비스 설치 전까지 그대로 둔다 |
| 시험 | 54개 통과(린트 포함). DDS 폴더 없이 읽히는지, 세 로봇 파싱·개수·중복 없음 시험 추가 |
| 가짜 모드 | `bridge_config` 없이 3대를 60초 돌려 중계 수 = 발행 수(scan 519, odom 1,560 등, pinky2 는 장애 시험대로 중간이 비어 있음), 오류 0. 설치 없이 복사한 코드에서도 기본 경로를 찾음 |
| 주의 | 목록이 따로 관리되므로 DDS YAML 이 바뀌어도 MQTT 목록은 자동으로 따라가지 않는다. 실물 pinky1 에는 아직 새 파일을 복사하지 않았다 |

---

## 8. 공통 규칙
- 모든 단계 시작 전 plan 승인(CLAUDE.md 10-1), `sudo`·`rm -rf`·로봇 구동·`ROS_DOMAIN_ID`/네트워크 변경은 실행 직전 재확인.
- 시험 한 번 뒤에는 PC·pinky1 잔여 프로세스, 브로커 retained 메시지, 열린 터널을 정리하고 보고한다.
- 린트 3종과 가짜 모드 시험이 매 단계 통과 조건이다.
- **호환 시험도 통과 조건이다**: 관제 도메인에서 `ros2 topic info -v`로 본 토픽 이름·타입·QoS가 DDS 브릿지를 쓸 때와 같아야 하고, `cobot_navigation` 노드는 코드·launch 수정 없이 그대로 값을 받아야 한다.
- 측정 시 자식 출력은 파이프 대신 파일로 받는다(파이프가 차면 중계가 멈춰 수신율이 거짓으로 낮게 나온다).

## 9. 위험 요소
| 위험 | 대응 |
|---|---|
| 명령 지연·유실로 로봇이 계속 움직임 | `cmd_vel` 워치독(연결 끊김 포함), 속도 상한, 사람이 옆에서 확인 |
| DDS·MQTT 이중 발행 | 기존 발행자 사전 검사, 한 번에 한 브릿지 |
| 브로커·터널이 단일 장애점 | D단계 재연결·status, G단계 자동 복구 |
| pinky1 부하 증가 | 프로세스 1개화, load 3.0 초과 시 자동 중단 |
| 다른 팀원의 DDS 브릿지 사용 중 | F단계 전 합의, 시험 도메인에서만 개발. DDS 브릿지는 유지하므로 언제든 되돌릴 수 있다 |
| 기존 코드와 호환 깨짐 | 매 단계 호환 시험(토픽 이름·타입·QoS 비교), 호환 안 되면 단계 통과 불가 |
| paho 2.x 등 버전 차이 | [TODO] 현재 1.6.1 기준만 검증 |

## 10. 승인 요청 사항
1. ~~새 폴더·패키지 생성~~ — 승인됨(`cobot_mqtt_bridge`).
2. `cmd_vel` 워치독 기본 시간·속도 상한 값 (팀 합의 필요 — [TODO]).
3. B단계 진행 승인 (A단계는 승인·완료).

## 관제 쪽 도메인 200 분리 결과 (2026-11-12)

- **배경:** 실물 시험 중 도메인 100에서 다른 팀의 DDS 브릿지(`pinky_bridge_pinky1/2/3_only_100`, `relay_patch_d100`)가 켜져 있는 것을 확인했다. 시작 전 검사가 `/pinky1/scan` 등 8개 토픽의 기존 발행자를 찾아 관제 쪽 노드를 중단시켰다. (그 전에 "브릿지가 꺼져 있다"고 본 판단은 틀렸고, 안전 검사가 막아 피해는 없었다.)
- **결정:** 이 패키지의 관제 쪽 ROS 도메인을 100에서 **200**으로 바꿔 다른 팀과 분리한다. 로봇 쪽 도메인 10은 그대로다.
- **변경:** `pc_domain` 기본값과 `config/mqtt_bridge.yaml`, `config/mqtt_topics_pinky1/2/3.yaml`의 `from_domain`/`to_domain`, launch 설명, 시험 값, README.
- **영향:** 관제 쪽 프로그램(`pinky_control_client.py`, GUI, 구역 관리 등)은 도메인 200에서 실행해야 MQTT로 온 값이 보인다. 도메인 100의 프로그램은 볼 수 없다.
- **검증:** 단위 시험 54개 통과. 가짜 모드(도메인 101 루프백, 임시 브로커)에서 `patrol_cmd`만 down으로 통과하고 `cmd_vel`/`goal_pose`/`initialpose`/`zone_manager/*`는 차단됨을 확인했다. 도메인 200에는 기존 노드와 토픽이 없다(읽기 전용 확인).
- **[TODO]** 실물 pinky1 `patrol_cmd` 시험(도메인 200 + 10)은 아직 하지 않았다. 실행 직전에 사람이 로봇 옆에 있는지, `goto` 지점, 보호 값(`watchdog_ms` 등)을 확인한다.

## 실물 `patrol_cmd` 시험 결과 (2026-11-12, 도메인 200 ↔ 10)

- **목적:** 관제의 순찰 명령(`patrol_cmd`)이 MQTT를 거쳐 pinky1 도메인 10의 순찰 노드까지 전달되는지 확인한다. 열 down 토픽은 `patrol_cmd` 하나로 한정했다.
- **설정:** 양쪽 `enable_down:=true`, 관제 `confirm_real_domain:=200`, 로봇 `confirm_real_domain:=10`. 추가 파라미터 파일로 `exclude_patterns`에 `/cmd_vel`, `/goal_pose`, `/initialpose`, `/zone_manager/*`를 더했고 `watchdog_ms=500`, `max_linear=0.15`, `max_angular=0.4`를 넣었다(제안값, 팀 합의 전). 서비스 파일과 코드는 바꾸지 않고 직접 실행했다(시험 뒤 임시 파일 삭제).
- **사전 선검증(가짜 모드, 도메인 101, 임시 브로커):** 제외 목록 없음에서는 6개 down 토픽이 모두 통과하고, 제외 목록 적용 시 `patrol_cmd`만 통과했다. 관제 쪽에서도 MQTT `down/`으로 나간 주제는 `patrol_cmd` 하나뿐이었다.
- **도메인 100 사건:** 처음 관제 쪽을 도메인 100에서 시작했을 때, 다른 팀의 DDS 브릿지(`pinky_bridge_pinky1_only_100` 등)가 `/pinky1/scan` 등 8개 토픽을 이미 발행 중이어서 기존 발행자 검사가 노드를 중단시켰다. 이전에 "브릿지가 꺼져 있다"고 본 판단은 틀렸다(당시 조회가 불완전했던 것으로 추정). 검사가 막아 영향은 없었다. 이후 관제 쪽 도메인을 200으로 분리했다.
- **결과(도메인 200 + 10, 실물 pinky1):**

| 항목 | 결과 |
|---|---|
| 시작 검사 | 통과. 두 역할 모두 `online` |
| up 중계(15초 구간) | `scan` 151, `odom` 453, `tf` 321, `battery/percent` 3건: 받음 = 중계, 버림·오류 0 |
| 차단 | 도메인 200에 `/pinky1/cmd_vel`, `goal_pose`, `initialpose` 토픽 없음 |
| `goto:P1` 전달 | 클라이언트 → MQTT `down/patrol_cmd` → 로봇 쪽 `받음 1 중계 1 오류 0` |
| 로봇 반응 | **확인 못함.** `/odom` 위치와 `/cmd_vel`이 변하지 않았고 `/patrol_status`에 값이 없었다 |

- **한계·미확인:**
  - 순찰 노드의 반응 로그를 읽지 못해 이동하지 않은 이유를 알 수 없다. 후보는 이미 P1 근처, 구역 출입 허가 대기(`/zone_manager/*`를 막아 둠), 이름 불일치 또는 위치 추정 문제(`/amcl_pose`가 0,0으로 보임)이다.
  - 도메인 10의 `/patrol_cmd`에는 다른 팀의 `pinky_bridge_pinky1_only_10`도 발행자로 있다. 두 경로의 명령이 함께 들어올 수 있다.
  - 로봇이 움직이는 경로(`goto` 후 이동)와 `stop`/`emergency_stop`은 시험하지 않았다.
  - pinky1 설치본의 설정은 아직 도메인 100 기준이다(동작에는 영향 없음, 맞추려면 복사 필요).
- **[TODO]** 순찰 노드 반응 확인, `/zone_manager/*` 허용 여부 결정, 보호 값 확정, `stop`/`emergency_stop` 시험.

## 로봇 도메인 10 통일 (2026-11-14)
- **결정:** 로봇 쪽 ROS 도메인은 pinky1·2·3 모두 10, 관제 PC 쪽은 200으로 고정한다. 로봇 쪽 DDS는 로봇 안(루프백 전용)에서만 쓰고, 로봇↔관제 통신은 MQTT만 쓴다.
- **변경:** `config/mqtt_topics_pinky2.yaml`의 20, `config/mqtt_topics_pinky3.yaml`의 30을 10으로 바꿨다(`from_domain`/`to_domain` 값만). 코드는 이미 10을 가정하므로 수정하지 않았다.
- **전제:** 3대가 같은 도메인이므로 로봇 DDS가 LAN에 열려 있으면 서로 섞인다. 각 로봇의 CycloneDDS 설정을 루프백 전용으로 먼저 바꿔야 한다. **[TODO]** pinky1~3의 현재 `cyclonedds_robot.xml`과 `ROS_DOMAIN_ID` 확인.
- **영향:** 로봇 구분은 `robot` 이름과 MQTT 주제(`mqtt_bridge/<robot>/...`)로 한다. 도메인으로는 구분하지 않는다.
