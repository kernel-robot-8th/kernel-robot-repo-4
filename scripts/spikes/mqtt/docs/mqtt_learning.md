# MQTT 학습 기록

기준 문서: [`[진행] mqtt_learning_prd.md`](%5B%EC%A7%84%ED%96%89%5D%20mqtt_learning_prd.md)
스크립트 사용법: [`mqtt_guide.md`](mqtt_guide.md)
담당: 주행 (`cobot_navigation`)

## 1단계: MQTT CLI 개념 실습 (2026-11-05)

### 환경
- 관제 PC(x86_64, Ubuntu 24.04), `mosquitto` 2.0.18, `mosquitto-clients` 2.0.18
- 브로커 `127.0.0.1:1883` (localhost 전용, 인증 없음, `persistence true`)
- 토픽은 모두 `mqtt_learning/` 아래에서만 사용. ROS, pinky1, 도메인과 무관하며 로봇 구동 없음.
- 아래 `B` 는 `-h 127.0.0.1 -p 1883` 를 뜻한다.

### 1. 토픽 계층
- 토픽은 `/` 로 단계를 나누는 문자열이고, 미리 만들어 둘 필요가 없다. 발행·구독하는 순간 생긴다.
- 명령: `mosquitto_pub $B -t mqtt_learning/pinky_1/status -m idle`
- 예상: 같은 토픽을 구독한 클라이언트만 받는다.
- 확인: 정확히 `mqtt_learning/pinky_1/status` 를 구독한 쪽은 `idle` 한 건만 받았다.

### 2. 와일드카드 (`+`, `#`)
발행한 4건: `pinky_1/status`, `pinky_1/battery`, `pinky_1/nav/state`, `pinky_2/status` (모두 `mqtt_learning/` 아래).

| 구독 토픽 | 예상 | 확인한 결과 |
|---|---|---|
| `mqtt_learning/pinky_1/status` | 1건 | `status` 1건 |
| `mqtt_learning/pinky_1/+` | 한 단계만 → `status`, `battery` | 2건 (`nav/state` 는 두 단계라 제외) |
| `mqtt_learning/#` | 하위 전부 | 4건 모두 |

- `+` 는 정확히 한 단계, `#` 는 그 아래 모든 단계(마지막에만 쓸 수 있음)다.
- 배운 점: 로봇이 늘어나면 `fleet/+/status` 처럼 한 구독으로 전체 로봇의 상태를 모을 수 있다. DDS 브릿지는 토픽을 일일이 나열해야 한다.

### 3. QoS 0/1/2
**3-a. 다운그레이드.** QoS 2 로 발행하고 구독 QoS 를 0/1/2 로 달리해 받았다.

| 구독 QoS | 받은 메시지의 QoS |
|---|---|
| 0 | 0 |
| 1 | 1 |
| 2 | 2 |

- 같은 브로커에서 발행 QoS 2, 구독 QoS 0 이면 구독자는 QoS 0 으로 받는다. 즉 **둘 중 낮은 쪽**이 구독자에게 적용된다.
- 이번 실습은 각 구독을 QoS 별로 따로 받았을 뿐, 한 클라이언트가 여러 QoS 로 받는 경우는 보지 않았다.

**3-b. 패킷 흐름** (`mosquitto_pub -d`, 발행 측)

| 발행 QoS | 흐름 |
|---|---|
| 0 | PUBLISH (응답 없음) |
| 1 | PUBLISH → PUBACK |
| 2 | PUBLISH → PUBREC → PUBREL → PUBCOMP |

- 배운 점: QoS 가 높을수록 왕복이 늘어난다. QoS 1 은 "최소 한 번"이라 중복이 올 수 있고, QoS 2 는 "정확히 한 번"을 4패킷으로 보장한다.
- 로봇 적용 판단(아직 가설): 주기적으로 계속 오는 상태값은 QoS 0, 명령은 QoS 1 이상. 4단계에서 지연과 함께 확인한다.

### 4. retained
| 동작 | 결과 |
|---|---|
| `-r` 로 `ret/last` 에 `v1` 후 `v2` 발행, `ret/plain` 은 `-r` 없이 발행 | - |
| 이후 **새로 접속한** 구독자 | `ret/last v2 retain=1` 만 받음. 최신 값만 남고, `-r` 없이 보낸 `ret/plain` 은 받지 못함 |
| 빈 페이로드 `-n -r` 로 `ret/last` 발행 후 재구독 | 아무것도 받지 못함 (retained 삭제) |

- retained 는 토픽당 마지막 한 건을 브로커가 보관했다가 새 구독자에게 즉시 준다.
- 주의: 브로커가 `persistence true` 라서 retained 는 디스크(`/var/lib/mosquitto/`)에도 남는다. 로봇 명령(`/cmd_vel` 등)에 쓰면 구독이 시작될 때 낡은 명령이 재생될 수 있으므로 쓰지 않는다 (PRD 6번).
- 정리: 실습 후 빈 retained 로 모두 지우고, `mqtt_learning/#` 구독에서 수신이 없음을 확인했다.

### 5. LWT (Last Will and Testament)
유언 메시지를 단 클라이언트(`--will-topic mqtt_learning/lwt/pinky_1 --will-payload offline --will-qos 1`)를 띄우고 종료 방식만 달리했다.

| 종료 방식 | 감시자 수신 |
|---|---|
| `kill -9` (비정상 종료) | `mqtt_learning/lwt/pinky_1 offline` 수신 |
| `SIGINT` (정상 종료, DISCONNECT 전송) | 수신 없음 |

- LWT 는 클라이언트가 **정상 DISCONNECT 없이** 사라질 때만 브로커가 대신 발행한다. 그래서 로봇의 온라인/오프라인 감지에 쓸 수 있다.
- 한계: 이번 실습에서는 프로세스를 직접 죽였다. 네트워크가 끊기는 경우는 keepalive 시간이 지나야 감지되므로 지연이 있다. 이번에는 확인하지 않았고, 실제 사용 시 keepalive 값을 파라미터로 둔다.
- 배운 점: 온라인 표시는 `online`(retained)과 LWT `offline`(retained)을 같은 토픽에 두는 방식이 흔하다. 이번 범위에서는 실습하지 않았다.

### 실습 후 정리 상태
- `mosquitto_*` 잔존 프로세스 없음
- `mqtt_learning/#` retained 없음
- 브로커는 계속 실행 중(`active`, localhost 전용). pinky1 접속·설치 없음.

## 2단계: 파이썬 pub/sub 스크립트 (2026-11-05)

### 산출물
| 파일 | 역할 |
|---|---|
| `scripts/spikes/mqtt/tools/mqtt_pub.py` | 발행기. `--count/--interval/--qos/--retain`, 발행마다 확인까지 걸린 시간 로그 |
| `scripts/spikes/mqtt/tools/mqtt_sub.py` | 구독기. `--count/--duration/--qos/--persistent-session/--will-topic`, 수신 순번의 누락·중복 요약 |

- 브로커 주소·포트·토픽·QoS·keepalive·간격 등은 모두 argparse 인자다 (기본값은 `127.0.0.1:1883`, `mqtt_learning/spike/data`).
- 로깅은 `logging`만 쓰고 `print`는 쓰지 않는다. 구독기는 항상 `--duration` 제한이 있어 백그라운드에 남지 않는다.
- 린트: `ament_flake8 scripts/`, `ament_pep257 scripts/`, `ament_copyright scripts/` 모두 통과.
- paho-mqtt 1.6.1 콜백 API(`on_connect(client, userdata, flags, rc)` 등) 기준이다. 2.x는 `callback_api_version` 인자가 필요해 그대로는 안 돈다.

