# cobot_mqtt_bridge

관제 PC와 Pinky 로봇 사이의 ROS 2 토픽을 **MQTT로 중계**하는 패키지입니다. 기존 DDS 브릿지(`cobot_domain_bridge`)와 같은 기능을 하며, 둘 중 하나를 골라 씁니다. 자세한 절차는 [`docs/usage.md`](docs/usage.md), 계획과 시험 결과는 [`docs/mqtt_bridge_prd.md`](docs/mqtt_bridge_prd.md)에 있습니다.

## 1. 주요 기능

- **로봇 → 관제(up):** 로봇의 `/scan`, `/odom`, `/tf`, 배터리 등을 MQTT로 보내 관제 쪽에서 `/pinky1/...` 이름으로 발행합니다. 실물 10분 시험에서 유실 0.
- **관제 → 로봇(down, 명령):** `patrol_cmd`(순찰 명령) 등을 전달합니다. **기본 꺼짐**이고, 켜려면 확인 인자가 필요합니다.
- **끊김 복구:** 자동 재접속, `online`/`offline` 상태 주제, 래치 토픽(`/tf_static`, `/amcl_pose`) 재발행.
- **기존 코드 수정 없음:** `cobot_navigation`과 `cobot_domain_bridge`는 그대로 두고, 둘을 **같은 도메인에서 동시에 켜지 않습니다.**
- **토픽 목록은 이 패키지 전용:** `config/mqtt_topics_pinky1~3.yaml`. 고쳐도 DDS 브릿지에 영향이 없습니다.

```
 pinky1 (ROS 도메인 10)                    관제 PC (ROS 도메인 200)
┌──────────────────────┐   SSH 역방향   ┌────────────────────────────────┐
│ robot 역할 노드        │ ─── 터널 ───▶ │ MQTT 브로커 127.0.0.1:1883      │
│ ROS 구독 → MQTT 발행   │               │   ▲                  │          │
└──────────────────────┘               │ pc 역할 노드: MQTT 구독 → ROS 발행 │
                                       └────────────────────────────────┘
```
- 관제 쪽 ROS 도메인은 **200**입니다(다른 팀의 DDS 브릿지가 쓰는 100과 분리). 관제 쪽 프로그램(`pinky_control_client.py` 등)은 `ROS_DOMAIN_ID=200`으로 실행해야 값이 보입니다.
- MQTT 주제: `mqtt_bridge/<로봇>/<up|down>/<토픽>`, 상태는 `mqtt_bridge/<로봇>/status/<robot|pc>`.

| 현재 상태 | |
|---|---|
| up 중계 (pinky1 실물) | 완료 |
| down `patrol_cmd` (pinky1 실물) | `goto P1` 전달·이동 성공. `stop`/`emergency_stop`은 미시험 |
| 3대 동시 | 가짜 모드만 시험 (실물은 pinky1) |
| 자동 시작(systemd) | 파일·재부팅 시험 완료, 현재 꺼 둠 |

## 2. 설치 방법

처음 한 번만 합니다. 준비물: 관제 PC(Ubuntu 24.04, ROS 2 Jazzy, 이 저장소), pinky1(ROS 2 Jazzy, `pinky@192.168.45.21`로 SSH 접속).

