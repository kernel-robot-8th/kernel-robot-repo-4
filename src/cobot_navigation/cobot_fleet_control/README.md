# 관제 서버 BT · MQTT · DB

UI → MQTT → 관제 서버의 `py_trees` → ROS 도메인 브릿지 → Pinky 공통 실행기 → Nav2 BT로 연결합니다. 업무 진행 상태와 실제 로봇 상태를 SQLite에 저장하고 MQTT 이벤트로 돌려줍니다. 전체 구조·분석·시연·검증 결과는 [단일 HTML 리포트](../docs/control_server_bt_report.html)에 있습니다.

현재는 이 브랜치에서 검증 가능한 독립 `ament_python` 패키지로 둡니다. 기존 `cobot_control_center`와의 통합 위치는 팀이 정하면 이전할 수 있습니다. 다른 기능 패키지의 Python 코드를 import하지 않습니다.

## 책임과 오픈소스

- `contracts.py`: 입력 검증, 로봇별 허용 목록, 명령 봉투.
- `service.py`: 중복 방지, 로봇별 한 작업, 결과 상관관계, BT 실행 수명.
- `behaviours.py`: `py_trees==2.2.3`의 memory Sequence로 전달 → 실제 작업 종료 대기. 후속 업무 단계는 Behaviour로 추가합니다.
- `repository.py`: 저장소 Protocol + 실제 SQLite 구현. 명령 상태와 outbox 이벤트를 함께 커밋합니다. 추후 서버 DB는 같은 경계를 구현합니다.
- `fleet_control_node.py`: `paho-mqtt==2.1.0` MQTT 통신, ROS 입출력, executor 스레드에서 DB/BT 실행.
- 로봇: Nav2가 제공하는 `nav2_bt_navigator`/BehaviorTree.CPP로 경로 계획·주행·복구. 이번 변경은 로봇의 Nav2 BT XML을 교체하지 않습니다.

## Docker로 버전과 실행 환경 고정

호스트의 venv·pip·colcon 절차를 Docker 이미지 빌드로 처리할 수 있습니다. Linux Docker Engine과 Compose 플러그인이 필요하며, 호스트에 ROS를 설치하지 않아도 됩니다. [Docker 실행·버전·배포 안내](config/docker/README.md)를 참고하세요.

```bash
# src/cobot_navigation에서
bash cobot_fleet_control/config/docker/fleet_docker.sh build
# 개발용 로컬 브로커도 함께 실행. 기존 브로커 사용 시에는 up
bash cobot_fleet_control/config/docker/fleet_docker.sh up-local
```

ROS·브로커 이미지는 digest, Python 직접·하위 의존성은 버전과 wheel 해시로 고정합니다. 세 관제 서비스는 같은 이미지를 사용하고 SQLite는 별도 named volume에 보존합니다. 이미지 전체 빌드·컨테이너 기동은 이 작업 환경에 Docker가 없어 아직 검증하지 못했습니다. 아래는 Docker를 쓰지 않을 때의 네이티브 실행 절차입니다.

## 설치와 빌드

Ubuntu 24.04 / ROS 2 Jazzy / Python 3.12 기준입니다. Paho의 Callback API v2를 사용하므로 배포판 기본 패키지 버전 대신 아래 고정 버전을 준비합니다.

```bash
source /opt/ros/jazzy/setup.bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install 'py_trees==2.2.3' 'paho-mqtt==2.1.0'
python -m colcon build --packages-select cobot_fleet_control cobot_pinky_patrol cobot_zone_traffic_control
source install/setup.bash
```

관제 서버는 `config/fleet_control.yaml`의 브로커·DB 경로를 사용합니다. 실행 전 각 로봇의 순찰 패키지도 새 버전으로 배포해야 JSON 명령/종료 응답을 처리합니다. `cobot_domain_bridge`의 기존 String 토픽은 그대로 사용합니다. 기존 zone_manager는 1개만 실행합니다.

```bash
# 브로커와 domain bridge, zone_manager, 로봇 실행기는 별도 기존 절차로 준비합니다.
# 아래 명령은 실제 로봇 연결 시 이동 명령을 수신할 수 있는 서버를 시작합니다.
ROS_DOMAIN_ID=100 ros2 launch cobot_fleet_control fleet_control.launch.xml
```

