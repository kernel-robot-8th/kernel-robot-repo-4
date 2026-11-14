# MQTT 학습 PRD (pinky1 실물 기준)

담당: 주행 (`cobot_navigation`)
작성일: 2026-11-05 / 수정: 2026-11-05 (격리 `.venv` 방식 → pinky1 실물 직접 시험 방식)

## 1. 목적
- ROS 2 도메인 브릿지(DDS 복사)와 MQTT(브로커 기반 pub/sub)의 통신 방식 차이를 **pinky1 실물과 실제 네트워크에서** 직접 확인한다.
- 기존 `cobot_domain_bridge` 코드는 수정·교체하지 않는다. 학습용 스크립트만 별도로 만든다.
- 가상환경(`.venv`)과 가짜 발행기를 쓰지 않고, 대상 장비에 바로 설치해 시험한다.

## 2. 범위
| 포함 | 제외 |
|---|---|
| MQTT 기본 개념 실습 (토픽, 와일드카드, QoS, retained, LWT) | 기존 `cobot_domain_bridge` 수정·교체 |
| `paho-mqtt` 파이썬 pub/sub 스크립트 (시스템 설치) | pinky2·pinky3 시험 (pinky1 결과 확인 후 별도 결정) |
| pinky1의 ROS 토픽을 MQTT로 중계하는 학습용 노드 | `msg/srv/action` 인터페이스 변경 |
| 지연·대역폭 측정 기록 | 서비스·액션의 MQTT 변환 |
| 구동 없는 토픽(상태·pose 등) 중계 → 마지막에 `/cmd_vel` 저속 시험 | 사용자 확인 없는 로봇 구동 |

## 3. 산출물과 위치
| 단계 | 산출물 | 위치 |
|---|---|---|
| 전체 | 이 PRD | `scripts/spikes/mqtt/docs/[진행] mqtt_learning_prd.md` |
| 1~4 | 학습·실험 기록 | `scripts/spikes/mqtt/docs/mqtt_learning.md` |
| 전체 | 스크립트 사용 가이드 | `scripts/spikes/mqtt/docs/mqtt_guide.md` |
| 4 보강 | 브릿지 토픽 전체 확인 | `scripts/spikes/mqtt/core/mqtt_bridge_check.py` (결과: `mqtt_learning.md`) |
| 2 | pub/sub 스크립트 | `scripts/spikes/mqtt/tools/mqtt_pub.py`, `scripts/spikes/mqtt/tools/mqtt_sub.py` |
| 3 | ROS↔MQTT 중계 스파이크 | `scripts/spikes/mqtt/core/mqtt_ros_relay.py` |
| 4 | 측정 스크립트 | `scripts/spikes/` 아래 평평하게 (스크립트용 하위 폴더 만들지 않음, 문서만 `scripts/spikes/mqtt/docs/`) |

- 스크립트는 `scripts/spikes/`(한 번 확인하고 끝나는 검증 스크립트) 바로 아래에 평평하게 두고, 문서(이 PRD와 학습 기록)만 사용자 지시(2026-11-07)로 `scripts/spikes/mqtt/docs/`에 둔다.
- 팀 결정(도메인 브릿지 교체 여부)으로 이어질 때만 요약을 최상위 `docs/`와 `docs/fms_decisions.md`에 올린다.

## 4. 제약
- **설치 방식**: 가상환경 없이 시스템에 직접 설치한다. 시스템 파이썬에 `pip install`은 하지 않는다 (PEP 668). 장비별로 apt만 쓴다.
  - 관제 PC: `sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt` (설치 직후 서비스 상태를 확인하고, 시험 전까지 필요하면 `stop`)
  - pinky1: `sudo apt install -y python3-paho-mqtt` (클라이언트만)
