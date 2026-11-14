# MQTT 중계 가이드 (쉬운 버전)

도메인 브릿지(DDS)를 MQTT로 바꿀 수 있는지 확인하려고 만든 스크립트들의 **컨셉, 기능, 실행 방법**을 정리했습니다.
왜 이렇게 판단했는지(측정 결과)는 [`mqtt_learning.md`](mqtt_learning.md)에 있습니다.

> 이 스크립트들은 **검증용**입니다. colcon 패키지가 아니고, 아직 실제 시스템에 들어가는 코드가 아닙니다.

---

## 1. 컨셉: 무엇을 하려는 건가

로봇(pinky1)과 관제 PC는 ROS 도메인이 서로 다릅니다. (로봇 10, 관제 100)
지금은 **domain_bridge**가 두 도메인 사이에서 토픽을 옮겨 줍니다.
이 스크립트들은 그 일을 **MQTT 브로커**를 거쳐서 하게 만듭니다.

```
지금 (DDS 브릿지)
  [pinky1 도메인 10] ── domain_bridge ── [관제 PC 도메인 100]

MQTT 방식
  [pinky1 도메인 10] → 중계(ros2mqtt) → MQTT 브로커 → 중계(mqtt2ros) → [관제 PC 도메인 100]
```

- 도메인은 **그대로 나눠 둡니다.** MQTT는 도메인을 합치는 게 아니라, 두 도메인 사이의 다리를 바꾸는 것입니다.
- 관제 쪽 기존 코드는 **원래 토픽 이름과 주기 그대로** 받을 수 있게 하는 것이 목표입니다. (예: `/pinky1/odom`)
- 브릿지와 MQTT 중계를 **동시에** 켜면 같은 토픽이 두 번 발행됩니다. 둘 중 하나만 씁니다.

### 지금까지 알아낸 것 (요약)
| 항목 | 결과 |
|---|---|
| 로봇→관제 방향 | 원래 이름·주기로 유실 없이 가능 (배터리, `/odom` 30Hz, `/scan` 10Hz 확인) |
| 지연 | DDS 브릿지보다 약 2~3 ms 김 |
| CPU | DDS 브릿지의 약 8~11배 (그래도 pinky1에서 감당 가능) |
| 네트워크 사용량 | 줄지 않음 (빠른 토픽은 오히려 늘 수 있음) |
| 관제→로봇(명령) 방향 | **아직 안 만듦** |

그래서 MQTT의 장점은 성능이 아니라 **구조**(브로커 한 곳으로 모으기)에 있습니다.

---

## 2. 파일 구성

```
scripts/spikes/mqtt/
├── core/    핵심: 브릿지를 대체하는 기능
│   ├── mqtt_ros_relay.py      중계 본체 (ROS 토픽 ↔ MQTT)
│   └── mqtt_bridge_check.py   토픽 전체를 올리고(serve) 점검하는(run) 실행기
├── tools/   사이드: 측정·학습 도구
│   ├── mqtt_bench_run.py      한 PC 안에서 DDS 브릿지와 MQTT 비교
│   ├── mqtt_bench_stream.py   가짜 메시지 발행/수신 (위 도구가 사용)
│   ├── mqtt_bench_net.py      pinky1의 Wi-Fi 송신량 비교
│   ├── mqtt_bench_rtt.py      두 장비 사이 왕복 시간
│   ├── mqtt_pub.py            MQTT 보내기 (ROS 없이, 학습용)
│   └── mqtt_sub.py            MQTT 받기 (ROS 없이, 학습용)
└── docs/    문서
```

---

## 3. 기능

### core
| 기능 | 어디에 | 설명 |
|---|---|---|
| 한 토픽 중계 | `mqtt_ros_relay.py` | `ros2mqtt`(읽어서 MQTT로) / `mqtt2ros`(받아서 ROS로). 전송 상한, 래치 토픽 지원 |
| 토픽 전체 올리기 | `mqtt_bridge_check.py --role serve` | 브릿지 설정 파일의 로봇→관제 토픽을 한꺼번에 올려 둠 |
| 토픽 전체 점검 | `mqtt_bridge_check.py --role run` | 가짜 메시지로 21개 토픽의 이름·타입·값이 맞는지 확인 |

