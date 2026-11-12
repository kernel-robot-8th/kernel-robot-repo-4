# MQTT 중계 스파이크

pinky1(도메인 10)과 관제 PC(도메인 100) 사이의 토픽 전달을 DDS `domain_bridge` 대신 MQTT 브로커로 할 수 있는지 확인하는 검증용 스크립트 모음입니다.

> 검증용 코드입니다. colcon 패키지가 아니고, 아직 실제 시스템에 포함하기로 결정된 것이 아닙니다. 현재는 **로봇→관제 방향만** 구현했고 관제→로봇(명령) 방향은 없습니다.

## 주요 기능

- **토픽 중계** (`core/mqtt_ros_relay.py`): ROS 토픽을 MQTT로 보내고(`ros2mqtt`), MQTT를 받아 ROS 토픽으로 내보냅니다(`mqtt2ros`). 전송 상한, 래치(`transient_local`) 토픽, MQTT 보관(retain)을 지원합니다.
- **토픽 전체 올리기** (`core/mqtt_bridge_check.py --role serve`): 브릿지 설정(`pinky_bridge_pinky1.yaml`)의 로봇→관제 토픽을 한꺼번에 올립니다. 원래 토픽 이름과 주기로 올릴 수 있습니다.
- **토픽 전체 점검** (`core/mqtt_bridge_check.py --role run`): 21개 토픽을 가짜 메시지로 보내 필드 값이 일치하는지 표로 확인합니다.
- **안전장치**: 시험 도메인(101/102)에서만 원래 이름으로 발행, 실제 도메인 100은 허용 토픽만 별도 옵션으로, 같은 이름의 발행자가 있으면 중단, pinky1 부하가 3.0을 넘으면 중단.
- **측정 도구** (`tools/`): DDS 브릿지와 MQTT의 지연·CPU·네트워크 사용량 비교, 왕복 시간 측정, ROS 없는 MQTT 송수신.

## 설치 방법

Ubuntu 24.04, ROS 2 Jazzy, `rmw_cyclonedds_cpp`가 이미 설치되어 있다고 가정합니다.

관제 PC:
```bash
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt python3-psutil python3-yaml
```
pinky1 (SSH 접속 후):
```bash
sudo apt install -y python3-paho-mqtt
```
- 시험에 쓴 버전은 mosquitto 2.0.18, python3-paho-mqtt 1.6.1입니다. 스크립트는 paho-mqtt 1.x의 콜백 방식을 씁니다. 2.x에서의 동작은 [TODO] 확인하지 않았습니다.
- `mqtt_bench_run.py`의 DDS 브릿지 경로는 `cobot_domain_bridge`가 빌드된 워크스페이스가 필요합니다.
- 브로커는 localhost에서만 듣도록 두고, pinky1은 SSH 역방향 터널로 연결합니다. 브로커 설정 파일 예시는 [TODO] 별도 문서화하지 않았습니다.

## 실행 방법

```bash
cd ~/dev_ws/kernel-robot-repo-4
source /opt/ros/jazzy/setup.bash

# 1) SSH 역방향 터널 (이미 열려 있으면 다시 열지 마세요)
ps -eo pid,cmd | grep "ssh.*-R 127.0.0.1:1883" | grep -v grep
ssh -f -N -o ExitOnForwardFailure=yes -R 127.0.0.1:1883:127.0.0.1:1883 pinky@192.168.45.21

# 2) 로봇→관제 토픽을 올림 (시험 도메인 102, 원래 이름)
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role serve --exact-names --serve-sec 300
```
pinky1에서는 직접 실행하지 않습니다. 스크립트가 ssh로 대신 띄웁니다.

## 사용 예시

배터리 하나를 올리고 확인하기:
```bash
# 터미널 1
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role serve --exact-names \
  --only /battery/percent --serve-sec 120

# 터미널 2 (시험 도메인 102는 loopback 설정이 필요)
export LO='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
export ROS_DOMAIN_ID=102 CYCLONEDDS_URI="$LO"
ros2 topic echo /pinky1/battery/percent
```

가짜 메시지로 21개 토픽 점검:
```bash
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role run --mode fake --out /tmp/check.json
```

