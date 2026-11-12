# cobot_mqtt_bridge

관제 PC와 Pinky 로봇 사이의 ROS 2 토픽을 **MQTT로 중계**하는 패키지입니다. 기존 DDS 브릿지(`cobot_domain_bridge`)와 같은 기능을 하며, 둘 중 하나를 골라 씁니다.

> 계획·단계별 시험 결과는 [`docs/mqtt_bridge_prd.md`](docs/mqtt_bridge_prd.md)에 있습니다.

## 목차
1. [주요 기능](#1-주요-기능)
2. [설치 방법](#2-설치-방법)
3. [실행 방법](#3-실행-방법)
4. [사용 예시](#4-사용-예시)
5. [환경변수 표](#5-환경변수-표)
6. [프로젝트 구조](#6-프로젝트-구조)
7. [기여 방법](#7-기여-방법)
8. [라이선스](#8-라이선스)

---

## 1. 주요 기능

- **DDS 브릿지와 같은 토픽을 MQTT로 중계**: 토픽 목록·방향·이름은 이 패키지의 `config/mqtt_topics_pinkyN.yaml`(**MQTT 전용**)에서 읽습니다. 처음에는 DDS 브릿지 YAML을 복사해 시작했고, 그 뒤로는 따로 관리합니다. 여기를 고쳐도 DDS 브릿지에는 영향이 없습니다.
- **기존 코드 수정 없음**: `cobot_navigation` 노드는 그대로 두고, 관제와 로봇 사이의 전송 방식만 바뀝니다. 도메인 브릿지(`cobot_domain_bridge`)는 삭제·수정하지 않고 읽지도 않으며, 한 도메인에서 동시에 켜지 않습니다.
- **로봇 한 대당 프로세스 1개**(역할별): 로봇 쪽(`robot`)은 구독해서 MQTT로 보내고, 관제 쪽(`pc`)은 MQTT를 받아 원래 이름으로 발행합니다.
- **끊김 복구**: 자동 재접속, 상태 주제(`online`/`offline`), 비정상 종료 감지, 래치 토픽(`/tf_static`, `/amcl_pose`) 재발행.
- **명령(`cmd_vel` 등) 안전장치**: 기본 꺼짐. 켜도 속도 상한, 오래된 명령 폐기, 워치독, 끊김 즉시 정지, 실제 도메인 발행 확인 절차가 있습니다.
- **자동 시작(선택)**: 터널·로봇 쪽 중계용 systemd 서비스 파일 제공(`autossh` 불필요).

### 동작 방식 (그림)
```
 pinky1 (로봇)                      관제 PC
┌──────────────────┐             ┌──────────────────────────────┐
│ ROS 도메인 10     │             │  MQTT 브로커 (mosquitto)       │
│  /scan /odom ... │             │   127.0.0.1:1883 (PC 안에서만) │
│        │         │             │        ▲            │         │
│  robot 역할 노드 ─┼─ SSH 역방향 ─┼────────┘            ▼         │
│  (구독 전용)      │   터널       │   pc 역할 노드 ──▶ ROS 도메인   │
└──────────────────┘             │   (/pinky1/scan ...)          │
                                 └──────────────────────────────┘
```
- **MQTT 브로커**는 우체국 같은 중계 프로그램입니다. 보내는 쪽이 "주제"에 메시지를 올리면, 그 주제를 구독한 쪽이 받습니다. 브로커는 **관제 PC에만** 설치합니다.
- **SSH 역방향 터널**은 pinky1의 `127.0.0.1:1883` 포트를 PC의 브로커로 이어 주는 SSH 연결입니다. 덕분에 브로커 포트를 네트워크에 열지 않아도 됩니다.
- MQTT 주제 이름: `mqtt_bridge/<로봇>/<up|down>/<로봇 쪽 토픽>`(up: 로봇→관제, down: 관제→로봇), 상태는 `mqtt_bridge/<로봇>/status/<robot|pc>`.

### 현재 상태
| 항목 | 상태 |
|---|---|
| 로봇→관제(up) 중계 | 완료. pinky1 실물 10분 시험: 유실 0 |
| 관제→로봇(down, 명령) | 구현됨, **가짜 모드만 시험**. 기본 꺼짐 |
| 3대(pinky1/2/3) 동시 | 가짜 모드 10분 시험 통과. 실물은 pinky1만 시험 |
| 재접속·상태 주제 | 완료 (터널 끊김 후 약 10~15초에 복구) |
| 자동 시작(systemd) | 파일 작성·재부팅 시험 완료, 현재는 꺼 둠 |
| 실제 도메인 100/10 전환 | **보류** (다른 팀의 DDS 브릿지를 끌 수 있을 때까지) |

## 2. 설치 방법

처음 한 번만 하면 됩니다. `[PC]`는 관제 PC, `[pinky1]`은 로봇에서 하는 일입니다. 모든 명령은 복사해서 그대로 실행할 수 있습니다.

### 2-0. 준비물
- 관제 PC: Ubuntu 24.04, ROS 2 Jazzy, 이 저장소(`~/dev_ws/kernel-robot-repo-4`)
- pinky1: ROS 2 Jazzy가 설치되어 있고 SSH로 접속 가능 (`pinky@192.168.45.21`)
- 두 장비가 같은 네트워크에 있을 것
- [TODO] pinky1의 IP(`192.168.45.21`)가 바뀌면 이 문서 전체와 `config/mqtt_bridge_tunnel.service`를 함께 고쳐야 합니다. 고정 IP 또는 호스트 이름 사용 검토

### 2-1. [PC] MQTT 브로커와 파이썬 라이브러리 설치
```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt
```
| 패키지 | 무엇인가 |
|---|---|
| `mosquitto` | MQTT 브로커 (중계 서버) |
| `mosquitto-clients` | 확인용 도구 `mosquitto_sub`(듣기), `mosquitto_pub`(보내기) |
| `python3-paho-mqtt` | 파이썬 MQTT 라이브러리. 이 패키지는 **1.6.1**(Ubuntu 24.04 apt 기본)로 시험했습니다 |

- pip로 따로 설치하지 않습니다(시스템 파이썬 보호 규칙, PEP 668).
- [TODO] paho-mqtt 2.x에서의 동작은 시험하지 않았습니다.
- 작성 환경의 설치 버전: mosquitto 2.0.18, python3-paho-mqtt 1.6.1

### 2-2. [PC] 브로커가 잘 켜졌는지 확인
```bash
systemctl is-active mosquitto
ss -ltn | grep 1883
```
- 첫 줄은 `active`, 둘째 줄은 `127.0.0.1:1883`(그리고 `[::1]:1883`)만 보여야 합니다. 이것은 **PC 안에서만** 접속된다는 뜻이고, 정상입니다.
- 꺼져 있으면: `sudo systemctl enable --now mosquitto`

주고받기 시험(한 줄):
```bash
mosquitto_sub -h 127.0.0.1 -t test -W 3 -v & sleep 1; mosquitto_pub -h 127.0.0.1 -t test -m hello; wait
```
`test hello`가 출력되면 브로커가 동작하는 것입니다(뒤에 나오는 `Timed out`은 3초 듣기가 끝났다는 뜻이라 정상입니다).

> **브로커를 외부에 열지 마세요.** Mosquitto 2.x는 설정에 `listener`가 없으면 localhost에서만 받습니다. 이 프로젝트는 `/etc/mosquitto/mosquitto.conf` 기본값을 그대로 쓰며, 인증 없이 외부에 열면 같은 네트워크의 누구나 로봇 토픽을 보거나 보낼 수 있습니다.

### 2-3. [pinky1] 파이썬 라이브러리 확인
pinky1에는 브로커를 설치하지 않습니다. 라이브러리만 있으면 됩니다.
```bash
ssh pinky@192.168.45.21 'python3 -c "import paho.mqtt, yaml; print(\"ok\")"'
```
`ok`가 나오면 끝입니다(현재 pinky1에는 `python3-paho-mqtt 1.6.1`이 설치되어 있음). 에러가 나면:
```bash
ssh -t pinky@192.168.45.21 'sudo apt install -y python3-paho-mqtt python3-yaml'
```

### 2-4. [PC] SSH 키로 비밀번호 없이 접속되게 하기
터널 서비스와 시험이 비밀번호 입력 없이 pinky1에 접속해야 합니다.
```bash
ssh -o BatchMode=yes pinky@192.168.45.21 echo ok
```
`ok`가 나오면 이미 된 것입니다. 안 되면 아래를 한 번만 실행합니다(이미 키가 있으면 `ssh-keygen`은 건너뜁니다).
```bash
ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519
ssh-copy-id pinky@192.168.45.21
```

### 2-5. [PC] 이 패키지 빌드
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_mqtt_bridge
source install/setup.bash
```
- 빌드 위치는 `src/cobot_navigation`입니다(저장소 루트가 아님).
- 이 환경에서는 `--symlink-install`을 써도 파이썬 파일이 복사본으로 설치됩니다. **코드를 고친 뒤에는 항상 다시 빌드**하세요.

### 2-6. [pinky1] 코드 복사
pinky1에는 빌드 없이 코드만 복사해서 씁니다(약 80 KB). 토픽 목록 YAML(`config/mqtt_topics_pinky1.yaml`)도 이 폴더 안에 들어 있어서 한 번에 복사됩니다. PC에서 실행합니다.
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
tar --exclude=__pycache__ -cf - cobot_mqtt_bridge/cobot_mqtt_bridge cobot_mqtt_bridge/config \
  | ssh pinky@192.168.45.21 'mkdir -p ~/mqtt_bridge && tar -xf - -C ~/mqtt_bridge'
ssh pinky@192.168.45.21 'find ~/mqtt_bridge -name "*.py" -o -name "*.yaml"'
```
- 마지막 줄에 `mqtt_topics_pinky1.yaml`과 `.py` 파일들이 나오면 성공입니다. 코드나 토픽 목록을 고치면 같은 명령으로 다시 복사(덮어쓰기)합니다.
- 예전 방식(DDS YAML을 함께 복사하던 `~/mqtt_bridge/cobot_domain_bridge/`)으로 이미 설치했다면, 새 서비스 파일을 다시 설치하기 전까지는 그 폴더를 **지우지 마세요**(실행 중인 서비스가 씁니다). 새 서비스 설치 뒤에는 지워도 됩니다.
- 임시로만 쓰려면 `~/mqtt_bridge` 대신 `/tmp/mqtt_f0` 같은 임시 폴더를 쓰고 끝나면 지웁니다.

### 2-7. (선택) 자동 시작 서비스 설치
"켜고 끄는 것"을 한 줄 명령으로 하고 싶으면 설치합니다. 서비스는 설치만 하고 켜지 않습니다. **`sudo`가 필요해서 직접 실행**하세요.
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
scp cobot_mqtt_bridge/config/mqtt_bridge_robot.service pinky@192.168.45.21:/tmp/
sudo cp cobot_mqtt_bridge/config/mqtt_bridge_tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
ssh -t pinky@192.168.45.21 'sudo cp /tmp/mqtt_bridge_robot.service /etc/systemd/system/ && sudo systemctl daemon-reload'
```
설치되는 서비스:

| 파일 | 설치 위치 | 하는 일 |
|---|---|---|
| `mqtt_bridge_tunnel.service` | PC | SSH 역방향 터널 유지. 끊기면 systemd가 5초 뒤 다시 연결(`autossh` 불필요) |
| `mqtt_bridge_robot.service` | pinky1 | 로봇 쪽 중계(도메인 10, **구독 전용**). 터널이 아직 없으면 종료 코드 2로 끝나고 30초 뒤 다시 시도 |

- 로봇 서비스에는 `enable_down`, `confirm_real_domain`을 넣지 않았습니다. 명령 방향은 서비스로 켜지 않습니다.
- 서비스 설치 없이도 아래 3-B의 "직접 실행"으로 모두 쓸 수 있습니다.

## 3. 실행 방법

### 3-A. 로봇 없이 연습하기 (한 PC 안, 가짜 값)
로봇 없이 동작을 눈으로 확인합니다. **주의: 이 연습은 실물과 같은 브로커·같은 MQTT 주제(`mqtt_bridge/pinky1/...`)를 씁니다. 실물 서비스나 터널이 켜져 있을 때는 하지 마세요**(상태 주제가 서로 덮어써집니다). 시험 도메인 101(로봇 역할)과 102(관제 역할)를 쓰고, 다른 사람에게 영향이 없는 루프백 전용 DDS 설정을 씁니다. 터미널 4개를 엽니다. **모든 터미널에서 먼저** 아래 5줄을 입력합니다.
```bash
source /opt/ros/jazzy/setup.bash
source ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/install/setup.bash
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
export P=~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/cobot_mqtt_bridge/config/mqtt_bridge.yaml
```
그다음 터미널마다 하나씩 실행합니다.
```bash
# 터미널 1: 관제 역할 (60초 동안 실행)
ROS_DOMAIN_ID=102 ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args --params-file $P -p robot:=pinky1 -p side:=pc -p duration_sec:=60.0
```
```bash
# 터미널 2: 로봇 역할
ROS_DOMAIN_ID=101 ros2 run cobot_mqtt_bridge mqtt_bridge_node --ros-args --params-file $P -p robot:=pinky1 -p side:=robot -p duration_sec:=60.0
```
```bash
# 터미널 3: 가짜 배터리 값을 초당 5번 발행 (로봇 도메인 101)
ROS_DOMAIN_ID=101 ros2 topic pub -r 5 /battery/percent std_msgs/msg/Float32 "{data: 88.0}"
```
```bash
# 터미널 4: 관제 도메인 102 에서 받아지는지 확인 → data: 88.0 이 계속 보이면 성공
ROS_DOMAIN_ID=102 ros2 topic echo /pinky1/battery/percent
```
- 끝나면 터미널 3, 4를 Ctrl+C로 끄고, 남은 보관 메시지를 지웁니다([3-D](#3-d-끄기와-정리) 참고).

### 3-B. 실물 pinky1에서 읽어 보기 (직접 켜기)
**읽기 전용**입니다. 로봇은 움직이지 않고, 관제 쪽은 도메인 102(루프백)에서 받으므로 다른 팀의 도메인 100에 영향이 없습니다.
**전제:** 2장 설치가 끝났고, pinky1에서 로봇 기능(bringup)이 켜져 있어야 데이터가 나옵니다.

**1단계. [PC] 터널 열기**
```bash
sudo systemctl start mqtt_bridge_tunnel
```
서비스를 설치하지 않았다면 별도 터미널에서 아래를 실행하고 그대로 둡니다(Ctrl+C로 종료).
```bash
ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:1883:127.0.0.1:1883 pinky@192.168.45.21
```

**2단계. [pinky1] bringup 확인**
```bash
ssh pinky@192.168.45.21 'source /opt/ros/jazzy/setup.bash; ROS_DOMAIN_ID=10 ros2 node list'
```
`/sllidar_node`, `/pinky_bringup` 등이 보여야 합니다. 안 보이면 pinky1에서 bringup을 먼저 켜세요(로봇 기동은 직접 하세요).

**3단계. [pinky1] 로봇 쪽 중계 켜기** (둘 중 하나)
- (가) 서비스로:
  ```bash
  ssh -t pinky@192.168.45.21 'sudo systemctl start mqtt_bridge_robot'
  ```
- (나) 직접 실행 (pinky1에 ssh로 들어가 입력. Ctrl+C로 종료):
  ```bash
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=10 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///home/pinky/.ros/cyclonedds_robot.xml
  cd ~/mqtt_bridge
  PYTHONPATH=$HOME/mqtt_bridge/cobot_mqtt_bridge:$PYTHONPATH python3 -m cobot_mqtt_bridge.mqtt_bridge_node --ros-args \
    --params-file $HOME/mqtt_bridge/cobot_mqtt_bridge/config/mqtt_bridge.yaml \
    -p robot:=pinky1 -p side:=robot
  ```
- 서비스와 직접 실행을 **동시에 쓰지 마세요**(같은 일을 두 번 하게 됩니다).

**4단계. [PC] 연결 확인**
```bash
mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/pinky1/status/#' -v -W 5
```
`mqtt_bridge/pinky1/status/robot {"state": "online", ...}`이 보이면 연결된 것입니다. `offline`이면 [문제 해결](#문제-해결)을 보세요.

**5단계. [PC] 관제 쪽 켜기** — 터미널 2개. **두 터미널 모두 아래 `source`/`export` 4줄을 각각 입력**해야 합니다(한쪽만 하면 서로 안 보입니다).
```bash
source /opt/ros/jazzy/setup.bash
source ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation/install/setup.bash
export ROS_DOMAIN_ID=102
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
```
```bash
# 터미널 1: 관제 쪽 중계 (pinky1만. 켜 둔 채로 둠)
ros2 launch cobot_mqtt_bridge mqtt_bridge.launch.xml pinky2:=false pinky3:=false
```
```bash
# 터미널 2: 값 확인
ros2 daemon stop                 # 처음 한 번: 옛 설정으로 떠 있는 ros2 데몬 종료
ros2 topic list --no-daemon      # /pinky1/scan, /pinky1/odom ... 이 보여야 함
ros2 topic hz /pinky1/scan       # 약 10 Hz 가 나오면 성공 (Ctrl+C 로 종료)
ros2 topic echo /pinky1/battery/percent --once
```
- `ros2 topic list`와 `node list`는 ros2 데몬을 거치는데, 데몬이 옛 설정(네트워크용)으로 떠 있으면 `/parameter_events`, `/rosout`만 보입니다. 그래서 `ros2 daemon stop`을 하거나 `--no-daemon`을 붙입니다.

### 3-C. 서비스로 켜고 끄기 요약
| 목적 | PC (터널) | pinky1 (로봇 쪽 중계) |
|---|---|---|
| 지금만 켜기 | `sudo systemctl start mqtt_bridge_tunnel` | `ssh -t pinky@192.168.45.21 'sudo systemctl start mqtt_bridge_robot'` |
| 지금만 끄기 | `sudo systemctl stop mqtt_bridge_tunnel` | `ssh -t pinky@192.168.45.21 'sudo systemctl stop mqtt_bridge_robot'` |
| 부팅 때 자동 켜기 + 지금 켜기 | `sudo systemctl enable --now mqtt_bridge_tunnel` | `ssh -t pinky@192.168.45.21 'sudo systemctl enable --now mqtt_bridge_robot'` |
| 자동 켜기 해제 + 지금 끄기 | `sudo systemctl disable --now mqtt_bridge_tunnel` | `ssh -t pinky@192.168.45.21 'sudo systemctl disable --now mqtt_bridge_robot'` |
| 상태 보기 | `systemctl status mqtt_bridge_tunnel` | `ssh pinky@192.168.45.21 'systemctl status mqtt_bridge_robot'` |
| 로그 보기 | `journalctl -u mqtt_bridge_tunnel -n 30` | `ssh pinky@192.168.45.21 'journalctl -u mqtt_bridge_robot -n 30'` |

- 로봇 쪽 중계는 켜져 있는 동안 pinky1 CPU를 코어 1개의 약 18% 씁니다(실측). MQTT를 쓰기로 한 때에만 켜고, DDS 브릿지를 쓰는 때에는 끄는 것을 권장합니다.
- 시험 결과: 터널을 끊으면 약 6초 뒤 다시 열리고 약 7초 만에 `online`으로 복구, pinky1 재부팅 뒤 사람 개입 없이 중계가 재개되었습니다.
- 완전히 지우기: `disable --now` 후 `/etc/systemd/system/mqtt_bridge_*.service`와 pinky1의 `~/mqtt_bridge/`를 삭제하고 `sudo systemctl daemon-reload`.

### 3-D. 끄기와 정리
```bash
# 1) 관제 쪽 launch 터미널에서 Ctrl+C
# 2) 로봇 쪽 중계 끄기 (직접 실행했다면 그 터미널에서 Ctrl+C)
ssh -t pinky@192.168.45.21 'sudo systemctl stop mqtt_bridge_robot'
# 3) 터널 끄기 (수동 터널이면 그 터미널에서 Ctrl+C)
sudo systemctl stop mqtt_bridge_tunnel
# 4) 남은 프로세스가 없는지 확인 (둘 다 "없음"이 나와야 함)
pgrep -af "mqtt_bridge_node|ssh .*-R 127.0.0.1:1883" || echo "없음"
ssh pinky@192.168.45.21 'pgrep -af "[m]qtt_bridge_node" || echo 없음'
# 5) 브로커에 남은 보관(retain) 메시지 확인 (아무것도 안 나오면 깨끗함)
mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/#' --retained-only -v -W 3
```
정상 종료하면 `status/robot`, `status/pc`가 `offline`으로 바뀌어 **보관 메시지로 남습니다**(래치 토픽 `/tf_static` 등도 남음). 5)에서 나온 주제마다 지웁니다.
```bash
mosquitto_pub -h 127.0.0.1 -t mqtt_bridge/pinky1/status/robot -r -n
```
(주제 이름만 5)에서 나온 것으로 바꿔 반복)

### 3-E. launch 인자 (관제 PC 쪽)
```bash
ros2 launch cobot_mqtt_bridge mqtt_bridge.launch.xml pinky2:=false pinky3:=false
```
| 인자 | 기본값 | 설명 |
|---|---|---|
| `pinky1`, `pinky2`, `pinky3` | true | 실행할 로봇 (기존 `bridges.launch.xml`과 같은 이름) |
| `enable_down` | false | 관제→로봇(명령) 중계. [안전 규칙](#안전-규칙) 참고 |
| `confirm_real_domain` | unset | 실제 도메인 100에 발행하려면 `100` |
| `duration_sec` | 0.0 | 실행 시간 [s], 0이면 계속 |
| `host`, `port` | 127.0.0.1, 1883 | 브로커 |
| `params_file` | 설치된 `mqtt_bridge.yaml` | 파라미터 YAML |

- Ctrl+C(SIGINT)와 SIGTERM으로 정상 종료합니다. launch를 `kill -9`로 죽여도 노드는 `exit_on_parent_loss`로 0.4초 안에 스스로 종료합니다.
- 로봇 쪽 기동은 launch에 넣지 않았습니다. 3-B의 3단계(서비스 또는 직접 실행)를 씁니다.

### 3-F. 할 수 있는 시험 한눈에 보기

위에서 아래로 갈수록 준비물이 많고 위험도가 높습니다. 앞 단계가 통과한 뒤에 다음으로 갑니다.

| 단계 | 시험 | 준비물 | 방법 | 통과 기준 |
|---|---|---|---|---|
| 1 | 단위 시험 + 린트 | PC만 | 아래 명령 | `54 tests, 0 errors, 0 failures` |
| 2 | 가짜 모드 1대 | PC + 브로커 | 3-A | 도메인 102에서 `data: 88.0`이 계속 보임 |
| 3 | 가짜 모드 3대 동시 | PC + 브로커 (로봇 없음) | 3-A의 launch를 `pinky2:=false pinky3:=false` 없이 실행(3대 모두 켜짐). 한 PC에서 오래 돌릴 때는 `-p load_abort:=50.0` | 각 토픽 받음 = 중계, 유실 0 |
| 4 | 실물 pinky1 읽기 전용 | pinky1 + 터널 + bringup | 3-B | 요약 로그에서 받음 = 중계, `/scan` 약 10 Hz |
| 5 | 연결 끊김 복구 | 4단계 상태 + 서비스 | 터널을 끊고 `online` 복구까지 시간 확인 | 약 15초 안에 `online` |
| 6 | 재부팅 자동 재개 | 서비스 설치(2-7) | pinky1 재부팅 후 bringup만 실행 | 사람 개입 없이 중계 재개 |
| 7 | 명령(down) | 로봇 구동 | **보류**. 가짜 모드(도메인 101/102)에서만 시험됨 | 팀 승인 후 |

**1단계: 단위 시험 (로봇·브로커 필요 없음, 1분 이내)**
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_mqtt_bridge
colcon test --packages-select cobot_mqtt_bridge
colcon test-result --verbose
```
- 확인하는 것: 토픽 YAML 3개 파싱(21/18/18개)과 DDS 브릿지 YAML과의 독립, 전송 상한과 JSON 봉투, 도메인 가드, `cmd_vel` 보호(상한·오래된 메시지·워치독), launch 인자, 서비스 파일(`enable_down` 없음, 재시작 정책), flake8·pep257·copyright.
- 코드를 고친 뒤에는 **빌드를 먼저** 해야 합니다(설치본이 복사본이라 빌드 없이는 옛 코드로 시험됨).

**실행 중 확인할 값**
- 로그의 60초 요약: `요약 robot up /scan 받음 N 중계 N 버림 0 오류 0`에서 받음 = 중계, 오류 0이면 정상입니다. `/tf`는 30 Hz 상한 때문에 버림이 생기는 것이 정상입니다.
- 상태: `mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/pinky1/status/#' -v`에서 `online`.
- 속도: `ros2 topic hz /pinky1/scan` (먼저 `ros2 daemon stop`).

**추가 측정 도구** (`scripts/spikes/mqtt/`, 지연·트래픽·왕복 시간 측정): 사용법은 [`scripts/spikes/mqtt/README.md`](../../../scripts/spikes/mqtt/README.md)를 봅니다. 이 패키지의 실제 측정값은 pinky1 구간 평균 지연 odom 16 ms, scan 24 ms, MQTT 전체 트래픽 약 218 KB/s(그중 `/scan`이 약 84%)입니다.

## 4. 사용 예시

### 값 보기 (3-B 5단계 환경에서)
```bash
ros2 topic hz /pinky1/odom --no-daemon                       # 약 30 Hz
ros2 topic echo /pinky1/battery/percent --once
ros2 topic info -v /pinky1/scan --no-daemon                  # 타입과 QoS(RELIABLE) 확인
```

### 연결 상태 보기
```bash
mosquitto_sub -h 127.0.0.1 -t 'mqtt_bridge/pinky1/status/#' -v
```
`online`/`offline`이 바뀌는 것을 실시간으로 볼 수 있습니다. 로봇 쪽이 비정상 종료되면 브로커가 `offline (cause: will)`을 대신 올립니다.

### 토픽 추가·리맵핑 (MQTT 전용)
**어디에 쓰나:** `config/mqtt_topics_pinkyN.yaml`입니다. DDS 브릿지의 YAML이 아니라서 여기를 고쳐도 DDS 브릿지에는 영향이 없습니다.

항목 한 개를 쓰는 법: 키(맨 앞 토픽 이름)와 `remap`이 가리키는 쪽이 방향에 따라 다릅니다.

| 방향 | 키 (맨 앞 이름) | `remap` | `from_domain` → `to_domain` |
|---|---|---|---|
| 로봇 → 관제 (up) | **로봇 쪽** 이름 | **관제 쪽** 이름 | 10 → 100 |
| 관제 → 로봇 (down) | **관제 쪽** 이름 | **로봇 쪽** 이름 | 100 → 10 |

`remap`을 쓰지 않으면 양쪽 이름이 같습니다(예: `/zone_manager/*`).
```yaml
topics:
  # 로봇 → 관제: 로봇의 /my_status 를 관제의 /pinky1/my_status 로
  /my_status:
    type: std_msgs/msg/String
    from_domain: 10
    to_domain: 100
    remap: /pinky1/my_status

  # 관제 → 로봇: 관제의 /pinky1/my_cmd 를 로봇의 /my_cmd 로 (명령 방향은 enable_down 을 켜야 중계됨)
  /pinky1/my_cmd:
    type: std_msgs/msg/String
    from_domain: 100
    to_domain: 10
    remap: /my_cmd
```
**고친 뒤 반영 (양쪽이 같은 파일을 봐야 합니다. 한쪽만 바꾸면 에러 없이 조용히 중계가 안 됩니다):**
1. PC: `cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation && colcon build --packages-select cobot_mqtt_bridge`
2. pinky1: 2-6의 복사 명령을 다시 실행
3. 두 노드를 다시 시작(관제 launch는 Ctrl+C 후 재실행, 로봇은 `sudo systemctl restart mqtt_bridge_robot`)
4. 메시지 타입(`type`)이 양쪽 장비에 설치되어 있어야 합니다.

토픽을 빼고 싶으면 항목을 지우거나 `config/mqtt_bridge.yaml`의 `exclude_patterns`에 이름 패턴을 추가합니다. 주기를 낮추려면 `rate_limits`에 `"/scan=5.0"`처럼 적습니다.
영상(카메라) 같은 큰 데이터는 JSON으로 보내면 원래 크기의 10배 이상이 되므로 추가하기 전에 먼저 상의하세요. [TODO]

### 3대 동시
```bash
ros2 launch cobot_mqtt_bridge mqtt_bridge.launch.xml          # pinky1/2/3 모두 (기본)
```
- 로봇마다 자기 터널(PC → 해당 로봇)과 로봇 쪽 중계가 필요합니다. 포함된 서비스 파일은 pinky1용이라 pinky2·3은 주소와 로봇 이름(`-p robot:=`, 브릿지 YAML 경로)을 바꾼 사본이 필요합니다. 3대 동시는 가짜 모드에서만 시험했습니다.
- `/zone_manager/*` 같은 공용 토픽은 로봇별 MQTT 주제로 올라가 관제에서 같은 이름으로 합쳐집니다. 관제→로봇 공용 토픽(`grant_entry`, `queue_slot`)은 모든 로봇에 내려가고 로봇 쪽이 메시지 안의 `robot_id`로 걸러냅니다(DDS 브릿지와 같은 동작).

### 연결이 끊겼을 때
- 브로커 연결이 끊기면 자동으로 재접속하고, 구독을 다시 걸고, 래치 토픽의 마지막 값을 다시 올립니다.
- 재접속 대기는 1초에서 시작해 실패할 때마다 두 배로 늘어나 최대 30초까지 갑니다. 그래서 끊긴 시간이 길수록 연결이 다시 열린 뒤 복구까지 최대 30초 걸릴 수 있습니다(터널 시험: 10~15초). [TODO] 현장에서 자주 끊기면 5~10초로 낮추는 것을 검토
- 끊긴 동안 쌓인 상태(up) 메시지는 복구하지 않습니다(최신 값만 의미가 있음). 래치 토픽만 다시 올립니다.
- 끊긴 동안 명령(down)은 버리고, 로봇 역할은 끊긴 순간 `cmd_vel`에 0 속도를 한 번 발행합니다.
- 첫 접속에 실패하면 재시도하지 않고 종료 코드 2로 끝납니다(서비스는 systemd가 다시 시도).

### 안전 규칙
이 패키지는 실제 로봇이 움직일 수 있어서 기본이 모두 "꺼짐"입니다.

| 규칙 | 내용 |
|---|---|
| 명령 방향 기본 꺼짐 | `enable_down:=true`를 줘야만 관제→로봇 토픽을 중계합니다 |
| 관제(pc) 역할이 발행할 수 있는 도메인 | 101·102(시험)는 허용. 도메인 100은 `confirm_real_domain:=100`과 기존 발행자 검사를 통과해야 함. 도메인 10은 **항상 거부** |
| 로봇(robot) 역할이 명령을 발행할 수 있는 도메인 | 101·102(시험)는 허용. 도메인 10은 `confirm_real_domain:=10`이고 `watchdog_ms`·`max_linear`·`max_angular`가 **모두 0보다 클 때만** 시작. 그 밖은 거부 |
| `cmd_vel` 보호 | 속도 상한 초과 시 방향 유지한 채 줄임, 오래된 메시지 폐기(`max_age_ms`), 워치독(마지막 명령 뒤 `watchdog_ms` 후 0 속도 1회), 종료 시 0 속도 |
| 부하 보호 | 로봇 역할은 1분 load가 `load_abort`(3.0)를 넘으면 스스로 중단 |
| 다른 팀과 겹침 방지 | 다른 팀이 도메인 100에서 DDS 브릿지를 쓰므로, 시험은 루프백 격리 또는 도메인 101/102에서만 합니다 |

- 구독 전용(`enable_down` 꺼짐)인 로봇 역할은 ROS에 아무것도 발행하지 않아 도메인 10에서 실행해도 로봇이 움직이지 않습니다.
- 도메인 브릿지(DDS)와 이 브릿지를 **같은 도메인에서 동시에** 켜지 않습니다(같은 이름을 이중 발행).
- [TODO] 보호 값(`watchdog_ms` 등)의 실제 기준은 팀이 정합니다. 시험 값은 실행할 때 `-p`로 넣습니다.

### 문제 해결
| 증상 | 원인과 조치 |
|---|---|
| `브로커에 닿지 않음 ... Connection refused`, 종료 코드 2 | 터널이 안 열려 있거나 브로커가 꺼짐. PC에서 `systemctl is-active mosquitto`와 터널 서비스 상태 확인. pinky1에서 `ss -ltn \| grep 1883`로 포트가 열려 있는지 확인 |
| 터널 서비스가 계속 재시작 | pinky1 포트 1883을 이전 터널이 아직 잡고 있음(`ExitOnForwardFailure`). 수십 초 기다리면 풀림. 계속되면 `journalctl -u mqtt_bridge_tunnel -n 30` |
| `Permission denied` / 비밀번호 요구 | 2-4의 SSH 키 설정 필요 |
| `ModuleNotFoundError: paho` | 해당 장비에서 `sudo apt install python3-paho-mqtt` |
| `ModuleNotFoundError: ament_index_python` (pinky1) | `source /opt/ros/jazzy/setup.bash`를 먼저 하고, `PYTHONPATH`는 덮어쓰지 말고 `...:$PYTHONPATH`로 뒤에 붙임 |
| `ROS_DOMAIN_ID=... 에서는 발행하지 않는다` | 안전 규칙에 걸림. 시험은 101·102 또는 루프백 격리에서. 도메인 100/10은 승인 절차 필요 |
| `ros2 topic list`에 `/parameter_events`, `/rosout`만 보임 (`echo $CYCLONEDDS_URI`는 루프백이 맞는데도) | **ros2 데몬이 옛 설정으로 떠 있음.** `ros2 daemon stop` 후 다시 실행하거나 `--no-daemon`을 붙임. `ps -eo cmd \| grep ros2-daemon`으로 확인 |
| 같은 증상, 데몬이 원인이 아닐 때 | 보는 터미널의 `CYCLONEDDS_URI`가 루프백이 아님(이 PC 기본값은 네트워크용). launch를 띄운 터미널과 보는 터미널 **둘 다** 3-B 5단계의 `source`·`export`를 입력. `echo $CYCLONEDDS_URI`로 확인 |
| `online`은 보이는데 관제에 토픽이 없음 | 관제 쪽 launch가 안 떠 있음. `pgrep -af mqtt_bridge_node`로 확인 |
| 토픽 이름은 보이는데 `ros2 topic hz`에 값이 없음 | pinky1 bringup이 꺼져 있음. 3-B 2단계로 `sllidar_node`가 있는지 확인 |
| 서비스가 켜져 있는데 `status/robot`이 `offline` | 이전 정지 기록이 남았거나 직접 실행과 서비스를 겹쳐 돌린 경우. 하나만 쓰고 `ssh -t pinky@192.168.45.21 'sudo systemctl restart mqtt_bridge_robot'`로 새로 고침 |
| `1분 load ... 한계를 넘어 중단` | pinky1 또는 시험 PC 부하가 `load_abort`(3.0)를 넘음. 서비스는 30초 뒤 다시 시도. 시험 PC 한 대에서 여러 개를 한꺼번에 돌릴 때만 `-p load_abort:=50.0` |
| 이전 시험의 `offline`/값이 보임 | 브로커의 보관(retain) 메시지. 3-D대로 지움 |
| 코드를 고쳤는데 반영 안 됨 | PC는 `colcon build` 다시, pinky1은 2-6 복사 다시 |
| 노드가 남아 있음 | `pgrep -af mqtt_bridge_node`로 찾아 종료 |

## 5. 환경변수 표

### 환경변수
이 패키지가 코드에서 직접 읽는 환경변수는 `ROS_DOMAIN_ID` 하나입니다(안전 검사와 시작 로그). 나머지는 ROS 2/DDS가 읽는 값으로, 이 문서의 명령에서 설정합니다.

| 이름 | 누가 읽나 | 값 예시 | 설명 |
|---|---|---|---|
| `ROS_DOMAIN_ID` | 이 패키지, ROS 2 | `101`, `102`(시험), `10`(로봇), `100`(관제 실제) | 어느 ROS 도메인에서 실행할지. 값에 따라 발행 허용 여부가 정해집니다(안전 규칙). 이 PC의 기본값은 `100`입니다 |
| `CYCLONEDDS_URI` | CycloneDDS | 루프백 XML(3-A, 3-B), PC 기본 `file:///home/jinho/.ros/cyclonedds_pc.xml`, pinky1 `file:///home/pinky/.ros/cyclonedds_robot.xml` | DDS 네트워크 설정. 시험에서는 루프백(`lo`)으로 묶어 다른 장비에 안 보이게 합니다 |
| `RMW_IMPLEMENTATION` | ROS 2 | `rmw_cyclonedds_cpp` | DDS 구현체. pinky1 직접 실행에서만 지정 |
| `PYTHONPATH` | 파이썬 | `$HOME/mqtt_bridge/cobot_mqtt_bridge:$PYTHONPATH` | pinky1에서 빌드 없이 실행할 때만. 기존 값 **뒤에** 붙여야 합니다 |
| `PYTHONUNBUFFERED` | 파이썬 | `1` | 서비스 로그가 바로 보이도록 서비스 파일에만 설정 |

### ROS 파라미터 (`config/mqtt_bridge.yaml`)
최상위 키가 `/**`라서 launch가 붙이는 노드 이름에도 그대로 적용됩니다. 시험 값은 `-p 이름:=값`으로 덮어씁니다(숫자는 `500.0`처럼 소수점 형태).

| 이름 | 기본값 | 설명 |
|---|---|---|
| `robot` | (필수) | 로봇 이름, 예 `pinky1` |
| `side` | (필수) | `robot` 또는 `pc` |
| `bridge_config` | 빈 값 | 토픽 목록 YAML 경로. 비우면 이 패키지의 `config/mqtt_topics_<robot>.yaml`(설치본이 없으면 코드 옆 `config/`) |
| `host`, `port` | 127.0.0.1, 1883 | 브로커 |
| `keepalive_sec` | 30 | MQTT keepalive |
| `topic_prefix` | `mqtt_bridge` | MQTT 주제 앞부분 |
| `pc_domain`, `robot_domain` | 100, 10 | 관제/로봇 도메인 번호(방향 판별과 안전 검사에 사용) |
| `exclude_patterns` | lane, crossline | 제외할 토픽 (fnmatch) |
| `latched_topics` | `/tf_static`, `/amcl_pose` | ROS transient_local + MQTT retain |
| `rate_limits` | `/tf=30.0` | "토픽=Hz". 적지 않은 토픽은 원래 주기. [TODO] 측정 후 조정 |
| `load_abort`, `load_check_sec` | 3.0, 15.0 | 로봇 역할: 1분 load가 넘으면 스스로 중단 / 확인 주기 |
| `summary_sec` | 60.0 | 토픽별 통계 로그 주기 |
| `duration_sec` | 0.0 | 0이면 계속 실행 |
| `discovery_wait_sec` | 3.0 | 실제 도메인에서 기존 발행자를 확인하기 전 대기 |
| `confirm_real_domain` | 빈 값 | 실제 도메인에 발행하려면 pc 역할은 `100`, 로봇 역할(명령)은 `10` |
| `enable_down` | false | 관제→로봇 명령 중계. 로봇이 움직일 수 있어 기본 꺼짐 |
| `cmd_vel_topics` | `/cmd_vel` | 속도 보호를 거치는 토픽(로봇 쪽 이름) |
| `watchdog_ms` | 0.0 | 마지막 `cmd_vel` 뒤 이 시간이 지나면 0 속도 1회 발행. 0이면 꺼짐 |
| `max_linear`, `max_angular` | 0.0 | `cmd_vel` 선속도 [m/s]·각속도 [rad/s] 상한. 0이면 제한 없음 |
| `max_age_ms` | 0.0 | 이보다 오래된 `cmd_vel` 폐기. 두 장비 시계를 맞춘 뒤에만 사용(pinky1은 부팅 직후 시계가 틀려 있다가 맞춰짐) |
| `reconnect_min_sec`, `reconnect_max_sec` | 1.0, 30.0 | 접속 뒤 연결이 끊겼을 때 재접속 대기(실패할수록 두 배) |
| `exit_on_parent_loss` | false | 부모 프로세스(launch)가 사라지면 스스로 종료. launch가 true로 켬 |

## 6. 프로젝트 구조
```
cobot_mqtt_bridge/
├── cobot_mqtt_bridge/
│   ├── bridge_config.py     # YAML → 중계 규칙 (순수 로직)
│   ├── relay_utils.py       # 전송 상한, JSON 봉투, 도메인 가드 (순수 로직)
│   ├── cmd_vel_guard.py     # 속도 상한, 오래된 메시지, 워치독 (순수 로직)
│   └── mqtt_bridge_node.py  # 노드 진입점 (로봇당 1프로세스, 역할별) — 실행 파일 mqtt_bridge_node
├── config/
│   ├── mqtt_bridge.yaml             # 노드 파라미터
│   ├── mqtt_topics_pinky1.yaml      # MQTT 전용 토픽 목록 (로봇별, DDS YAML 과 별개)
│   ├── mqtt_topics_pinky2.yaml
│   ├── mqtt_topics_pinky3.yaml
│   ├── mqtt_bridge_tunnel.service   # PC 터널 서비스 (systemd)
│   └── mqtt_bridge_robot.service    # pinky1 로봇 쪽 서비스 (systemd)
├── launch/mqtt_bridge.launch.xml    # 관제 PC 쪽 실행
├── docs/mqtt_bridge_prd.md          # 계획·시험 절차·결과
├── test/                            # 단위 시험 + 린트
├── package.xml
├── setup.py
└── setup.cfg
```
- `cobot_domain_bridge`의 파일은 읽지 않습니다(launch 인자 이름을 맞추는 시험만 그 launch 파일을 읽기 전용으로 비교).
- 검증용 원본 스크립트(학습·벤치마크)는 `scripts/spikes/mqtt/`에 있습니다.

시험 실행:
```bash
cd ~/dev_ws/kernel-robot-repo-4/src/cobot_navigation
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_mqtt_bridge
colcon test --packages-select cobot_mqtt_bridge
colcon test-result --verbose
```
54개(토픽 YAML 파싱, 전송 상한, JSON 봉투, 도메인 가드, `cmd_vel` 보호, launch 파일, 서비스 파일)와 린트(flake8, pep257, copyright)가 모두 통과합니다. 실물·장시간 시험 결과는 PRD의 단계별 결과 표에 있습니다.

## 7. 기여 방법

팀 공통 규칙은 저장소 루트의 [`CLAUDE.md`](../../../CLAUDE.md)와 [`docs/fms_branch_workflow.md`](../../../docs/fms_branch_workflow.md)를 따릅니다.

1. 분야 브랜치(`feature/navigation` 등)에서 작업합니다. 새 분야 브랜치는 최신 `submaster`에서 시작하고, `main`에 직접 push하지 않습니다.
2. 코드를 고쳤다면 **빌드 → 테스트 → 린트**를 모두 통과시킵니다(위 "시험 실행").
3. 코드나 동작을 바꾸면 이 README와 `docs/mqtt_bridge_prd.md`도 **같은 PR에서** 고칩니다.
4. 커밋 메시지는 Conventional Commits에 패키지 이름(scope)을 씁니다. 예: `feat(navigation): …`, `docs(navigation): …`
5. PR 대상은 `submaster`이며 최소 1명의 리뷰가 필요합니다.
6. 새 의존성 추가, 메시지/서비스/액션 변경, `ROS_DOMAIN_ID`·네트워크 설정 변경, 실제 로봇을 움직이는 시험은 먼저 팀의 허락을 받습니다.
7. [TODO] 이 패키지의 CODEOWNERS 지정 여부는 확인하지 않았습니다. 담당자: 김진호(`package.xml`의 maintainer)

## 8. 라이선스

Apache License 2.0 (`package.xml`의 `license`와 소스 파일 머리말의 `Copyright 2026 Pinky_Team4` 기준).
[TODO] 저장소에 `LICENSE` 파일이 없어 전문은 첨부되어 있지 않습니다. 추가 여부는 팀에서 정합니다.
