# 홈랩 7번 적재 확인과 메뉴 6.5 검증

팀 기준 c9374ec, 현장 통합본 7291d38에서 파생한 개인 시험용 기능이다. 7번 결합은 기본 꺼짐이며 77/140 LOCALHOST 및 camera_policy=sim에서만 켤 수 있다. 남은 15번 및 물리 팔·비전 단계는 기존 수동/시뮬 어댑터 계약을 유지한다. 실물 명령은 이 절차에서 사용하지 않는다.

## 재현

ROS 2 Jazzy 워크스페이스에서 다음을 실행한다. 팀 fleet와 모니터 시험에는 py-trees==2.2.3, pydot==2.0.0이 필요하다. MQTT 수신기를 실행할 경우 시험 venv에 paho-mqtt==2.1.0을 설치한다.

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=140 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_LOCALHOST_ONLY=1
colcon build --packages-up-to cobot_anomaly_monitor cobot_fleet_control
source install/setup.bash
python3 -m pytest -q src/cobot_anomaly_monitor/test/test_load_evidence.py src/cobot_anomaly_monitor/test/test_sim_debug.py
```

이 시험은 팀 ScenarioService와 ControlAPI, 실제 상태 저장소를 사용해 주문을 VERIFY_LOAD까지 진행시킨다. 합성된 세 프레임과 운영자 확인 후 LEAVE_PICKUP으로 넘어가야 한다. 틀린 모델·보정·호기 위치 미확인·중복·이전 시각·마커 유실·팔 확인 누락·수동 전환 뒤 늦은 입력은 성공으로 처리하지 않는다. 실물 카메라 영상을 사용하지 않는다.

## 시뮬 연결

홈랩의 기존 장치 시뮬과 모니터가 같은 요청에 각각 work_result를 발행하면 단일 소유권 검사가 차단한다. 재생 시에는 해당 시뮬의 별도 결과 발행기를 끄고 기존 모니터가 모든 결과를 발행하게 한다. 다른 단계의 수동 승인은 기존대로 사용할 수 있다. 실제 repo65의 로컬 변경이나 장치 시뮬은 이 배포물에 포함되지 않는다.

각 셸에서 위 ROS 환경과 install/setup.bash를 먼저 읽는다. 다음은 서로 다른 셸에서 실행한다.

```bash
ros2 launch cobot_anomaly_monitor anomaly_monitor.launch.xml camera_policy:=sim console_commands:=true verify_load_join:=true mode:=OBSERVE_ONLY scenario_config:="$(ros2 pkg prefix --share cobot_fleet_control)/config/scenario.yaml" db_path:=/tmp/homelab-verify-load.sqlite3
```

```bash
ros2 run cobot_anomaly_monitor sim_link_probe
```

```bash
ros2 run cobot_anomaly_monitor mqtt_zone_evidence --broker 127.0.0.1 --port 1883
```

개인 시험 브로커에서 relay/evidence/zones에 JSON을 QoS 1, retain=false로 발행한다. 수신기는 /anomaly_monitor/zone_evidence에 전달한다. 기존 탐지 프로그램에서 다음 형태로 변환하는 생산자와 실제 캘리브레이션은 홈랩에서 연결해야 한다. 아래 숫자는 필드 예시이며 실제 시험에서는 새 캡처 시각과 순번을 사용한다.

```json
{"source_kind":"model_output","stream_id":"ceiling","stream_epoch":"capture-run-01","frame_seq":51,"capture_time":1794200000.25,"clock_error_sec":0.02,"model_id":"pinky-v1","calibration_id":"replay-v1","marker_state":"OK","zones":{"ZA":"LOADED","ZB":"EMPTY"}}
```

실제 모델 없이 확인할 때는 모니터와 MQTT 수신기를 먼저 열고, 주문이 7번에 도달한 뒤 아래 명령을 실행한다. 10초 동안 메뉴에서 팔 퇴피를 확인한다. fixture 결과는 source_kind=sim_fixture로 저장돼 모델 성적에서 제외할 수 있다.

```bash
ros2 run cobot_anomaly_monitor replay_zone_evidence --zone ZA --state LOADED --port 1883
```

capture_time은 관제와 비교 가능한 Unix 초이다. 원천에서 측정한 시계 오차 상한이 없으면 성공 근거를 보낼 수 없다. LOADED는 해당 구역에 정확히 한 대의 적재 핑키가 있는 경우에만 쓴다. 다중·빈 차·미검출·마커 유실은 LOADED로 변환하지 않는다. 실사 과거 클립은 격리된 재생 시계에서만 다시 타임스탬프를 매기고 테스트 데이터로 표시한다.

합격 조건은 요청 이후 촬영된 고유 표본 3개가 3초 이내이고, 같은 요청에 대한 팔 퇴피 확인이 단계 제한 시간(`timeout_sec`, 없으면 60초) 안에 있는 경우다(11-09 홈랩 보완: 이전에는 3초 뒤 확인이 지워졌다. 세션 변경·단계 만료 때는 지운다). 허용 시계 오차 상한은 0.25초이다. 대상 호기는 해당 상차점 0.15 m 이내이며 점유·실제 도착·정지·잠금·주문/요청 일치가 필요하다. 다른 호기는 정지를 요구하지 않는다(11-09 보완: 다른 구역 주행 중인 호기가 적재 확인을 막던 결함). 같은 구역 토큰이면 막고, 정지 중이면 0.35 m 밖, 주행 중이면 3초 안의 최신 위치가 0.50 m 밖이어야 한다. 상태가 3초 넘게 안 오는 호기는 기동하지 않은 것으로 보고 배제하되, 마지막 위치가 0.50 m 안이면 막는다. 이 수치는 홈랩 초기값이며 현장 실측값이 아니다.

메뉴 6.5에서 운영자 이름을 입력한다. ‘팔 퇴피 확인’은 카메라 적재 근거를 생성하지 않는다. ‘전체 수동 확인’은 실제 적재·팔 퇴피 체크와 사유가 필요하다. 결과는 manual_work.result_json에 근거별 출처 및 operator_override 또는 camera_and_operator로 남는다. PUBLISH_UNCONFIRMED는 결정 저장 뒤 발행 여부가 불명확한 상태다. 자동 재발행 없이 관제의 주문 기록을 대조한다.

## 디버깅 포인트 확인표

| 항목 | 현재 확인 방법 |
|---|---|
| P2 연결 수 | ‘명령 토픽 연결 노드’에서 patrol_cmd, task_request, tasks 끝점 이름 확인. 명령 토픽 구독 없이 그래프 조회 |
| P5 전달 | sim_link_probe가 관제 140과 로봇 141/142/143에서 10초 수신 표본을 비교. 77이면 78/79/80 사용. 원천 0과 원천 있음·전달 0을 구분. scan, odom, patrol_status, battery, amcl_pose 대상. 영역 매니저 이벤트·실물 MQTT 진단 송신은 미구현 |
| P7 배정 | ‘배정 대기 사유’에서 3대 상태·배터리 나이, 보류, 작업·주문 예약, 구역 점유, central_latched 확인. 팀 기본값 3초·10초·20% 기준의 관측치 |
| P8 주문 | WAITING 주문 ID 옆에 후보 호기별 사유를 표시. 주문 카드·단계 이력은 기존 콘솔 사용 |
| P9 보류 | 기존 보류·복구 표시. 운영 승인과 실측 증거는 별도 |
| P10 순찰 경고 | 원천 도메인의 /rosout에서 최근 60초 patrol WARN 이상. probe 중단 시 과거 값을 정상으로 표시하지 않음 |
| P12 위치 | 기존 자세·수신 나이 표시. 정지/이동별 완전한 판정은 미구현 |
| P1·P3·P4·P6·P11·P13 | 컨테이너/실기 버전·lifecycle·명령 도착 지연·망·폰 영상은 이번 변경에서 미구현 |

웹 시험은 src/cobot_gui/web에서 npm ci, npm run build, npm run lint, npm test 순서로 실행한다. UI 재생에는 Vite가 8083의 모니터에 접속할 수 있어야 한다. Vite가 별도 컨테이너에 있으면 VITE_ANOMALY_MONITOR_URL을 시험용 모니터 주소로 지정한다. 운영 웹에 연결하지 않는다.

## 주문별 추적 (Phase 1)

메뉴의 주문 목록 또는 활성 주문이 있는 로봇 카드를 선택한다. 읽기 API는 GET /api/fms/orders/{order_id}/trace이다. 모니터가 관찰한 주문 스냅샷·요청 ID·로봇 최종 보고·장치 요청/결과와 자체 SQLite 작업 기록을 연결한다. 기존 DB도 열 수 있다. 새 기록기를 설치하기 전에 놓친 주행 ID, 장치 수신, 결과 수용은 추정하지 않는다. 팀 BT 원장 전체를 직접 가져오는 기능은 없다. 미관측 구간은 팀 fleet_bt_trace와 대조한다.

- 기본 19행, 실제 요청·시도만큼 추가행. 도킹 보정 뒤 새 측정은 새 request_id로 남는다.
- 주문 스냅샷의 request_id가 주행 command_id이다. 단일 zone 명령은 주문이 없으므로 자동으로 배송 주문의 단계에 포함되지 않는다.
- B 점유·UNKNOWN과 시간 초과를 구분한다. 결과 기록만 있으면 ‘수용 미확인’이다. 후속 단계 관측과 운영자 완료는 각각 표시한다.
- 7번 결과 서랍에는 결정·운영자·사유와 저장된 프레임의 촬영/수신 시각, 지연이 있다. 기존 기록에 필드가 없으면 ‘미기록’으로 표시한다. 다른 요청에 귀속되지 않은 결과도 별도로 열 수 있다.
- 화면 접속만 200이고 live_state와 trace가 500이면 Vite에서 지정한 8083 모니터가 실행 중인지 확인한다. 위의 시뮬 실행 절차를 사용한다. 조회 자체에는 console_commands=true가 필요하지 않다.

## 홈랩 좌표계와 실사 재생 점검

1. 실행 중인 repo65 브랜치·커밋과 시뮬 도메인을 기록한다. 해당 도메인에서 `ros2 node list`로 실제 노드 이름을 찾고, 맵 서버의 `yaml_filename`과 모니터의 `site_config`를 각각 `ros2 param get`으로 읽는다. 맵 서버가 없는 구성은 시뮬 런처가 사용한 맵 파일과 근거를 기록한다. 세 핑키의 순찰 사이트와 구역 관리자 대기열 파일도 해당 launch 또는 실행 파라미터로 확인한다.
2. 메뉴 6.5의 연결 진단에서 모니터 좌표 파일 이름과 SHA-256 앞 12자리를 실제 파일의 `sha256sum`과 대조한다. 이 값은 모니터가 읽은 파일만 식별한다. 순찰과 모니터는 같은 사이트를 사용해야 한다. 다른 사이트를 쓰는 홈랩은 모니터 launch에 `site_config:=<순찰 사이트 YAML 절대 경로>`를 지정할 수 있다.
3. 축 회전이 없는 trinary 맵을 쓰는 홈랩은 실제 파일 세 개로 아래 검사를 실행한다. 이미 같은 좌표계이면 오프셋을 주지 않는다. 출력의 `missing` 또는 `blocked`에 항목이 있으면 종료 코드는 1이다. 이 검사는 지점과 슬롯 중심만 본다. 차체 외곽이나 이동 구간 전체의 충돌은 별도 시뮬 확인 사항이다.

```bash
ros2 run cobot_anomaly_monitor audit_site_map --map "$MAP_YAML" --site "$PATROL_SITE_YAML" --queues "$QUEUE_YAML"
```

11월 4일 인계서의 변환을 검산하려면 정본 gate67 맵, 변경 전 lab.yaml과 zone_params.yaml에만 `--offset 1.415 1.639`를 추가한다. 팀 파일 기준 중심 53개 중 12개가 점유 셀이다. P1·P2·P3·P4·P9·P10·P12·P13·ZC_EXIT와 C 슬롯 0·1·2다. 이 결과로 시뮬 좌표 프로필을 자동 생성하지 않는다.

4. 실사 추론 결과를 재생하려면 격리 도메인 77 또는 140, LOCALHOST와 루프백 시험 브로커를 사용한다. 다음 명령은 원본 녹화 하나·모드 하나만 골라 실제 표본 간격으로 MQTT에 보낸다. `capture_time`은 시뮬 재생 시각이고, `capture_time_rel`, `recorded_epoch` 및 원본 프레임 번호는 보존한다.

```bash
ros2 run cobot_anomaly_monitor replay_zone_evidence --recording "$RECORDING_JSONL" \
  --epoch real-20261108-195226-1-raw --start-seq 0 --limit 3 --port "$TEST_BROKER_PORT"