인증 정보는 `COBOT_MQTT_USERNAME`, `COBOT_MQTT_PASSWORD`, TLS CA는 `COBOT_MQTT_CA` 환경변수로 전달합니다. UI의 계정/역할 인증, 브로커 ACL, TLS 배포 설정은 운영 환경에서 별도로 구성해야 합니다. 브라우저에서 MQTT를 직접 쓰려면 해당 브로커의 WebSocket/WSS 리스너가 필요합니다.

## 데이터 계약

UI는 `cobot/fleet/commands`에 **QoS 1 / retain=false**로 아래 JSON을 보냅니다. 한 사용자 동작의 재전송에는 같은 `command_id`를 사용하고 새 작업에는 새 ID를 만듭니다.

```json
{"command_id":"job-20261031-001","robot_id":"pinky1","operation":"goto","points":["P1","P2"],"timeout_sec":300}
```

지원 업무는 `goto`(1~50개 지점), `zone`(1개), `leave`/`home`(지점 없음)입니다. 실제 지점 존재/구역 검증은 로봇 YAML을 기준으로 로봇이 최종 검증합니다. 기존 CLI의 `stop`/`emergency_stop`은 유지되지만 신규 MQTT 업무 API의 취소·선점 계약은 아직 포함하지 않습니다.

| 구간 | 토픽/저장소 | 내용 |
|---|---|---|
| UI → 관제 | `cobot/fleet/commands` | 위 JSON 명령 |
| 관제 → UI | `cobot/fleet/receipts` | 접수/중복 시 현재 상태 또는 REJECTED. 편의 알림이며 outbox에는 보관하지 않음 |
| 관제 → 로봇 | `/pinkyN/patrol_cmd` | `{"command_id":"…","command":"goto:P1,P2"}` |
| 로봇 → 관제 | `/pinkyN/patrol_status` | 기존 state/waypoint/detail/time + command_id/task_finished |
| 관제 → UI | `cobot/fleet/events` | 영속 outbox 이벤트. `type=command_state`, `robot_status` 또는 `bt_snapshot`, event_id, recorded_at |
| DB | `commands` | 명령 입력 원문 정규화, 최신 업무 상태 |
| DB | `robot_status` | 로봇별 최신 수신 원문과 서버 수신 시각 |
| DB | `outbox` | 작업 전이/수신 상태 이벤트, MQTT PUBACK 완료 여부 |

로봇은 내부 `DONE` 이후 정리 단계가 끝난 최종 상태에만 `task_finished=true`를 붙입니다. 관제는 로봇 ID와 명령 ID가 모두 일치하는 최종 응답만 완료로 처리합니다. 로봇의 `HOLDING_ZONE`은 구역 점유 상태이고 업무 `SUCCEEDED`와 별개의 개념입니다.

상태: `ACCEPTED → RUNNING → SUCCEEDED/FAILED`. 시간 초과·서버 재시작·전달 예외는 `UNKNOWN`으로 남아 로봇을 계속 예약합니다. 같은 ID의 지연 최종 응답이 오면 해제할 수 있습니다. 응답이 영구 유실된 경우 현재는 현장 확인·별도 운영 조정이 필요하며 자동 초기화/재전송 API는 제공하지 않습니다.

MQTT 이벤트는 QoS 1이므로 중복될 수 있습니다. UI는 `event_id`로 중복을 제거합니다. `recorded_at`은 서버 수신/기록 시각이고 `status.time`은 로봇 보고 시각입니다. UI 재접속 시 과거 이벤트를 조회하는 HTTP API는 아직 없으며 DB 조회 어댑터를 추가할 수 있습니다.

## 시험

```bash
# ROS 환경 source 및 위 가상환경 활성화 후, 저장소 루트에서
python -m pytest cobot_fleet_control/test -q
# 로컬 MQTT 브로커 왕복 시험까지 실행하려면 테스트 환경에만 amqtt 설치
python -m pip install 'amqtt==0.11.3'
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python -m pytest \
  cobot_fleet_control/test cobot_pinky_patrol/test cobot_zone_traffic_control/test -q
ament_flake8 cobot_fleet_control
ament_pep257 cobot_fleet_control
```

테스트 브로커는 임의 로컬 포트, DB는 pytest 임시 디렉터리, ROS는 격리 도메인 77에서 사용합니다. 가짜 navigator를 사용하므로 실측 주행·다중 실제 장비·브릿지 왕복·실제 Nav2 XML 선택은 별도 현장 검증 대상입니다.

## 운영 범위