### 안전장치 (실수로 로봇에 영향을 주지 않게)
- 기본으로는 `/mqtt_test/` 이름으로만 발행합니다. 원래 이름으로 내보내려면 옵션을 명시해야 합니다.
- 원래 이름 발행(`--exact-names`)은 **시험 도메인 101/102에서만** 됩니다.
- 실제 관제 도메인 100은 `--real-domain 100`으로만 열리고, **허용된 토픽만** 올라갑니다. (배터리, `patrol_status`, `battery_state`, `zone_manager/*`, 그리고 `--include-fast`/`--include-latched`를 줄 때 `odom`, `scan`, `tf_static`)
- 시작 전에 도메인 100에 **같은 이름의 발행자가 이미 있으면 중단**합니다. (DDS 브릿지가 켜져 있을 때)
- pinky1은 도메인 10을 **구독만** 합니다. 명령 토픽은 건드리지 않습니다.
- 실행 중 pinky1 부하(load)가 3.0을 넘으면 스스로 멈춥니다.

---

## 4. 준비 (한 번만)

| 필요한 것 | 확인 |
|---|---|
| 관제 PC에 mosquitto 브로커가 떠 있음 (localhost 전용) | `systemctl is-active mosquitto` → `active` |
| pinky1에서 관제 PC의 브로커로 가는 **SSH 역방향 터널** | 아래 확인 명령 |
| pinky1에 `python3-paho-mqtt` 설치됨 | 설치 완료 |
| ROS 환경 | `source /opt/ros/jazzy/setup.bash` |

터널 확인과 열기:
```bash
ps -eo pid,cmd | grep "ssh.*-R 127.0.0.1:1883" | grep -v grep   # 한 줄 나오면 열려 있음
ssh -f -N -o ExitOnForwardFailure=yes -R 127.0.0.1:1883:127.0.0.1:1883 pinky@192.168.45.21
```
- 이미 열려 있으면 다시 열지 마세요. (`remote port forwarding failed`가 납니다)
- 프로세스는 있는데 pinky1에서 접속이 안 되는 **죽은 터널**일 수 있습니다. 그러면 `kill <PID>` 후 다시 엽니다.

---

## 5. 실행 방법

모든 명령은 저장소 루트(`~/dev_ws/kernel-robot-repo-4`)에서 실행합니다. **pinky1에서는 아무것도 치지 않습니다.** 스크립트가 ssh로 대신 띄웁니다.

### 5-1. 가장 간단한 확인: 배터리 하나 (시험 도메인 102, 안전)

터미널 1 — 올리기:
```bash
source /opt/ros/jazzy/setup.bash
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role serve --exact-names \
  --only /battery/percent --serve-sec 120
```
`pinky1 부하 ...` 로그가 나올 때까지(약 15초) 기다립니다.

터미널 2 — 확인 (**시험 도메인 102는 loopback 설정이 필요합니다**):
```bash
export LO='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
export ROS_DOMAIN_ID=102 CYCLONEDDS_URI="$LO"
ros2 topic echo /pinky1/battery/percent
```
값이 약 6초마다 나오면 성공입니다. (`pinky_bringup`이 켜져 있어야 값이 있습니다)

### 5-2. 로봇→관제 토픽 전부 올리기 (시험 도메인 102)
```bash
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role serve --exact-names --serve-sec 300
```
확인 터미널(위와 같은 `export` 3줄 후):
```bash
ros2 topic list
```
`/pinky1/...`, `/zone_manager/...` 이름이 보입니다. **그 토픽을 내는 노드가 꺼져 있으면 이름만 뜨고 값은 안 옵니다.**

옵션:
| 옵션 | 뜻 |
|---|---|
| `--serve-sec N` | N초 동안 유지 (기본 600) |
| `--serve-rate-hz N` | 토픽당 전송 상한 (기본 5Hz) |
| `--only /토픽 ...` | 지정한 토픽만 |
| `--include-latched` | 래치 토픽(`/amcl_pose`, `/tf_static`)도 올림 |

### 5-3. 실제 관제 도메인 100에 올리기 (주의)

**먼저 이것을 확인하세요.**
- 도메인 100에서 DDS 브릿지를 쓰는 사람이 없는지. 있으면 이 단계를 하지 마세요. (시작 전 점검이 막아 주지만, 먼저 확인하는 게 맞습니다)
- 확인할 터미널에서 `echo "$CYCLONEDDS_URI" | cut -c1-30`이 `<CycloneDDS>`로 시작하면 loopback 설정이 남은 겁니다. 새 터미널을 열거나 `export CYCLONEDDS_URI=file:///home/$USER/.ros/cyclonedds_pc.xml`로 되돌립니다.