```

이 예의 ZC 표본은 전송 형식을 확인하는 용도다. 7번 상차 시험은 ZA/ZB의 주문 위치와 일치하는 적재 구간을 골라야 한다. 홈랩 안티그래비티는 같은 주문의 trace 응답과 메뉴 표시를 대조하고, 사용한 맵·사이트·요청 ID·관측 결과를 함께 남긴다.

## 역할별 중계 웹 화면

| 경로 | 표시와 동작 |
|---|---|
| `/`, `/debug/overview` | 핑키별 주문·적재·배정 대기, 관제 수신, 마지막 배터리·정지 래치와 표본 나이. 격리 시뮬에서는 무장·일시정지·비상정지·재고 설정·수량 지정 주문·수령 확인. 모터 전원은 미계측. |
| `/debug/trace` | 주문별 19단계, 보정·재시도, 미연결 결과·완료 증거. SQLite 주문 원문 이력을 열어 요청 ID·수신 시각·내용을 페이지당 50건씩 대조한다. |
| `/debug/comm` | 구역 점유 대조, P2 준비 조건, P5 원천·목적지 표본 수, P10 경고, P12 토픽 나이, 최근 관제 RTT·작업 상태, AMCL과 사이트 지점 간 거리로 추정한 경유 이력. 수신 수의 차이만으로 개별 DDS 패킷 손실을 확정할 수 없다. |
| `/debug/vision` | 7번 적재 증거·녹화 프레임 대조와 CCTV 이상 기록. 권한이 켜진 격리 시뮬에서만 승인·오탐 처리·복구 양식이 나타난다. |
| `/debug/sim-tools`, 기존 `/menus/6.5` | 브라우저 모의 캔버스, 예제 SEND/ACK/DONE, 화면 모의 정지. 격리 시뮬의 관제 경유 단일 이동·모의 이상 주입은 별도 도구로 표시한다. |

중계의 도메인 100은 기존 관측 전용 프로필을 사용한다. 명령 UI는 도메인 77·140, 모니터 연결, 서버 명령 허용 세 조건을 모두 확인한다. 브라우저 모의 장면의 위치와 예제 지연은 관제 측정값과 분리해 읽는다.

읽기 API `GET /api/fms/orders/<order_id>/history?after=<cursor>`는 모니터 SQLite에 남은 해당 주문 기록만 반환한다. `control_request/control_reply`는 이 모니터에서 생성한 주문 관련 관제 요청·응답, `request/result`는 관측한 장치 작업 원문이다. 관제 응답과 일치하는 요청에서 측정한 RTT만 표시한다. 모니터가 관측하지 못한 응답, 기존 DB에 없는 과거 RTT, 다른 발행자가 보낸 주문 제어 요청은 복원하지 않는다. 상시 진단 페이지의 최근 메모리 로그와 적용 범위가 다르다.