단일 서버 프로세스 기준입니다. 다중 서버는 DB 고유 제약/원자적 로봇 예약·리더 선출·lease가 추가되어야 합니다. ROS String 토픽의 전송은 영속 원자 트랜잭션에 포함되지 않으므로 물리 동작의 exactly-once는 보장하지 않습니다. UNKNOWN 작업의 자동 재전송은 하지 않습니다.

브로커 연결이 끊겨도 수신한 작업의 DB 상태/outbox는 남습니다. 브로커의 영속 세션·메시지 저장 설정이 필요합니다. 이벤트 PUBACK은 UI 수신 확인과 다릅니다. receipts 거절 알림, DB 보존 기간/백업, 수신 큐 포화 시 운영 대응, 장기 DB 용량·복구 API는 후속 운영 작업입니다.

기존 로봇의 유휴 자동 복귀(120초), 구역 FIFO/토큰·강제 만료 정책, zone_gate_client 패키지 간 직접 import는 유지합니다. 업무를 관제로 모두 이전하려면 유휴 복귀도 관제 BT로 옮기고 구역 점유 상태·물리 위치 검증을 추가해야 합니다.

## BT 실행 시각화

[HTML 리포트의 BT 실행 시각화](../docs/control_server_bt_report.html#bt-visualizer)에서 이전/다음 tick, 자동 재생, 슬라이더로 실제 노드 상태를 확인합니다. 기본 데이터는 실제 `py_trees` 실행기와 가짜 로봇으로 수집한 5개 시나리오입니다. 손으로 상태 색을 맞춘 시연 데이터가 아닙니다.

`bt_visualization.py`는 `SnapshotVisitor`로 노드 ID·구조·상태·이번 tick 방문 여부·피드백을 관측합니다. 생성 시점과 상태/방문 경로가 바뀐 시점만 outbox에 `type=bt_snapshot`으로 저장하며 기존 `cobot/fleet/events`로 발행합니다. 매번 같은 대기 상태인 tick은 저장하지 않아 이력의 tick 번호에 간격이 있을 수 있습니다.

- 첫 tick: 전달 SUCCESS(방문), 결과 대기 RUNNING(방문).
- 다음 tick: 전달 SUCCESS(이번 tick 미방문), 결과 대기 RUNNING(방문). 명령이 다시 전송되지 않음을 확인합니다.
- 종료: 최종 결과에 따라 대기와 루트가 SUCCESS 또는 FAILURE.
- 시간 초과: 트리는 FAILURE, 업무는 UNKNOWN. 물리 정지를 의미하지 않습니다.
- 전달 예외: `phase=tick_error`, 업무 UNKNOWN. 노드 상태는 마지막 관측값이므로 FAILURE 색을 임의로 덮어쓰지 않습니다.

운영 DB 이력은 아래 명령으로 읽기 전용 추출 후 리포트의 파일 선택으로 가져옵니다. ACK가 끝난 이벤트도 추출합니다. HTML 파일은 서버나 CDN 없이 열리며 운영 MQTT를 직접 구독하지 않습니다.

```bash
# 새 console script 등록 후에는 패키지를 재빌드하고 install/setup.bash를 source합니다.
ros2 run cobot_fleet_control fleet_bt_trace \
  --db ~/.cobot/fleet_control.sqlite3 \
  --command-id job-20261031-001 \
  --output /tmp/bt_trace.json
```

JSON 형식은 `cobot-bt-trace-v1`, 브라우저 입력 제한은 10 MiB/5,000 스냅샷입니다. 많은 작업은 `--command-id`로 나눠 추출합니다. 현재 관측 대상은 관제 Python BT이며 로봇 Nav2 내부 BT·실제 물리 위치는 별도 계측이 필요합니다. 재시작 후 종료된 트리를 자동 재개하거나 지연 결과에 맞춰 과거 트리 색을 다시 칠하지 않습니다.

## 실행 스레드와 디버깅

관제 BT·DB·ROS 처리는 명시적인 SingleThreadedExecutor에서 실행합니다. Paho loop_start의 통신 스레드는 수신 큐만 갱신하며 업무 상태는 직접 변경하지 않습니다. 로봇은 작업 스레드 대신 비동기 액션·타이머 상태 기계로 전환했습니다. SQLite·작은 위치 파일 I/O는 동기이므로 하드 실시간 실행을 보장하는 구조는 아닙니다.

[실제 로직·디버깅 지도](../docs/control_server_bt_report.html#logic-debug)에 MQTT 수신부터 관제 BT, 로봇 상태 기계, 액션 취소·결과까지 읽는 순서와 증상별 확인 함수·변수를 정리했습니다.