### 구조에서 배운 점
- **구독은 `on_connect` 안에서 건다.** 재접속하면 `on_connect`가 다시 불리므로 구독이 자동으로 복구된다. `connect()` 직후에 한 번만 구독하면 재접속 뒤에는 구독이 사라질 수 있다.
- **`loop_start()`는 네트워크 처리를 별도 스레드에 맡긴다.** 콜백은 그 스레드에서 불리므로 `threading.Event`/`Lock`으로 메인과 신호·통계를 주고받고, 콜백 안에서는 오래 걸리는 일을 하지 않는다.
- **정상 종료는 `disconnect()`로 한다.** 안 부르면 브로커가 비정상 종료로 보고 유언(LWT)을 보낸다 (1단계 LWT 실습과 같은 원리).
- **지속 세션은 `--client-id`가 있어야 이어진다.** 자동 생성 ID는 매번 달라 세션을 못 찾으므로, 구독기는 `--persistent-session`일 때 `--client-id`를 필수로 했다.

### 시험 결과 (모두 localhost, 토픽 `mqtt_learning/spike/data`)
**A/B. 기본 수신과 QoS 비교** (발행 10건, 간격 0.1 s)

| 발행·구독 QoS | 구독 수신 | 누락 | 중복 | 발행기 확인 | 확인까지 시간(seq 0 / seq 9) |
|---|---|---|---|---|---|
| 0 | 10건 | 0 | 0 | 10/10 | 0.09 / 0.24 ms |
| 1 | 10건 | 0 | 0 | 10/10 | 0.17 / 0.44 ms |
| 2 | 10건 | 0 | 0 | 10/10 | 0.20 / 0.46 ms |

- localhost에서는 유실이 없어서 **QoS 0/1/2의 수신 결과 차이는 보지 못했다.** 차이는 확인까지 걸린 시간에서만 보이고, 그것도 0.1~0.3 ms 수준이라 한 번 측정한 값으로는 단정하기 어렵다. 4단계에서 반복 측정이 필요하다.
- 발견한 버그: 처음에는 QoS 0일 때 확인을 기다리지 않아서 `is_published()`가 False로 나와 "확인 못 받음 10건"으로 잘못 집계됐다. `on_publish`가 비동기라서였고, 항상 `wait_for_publish()`를 부르도록 고쳤다.

**C. 재접속 (지속 세션)**: 구독만 걸고 종료 → 구독기가 꺼진 사이 5건 발행 → 같은 `--client-id`로 재접속.

| QoS | 재접속 시 `session_present` | 꺼진 사이 발행한 5건 |
|---|---|---|
| 1 | 1 | **5건 모두 수신** (누락 0, 중복 0) |
| 0 | 1 | **0건 수신** (QoS 0은 브로커가 보관하지 않음) |

- 세션이 유지되어도(`session_present=1`) QoS 0 메시지는 끊긴 사이 사라진다. 끊김에도 놓치면 안 되는 메시지는 QoS 1 이상 + 지속 세션이 필요하다.
- 정리: 같은 `--client-id`로 `--persistent-session` 없이 접속해 세션을 지웠고, 다시 지속 세션으로 접속하면 `session_present=0`임을 확인했다. `mqtt_learning/#` retained 없음, 스크립트 프로세스 잔존 없음.

**D. 브로커 재시작 중 자동 재접속** (구독기 `--qos 1 --reconnect-min 1 --reconnect-max 3`, 사용자가 `sudo systemctl restart mosquitto` 실행)

| 시각 | 구독기 로그 |
|---|---|
| 20:28:02 | `예기치 않게 끊김 rc=7, 재접속 시도 중` |
| 20:28:03 | `접속 성공 session_present=0` (1초 뒤 자동 재접속) |
| 20:28:07 / 20:28:08 | 같은 끊김·재접속이 한 번 더 기록됨 (재시작을 두 번 실행한 것으로 보이나 확인하지 않음) |
| 20:28:17 | 재시작 뒤 발행한 3건(`after_restart`, QoS 1)을 모두 수신 |

- 브로커가 내려가면 `on_disconnect`가 `rc=7`(예기치 않은 끊김)로 불리고, paho가 `reconnect_delay_set`의 최소 대기(1초) 뒤 자동으로 다시 붙었다. 코드에서 재접속을 따로 짜지 않아도 된다.
- 재접속 때 `on_connect`가 다시 불려 **구독이 자동으로 복구**됐다. 구독을 `on_connect` 안에서 거는 구조의 효과다.
- 이번에는 clean session이라 `session_present=0`이다. 끊긴 동안의 메시지는 받지 못하며, 그것이 필요하면 C의 지속 세션을 함께 쓴다.
- 한계: 대기 시간이 1초였고 재접속이 바로 성공했다. 브로커가 오래 내려가 있을 때 대기가 최대값(3초)까지 늘어나는 동작은 확인하지 않았다.

## 3단계 3a: ROS 토픽 ↔ MQTT 중계, 구동 없는 토픽 (2026-11-05)

### 산출물
- `scripts/spikes/mqtt/core/mqtt_ros_relay.py`: `--direction ros2mqtt`(ROS 구독 → JSON → MQTT, ROS 쪽 읽기 전용)와 `mqtt2ros`(MQTT → ROS 재발행) 한 스크립트. 린트 3종 통과.
- 메시지는 `{"type", "sent_at", "data"}` JSON이고 `rosidl_runtime_py`의 `message_to_ordereddict`/`set_message_fields`로 변환한다. `set_message_fields`는 `rosidl_runtime_py.convert`가 아니라 `rosidl_runtime_py.set_message`에 있다.
- 안전장치: `mqtt2ros`의 발행 토픽은 `/mqtt_test/`로 시작하지 않으면 실행을 거부한다. 중계율 상한(`--max-rate-hz`)과 실행 시간(`--duration`)이 항상 있다. retained는 쓰지 않는다. `cobot_domain_bridge`는 수정하지 않았다.

> **정정 (2026-11-07):** 아래와 이후 절에서 "localhost 전용"이라고 적은 시험 중 관제 PC 쪽은 사실과 다르다. 이 PC는 `CYCLONEDDS_URI`(`~/.ros/cyclonedds_pc.xml`)가 Wi-Fi 인터페이스와 고정 피어 목록을 지정하고, 그 설정이 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`를 이겨서 로컬 시험에서도 Wi-Fi TX가 약 0.9 KB/s(기준선)에서 약 11.7 KB/s로 올라가는 것을 확인했다. 대상은 시험용 격리 도메인(77, 101, 102)이거나 `/mqtt_test/` 시험 토픽이었고 로봇 구동 토픽은 없었다. loopback 전용 DDS 설정(`lo` 인터페이스 + 피어 `127.0.0.1`)에서는 유출이 없고 데이터도 정상으로 흐르는 것을 확인했다. 새 스크립트(`mqtt_bench_net.py`)와 수정한 러너(`mqtt_bench_run.py`)는 이 설정을 쓴다.

### 시험 1: 격리 드라이런 (관제 PC, 도메인 77, 로봇 없음. 위 정정 참고)
| 항목 | 결과 |
|---|---|
| `--ros-out-topic /cmd_vel` | 접두사 검사로 실행 거부 (종료 코드 2) |
| 가짜 `Float32 42.5`, 5Hz 입력, 상한 2Hz | 받음 26 → 중계 9, 버림 17, 오류 0. 재발행 값 `42.5` 일치 |
| MQTT 구간 지연 | 0.6~1.1 ms (같은 PC) |

### 시험 2: pinky1 실물 → MQTT → 관제 PC
**환경**
- 브로커 접속은 SSH 역방향 터널 `-R 127.0.0.1:1883:127.0.0.1:1883`로 했다. 브로커 설정과 LAN 개방은 바꾸지 않았다. 시험 후 터널을 닫았고 pinky1의 1883 리스너는 0개다.
- pinky1에는 `python3-paho-mqtt` 1.6.1만 설치했다. 스크립트는 파일로 두지 않고 `ssh ... python3 - <인자> < mqtt_ros_relay.py`로 stdin 실행했다.
- pinky1은 도메인 10, ros2mqtt(읽기 전용)만 실행. 관제 PC는 도메인 100, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`로 mqtt2ros 실행(위 정정: 실제로는 LAN 으로 나갔을 수 있다).

