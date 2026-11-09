# cobot_mqtt_bridge

도메인 브릿지(`cobot_domain_bridge`, DDS)와 **같은 기능을 MQTT로 제공**하는 패키지입니다. 도메인 브릿지는 그대로 유지하고, 상황에 맞게 하나를 골라 씁니다(한 도메인에서 동시에 켜지 않음). `cobot_navigation` 노드는 코드 수정 없이 같은 토픽 이름으로 호환됩니다.
브릿지 YAML(`pinky_bridge_pinkyN.yaml`)을 읽어, 로봇 한 대의 토픽을 프로세스 1개로 중계합니다.

> 상태: **E단계(3대 동시, 가짜 모드) 완료**, D단계(실물 없이 가능한 부분) 완료, C단계 PC 쪽(launch)·B단계 완료(가짜 모드) — 로봇→관제(up)와 관제→로봇(down) 모두 구현. down은 `enable_down:=true`로 켭니다(기본 꺼짐). 실물 pinky1·실제 도메인 시험은 아직 안 했습니다.
> 전체 계획·단계별 시험 절차·Claude Code 프롬프트는 [`docs/mqtt_bridge_prd.md`](docs/mqtt_bridge_prd.md).

## 동작 방식
```
로봇 도메인(10)          MQTT 브로커 (관제 PC)          관제 도메인(100)
 /scan, /odom ... ──▶ robot 역할 ──▶ mqtt_bridge/pinky1/up/scan ──▶ pc 역할 ──▶ /pinky1/scan
```
- `robot` 역할(pinky1에서 실행): 로봇 도메인 토픽을 구독해 MQTT로 보냅니다. ROS에는 발행하지 않습니다.
- `pc` 역할(관제 PC에서 실행): MQTT를 받아 관제 쪽 이름(`remap` 결과)으로 발행합니다.
- 토픽 목록·방향·이름은 `cobot_domain_bridge/config/pinky_bridge_pinkyN.yaml`에서 읽습니다.
- MQTT 주제: `mqtt_bridge/<로봇>/<up|down>/<로봇 쪽 토픽>`

## 실행 (시험 도메인, 한 PC 안)
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_mqtt_bridge
source install/setup.bash

ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args \
  --params-file src/cobot_navigation/cobot_mqtt_bridge/config/mqtt_bridge.yaml \
  -p robot:=pinky1 -p side:=pc -p duration_sec:=60.0
