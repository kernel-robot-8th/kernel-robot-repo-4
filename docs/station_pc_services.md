# Station PC 상시 실행 (systemd 사용자 서비스)

Station PC 에서 아래 두 노드를 계속 띄워 둔다. 노드가 죽으면 다시 켜고, 부팅하면 자동으로 켠다.

| 서비스 | 띄우는 것 | 다시 켜기 |
|---|---|---|
| `cobot-arm-adapter` | [`scripts/run_arm_adapter.sh`](../scripts/run_arm_adapter.sh) → `arm_adapter_node` (팔 `COBOT_ARM_ID`, backend `COBOT_ARM_BACKEND`) | 실패로 끝났을 때만. 2분 안에 5번 실패하면 멈춘다 |
| `cobot-host-status` | [`host_status.launch.xml`](../src/cobot_control_center/launch/host_status.launch.xml) → `host_status_node` (host=station) | 항상 |

팔 이름은 PC 가 아니라 자리에 붙는다 (ZA = omx1, ZB = omx2, ZC = omx3). 어떤 PC 가 어떤 팔인지는 [`site_arms.yaml`](../src/cobot_control_center/config/site_arms.yaml) 의 `host` 를 보고 `~/.config/cobot/station.env` 에 적는다.

| PC | `COBOT_ARM_ID` | `COBOT_ARM_BACKEND` | 이유 | 적용 상태 |
|---|---|---|---|---|
| OMEN-11 | `omx3` (ZC 하차) | `none` | ZC 팔 모델이 아직 없다. 이 PC 에 있는 모델은 ZB 팔 것이다 | 2026-11-16 두 서비스 켬, 부팅 자동 시작 등록. 재부팅 확인 전 |

2026-11-16 OMEN-11 시험 결과:
- host-status: `/control_center/host_status` 에 `station (11Ubuntu)` 가 3 s 마다 나옴. 노드를 kill 하면 5 s 뒤 다시 뜸.
- arm-adapter: `omx3 탐지 READY` (보드 `6D96…`), `/manipulation/omx_3/status` 수신 (`torque_enabled: false`). 노드를 kill 하면 5 s 뒤 다시 뜸. `stop` 은 0.3 s.
- 팔이 켜진(토크 ON) 상태에서 끌 때 토크가 해제되는지는 확인하지 않았다 (backend=none 이라 켜지지 않음).

backend 는 이렇게 고른다.
- `none`: 상태와 보드 연결만 관제에 보인다. 켜기(START)와 작업은 모두 거절하므로 토크가 켜지지 않는다.
- `worker`: 실행기 `fleet_arms.yaml` 의 `arms.<팔 이름>` 에 **그 팔의** 모델이 있을 때만 쓴다. 바꿀 때는 `station.env` 의 `COBOT_ARM_BACKEND=worker` 로 고친 뒤 `systemctl --user restart cobot-arm-adapter` 한다.

> **시험 적용 상태.** [팔 PRD 6절](../src/cobot_manipulation/docs/prd.md)에는 부팅 때 자동 시작을 "D18(현장 실측) 뒤"로 적어 두었다. 지금은 이 Station PC 하나에서만 시험하는 단계이고, 팀이 확정한 운영 방식은 아니다.

## 왜 도커가 아니라 systemd 인가
- 팔 어댑터는 `/dev/serial/by-id` 로 보드를 찾는다. USB 를 뺐다 다시 꽂아도 따라가야 한다.
- PC 상태 보고는 컨테이너가 아니라 **이 PC 자체의** `/proc`·`/sys`·`ip`·`nmcli` 값을 읽어야 한다.
- 두 노드 모두 관제 PC 와 DDS 로 통신하므로 host 네트워크가 필요하다.
- 팀 개발용 도커([`scripts/docker/Dockerfile`](../scripts/docker/Dockerfile))는 빌드·시험 전용이다. 장치를 연결하지 않고 네트워크 없이 돈다.
- [아키텍처 제안 3-3](fms_architecture_proposal.md)도 "로봇·작업장 PC 는 systemd" 방향이다.

## 설치
사용자 서비스라서 sudo 가 필요 없다. 로그인하지 않아도 부팅 때 뜨려면 linger 가 켜져 있어야 한다. `loginctl show-user "$USER" -p Linger` 로 확인하고, `Linger=no` 이면 관리자에게 `loginctl enable-linger` 를 부탁한다.

```bash
colcon build --symlink-install --packages-up-to cobot_manipulation cobot_control_center
```
```bash
scripts/systemd/install_station_services.sh
```
처음 실행하면 `~/.config/cobot/station.env` 만 만들고 멈춘다. 이 파일의 값(`ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, `CYCLONEDDS_URI`, `OMX_VENV_PY`)이 `~/.bashrc` 와 같은지, `COBOT_ARM_ID`·`COBOT_ARM_BACKEND` 가 이 PC 자리에 맞는지 확인한 뒤 같은 명령을 다시 실행한다. systemd 는 `~/.bashrc` 를 읽지 않기 때문이다. 이 파일은 커밋하지 않는다.

부팅 때 자동 시작까지 등록하려면 아래처럼 한다.
```bash
scripts/systemd/install_station_services.sh --enable
```

## 쓰기
```bash
systemctl --user start cobot-host-status cobot-arm-adapter
```
```bash
systemctl --user status cobot-arm-adapter
```
```bash
journalctl --user -u cobot-arm-adapter -f
```
```bash
systemctl --user stop cobot-arm-adapter
```
사전 검사가 계속 실패해 재시작이 멈췄으면, 원인을 고친 뒤 `systemctl --user reset-failed cobot-arm-adapter` 하고 다시 켠다.

## 주의
- 팔 어댑터는 꺼짐(DISARMED), `auto_start=false` 로 시작한다. 그래서 **부팅만으로는 팔이 움직이지 않는다.**
- backend=worker 이면 관제에서 '켜기'(START)를 누르면 실제 팔에 토크가 켜지고, PICK 단계를 보내면 팔이 움직인다. 관제 웹에는 아직 로그인이 없다. **팔 옆에 사람이 없으면 `cobot-arm-adapter` 를 끈다.**
- 끌 때는 SIGINT 를 보낸다. 터미널에서 Ctrl+C 한 것과 같아서, 켜져 있던 팔은 토크가 꺼진다. 팔을 받친다.
- 단독으로 띄운 실행기(`omx_fleet_worker.py`)가 포트를 잡고 있으면 사전 검사에 실패해 서비스가 뜨지 않는다. 그 실행기를 먼저 끈다.
- `--symlink-install` 빌드를 그대로 쓴다. 이 저장소에서 브랜치를 바꾸거나 다시 빌드하면 서비스가 쓰는 코드도 바뀐다. 반영하려면 `systemctl --user restart` 한다.
- `ROS_DOMAIN_ID` 는 지금 쓰는 값을 옮길 뿐이고 바꾸지 않는다 ([D2](fms_decisions.md#d2)).

## 되돌리기
```bash
scripts/systemd/install_station_services.sh --uninstall
```
서비스를 끄고 서비스 파일을 지운다. `~/.config/cobot/station.env` 는 남는다.