**토픽 선택 (계획과 달라진 점)**
- 계획한 `/battery/percent`는 **발행자가 없었다**. 토픽 이름만 목록에 있었고 `ros2 topic echo`가 "발행된 적 없음"이었다. `/amcl_pose`, `/odom`, `/scan`도 발행자가 없었다.
- 당시 발행 중인 구동 없는 토픽은 `/fleet_heartbeat`(`std_msgs/String`, 2Hz, 발행 노드 `pinky_bridge_pinky1_only_10`)뿐이라 이것으로 시험했다. `/amcl_pose` 시험은 하지 못했다.

**결과** (`/fleet_heartbeat`, 상한 1Hz, 18초)
| 구간 | 결과 |
|---|---|
| pinky1 ros2mqtt | 받음 36 → 중계 14, 상한으로 버림 22, 오류 0 |
| 관제 PC mqtt2ros | 받음 14 → 재발행 14, 오류 0 |
| 값 일치 | 관제 PC `/mqtt_test/pinky1/fleet_heartbeat`에서 `seq`·`session_id`·`ttl_sec`가 포함된 JSON 문자열이 원본 형태로 도착 |
| MQTT 구간 지연 | 1.8 ms (장비 간이므로 두 PC의 시계 오차가 섞여 있다. 정확한 지연이 아니다) |
| pinky1 부하 | 전체 CPU 약 91% idle. 중계 프로세스는 스냅샷에서 CPU 0.0%, 메모리 약 65 MB |

**한계**
- 관제 PC 쪽 주기 측정(`ros2 topic hz`)은 시간 초과로 값을 얻지 못했다. 재발행 건수(14건/약 18초)로만 확인했다.
- CPU는 `top` 스냅샷 1회라서 4단계에서 반복 측정이 필요하다.
- 상태값이 아닌 큰 메시지(`/scan` 등), 한글·바이너리 필드는 시험하지 않았다.

### 시험 3: `/battery/percent` 재시험 (pinky1 bringup 재시작 후)
- pinky1의 `pinky_bringup`이 다시 올라온 뒤 계획했던 토픽으로 같은 방식(SSH 터널, pinky1 도메인 10 읽기 전용, 관제 PC 도메인 100 localhost 전용)으로 40초 중계했다.

| 항목 | 결과 |
|---|---|
| pinky1 ros2mqtt | 받음 7, 중계 7, 버림 0, 오류 0 (상한 1Hz보다 느린 토픽이라 한 건도 버려지지 않음) |
| 관제 PC mqtt2ros | 받음 7, 재발행 7, 오류 0 |
| 값 일치 | 관제 PC `/mqtt_test/pinky1/battery_percent`의 `data: 100.0`이 같은 시점 pinky1 원본 `100.0`과 같음 |
| 발행 주기 | 40초에 7건, 약 0.2Hz (6초 안팎). 느린 토픽이라 처음 5초 동안은 값이 없었다 |
| MQTT 구간 지연 | 2.5 ms (장비 간이므로 시계 오차가 섞인 값) |

- 정리: 터널을 닫았고 pinky1 1883 리스너 0개, 양쪽 중계 프로세스 없음, `ros2 daemon` 정리.
- `/amcl_pose`는 Nav2가 떠 있지 않아 발행자가 없었다. 미시험이다.

### 시험 뒤 정리 상태
- 관제 PC와 pinky1 모두 중계 프로세스 없음. SSH 터널 닫힘. `mqtt_learning/#` retained 없음. 브로커는 localhost 전용으로 실행 중.
- 시험 중 `ros2 topic` 명령이 pinky1에 `ros2 daemon`을 띄워서 `ros2 daemon stop`으로 정리했다.
- pinky1에 남은 변경: `python3-paho-mqtt` 패키지 1개.

### 확인이 필요한 점
- 시험 2 직후 pinky1에서 `pinky_bringup`과 라이다 프로세스가 한동안 보이지 않았다. 이 작업에서 프로세스를 종료한 명령은 없고, 다시 확인했을 때 bringup이 새로 시작되어 있었다(누가 재실행했는지는 확인하지 못함). 시험 3은 그 뒤에 했다.

### 다음
- 3b(`/cmd_vel` 재발행)는 별도 계획과 승인이 필요하다. 4단계는 아래 절을 이어서 한다.

## 4단계: 지연·부하 측정과 DDS 브릿지 비교 (2026-11-07)

### 산출물 (`scripts/spikes/`, 평평하게, 린트 3종 통과)
| 파일 | 역할 |
|---|---|
| `mqtt_bench_stream.py` | 갈래 A. `--role source`(합성 `TwistStamped`/`LaserScan` 발행, `header.stamp`에 발행 시각·`frame_id`에 순번) / `--role sink`(지연 p50·p95·max, 수신, 누락, 중복) |
| `mqtt_bench_rtt.py` | 갈래 B. `--transport mqtt|ros`, `--role ping|pong`. ping 쪽 한 시계로만 RTT를 재서 두 PC의 시계 오차가 없다 |
| `mqtt_bench_run.py` | 갈래 A 러너. 경로 4개 × 조건 5개 × 3회 반복, 중계 프로세스 CPU는 `psutil`로 측정 |

- 시험용 DDS 브릿지 설정은 임시 폴더에 `/bench/` 토픽 하나만 담아 만들고 끝나면 지운다. 기존 `pinky_bridge_pinky*.yaml`(구동 토픽 포함)은 쓰지 않았다. 기존 브릿지 실행 파일은 `src/cobot_navigation/install`에 이미 있어 빌드가 필요 없었다.

### 측정 중 찾아 고친 버그 (이전 결과는 전부 버림)
처음 돌린 갈래 A에서 MQTT 수신율이 100Hz에서 52%, 300Hz에서 17%로 나왔다. 두 값의 절대 건수가 약 416건으로 같고 QoS 0/1이 소수점까지 같아서 이상하다고 보고 원인을 찾았다.
- 원인은 MQTT의 한계가 아니라 **측정 장치**였다. 러너가 자식 프로세스 출력을 파이프로 받으면서 끝날 때까지 읽지 않았고, `mqtt2ros` 중계가 메시지마다 로그를 한 줄(약 150 B) 남겨서 파이프 버퍼(64 KB, 약 430줄)가 차자 중계가 멈췄다.
- 고친 것: 러너는 출력을 파일로 받고, 중계는 첫 건만 INFO 로그를 남긴다. 고친 뒤 300Hz도 네 경로 모두 수신율 100%였다.
- 확인 과정에서 변환 비용도 쟀다. `TwistStamped` 한 건의 JSON 변환은 약 0.04 ms, `LaserScan`(360점)은 약 0.15 ms라서 병목이 아니다.