DDS 브릿지와 MQTT 성능 비교(한 PC 안, 약 7분):
```bash
source src/cobot_navigation/install/setup.bash
python3 scripts/spikes/mqtt/tools/mqtt_bench_run.py --reps 3 --duration 8 \
  --only odom:30 laser:10 twist:20 --out /tmp/bench.json
```

더 자세한 설명(컨셉, 옵션, 실제 도메인 100 사용 시 주의, 문제 해결)은 [`docs/mqtt_guide.md`](docs/mqtt_guide.md)를 봅니다.

## 환경변수

스크립트가 직접 설정하거나 읽는 값입니다.

| 이름 | 용도 | 비고 |
|---|---|---|
| `ROS_DOMAIN_ID` | 중계가 참가할 ROS 도메인 | 중계는 이 값을 바꾸지 않고 시작 로그에 남깁니다. `serve`가 자식 프로세스에 101/102/100/10을 지정합니다. |
| `CYCLONEDDS_URI` | DDS 설정 | 시험 도메인은 loopback 전용 설정을 씁니다. 실제 도메인 100은 `~/.ros/cyclonedds_pc.xml`을 씁니다. |
| `RMW_IMPLEMENTATION` | RMW 선택 | pinky1에 ssh로 띄울 때 `rmw_cyclonedds_cpp`로 지정합니다. |
| `ROS_AUTOMATIC_DISCOVERY_RANGE`, `ROS_LOCALHOST_ONLY` | DDS 발견 범위 | 스크립트가 자식 프로세스에서 제거합니다(설정 파일이 우선하기 때문). |

브로커 주소와 포트는 환경변수가 아니라 `--host`, `--port`(기본 `127.0.0.1:1883`) 인자로 지정합니다.

## 프로젝트 구조

```
scripts/spikes/mqtt/
├── README.md
├── core/                       # 핵심: 브릿지 대체 기능
│   ├── mqtt_ros_relay.py       # 한 토픽 중계 (ROS ↔ MQTT)
│   └── mqtt_bridge_check.py    # 토픽 전체 올리기(serve) / 점검(run)
├── tools/                      # 사이드: 측정·학습 도구
│   ├── mqtt_bench_run.py       # 한 PC 안에서 DDS 브릿지 vs MQTT 비교
│   ├── mqtt_bench_stream.py    # 가짜 메시지 발행/수신 (위 도구가 사용)
│   ├── mqtt_bench_net.py       # pinky1 Wi-Fi 송신량 비교
│   ├── mqtt_bench_rtt.py       # 두 장비 사이 왕복 시간
│   ├── mqtt_pub.py             # MQTT 보내기 (ROS 없음)
│   └── mqtt_sub.py             # MQTT 받기 (ROS 없음)
└── docs/
    ├── mqtt_guide.md           # 사용 가이드 (컨셉, 기능, 실행)
    ├── mqtt_learning.md        # 단계별 실습 기록과 측정 결과
    └── [진행] mqtt_learning_prd.md   # 계획과 승인 범위
```

## 기여 방법

팀 규칙([`CLAUDE.md`](../../../CLAUDE.md))을 따릅니다.

1. 브랜치는 `feature/<역할>` 또는 `feature/<역할>-<내용>`에서 작업합니다. PR 대상은 `submaster`입니다.
2. 커밋 메시지는 Conventional Commits입니다. 예: `feat(navigation): MQTT 중계 스크립트 추가`
3. `scripts/`는 `colcon test`의 린트가 검사하지 않으므로 직접 돌립니다.
   ```bash
   source /opt/ros/jazzy/setup.bash
   ament_flake8 scripts/spikes
   ament_pep257 scripts/spikes
   ament_copyright scripts/spikes
   ```
4. 실제 로봇을 구동하는 코드·명령, `sudo`, 도메인·네트워크 설정 변경은 사용자 확인 후에만 실행합니다. 이 스크립트를 실제 도메인 100에서 쓸 때는 DDS 브릿지가 켜져 있지 않은지 먼저 확인합니다.
5. 코드를 바꾸면 관련 문서도 같은 PR에서 고칩니다.

## 라이선스

각 스크립트 파일 머리말에 `Apache License, Version 2.0`이 적혀 있습니다. 저장소 최상위에 `LICENSE` 파일은 없습니다. [TODO] 저장소 차원의 라이선스는 팀 확인이 필요합니다.