```
`ROS_DOMAIN_ID`는 바꾸지 않고 호출한 셸의 값을 씁니다. `side:=pc`는 101·102에서만 시작하고, 실제 도메인 100은
`-p confirm_real_domain:=100`과 기존 발행자 검사를 통과해야 하며, 도메인 10에서는 항상 거부합니다.
`side:=robot`으로 명령을 발행할 때(`enable_down:=true`)는 101·102에서만 시작하고, 도메인 10은 `confirm_real_domain:=10`과
`watchdog_ms`·`max_linear`·`max_angular`가 모두 0보다 클 때만 시작합니다.

### launch로 실행 (관제 PC 쪽)
```bash
ros2 launch cobot_mqtt_bridge mqtt_bridge.launch.xml pinky2:=false pinky3:=false
```
- 인자: `pinky1/2/3`(기존 `bridges.launch.xml`과 같은 이름), `enable_down`, `confirm_real_domain`, `duration_sec`, `host`, `port`, `params_file`
- 도메인 브릿지와 한 도메인에서 동시에 켜지 않습니다. 실제 도메인 100은 `confirm_real_domain:=100`이 필요합니다.
- Ctrl+C(SIGINT)와 SIGTERM으로 정상 종료합니다. launch를 `kill -9`로 죽이면 노드가 남을 수 있으니 직접 정리합니다.
- launch가 `kill -9`로 죽어도 노드는 `exit_on_parent_loss`로 스스로 종료합니다(0.4초 이내 확인).
- 로봇 쪽(pinky1) 기동은 아직 launch에 없습니다(실물 시험 보류).

### 연결이 끊겼을 때 (D단계)
- 브로커 연결이 끊기면 자동으로 재접속하고, 구독을 다시 걸고, 래치 토픽(`/tf_static`, `/amcl_pose`)의 마지막 값을 다시 올립니다.
- 끊긴 동안 명령(`down`)은 보내지 않고 버립니다(재접속 뒤 오래된 명령이 몰려 나가지 않게).
- 로봇 역할은 연결이 끊기면 움직이던 `cmd_vel`에 0 속도를 즉시 한 번 발행합니다(워치독 시간을 기다리지 않음).
- 상태 주제 `mqtt_bridge/<로봇>/status/<robot|pc>`에 `online`/`offline`(retain)이 올라옵니다. 비정상 종료는 브로커가 `offline`(cause: will)을 대신 올립니다. 시험 뒤 보관된 상태 메시지는 `mosquitto_pub -r -n -t <주제>`로 지웁니다.

## 파라미터 (`config/mqtt_bridge.yaml`)
| 이름 | 기본값 | 설명 |
|---|---|---|
| `robot` | (필수) | 로봇 이름, 예 `pinky1` |
| `side` | (필수) | `robot` 또는 `pc` |
| `bridge_config` | 빈 값 | 브릿지 YAML 경로. 비우면 `cobot_domain_bridge` 설치본에서 `pinky_bridge_<robot>.yaml` |
| `host`, `port` | 127.0.0.1, 1883 | 브로커 |
| `exclude_patterns` | lane, crossline | 제외할 토픽 (fnmatch) |
| `latched_topics` | `/tf_static`, `/amcl_pose` | ROS transient_local + MQTT retain |
| `rate_limits` | `/tf=30.0` | "토픽=Hz". 적지 않은 토픽은 원래 주기 |
| `load_abort` | 3.0 | robot 역할: 1분 load가 넘으면 스스로 중단 |
| `duration_sec` | 0.0 | 0이면 계속 실행 |
| `enable_down` | false | 관제→로봇 명령 중계. 로봇이 움직일 수 있어 기본 꺼짐 |
| `watchdog_ms` | 0.0 | 마지막 `cmd_vel` 뒤 이 시간이 지나면 0 속도 1회 발행. 0이면 꺼짐 |
| `max_linear`, `max_angular` | 0.0 | `cmd_vel` 선속도 [m/s]·각속도 [rad/s] 상한. 0이면 제한 없음 |
| `max_age_ms` | 0.0 | 이보다 오래된 `cmd_vel` 폐기. 두 장비 시계를 맞춘 뒤에만 사용 |
| `reconnect_min_sec`, `reconnect_max_sec` | 1.0, 30.0 | 접속 뒤 연결이 끊겼을 때 재접속 대기(실패할수록 두 배로 늘어남). 첫 접속 실패는 종료 코드 2 |
| `exit_on_parent_loss` | false | 부모 프로세스(launch)가 사라지면 스스로 종료. launch가 true로 켬 |
| `confirm_real_domain` | 빈 값 | 실제 도메인에 발행하려면 pc 역할은 `100`, robot 역할(명령)은 `10` |

## 시험
```bash
colcon test --packages-select cobot_mqtt_bridge && colcon test-result --verbose
```
YAML 파싱·상한·봉투·도메인 가드 단위 시험과 린트(flake8, pep257, copyright)가 포함됩니다.

## 구조
```
cobot_mqtt_bridge/
├── cobot_mqtt_bridge/
│   ├── bridge_config.py     # YAML → 중계 규칙 (순수 로직)
│   ├── relay_utils.py       # 전송 상한, JSON 봉투, 도메인 가드 (순수 로직)
│   ├── cmd_vel_guard.py     # 속도 상한, 오래된 메시지, 워치독 (순수 로직)
│   └── mqtt_bridge_node.py  # 노드 진입점 (로봇당 1프로세스)
├── config/mqtt_bridge.yaml
├── launch/mqtt_bridge.launch.xml
├── docs/mqtt_bridge_prd.md
└── test/
```
검증용 원본 스크립트는 `scripts/spikes/mqtt/`에 있습니다.