### 갈래 A: 한 PC 안에서 경로별 비교 (source 도메인 101 → sink 도메인 102, 8초 × 3회 평균)
> **주의:** 이 측정은 위 정정의 영향을 받는다. DDS 구간이 loopback이 아니라 Wi-Fi 인터페이스 주소를 거쳤을 수 있어서 절대 지연값은 다를 수 있다. 네 경로가 모두 같은 조건이라 경향(MQTT가 약 2~3 ms 더 길고 CPU를 더 씀)은 유효할 가능성이 높지만 확인하지 않았다. 수정한 러너로 재측정했고(아래 "DDS 브릿지 vs MQTT 나란히 재측정") 경향은 같았다. 절대값은 그 표를 본다.
단방향 지연(같은 시계). 수신율은 60회 전부 100%였다. max는 한 번의 순간 튐에 좌우돼서 판단에 쓰지 않는다.

| 메시지 | 발행율 | 경로 | p50 ms | p95 ms | 중계 CPU % |
|---|---|---|---|---|---|
| twist | 10 Hz | direct | 0.81 | 0.90 | - |
| | | dds_bridge | 1.00 | 1.12 | 0.57 |
| | | mqtt_q0 | 3.11 | 3.30 | 3.13 |
| | | mqtt_q1 | 3.04 | 3.26 | 3.37 |
| twist | 100 Hz | direct | 0.60 | 0.85 | - |
| | | dds_bridge | 0.86 | 1.09 | 2.27 |
| | | mqtt_q0 | 2.80 | 3.16 | 20.7 |
| | | mqtt_q1 | 2.75 | 3.20 | 22.0 |
| twist | 300 Hz | direct | 0.63 | 0.79 | - |
| | | dds_bridge | 0.70 | 0.96 | 4.87 |
| | | mqtt_q0 | 1.78 | 2.14 | 38.2 |
| | | mqtt_q1 | 1.82 | 2.21 | 43.4 |
| laser (360점) | 5 Hz | direct | 0.84 | 1.18 | - |
| | | dds_bridge | 1.02 | 1.23 | 0.4 |
| | | mqtt_q0 | 3.76 | 4.04 | 2.7 |
| | | mqtt_q1 | 3.76 | 4.14 | 2.8 |
| laser (360점) | 20 Hz | direct | 0.84 | 0.90 | - |
| | | dds_bridge | 1.09 | 1.18 | 0.77 |
| | | mqtt_q0 | 3.75 | 4.04 | 6.6 |
| | | mqtt_q1 | 3.77 | 3.97 | 7.0 |

- CPU는 코어 하나를 다 쓰면 100%다. MQTT 경로는 중계 프로세스 두 개(ros2mqtt + mqtt2ros)의 합이고, 브로커 프로세스의 CPU는 포함하지 않았다.
- 같은 조건에서 반복 3회의 p50 편차는 대부분 0.1 ms 안쪽이라 위 차이(약 2~3 ms)는 편차보다 크다.
- 모든 경로에서 발행율이 높을수록 p50이 약간 낮아지는 경향이 있었다(예: direct 10Hz 0.81 → 300Hz 0.63). 원인은 확인하지 않았다(CPU 절전 상태 전환 영향으로 추정만 한다).

### 갈래 B: 관제 PC ↔ pinky1 왕복 시간 (RTT, 5Hz, 20초 × 3회)
ping 쪽 한 시계로만 잰 값이라 시계 오차가 없다. 둘 다 같은 Wi-Fi(`192.168.45.x`)를 쓴다.

| 방식 | 유실 | p50 ms (3회) | p95 ms | pinky1 응답 프로세스 |
|---|---|---|---|---|
| DDS 직접 (도메인 101, cyclonedds, 브릿지 없음) | 0/300 | 9.0 / 8.1 / 8.9 | 15~17 | CPU 5.3%, 메모리 약 63 MB |
| MQTT QoS 0 (ping·pong 모두 QoS 0) | 0/300 | 8.6 / 9.5 / 8.8 | 15~19 | CPU 0.1%, 메모리 약 21 MB |
| MQTT QoS 1 (ping·pong 모두 QoS 1) | 0/300 | 41.4 / 41.6 / 41.5 | 43 / 252 / 130 | 측정 안 함 |

- pinky1 CPU·메모리는 10초 구간 `top` 1회 값이다. 반복 측정이 아니다.
- **QoS 0 MQTT와 DDS 직접은 RTT가 같은 수준**이다(Wi-Fi 구간이 지배한다).
- **QoS 1은 p50이 약 41 ms로 QoS 0보다 약 32 ms 더 길다.** 값이 매번 41 ms 근처로 일정해서 TCP의 Nagle/지연 ACK(약 40 ms) 상호작용을 의심하지만 **검증하지 않았다**. 아래 한계의 SSH 터널도 원인일 수 있다.
- 처음에는 ping만 QoS 1, pong은 QoS 0으로 돌렸더니 수신이 100건 중 9, 6, 0건이었다. pong의 실행 제한(130초)이 끝난 시점과 겹친 구간은 설명되지만, 응답 프로세스가 살아 있던 구간의 유실은 **원인을 찾지 못했다**. 이 조합의 값은 결론에 쓰지 않았다.

### 네트워크 부하: pinky1이 Wi-Fi로 보낸 양 (2026-11-07)
`mqtt_bench_net.py`로 pinky1 → 관제 PC 방향 합성 메시지를 보낼 때 pinky1 `wlan0`의 송신 카운터(`/proc/net/dev`) 증가량을 쟀다. 시험 직전 5초 기준선(아무것도 안 돌릴 때)을 빼고, 데이터 12초(idle은 20초) × 2회 평균이다. 두 방식 모두 pinky1은 도메인 101에서만 동작했고(도메인 10 사용 없음) 로봇 구동은 없었다.
- DDS: pinky1 source ↔ 관제 PC sink 직접 연결 (팀의 `cyclonedds_robot.xml` 설정 사용). 기존 DDS 브릿지는 로봇 도메인을 네트워크로 구독하므로 선로 위 트래픽이 같다고 가정했다.
- MQTT: pinky1의 source + ros2mqtt 중계가 loopback 전용 DDS로 묶이고, LAN 브로커(`192.168.45.11:1883`, 시험 중에만 개방)로 QoS 0 전송. 선로에는 MQTT(TCP)만 지난다.

| 조건 | 방식 | pinky1 TX [B/s] | pinky1 TX [pkt/s] | 메시지당 [B] | 반복별 TX [B/s] |
|---|---|---|---|---|---|
| idle (데이터 없음) | DDS | 3075 | 9.5 | - | 2787 / 3362 |
| | MQTT | -480 | -2.0 | - | -311 / -650 |
| twist 10 Hz | DDS | 6078 | 21.9 | 608 | 6252 / 5904 |
| | MQTT | 3192 | 8.5 | 319 | 3097 / 3288 |
| twist 100 Hz | DDS | 23745 | 110.6 | 237 | 23178 / 24312 |
| | MQTT | 36552 | 94.0 | 366 | 35653 / 37452 |
| laser 20 Hz (360점) | DDS | 37119 | 50.9 | 1856 | 37906 / 36331 |
| | MQTT | 47504 | 39.6 | 2375 | 47371 / 47637 |