- **새 의존성·apt**: `paho-mqtt`·`mosquitto` 도입은 2026-11-05 허락을 받았다. 모든 `apt install`/`sudo` 명령은 실행 직전에 다시 확인받는다. 2026-11-05 기준 관제 PC에 미설치이고 `apt-get install -s` 시뮬레이션에서 신규 6개(`mosquitto`, `mosquitto-clients`, `python3-paho-mqtt`, `libmosquitto1`, `libdlt2`, `libwebsockets19t64`), 업그레이드·제거 0개, `ros-jazzy-*` 영향 없음을 확인했다. pinky1(`192.168.45.21`)은 2026-11-05 읽기 전용으로 확인했다: Ubuntu 24.04.4 aarch64, `ros-jazzy-ros-base` 설치됨, `~/.bashrc`의 `ROS_DOMAIN_ID=10`·`rmw_cyclonedds_cpp`, MQTT 관련 패키지 미설치, 1883 포트 미사용, `apt-get install -s python3-paho-mqtt` 결과 신규 1개·업그레이드/제거 0개·`ros-jazzy-*` 영향 없음, `/` 여유 7.5G. 확인 시점에 `pinky_bringup`(라이다·바퀴 제어 포함)이 실행 중이었다. 설치는 별도 확인 후에 한다. `python3-paho-mqtt`는 Ubuntu 24.04에서 1.6.1이므로 2단계 스크립트는 이 버전의 콜백 API에 맞춘다.
- **시험 대상**: pinky1 한 대만 한다. 다른 로봇의 토픽·도메인에 영향을 주지 않는다. pinky1은 시험 중 `pinky_bringup`이 실행 중인 주행 가능 상태일 수 있으므로, 구동 토픽은 3b 승인 전까지 건드리지 않는다.
- **접속 방식**: pinky1 SSH는 키 인증(`pinky@192.168.45.21`)으로 하고, 비밀번호는 문서·스크립트·저장소에 적지 않는다.
- **ROS_DOMAIN_ID**: 임의로 바꾸지 않는다. pinky1은 현행 `10`(README, `pose_recovery.yaml` 기준), 관제 PC는 `100`이다. pinky1 장비에서 실제 값을 시험 전에 한 번 더 읽어 확인한다.
- **도메인 10 예외 (2026-11-05 사용자 승인)**: `docs/fms_interfaces.md`는 실물 망에서 개발 노드를 10·12로 띄우지 않도록 하지만, 이 시험에 한해 **구독 전용** relay(pinky1 토픽 → MQTT)를 pinky1의 도메인 10에서 실행하는 것을 허용한다. 재발행(MQTT → ROS, 쓰기 방향)은 이 승인에 포함되지 않으며 3b 단계에서 별도로 승인받는다.
- **브로커**: 위치는 **관제 PC**, 주소는 `<관제 PC LAN IP>:1883`이다(2026-11-05 기준 `192.168.45.11`, DHCP로 바뀔 수 있어 시험 당일 다시 확인해 기록). pinky1이 접속하려면 LAN 접속을 열어야 하므로 네트워크 설정 변경에 해당하고, 열기 직전에 확인받는다. pinky1에는 브로커를 두지 않는다. 공개 브로커에는 로봇 데이터를 보내지 않는다. 인증 없는 브로커는 시험 동안만 열고 끝나면 내린다.
- **로봇 구동**: 구동하는 토픽(`/cmd_vel` 등)은 사용자 확인 후에만 보낸다. 시험 전에 비상정지 수단을 확보하고, 바퀴를 띄우거나 저속·짧은 시간으로 시작하며, 속도 상한은 파라미터로 받는다.
- **코드 규칙**: 값은 파라미터나 인자로 받고(매직 넘버 금지), 로깅은 `get_logger()`/`logging`을 쓰며 `print`는 쓰지 않는다. `ament_flake8 scripts/`, `ament_pep257 scripts/`, `ament_copyright scripts/`를 통과해야 한다.