```bash
# [PC] 브로커와 파이썬 라이브러리 (브로커는 PC에만 설치)
sudo apt update && sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt
systemctl is-active mosquitto && ss -ltn | grep 1883       # active, 127.0.0.1:1883 만 보이면 정상

# [PC] SSH 키 (비밀번호 없이 pinky1 접속). ok 가 나오면 이미 된 것
ssh -o BatchMode=yes pinky@192.168.45.21 echo ok || { ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519; ssh-copy-id pinky@192.168.45.21; }

# [PC] 빌드 (저장소 루트가 아니라 src/cobot_navigation 에서. 코드를 고치면 매번 다시 빌드)
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_mqtt_bridge
source install/setup.bash
```
```bash
# [PC → pinky1] 코드 복사 (빌드 없이 복사만. 코드·토픽 YAML 을 고치면 다시 실행)
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
tar --exclude=__pycache__ -cf - cobot_mqtt_bridge/cobot_mqtt_bridge cobot_mqtt_bridge/config \
  | ssh pinky@192.168.45.21 'mkdir -p ~/mqtt_bridge && tar -xf - -C ~/mqtt_bridge'
ssh pinky@192.168.45.21 'python3 -c "import paho.mqtt, yaml; print(\"ok\")"'     # ok 가 나와야 함
```
- paho-mqtt는 1.6.1(apt 기본)로 시험했습니다. pip로 설치하지 않습니다.
- 자동 시작 서비스(선택, `sudo` 필요)와 설치 상세: [`docs/usage.md` 2장](docs/usage.md#2-설치-방법).

## 3. 실행·시험 순서

앞 단계가 통과한 뒤 다음으로 갑니다. 아래로 갈수록 준비물이 많고 위험합니다.

| 단계 | 시험 | 준비물 | 통과 기준 |
|---|---|---|---|
| ① | 단위 시험 | PC만 | `54 tests, 0 errors` |
| ② | 가짜 모드 | PC + 브로커 | 도메인 102에서 `data: 88.0`이 계속 보임 |
| ③ | 실물 읽기 | pinky1 bringup + 터널 | `status`가 둘 다 `online`, `/pinky1/scan` 약 10 Hz |
| ④ | 명령 `goto` | ③ + Nav2 + 순찰 노드 | 로봇 쪽 `받음 = 중계`, **로봇이 이동** |

### ① 단위 시험 (1분 이내, 위험 없음)
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_mqtt_bridge && colcon test --packages-select cobot_mqtt_bridge
colcon test-result --verbose
```

### ② 가짜 모드 (로봇 없이, 터미널 4개)
실물 서비스·터널이 꺼져 있을 때만 하세요(같은 MQTT 주제를 씁니다). **모든 터미널에서 먼저** 입력:
```bash
source /opt/ros/jazzy/setup.bash; source ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/install/setup.bash
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
export P=~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/cobot_mqtt_bridge/config/mqtt_bridge.yaml
```
```bash
ROS_DOMAIN_ID=102 ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args --params-file $P -p robot:=pinky1 -p side:=pc -p duration_sec:=60.0      # 터미널 1: 관제 역할
ROS_DOMAIN_ID=101 ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args --params-file $P -p robot:=pinky1 -p side:=robot -p duration_sec:=60.0   # 터미널 2: 로봇 역할
ROS_DOMAIN_ID=101 ros2 topic pub -r 5 /battery/percent std_msgs/msg/Float32 "{data: 88.0}"                                                      # 터미널 3: 가짜 값
ROS_DOMAIN_ID=102 ros2 topic echo /pinky1/battery/percent                                                                                        # 터미널 4: 받는 쪽
```

### ③ 실물 읽기 (로봇은 움직이지 않음)
전제: pinky1에서 bringup이 켜져 있어야 합니다(로봇 기동은 직접).
```bash
# 1) [PC] 터널 열기 (서비스 미설치면: ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:1883:127.0.0.1:1883 pinky@192.168.45.21)
sudo systemctl start mqtt_bridge_tunnel
# 2) [PC → pinky1] 로봇 쪽 중계 켜기 (읽기 전용 서비스)
ssh -t pinky@192.168.45.21 'sudo systemctl start mqtt_bridge_robot'
# 3) [PC] 연결 확인: robot, pc 가 online (pc 는 4) 를 켠 뒤에 보임)
mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/pinky1/status/#' -v -W 5
```
```bash
# 4) [PC] 관제 쪽 켜기 (터미널 2개, 둘 다 먼저: 위 ②의 source·export 3줄 + export ROS_DOMAIN_ID=102)
ros2 launch cobot_mqtt_bridge mqtt_bridge.launch.xml pinky2:=false pinky3:=false     # 터미널 1
ros2 daemon stop; ros2 topic list --no-daemon; ros2 topic hz /pinky1/scan             # 터미널 2: 약 10 Hz
```
- 이 시험은 관제 쪽을 루프백 도메인 102에서 받습니다. 실제 관제 도메인 200에 내보내려면 `confirm_real_domain:=200`을 붙입니다.
- **launch는 관제 PC에서만 실행합니다.** 로봇(도메인 10)에서 실행하면 안전 규칙으로 거부됩니다.

### ④ 명령 `goto` (**로봇이 움직임** — 옆에서 전원을 끌 수 있는 사람이 지켜볼 때만)
서비스(읽기 전용)를 끄고, 양쪽 노드를 `enable_down`으로 직접 켭니다. 열 명령 토픽은 `patrol_cmd` 하나로 줄입니다. 터미널은 A(pinky1), B(PC), C(PC)입니다.

```bash
# 0) [PC] 한 번만: 제외 목록·보호 값 파일 만들고 pinky1 에 복사 (이 파일 없이 켜지 마세요)
cat > ~/mqtt_down_test.yaml <<'YAML'
"/**":
  ros__parameters:
    exclude_patterns: ["*/lane/*", "*/crossline/*", "/cmd_vel", "/goal_pose", "/initialpose", "/zone_manager/*"]
    watchdog_ms: 500.0
    max_linear: 0.15
    max_angular: 0.4
YAML
scp ~/mqtt_down_test.yaml pinky@192.168.45.21:~/
# 1) [PC] pinky1 서비스 끄기 (inactive 가 나와야 함. 겹쳐 켜면 서로 끊김)
ssh -t pinky@192.168.45.21 'sudo systemctl stop mqtt_bridge_robot; systemctl is-active mqtt_bridge_robot'
```
```bash
# 터미널 A (pinky1 에 ssh 접속 후, 켜 둠): 로봇 쪽
source /opt/ros/jazzy/setup.bash; source ~/cobot_navigation/install/setup.bash
export ROS_DOMAIN_ID=10 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///home/pinky/.ros/cyclonedds_robot.xml
ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args \
  --params-file ~/cobot_navigation/install/cobot_mqtt_bridge/share/cobot_mqtt_bridge/config/mqtt_bridge.yaml \
  --params-file ~/mqtt_down_test.yaml \
  -p robot:=pinky1 -p side:=robot -p enable_down:=true -p confirm_real_domain:=10 -r __node:=mqtt_bridge_pinky1_robot
```
```bash
# 터미널 B (PC, 켜 둠): 관제 쪽 — 도메인 200
source /opt/ros/jazzy/setup.bash; source ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/install/setup.bash
export ROS_DOMAIN_ID=200 CYCLONEDDS_URI=file:///home/jinho/.ros/cyclonedds_pc.xml
ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args \
  --params-file ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/install/cobot_mqtt_bridge/share/cobot_mqtt_bridge/config/mqtt_bridge.yaml \
  --params-file ~/mqtt_down_test.yaml \
  -p robot:=pinky1 -p side:=pc -p enable_down:=true -p confirm_real_domain:=200 -r __node:=mqtt_bridge_pinky1
```
```bash
# 확인: pc, robot 이 둘 다 online 이어야 다음으로
mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/pinky1/status/#' -v -W 3

# 터미널 C (PC): 명령 보내기 — 이름은 pinky1, 도메인 200
source /opt/ros/jazzy/setup.bash; source ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/install/setup.bash
export ROS_DOMAIN_ID=200 CYCLONEDDS_URI=file:///home/jinho/.ros/cyclonedds_pc.xml
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/cobot_pinky_patrol_cmd
python3 pinky_control_client.py pinky1 goto P1          # 정지: emergency_stop
```
- 통과: 터미널 A에 `robot down /patrol_cmd 받음 N 중계 N`(15초 주기), 로봇이 이동.
- 한 쪽이라도 꺼져 있으면 명령은 **조용히 사라지고** 클라이언트는 그래도 "전송 완료"라고 출력합니다. 위의 `online` 확인을 먼저 하세요.

### 끄기와 정리
```bash
# ④를 했다면 터미널 A, B 에서 Ctrl+C, 그다음 서비스 복구
ssh -t pinky@192.168.45.21 'sudo systemctl start mqtt_bridge_robot'     # 읽기 전용 서비스를 다시 켤 때
# 끄기 전체: 관제 launch/노드 Ctrl+C → 서비스 stop → 터널 stop
ssh -t pinky@192.168.45.21 'sudo systemctl stop mqtt_bridge_robot'; sudo systemctl stop mqtt_bridge_tunnel
pgrep -af "[m]qtt_bridge_node" || echo 없음                               # 남은 프로세스 확인
```
- 서비스로 켠 노드는 `kill`로 끄면 30초 뒤 다시 켜집니다. 서비스는 `systemctl stop`으로 끕니다.
- 정상 종료 뒤 브로커에 `offline` 기록이 남는 것은 정상입니다(보관 메시지 정리는 [`docs/usage.md` 3-D](docs/usage.md#3-d-끄기와-정리)).

## 4. 사용 예시

```bash
mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/pinky1/status/#' -v        # 연결 상태 (online/offline)
ros2 topic hz /pinky1/odom --no-daemon                                  # 약 30 Hz
ros2 topic echo /pinky1/battery/percent --once
ros2 launch cobot_mqtt_bridge mqtt_bridge.launch.xml                    # pinky1/2/3 모두 (3대 동시, 가짜 모드만 시험)
```
- 토픽 추가·리맵핑, 3대 동시 설정, 끊김 동작, 안전 규칙 전체: [`docs/usage.md` 4장](docs/usage.md#4-사용-예시).

**안전 규칙 요약**
- 명령(down)은 기본 꺼짐입니다. `enable_down:=true`를 줘야만 중계합니다.
- 실제 관제 도메인 200에 발행하려면 `confirm_real_domain:=200`, 로봇 도메인 10에 명령을 발행하려면 `confirm_real_domain:=10`과 `watchdog_ms`·`max_linear`·`max_angular` > 0이 필요합니다. 관제(pc) 역할은 도메인 10에 **항상 거부**됩니다.
- 시험은 가능한 한 가짜 도메인(101/102)이나 루프백에서 하고, 로봇이 움직이는 시험은 사람이 옆에서 지켜봅니다.
- 도메인 브릿지(DDS)와 이 브릿지를 같은 도메인에서 동시에 켜지 않습니다.

**자주 막히는 곳**

| 증상 | 원인과 해결 |
|---|---|
| `... 에 발행하려면 confirm_real_domain:=값 을 명시해야 한다` | 확인 인자 누락. `:=` 형식으로 추가 (`=` 아님) |
| `이미 발행자가 있는 토픽이 있어 중단한다` | 같은 도메인에 다른 발행자(예: 다른 팀 DDS 브릿지). 관제 쪽은 도메인 200 사용 |
| `status/robot`이 `offline` | 로봇 쪽 노드 미실행, 또는 서비스와 직접 실행이 겹침 |
| 전송 완료인데 로봇이 안 움직임 | 로봇 쪽 `받음` 숫자 확인. 이름은 `pinky1`, 도메인은 200 |
| `ros2 topic list`에 `/parameter_events`, `/rosout`만 | ros2 데몬이 옛 설정. `ros2 daemon stop` 또는 `--no-daemon` |
| `can't open configuration file ...cyclonedds_robot.xml` | PC 터미널의 `CYCLONEDDS_URI`가 pinky용. PC는 `cyclonedds_pc.xml` |
| `Error opening YAML file` | `~/mqtt_down_test.yaml` 없음 (④의 0단계) |
| 코드를 고쳤는데 반영 안 됨 | PC는 다시 빌드, pinky1은 복사 명령 다시 |

더 많은 증상: [`docs/usage.md` 문제 해결](docs/usage.md#문제-해결).

## 5. 환경변수 표

| 이름 | 값 예시 | 설명 |
|---|---|---|
| `ROS_DOMAIN_ID` | `200`(관제), `10`(로봇), `101`·`102`(시험) | 어느 ROS 도메인에서 실행할지. 값에 따라 발행 허용이 정해집니다(이 패키지가 코드에서 직접 읽는 유일한 환경변수) |
| `CYCLONEDDS_URI` | PC `file:///home/jinho/.ros/cyclonedds_pc.xml`, pinky1 `file:///home/pinky/.ros/cyclonedds_robot.xml`, 시험은 루프백 XML | DDS 네트워크 설정. 장비마다 다릅니다 |
| `RMW_IMPLEMENTATION` | `rmw_cyclonedds_cpp` | pinky1 직접 실행에서만 지정 |

**주요 파라미터** (`config/mqtt_bridge.yaml`, 실행할 때 `-p 이름:=값`으로 덮어씀. 숫자는 `500.0`처럼 소수점 형태)

| 이름 | 기본값 | 설명 |
|---|---|---|
| `robot`, `side` | (필수) | 로봇 이름(`pinky1`), 역할(`robot` 또는 `pc`) |
| `enable_down` | false | 관제→로봇 명령 중계 |
| `confirm_real_domain` | 빈 값 | 실제 도메인 발행 확인: 관제 `200`, 로봇 `10` |
| `pc_domain`, `robot_domain` | 200, 10 | 관제·로봇 도메인 번호 |
| `exclude_patterns` | lane, crossline | 제외할 토픽(fnmatch). 명령은 이것으로 최소한만 엽니다 |
| `watchdog_ms`, `max_linear`, `max_angular` | 0.0 | `cmd_vel` 보호. 도메인 10 명령 발행에는 셋 다 > 0 필요 |
| `rate_limits` | `/tf=30.0` | "토픽=Hz" 전송 상한 |
| `bridge_config` | 빈 값 | 토픽 목록 YAML. 비우면 `config/mqtt_topics_<robot>.yaml` |

전체 표: [`docs/usage.md` 5장](docs/usage.md#5-환경변수-표).

## 6. 프로젝트 구조
```
cobot_mqtt_bridge/
├── cobot_mqtt_bridge/      # 파이썬 소스: bridge_config, relay_utils, cmd_vel_guard, mqtt_bridge_node
├── config/                 # mqtt_bridge.yaml, mqtt_topics_pinky1~3.yaml, systemd 서비스 2개
├── launch/mqtt_bridge.launch.xml   # 관제 PC 쪽 실행
├── docs/                   # usage.md(상세 사용), mqtt_bridge_prd.md(계획·시험 결과)
├── test/                   # 단위 시험 + 린트
└── package.xml, setup.py, setup.cfg
```
검증용 원본 스크립트(학습·벤치마크)는 `scripts/spikes/mqtt/`에 있습니다.

## 7. 기여 방법
팀 규칙은 [`CLAUDE.md`](../../../CLAUDE.md)와 [`docs/fms_branch_workflow.md`](../../../docs/fms_branch_workflow.md)를 따릅니다.
1. 분야 브랜치(`feature/navigation`)에서 작업하고 `main`에 직접 push하지 않습니다. PR 대상은 `submaster`, 최소 1명 리뷰.
2. 고친 뒤 **빌드 → 테스트 → 린트**(위 ①)를 통과시킵니다.
3. 동작을 바꾸면 이 README와 `docs/`도 같은 PR에서 고칩니다. 커밋은 `feat(navigation): …` 형식.
4. 새 의존성, 메시지·서비스 변경, `ROS_DOMAIN_ID`·네트워크 설정 변경, 로봇을 움직이는 시험은 먼저 팀 허락을 받습니다.
5. [TODO] CODEOWNERS 지정 여부 미확인. 담당자: 김진호(`package.xml`).

## 8. 라이선스
Apache License 2.0 (`package.xml`과 소스 머리말 기준). [TODO] 저장소에 `LICENSE` 파일이 없어 전문은 없습니다.