- 기준선 자체가 pinky1 TX 약 0.6 KB/s였다. 음수(-480)는 기준선보다 잠깐 낮았다는 뜻이고, **MQTT idle은 잡음 범위(약 ±0.7 KB/s) 안이라 사실상 0**으로 읽는다.
- 메시지당 바이트는 "TX ÷ 발행율"이며 idle 몫이 섞여 있다(저주파일수록 크게 보임).

**읽은 내용**
- **idle:** DDS는 데이터가 없어도 약 3 KB/s를 보냈다(참여자 간 탐색·상태 확인). MQTT는 연결만 유지하면 측정 가능한 수준이 아니었다(keepalive 30초).
- **저주파(10 Hz):** MQTT가 DDS의 약 52% 바이트, 약 39% 패킷으로 **부하가 절반 정도**였다. DDS는 메시지마다 신뢰성 확인 교환(하트비트·ACK)이 붙어 건당 비용이 컸다.
- **고주파(100 Hz twist, 20 Hz laser):** MQTT가 오히려 **바이트가 많았다**(twist +54%, laser +28%). 패킷 수는 MQTT가 더 적었다(twist 94 대 111, laser 40 대 51 pkt/s).
- 원인 후보(검증 안 함): MQTT 쪽은 JSON 변환으로 메시지가 커졌고, 우리 중계가 메시지마다 `type` 문자열과 `sent_at`을 담은 봉투를 덧붙인다(건당 약 100 B). 봉투를 줄이면 고주파 격차는 줄어들 수 있다.

**이 결과의 한계 (중요)**
- PC 쪽 카운터는 쓰지 않았다. 이 PC의 다른 트래픽이 섞여 idle에서도 수십 KB/s가 나와서 신호보다 잡음이 컸다.
- 구간이 짧고(12~20초) 반복이 2회뿐이다.
- DDS는 발견에 몇 초가 걸렸다. 전체 구간 수신 건수가 발행의 약 68~70%(예: twist 100Hz 2400건 중 약 1640건)였던 것은 구간 앞부분이 매칭 전이라는 뜻이다. 시험 구간 시작(발행 8초 후)이 발견 완료와 겹쳤을 수 있어서 **DDS 값은 idle/탐색 몫이 과대, 데이터 몫이 과소일 수 있다.** 방향은 알 수 없다. 발견 대기를 15초 이상으로 늘려 다시 재야 정확하다.
- IP 계층 바이트라서 Wi-Fi 프레임 헤더와 재전송은 빠졌다. pinky1 → PC 한 방향만 봤다.
- 이 시험의 DDS는 참여자 두 개와 토픽 하나뿐이다. 실제 로봇 도메인에는 Nav2 등 훨씬 많은 노드·엔드포인트가 있어서 DDS 탐색 비용이 더 클 가능성이 있다. 이것이 MQTT가 부하를 줄일 수 있는 진짜 근거일 수 있지만 **재지 않았고 가설일 뿐이다.**
- 팀 설정은 멀티캐스트를 끄고 고정 피어로만 탐색하므로, "탐색 패킷이 Wi-Fi 전체에 퍼진다"는 가설은 이 환경에서는 해당하지 않는다.

### 한계
- MQTT는 SSH 역방향 터널을 거쳤다(pinky1 → 터널 → 관제 PC 브로커). 암호화와 터널 홉이 끼어 있어서 실제 LAN 직접 접속과 다를 수 있다. 특히 QoS 1의 41 ms가 터널 때문인지 MQTT 때문인지 분리하지 못했다.
- 갈래 B는 5Hz·작은 메시지(약 100 B) 한 가지 조건과 3회 반복뿐이다. 큰 메시지나 고주파는 갈래 A(같은 PC)에서만 잰 것이다. 네트워크 부하(바이트·패킷)는 위 "네트워크 부하" 절에서 따로 쟀다.
- 시험 때 pinky1의 `pinky_bringup`이 실행 중이지 않았다. 주행 시스템이 도는 상태의 pinky1 CPU 여유는 모른다.
- 갈래 A는 같은 PC라서 네트워크 전송 비용이 빠졌다. DDS 브릿지가 실제 두 장비 사이에서 추가하는 지연은 직접 재지 않았다(기존 브릿지를 두 장비 사이에서 돌리면 구동 토픽이 섞일 수 있어 피했다).
- MQTT 중계 CPU는 이번에 만든 파이썬 학습용 스크립트의 값이다. 실제로 쓰려면 구현을 다듬어야 하고 수치도 달라질 수 있다.

### 결론 (제안, 팀 결정이 아님)
같은 PC 안에서는 MQTT 중계가 DDS 브릿지보다 지연이 약 2~3 ms 더 길고 CPU를 5~10배 쓴다. 실제 망(Wi-Fi) 구간의 RTT는 QoS 0 MQTT와 DDS 직접이 같은 수준(약 9 ms)이었다. 이 측정 범위 안에서는 다음 구성이 합리적으로 보인다.
- **저주파·작은 상태 토픽**(배터리 약 0.2Hz, heartbeat 2Hz 등): MQTT QoS 0으로 중계해도 비용과 지연이 문제가 되지 않았다. pinky1 쪽 부담도 DDS 쪽보다 가벼웠다(메모리 21 MB 대 63 MB, 1회 측정). **네트워크 부하는 이 구간에서 MQTT가 더 낮았다**(10 Hz에서 DDS의 약 절반, idle은 DDS 약 3 KB/s 대 MQTT 거의 0). 네트워크 부하를 줄이고 싶다면 이 영역이 유일하게 측정으로 뒷받침된다.
- **고주파·큰 토픽**(`/scan`, `/tf`, `/odom` 등): 지금의 DDS 브릿지를 유지하는 편이 낫다. MQTT 중계는 300Hz까지 유실은 없었지만 한 코어의 약 40%를 썼고, 네트워크 바이트도 DDS보다 많았다(100 Hz twist +54%, 20 Hz laser +28%).
- **명령 토픽**(`/cmd_vel` 등): 이번 측정으로는 판단할 수 없다. QoS 1의 지연이 길게 나왔고 3b(구동 시험)를 하지 않았다.
- 이번에는 재지 않은 MQTT의 장점이 있을 수 있다(브로커로 도메인과 분리, 유언 메시지로 오프라인 감지, 재접속 자동 복구). 지연과 부하만으로 교체 여부를 정하기는 이르다.
- `docs/fms_decisions.md` 결정 항목으로 올릴지는 팀이 판단한다. 올린다면 후보 문구는 "상태 토픽 일부를 MQTT로 병행하는 시험 도입 여부"이고, 현행 DDS 브릿지를 대체하자는 제안은 아니다. 이 문서는 수정하지 않았다.

### 시험 뒤 정리 상태
- 양쪽 중계·ping/pong 프로세스 없음, SSH 터널 닫힘, pinky1 1883 리스너 0개, `mqtt_learning/#` retained 없음.
- 제가 pinky1에서 상태 확인 때 띄운 `ros2 daemon`(도메인 0)은 정리했다.
- pinky1에 남은 변경: `python3-paho-mqtt` 패키지 1개. 관제 PC의 `mosquitto`는 localhost 전용으로 계속 실행 중이다.