## 5. 단계별 완료 기준
| 단계 | 완료 기준 |
|---|---|
| 0 | 설치 항목, 대상 장비, pinky1 도메인(10), 브로커 위치(관제 PC)가 정해지고, 도메인 10 예외는 승인됐다. 새 의존성(`paho-mqtt`, `mosquitto`) 허락은 받았다(2026-11-05). pinky1 읽기 전용 확인도 끝났다(2026-11-05). 남은 것은 설치 실행 확인(`sudo apt`)과 브로커 LAN 개방 확인이다. |
| 1 | `mosquitto_pub/sub`로 와일드카드, QoS, retained, LWT 동작을 직접 확인하고 기록한다. **완료 (2026-11-05, 기록: `scripts/spikes/mqtt/docs/mqtt_learning.md`)** |
| 2 | `mqtt_pub.py`와 `mqtt_sub.py`가 브로커로 메시지를 주고받고, 재접속과 QoS 차이를 보여 준다. **완료 (2026-11-05, 기록: `scripts/spikes/mqtt/docs/mqtt_learning.md`)** |
| 3a | pinky1의 구동 없는 토픽 하나(예: pose·상태)가 MQTT를 거쳐 관제 PC에서 재발행된다. **완료 (2026-11-05, `/fleet_heartbeat`와 `/battery/percent`로 시험. `/amcl_pose`는 Nav2 미실행으로 미시험, 기록: `scripts/spikes/mqtt/docs/mqtt_learning.md`)** |
| 3b | (확인 후) `/cmd_vel`을 저속·단시간으로 MQTT 경유 전달해 동작을 확인한다. 속도 상한과 정지 수단을 먼저 확인한다. |
| 4 | 지연(ms)과 메시지율을 측정하고 DDS 브릿지와 비교한 표를 남긴다. **완료 (2026-11-07, 갈래 A 60회·갈래 B 실물 RTT·네트워크 부하(pinky1 TX) 측정, 결과 표와 제안 결론과 한계: `scripts/spikes/mqtt/docs/mqtt_learning.md`)** |

## 6. 위험 요소
| 위험 | 대응 |
|---|---|
| 실물 로봇이 의도치 않게 움직임 | 3a(구동 없음)부터 시작, 3b는 매번 확인 후 저속·단시간, 비상정지 확보, 속도 상한 파라미터 |
| MQTT 단절·지연으로 `/cmd_vel`이 끊기거나 늦게 도착 | 수신 측 워치독(일정 시간 수신 없으면 0 속도) 포함, 시험 중 retained 메시지 사용 금지 |
| 고주파 토픽 때문에 브로커·네트워크·pinky1 CPU 과부하 | 중계 주기를 제한하고 4단계에서 단계적으로 올린다. |
| 도메인·네트워크 설정을 건드려 다른 로봇·팀 시험에 영향 | 도메인과 네트워크는 바꾸지 않고, 브로커 포트만 사용한다. 도메인 10에는 구독 전용 relay만 띄운다. |
| 공개 브로커·무인증 브로커로 데이터 유출 | 사설 LAN 안의 브로커만 쓰고 시험 후 내린다. |
| 시스템 설치로 장비 환경이 변함 | 설치 목록을 기록하고, 끝나면 제거할지 정한다(제거는 확인 후). |

## 7. 참고: 통신 구조
```
[pinky1 (ROS 2, 도메인 10)]             [관제 PC (ROS 2, 도메인 100)]
   relay 노드 ──publish──▶ [MQTT 브로커] ──subscribe──▶ relay 노드
   (ROS 토픽 ↔ MQTT)                                  (MQTT ↔ ROS 토픽)
```
- 브로커는 관제 PC에 둔다(4번 제약 참고).
- 서비스·액션은 MQTT에 요청/응답이 없어 요청·응답 토픽과 correlation id가 필요하다. 이번 범위에서는 제외한다.

## 8. 단계별 Claude Code 프롬프트
각 프롬프트는 Plan 모드에서 시작하는 것을 전제로 한다. 이전 단계가 끝난 뒤에 다음을 실행한다. 모든 단계에서 `sudo`·`apt`·로봇 구동은 실행 직전에 다시 확인받는다.

### 0단계: 준비와 허락 확인
```
CLAUDE.md의 10-1 규칙에 따라 Plan 모드로 진행해줘.
목표: pinky1 실물 MQTT 시험 준비. 아직 파일 수정·설치는 하지 말고 계획만 세워줘.
- 가상환경 없이 시스템에 설치. paho-mqtt, mosquitto 설치 여부를 읽기 전용으로 확인
- 설치는 pip 가 아니라 apt (python3-paho-mqtt, mosquitto, mosquitto-clients) 로 계획
- 새 의존성 허락 필요 여부, 설치할 장비, pinky1 의 현재 ROS_DOMAIN_ID, 브로커 위치·주소 정리
- 설치 명령은 내가 확인한 뒤에만 실행. sudo/apt 는 실행 직전에 다시 물어봐줘
- 이 PRD 를 기준 문서로 삼기
- 로봇 구동 여부와 위험 요소도 계획에 적어줘
```