```bash
# 느린 토픽 7개
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role serve --real-domain 100 --serve-sec 300
# 위 + /odom, /scan 을 원래 주기로 (--fast-rate-hz 0 = 제한 없음, 최대 30)
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role serve --real-domain 100 \
  --include-fast --fast-rate-hz 0 --serve-sec 300
```
확인:
```bash
ROS_DOMAIN_ID=100 ros2 topic echo /pinky1/battery/percent
```
끝날 때 로그의 `요약`에서 토픽마다 `src 중계`와 `dst 받음`이 **같으면 유실이 없는 것**입니다. 5% 넘게 모자라면 `유실 경고`가 나옵니다.

### 5-4. 토픽 21개를 가짜 메시지로 점검 (로봇 영향 없음)
```bash
python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role run --mode fake --out /tmp/check.json
```
토픽 이름·타입은 그대로, 내용만 가짜인 메시지를 시험 도메인에서 보내 값이 필드마다 일치하는지 표로 보여 줍니다. 수 분 걸립니다. 명령 토픽 6개도 이 방식으로만 확인하며 실제 `/cmd_vel` 등에는 가지 않습니다.

### 5-5. 성능 비교 (tools)
```bash
source /opt/ros/jazzy/setup.bash
source src/cobot_navigation/install/setup.bash        # DDS 브릿지(domain_bridge)를 쓰는 경로용
python3 scripts/spikes/mqtt/tools/mqtt_bench_run.py --reps 3 --duration 8 \
  --only odom:30 laser:10 twist:20 --out /tmp/bench.json
```
한 PC 안(도메인 101→102, loopback)에서 직접 / DDS 브릿지 / MQTT QoS0 / MQTT QoS1의 지연, 수신율, CPU를 비교합니다. 약 7분 걸립니다.

### 5-6. MQTT만 만져 보기 (ROS 없이)
```bash
mosquitto_sub -h 127.0.0.1 -t 'mqtt_learning/#' -v -C 3 -W 20      # 지나가는 메시지 보기
python3 scripts/spikes/mqtt/tools/mqtt_pub.py --count 10 --qos 1
python3 scripts/spikes/mqtt/tools/mqtt_sub.py --count 10 --qos 1
```

---

## 6. 끝난 뒤
- `serve`는 시간이 지나면 pinky1 쪽까지 스스로 정리합니다. `Ctrl+C`로 끝내도 같습니다.
- 래치 토픽을 올렸다면 브로커의 보관 메시지도 `serve`가 끝날 때 지웁니다.
- 터널은 직접 닫습니다. `ps`로 PID를 보고 `kill <PID>`.
- 남은 게 없는지: `pgrep -af "mqtt_ros_relay|mqtt_bridge_check"`

---

## 7. 안 될 때

| 증상 | 원인과 해결 |
|---|---|
| `pinky1 의 127.0.0.1:1883 에 닿지 않는다` | 터널이 없거나 죽음. 4절의 확인·재개방 |
| `ros2 topic echo`에서 `does not appear to be published yet` | ① `serve`가 아직 시작 전/이미 끝남 ② 터미널의 `CYCLONEDDS_URI` 불일치(102는 `$LO`, 100은 `cyclonedds_pc.xml`) ③ `ros2 daemon stop` 후 재시도 |
| `도메인 100 에 이미 발행자가 있어 중단한다` | DDS 브릿지 등이 같은 토픽을 이미 발행 중. 끄거나 이 단계를 하지 않음 |
| 이름은 뜨는데 값이 안 옴 | 그 토픽을 내는 노드(순찰, Nav2, 차선 등)가 꺼져 있음 |
| `/pinky1/patrol_status`가 0건 | 상태가 바뀔 때만 나가는 토픽. 순찰 명령 뒤에만 나옴 |
| `pinky1 load ... 이라 중단한다` | pinky1 부하 3.0 초과. 토픽 수나 주기를 줄임 |
| `--allow-any-out-topic 은 ... 일 때만 허용된다` | 도메인 10/100 등 허용되지 않은 도메인에서 원래 이름 발행을 시도함 |