### 다음
- 3b(`/cmd_vel` 재발행)는 별도 계획과 승인이 필요하다. 이번 4단계 결과로는 명령 토픽을 MQTT로 보내도 되는지 판단하지 못한다.

## 도메인 브릿지 토픽 전체 확인 (2026-11-07)
기존 도메인 브릿지 설정(`pinky_bridge_pinky1.yaml`)의 토픽 21개가 MQTT 중계로 제대로 오가는지 `mqtt_bridge_check.py`로 확인했다. 설정 파일은 읽기만 했다.

### 방법 1: 가짜 메시지로 21개 전부 (격리 도메인, 로봇·실제 토픽 무관)
토픽 이름·타입은 설정 파일 그대로, 모든 필드를 알아볼 수 있는 값으로 채운 가짜 메시지를 5Hz로 보낸다. 출발 쪽은 loopback 전용 DDS(pinky1 도메인 101, 이 PC 도메인 102)이고, 도착 쪽 이름은 `/mqtt_test/check/<목적지 이름>`이다. 관제→로봇 방향 6개도 pinky1의 `/mqtt_test/…`에만 도착하고 **실제 `/cmd_vel` 등에는 아무것도 가지 않는다.** 도착한 메시지를 기대한 값과 **필드마다 비교**한다. 통과는 "5건 이상 도착, 값 불일치 0".

| 방향 | 토픽 | 타입 | 도착 | 불일치 | 결과 |
|---|---|---|---|---|---|
| 관제→로봇 | `/pinky1/cmd_vel` | Twist | 50 | 0 | PASS |
| | `/pinky1/goal_pose` | PoseStamped | 86 | 0 | PASS |
| | `/pinky1/initialpose` | PoseWithCovarianceStamped | 71 | 0 | PASS |
| | `/pinky1/patrol_cmd` | String | 47 | 0 | PASS |
| | `/zone_manager/grant_entry` | String | 78 | 0 | PASS |
| | `/zone_manager/queue_slot` | String | 90 | 0 | PASS |
| 로봇→관제 | `/battery/percent` | Float32 | 85 | 0 | PASS |
| | `/battery/voltage` | Float32 | 78 | 0 | PASS |
| | `/battery_state` | BatteryState | 84 | 0 | PASS |
| | `/odom` | Odometry | 84 | 0 | PASS |
| | `/scan` | LaserScan | 85 | 0 | PASS |
| | `/tf` | TFMessage | 86 | 0 | PASS |
| | `/patrol_status` | String | 71 | 0 | PASS |
| | `/pinky1/lane/center_offset` | Float32 | 80 | 0 | PASS |
| | `/pinky1/lane/detected` | Bool | 80 | 0 | PASS |
| | `/pinky1/crossline/detected` | Bool | 81 | 0 | PASS |
| | `/zone_manager/request_entry` | String | 85 | 0 | PASS |
| | `/zone_manager/notify_exit` | String | 77 | 0 | PASS |
| | `/zone_manager/cancel_entry` | String | 79 | 0 | PASS |
| | `/amcl_pose` | PoseWithCovarianceStamped | 0 | - | **FAIL (래치 토픽)** |
| | `/tf_static` | TFMessage | 0 | - | **FAIL (래치 토픽)** |

**결과: 21개 중 19개 통과, 값 불일치 0건.** 이름 대응, 타입 변환, 중첩 메시지(`TFMessage`, `Odometry` 등), 고정 길이 배열(공분산 36개)까지 값이 보존됐다.
- 도착 건수(47~90)는 발행(120) 중 중계가 붙기 전에 나간 메시지를 뺀 값이다. 이 표는 건수 비교가 아니라 **내용 일치**를 본 것이다.
- **실패 2개는 예상한 한계다.** `/amcl_pose`와 `/tf_static`은 마지막 값을 래치(transient_local)하는 토픽이다. 현재 중계(`mqtt_ros_relay.py`)는 `volatile`로 구독하므로, 발행자가 먼저 값을 한 번 보낸 뒤 중계가 붙으면 그 값을 받지 못한다(가짜 발행도 같은 방식으로 한 번만 보냈다). 고치려면 중계에 `transient_local` 구독 옵션을 추가해야 하며, 이 변경은 아직 하지 않았다(별도 승인 필요).

### 방법 2: 실제 토픽 읽기 전용 확인 (pinky1 도메인 10 구독만)
승인된 예외(구독 전용) 범위에서 pinky1 도메인 10의 실제 토픽을 최대 5Hz로 중계했다. 재발행은 이 PC 도메인 102의 `/mqtt_test/live/…`에서만 했다.

| 토픽 | 로봇이 받음 | 로봇이 중계 | 관제가 재발행 | 결과 |
|---|---|---|---|---|
| `/battery/percent` | 3 | 3 | 3 | PASS |
| `/battery/voltage` | 3 | 3 | 3 | PASS |
| `/odom` | 435 | 67 | 67 | PASS |
| `/scan` | 145 | 53 | 53 | PASS |
| `/tf` | 879 | 83 | 83 | PASS |
| 나머지 10개 | 0 | - | - | **발행 없음** |

- 발행이 있는 5개는 **로봇이 중계한 건수와 관제가 재발행한 건수가 정확히 같다.** `/odom`, `/scan`, `/tf`는 원래 20~90Hz로 발행되지만 시험은 5Hz 상한으로 걸어 둔 값이다. 5Hz에서의 통과이므로 원래 속도로 유실 없이 흐른다는 뜻은 아니다(고주파는 앞의 4단계 측정을 본다).
- **발행 없음 10개**: `/amcl_pose`(Nav2 꺼짐), `/patrol_status`, `/battery_state`, `/pinky1/lane/*`, `/pinky1/crossline/detected`, `/zone_manager/*`(request_entry, notify_exit, cancel_entry), `/tf_static`. 해당 노드가 꺼져 있거나 이벤트가 있을 때만 발행하는 토픽이라, **지금 pinky1에서는 실제 값을 확인하지 못했다.** 이 토픽들은 방법 1(가짜 메시지)로만 전송 경로를 확인했다.

### 시험 중 고친 것
- 실제 토픽 확인의 첫 실행에서 `/odom`, `/scan`, `/tf`가 FAIL(로봇 70건 중계, 관제 56건 재발행)로 나왔다. 유실이 아니라 **시험 설계의 시간차**였다. 이 PC의 받는 쪽이 먼저 시작해 먼저 끝났고, pinky1 쪽은 ssh와 import 때문에 늦게 시작해서 마지막 몇 초분이 받는 쪽이 끝난 뒤 도착했다. 받는 쪽의 실행 시간을 12초 늘리자 건수가 정확히 같아졌다.

### 한계
- 가짜 메시지는 값 보존과 경로를 확인하지만, 실제 노드의 발행 주기·QoS는 재현하지 못한다. `LaserScan`의 가변 배열은 3개 요소로 채웠다(실제 360점 크기는 방법 2의 `/scan`으로 확인).
- 래치 토픽 2개는 현재 중계로는 전달되지 않는다. 실제로 쓰려면 중계 수정이 먼저다.
- 한 번의 12초 구간이다. 장시간 안정성과 재접속 후 복구는 이 시험에서 보지 않았다.
- 명령 방향 6개는 이름·타입·값 보존만 확인했다. **실제 명령 토픽 중계(3b)는 하지 않았고 여전히 별도 승인 대상이다.**