### 1단계: MQTT CLI 개념 실습
```
Plan 모드로 진행해줘. 승인 전에는 파일 수정·명령 실행 금지.
목표: mosquitto_pub/sub 명령으로 MQTT 기본 개념을 익히고 scripts/spikes/mqtt/docs/mqtt_learning.md 에 기록.
- 0단계에서 정한 브로커만 사용. 공개 브로커 사용 금지
- 실습 항목: 토픽 계층, 와일드카드(+, #), QoS 0/1/2, retained, LWT
- pinky1 과 관제 PC 사이에서 실제로 주고받아 확인
- 각 항목마다 "명령 → 예상 결과 → 확인한 결과" 형식으로 기록, 한국어로 작성
- 계획에 변경 파일 목록, 위험 요소, 검증 방법을 포함해줘
```

### 2단계: 파이썬 pub/sub 스크립트
```
Plan 모드로 진행해줘.
목표: paho-mqtt 로 publish/subscribe 를 직접 구현하는 학습용 스크립트 작성.
- 위치: scripts/spikes/mqtt/tools/mqtt_pub.py, scripts/spikes/mqtt/tools/mqtt_sub.py (스크립트용 하위 폴더·새 colcon 패키지 만들지 말 것)
- 브로커 주소·포트·토픽·QoS 는 argparse 인자로 받기 (매직 넘버 금지)
- 로깅은 logging 모듈 사용, print 금지. on_connect/on_message 콜백 구조로 작성
- 재접속과 QoS 0/1 차이를 관찰할 수 있는 옵션 포함
- 코드마다 "왜" 이런 구조인지 한국어 주석으로 설명
- 검증: ament_flake8 scripts/, ament_pep257 scripts/, ament_copyright scripts/ 통과
- 결과와 배운 점을 scripts/spikes/mqtt/docs/mqtt_learning.md 에 추가
```

### 3단계: ROS 토픽 ↔ MQTT 중계 (pinky1 실물)
```
Plan 모드로 진행해줘.
목표: pinky1 의 ROS 토픽을 MQTT 로 중계하는 학습용 스파이크. 3a(구동 없는 토픽) 먼저, 3b(/cmd_vel) 는 별도 승인.
- 위치: scripts/spikes/mqtt/core/mqtt_ros_relay.py (기존 cobot_domain_bridge 수정 금지)
- 구조: rclpy 노드가 토픽 구독 → JSON 직렬화 → MQTT publish,
  반대 방향 MQTT subscribe → ROS 토픽 재발행
- 직렬화는 rosidl_runtime_py.convert (message_to_ordereddict, set_message_fields) 사용
- ROS_DOMAIN_ID 는 pinky1 현재 값(10)을 그대로 사용, 변경 금지. 3a 는 구독 전용 relay 만 허용(도메인 10 예외), 재발행 방향은 3b 에서 별도 승인
- 토픽 이름·MQTT 토픽·QoS·속도 상한·워치독 시간은 declare_parameter 또는 인자로 받기
- 3b 는 비상정지 수단, 저속, 단시간, 수신 워치독(끊기면 0 속도)을 계획에 명시하고 실행 직전에 다시 확인
- 계획에 "로봇 구동 여부"(3a 없음 / 3b 있음)와 위험 요소를 명시하고, 검증 절차를 적어줘
- 결과는 scripts/spikes/mqtt/docs/mqtt_learning.md 에 기록
```

### 4단계: 측정과 비교
```
Plan 모드로 진행해줘.
목표: MQTT 중계와 기존 DDS 도메인 브릿지의 지연·부하를 비교하는 측정 기록.
- 새 측정 스크립트는 scripts/spikes/ 에 평평하게만 만들기
- 측정 항목: 왕복 지연(ms), 메시지율(Hz), CPU 사용률(pinky1 포함). 주기를 단계적으로 올려가며 측정
- 구동하지 않는 토픽으로만 측정. 고주파 시험이 pinky1 주행·다른 로봇에 영향을 주지 않게 상한을 둔다
- 결과는 표로 scripts/spikes/mqtt/docs/mqtt_learning.md 에 정리하고, 하이브리드 구성(가벼운 토픽만 MQTT)이 적합한지 결론 작성
- docs/fms_decisions.md 의 결정 항목으로 올릴지는 내가 판단할 테니 제안만 해줘
```