## 전체 토픽 올리기와 원래 이름 발행 (2026-11-07)

`mqtt_bridge_check.py --role serve`로 로봇→관제 토픽을 계속 올려 두는 방식을 확인했다. 사용법은 `mqtt_guide.md` 0-5절.

| 확인 | 결과 |
|---|---|
| 래치 제외 13개를 `/mqtt_test/pinky1/...`로 올림 (도메인 102, 60·120초) | 13개 모두 이름이 뜸. 값은 `/odom`, `/scan`, `/tf`, 배터리 2개만 옴(나머지는 노드 꺼짐). 건수 일치. pinky1 load 1.3~1.5/4코어 |
| `--exact-names`: 브릿지 yaml 도착 이름 그대로 발행 (도메인 102) | 13개 이름 일치(`/pinky1/odom` 등), 값 확인. 같은 시각에 `serve`가 둘 돌아 건수 비교는 무효 → "한 번에 하나만" 주의 추가 |
| `--real-domain 100`: 실제 관제 도메인, 3개 토픽(화이트리스트), 120초 | `/pinky1/battery/percent`·`voltage` 24건=24건, 값 확인. 시작 전 발행자 중복 점검 통과 |
| `/pinky1/patrol_status` 실제 값 | 0건 (순찰 노드를 켜고, 중계를 띄운 뒤 재시작해도). 상태가 바뀔 때만 나가는 토픽이고 시작 시 1회는 발견 전에 지나간 것으로 추정. 가짜 시험은 통과 |

안전장치: 원래 이름 발행은 도메인 101/102에서만(`--allow-any-out-topic`), 도메인 100은 `--confirm-real-domain 100`을 함께 줘야 하고, 도메인 10은 항상 거부.

**남은 것:** `/pinky1/patrol_status` 실제 상태 변화 확인(순찰 명령 후), 래치 토픽 `transient_local` 옵션, 한 프로세스로 묶기, 명령 방향(관제→로봇), 빠른 토픽(`/odom`, `/scan`)의 도메인 100 발행. 팀 결정 항목화 여부는 팀 판단.

### 도메인 100 확대 시험 (2026-11-07, 18:2x~18:3x)

`serve --real-domain 100`의 화이트리스트를 단계적으로 늘렸다. `lane`·`crossline`은 사용하지 않아 제외, `/pinky1/tf`는 TF 충돌 우려로 제외, 명령 토픽은 미포함. 모든 시험에서 로봇은 움직이지 않았다(pinky1은 도메인 10을 구독만).

| 시험 | 결과 |
|---|---|
| 7개(배터리 3, patrol_status, zone_manager 3) 이름 | 도메인 100에 원래 이름 그대로 7개 확인 |
| `/pinky1/odom` 단독 60초, 5Hz 상한 | pinky1 구독 1789건 → 중계 273 → 도메인 100 수신 273 (유실 0), 약 4.5Hz, load 0.7~0.97 |
| `/pinky1/scan` 단독 60초, 5Hz 상한 | 구독 585 → 중계 212 → 수신 212 (유실 0), 값 확인, load 0.35~0.58 |
| 9개 동시 300초 (7개 + odom + scan) | `/scan` 1082=1082, `/odom` 1327=1327, 배터리 2개 59=59, 유실 0. 값이 없는 토픽(patrol_status, battery_state, zone_manager 3개)은 0건(발행 노드 꺼짐/이벤트형). pinky1 load 최대 1.63(시작 직후) → 0.5 안팎, 중단 기준 3.0 미달 |
| pinky1 Wi-Fi 송신 총량 (같은 구간) | 약 97.6 KB/s, 130 패킷/s (pinky1 전체 송신이라 다른 트래픽 포함, MQTT만의 값이 아님. 같은 조건의 DDS 브릿지 값은 이번에 재지 않음) |

해석과 한계:
- 5Hz 상한 때문에 `/odom`은 약 30Hz → 약 4.4Hz, `/scan`은 약 10Hz → 약 3.6Hz로 줄었다. 원래 주기를 기대하는 관제 코드는 동작이 달라질 수 있다.
- `/pinky1/patrol_status` 실제 값은 상태가 바뀔 때만 나가서 확인하지 못했다(가짜 시험은 통과).
- 발견한 결함: `serve`를 Ctrl+C로 끝내면 pinky1 구독 프로세스가 `--duration`까지 남았다(14개 정리). 종료 시 원격 정리를 추가했으나 실제 Ctrl+C 시험은 아직 하지 않았다.
- 남은 것: 원래 주기 발행(5Hz 상한 해제), 래치 토픽 옵션, `/pinky1/tf`, 명령 방향, 한 프로세스로 묶기, 기존 DDS 브릿지와 동시 비교.

### 원래 주기 발행 시험 (2026-11-07, `--fast-rate-hz`)

`/pinky1/odom`, `/pinky1/scan`의 전송 상한을 단계적으로 올렸다(도메인 100, 로봇 정지 상태, pinky1은 도메인 10 구독만). 상한을 걸면 원래 주기의 정수 분의 1로 줄어드는 점(예: odom 30Hz에 10Hz 상한 → 약 8Hz, 4개 중 1개 통과)을 확인했다. 상한을 풀면 원래 주기가 그대로 나온다.

| 상한 | 시간 | `/scan` 수신 | `/odom` 수신 | 유실 | pinky1 load | pinky1 Wi-Fi 송신(전체) |
|---|---|---|---|---|---|---|
| 10Hz | 60초 | 388건 (6.5Hz) | 498건 (8.3Hz) | 0 | 0.36~0.44 | 131 KB/s |
| 20Hz | 60초 | 556건 (9.3Hz) | 805건 (13.4Hz) | 0 | 0.54~0.86 | 197 KB/s |
| 제한 없음 | 60초 | 572건 (9.5Hz) | 1633건 (27Hz) | 0 | 0.45~0.58 | 211 KB/s |
| **제한 없음, 9개 토픽 동시** | **300초** | **2933건 (9.8Hz)** | **8856건 (29.5Hz)** | **0** | **0.59~1.18** | **233 KB/s** |

- 5분 시험에서 보낸 건수 = 받은 건수가 `/scan`, `/odom`, 배터리 2개 모두 일치(유실 경고 없음). 나머지 5개(patrol_status, battery_state, zone_manager 3개)는 발행 노드가 꺼졌거나 이벤트형이라 0건.
- 4코어 pinky1에서 load는 최대 1.18로 중단 기준(3.0)에 한참 못 미쳤다. 원래 주기가 가능하다.
- Wi-Fi 송신량은 **pinky1 전체 송신**(다른 트래픽 포함)이라 MQTT만의 수치가 아니다. 같은 조건의 DDS 브릿지와 나란히 비교한 값은 아직 없다. 이전 측정(JSON + 약 100 B 포장으로 빠른 토픽은 MQTT가 더 큼)을 고려하면 네트워크 이점은 기대하기 어렵다.
- 이 시험의 지연은 재지 않았다(두 장비 시계 차이). 지연 비교는 이전 RTT 시험(DDS 8~9 ms, MQTT QoS0 9 ms)을 참고.
- 기존 코드는 원래 이름·타입·주기로 `/pinky1/odom`, `/pinky1/scan`을 받을 수 있는 상태다. 단, 관제 쪽 구독 노드로 실제 확인한 것은 아니다.

### 래치 토픽 지원 (2026-11-07, 4단계)

`mqtt_ros_relay.py`에 `--ros-durability transient_local`(마지막 값 보관 토픽을 받고, 늦게 붙는 구독자에게 건넴)과 `--mqtt-retain`(브로커가 마지막 값 보관)을 추가했다. 기본은 예전과 같다(volatile, retain 끔).

| 확인 | 결과 |
|---|---|
| 가짜 메시지 시험 (격리 도메인, `--only /amcl_pose /tf_static`) | **2개 모두 PASS**, 필드 값 불일치 0 (이전 FAIL → PASS). 시험 뒤 브로커 보관 메시지 정리 확인 |
| 실제 도메인 100 `/pinky1/tf_static` | **시험하지 못함.** 시작 전 점검이 도메인 100에 이미 있는 발행자(`pinky_bridge_pinky1_only_100`, 기존 DDS 도메인 브릿지)를 발견해 중단. 아무것도 발행하지 않음 |
| `/pinky1/amcl_pose` 실제 값 | 미확인 (Nav2/AMCL이 켜져 있어야 함) |

참고:
- 같은 날 앞선 도메인 100 시험(배터리, odom, scan 등)은 모두 시작 전 점검(같은 이름의 발행자 없음)을 통과한 시점의 결과다. 이 시험 시점에는 다른 곳에서 브릿지가 다시 켜져 있었다(다른 팀원이 시험 중). 브릿지가 켜진 동안은 도메인 100에 MQTT 중계를 올리지 않는다.
- 실제 도메인 100에서는 래치 토픽 중 `/tf_static`만 `--include-latched`로 허용하고, `/amcl_pose`는 거부한다.
- 래치 토픽은 브로커에 마지막 값을 남기므로 `serve`가 끝날 때 보관 메시지를 지운다(`mosquitto_pub -r -n`).
- 정적 TF가 여러 건으로 나뉘어 발행되면 MQTT 보관은 마지막 1건만 남는다. 실제 `tf_static`에서 확인하지 못한 한계다.

### DDS 브릿지 vs MQTT 나란히 재측정 (2026-11-07, 실제 토픽 주기, loopback 수정 후)

같은 PC 안(source 도메인 101 → sink 도메인 102, 둘 다 loopback 전용 DDS), 8초 × 3회 평균. 합성 메시지의 모양과 주기를 실제 토픽에 맞췄다: `/odom`(Odometry 30Hz), `/scan`(LaserScan 10Hz, 360점), 명령 모양(TwistStamped 20Hz). 로봇과 실제 도메인(10, 100)은 쓰지 않았다. 앞서 정한 판정 기준: p50 차이 ±3 ms 이내를 "비슷함", CPU는 코어 점유율 비교.

| 조건 | 경로 | 수신 | p50 [ms] (3회 범위) | p95 [ms] | max [ms] | 중계 CPU |
|---|---|---|---|---|---|---|
| odom 30Hz | 직접(기준선) | 100% | 0.91 (0.90~0.92) | 1.06 | 2.6 | 0.0% |
| | DDS 브릿지 | 100% | 1.13 (1.09~1.17) | 1.31 | 2.0 | 0.9% |
| | MQTT QoS0 | 100% | 4.02 (3.98~4.06) | 7.76 | 12.8 | 10.1% |
| | MQTT QoS1 | 100% | 3.98 (3.96~4.02) | 4.61 | 6.1 | 10.6% |
| laser 10Hz | 직접 | 100% | 0.84 | 0.95 | 1.6 | 0.0% |
| | DDS 브릿지 | 100% | 1.07 | 1.23 | 1.4 | 0.5% |
| | MQTT QoS0 | 100% | 3.86 | 4.46 | 5.1 | 3.8% |
| | MQTT QoS1 | 100% | 3.80 | 4.27 | 4.8 | 3.9% |
| twist 20Hz | 직접 | 100% | 0.81 | 0.92 | 1.4 | 0.0% |
| | DDS 브릿지 | 100% | 1.10 | 1.23 | 1.4 | 0.7% |
| | MQTT QoS0 | 100% | 3.15 | 3.42 | 3.8 | 5.3% |
| | MQTT QoS1 | 100% | 3.14 | 3.48 | 4.0 | 5.8% |

해석:
- **지연:** MQTT는 DDS 브릿지보다 p50이 약 2.1~2.9 ms 길다(odom +2.9, laser +2.8, twist +2.0). 기준(±3 ms) 안이지만 odom은 경계에 가깝다. 이 장비 안에서는 QoS0과 QoS1의 차이가 없다(이전 실물 RTT에서 QoS1이 컸던 것은 이 시험에서는 재현되지 않았고, 네트워크 구간의 영향으로 추정하나 확인하지 않았다).
- **수신:** 모든 경로 100%.
- **CPU:** MQTT 중계가 DDS 브릿지의 약 8~11배(odom 10.1% vs 0.9%, laser 3.8% vs 0.5%, twist 5.3% vs 0.7%). 한 코어 대비 %이며 이 PC 기준이다. 앞서 실제 pinky1(4코어)에서 원래 주기로 올렸을 때 load는 최대 1.18이었다.
- **MQTT QoS0 odom의 p95 7.76 ms, max 12.8 ms**는 간헐적 지터가 있다는 뜻이다(QoS1은 4.61/6.1). 3회 평균이라 원인은 확인하지 못했다.
- **한계:** 같은 PC 안이라 네트워크 전송 비용이 빠졌다. LaserScan은 360점으로 고정했고 실제 라이다 점 수와 다를 수 있다. 직접 경로의 CPU는 중계 프로세스가 없어 0이다.
- **이전 갈래 A의 "참고값" 주의 해소:** 경향(MQTT가 약 2~3 ms 길고 CPU를 더 씀)은 loopback 수정 후에도 같다. 절대값은 이 표를 기준으로 본다.

### 폴더 정리와 pinky1 사본 삭제 (2026-11-07)

- 스크립트를 `scripts/spikes/mqtt/{core,tools,docs}`로 나눴다. 핵심(`core`)은 중계 본체와 전체 실행기, 나머지 측정·학습 도구는 `tools`. 경로 계산만 고쳤고 동작 로직은 그대로다.
- pinky1에 시험 초기에 복사해 둔 `/home/pinky/scripts/spikes/mqtt_ros_relay.py`(오래된 사본)와 빈 폴더 2개(`scripts/spikes`, `scripts`)를 삭제했다. 지금은 `serve`·`run`이 최신 코드를 ssh 입력으로 흘려 보내 실행하므로 pinky1에는 시험 파일이 남지 않는다.
- 폴더 이동 뒤 `mqtt_bridge_check.py`가 pinky1에서 실행될 때(파일이 아니라 ssh 입력) 상위 폴더 계산이 실패해 가짜 점검이 전부 0건이 되는 문제를 찾아 고쳤다. 고친 뒤 `/battery/percent`, `/tf_static`, `/pinky1/cmd_vel`(격리 도메인의 가짜 경로) 3개가 PASS(값 불일치 0).
- 터널이 pinky1 쪽에서만 죽는 경우가 있다(PC에는 `ssh` 프로세스가 남아 있음). 증상은 `pinky1 의 127.0.0.1:1883 에 닿지 않는다`이고 해결은 옛 터널을 `kill`하고 다시 여는 것이다. 이미 정상이면 다시 열 때 `remote port forwarding failed`가 나는데 정상 동작이다.
