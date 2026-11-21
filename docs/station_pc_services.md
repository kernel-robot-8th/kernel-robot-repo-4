# Station PC 상시 실행 (systemd 사용자 서비스)

Station PC 에서 아래 노드를 계속 띄워 둔다. 노드가 죽으면 다시 켜고, 부팅하면 자동으로 켠다.

| 서비스 | 띄우는 것 | 다시 켜기 |
|---|---|---|
| `cobot-arm-adapter@<팔>` (팔마다 하나) | [`scripts/run_arm_adapter.sh`](../scripts/run_arm_adapter.sh) `--arm <팔>` → `arm_adapter_node` (`COBOT_WORKER_ARMS` 에 있으면 worker, 없으면 none) | 실패로 끝났을 때만. 2분 안에 5번 실패하면 멈춘다 |
| `cobot-host-status` | [`host_status.launch.xml`](../src/cobot_control_center/launch/host_status.launch.xml) → `host_status_node` (host=station) | 항상 |

팔 이름은 PC 가 아니라 자리에 붙는다 (ZA = omx1, ZB = omx2, ZC = omx3). 어떤 PC 가 어떤 팔인지는 [`site_arms.yaml`](../src/cobot_control_center/config/site_arms.yaml) 의 `host` 를 보고 `~/.config/cobot/station.env` 의 `COBOT_ARMS` 에 적는다 (공백으로 구분).

팔 어댑터 서비스는 **템플릿**(`cobot-arm-adapter@.service`)이다. 서비스 파일은 하나이고 `@` 뒤 이름이 팔 이름이 된다. 한 PC 에 팔이 둘이면 `cobot-arm-adapter@omx1`, `cobot-arm-adapter@omx2` 를 따로 켜고 끈다. 한쪽이 죽어도 다른 쪽은 그대로 돈다.

| PC | `COBOT_ARMS` | `COBOT_WORKER_ARMS` | 이유 | 적용 상태 |
|---|---|---|---|---|
| OMEN-11 | `omx3` (ZC 하차) | (없음, 옛 `COBOT_ARM_BACKEND=none`) | ZC 팔 모델이 아직 없다. 이 PC 에 있는 모델은 ZB 팔 것이다 | 2026-11-16 두 서비스 켬, 부팅 자동 시작 등록. 재부팅 확인 전. 템플릿 전 단일 서비스(`cobot-arm-adapter`)로 등록됨 → 설치 스크립트를 다시 돌리면 `@omx3` 로 옮겨진다 |
| 8-OMEN | `omx1 omx2` (ZA 창고 하차 · ZB 상차) | `omx1 omx2` | 실행기 `OMX_FLEET_DIR=<저장소>/omx_fleet`. 모델: omx1 = `omx_1119_act` 16번, omx2 = `omx_1031_act_smolvla` 25번, 둘 다 `ACT_ENSEMBLE_K=5` | 2026-11-18 `@omx2` 켬. 2026-11-21 omx1 을 worker 로 추가(설정만, 켜기는 시험 때), 카메라를 by-path 로 바꿈. 부팅 자동 시작 등록 안 함 |

2026-11-16 OMEN-11 시험 결과:
- host-status: `/control_center/host_status` 에 `station (11Ubuntu)` 가 3 s 마다 나옴. 노드를 kill 하면 5 s 뒤 다시 뜸.
- arm-adapter: `omx3 탐지 READY` (보드 `6D96…`), `/manipulation/omx_3/status` 수신 (`torque_enabled: false`). 노드를 kill 하면 5 s 뒤 다시 뜸. `stop` 은 0.3 s.
- 팔이 켜진(토크 ON) 상태에서 끌 때 토크가 해제되는지는 확인하지 않았다 (backend=none 이라 켜지지 않음).

backend 는 이렇게 고른다.
- `none`: 상태와 보드 연결만 관제에 보인다. 켜기(START)와 작업은 모두 거절하므로 토크가 켜지지 않는다.
- `worker`: 실행기 `fleet_arms.yaml` 의 `arms.<팔 이름>` 에 **그 팔의** 모델이 있을 때만 쓴다.

이 PC 팔 설정은 `~/.config/cobot/station.env` 한 파일에서 본다. 팔 상세(카메라·모델)만 실행기 `fleet_arms.yaml` 에 있다.
```
COBOT_ARMS="omx1 omx2"     # 이 PC 팔 (팔마다 서비스 하나)
COBOT_WORKER_ARMS="omx2"   # 그중 실제로 돌릴 팔. 나머지는 none
OMX_FLEET_DIR=/절대/경로/omx_fleet   # 실행기 폴더. 비우면 저장소 옆 -omx-dashboard/omx_fleet
```
`COBOT_WORKER_ARMS` 를 고친 뒤에는 그 팔만 다시 켠다.
```bash
systemctl --user restart cobot-arm-adapter@omx2
```
옛 `station.env`(`COBOT_ARM_ID`·`COBOT_ARM_BACKEND`, OMEN-11)도 그대로 읽는다. `COBOT_ARM_BACKEND` 는 `COBOT_WORKER_ARMS` 에 없는 팔의 기본값이 된다.

한 PC 에 팔이 둘일 때 실행기 `fleet_arms.yaml` 에서 주의한다.
- 카메라: 같은 모델 카메라를 두 팔에 꽂으면 `/dev/v4l/by-id` 이름이 같아진다. 그때는 꽂은 USB 포트 기준인 `/dev/v4l/by-path/…` 로 적는다. 8-OMEN 은 2026-11-21 이 경우라 by-path 로 적었다 (omx1 = 허브 usb 10.x, omx2 = 허브 usb 4.x). by-id 는 나중에 꽂은 카메라를 가리키므로 다른 팔 영상을 쓰게 된다.
- 캘리브레이션: `robot_id` 를 팔마다 다르게 둔다. 같으면 캘리브레이션 파일을 서로 덮어쓴다. (OMX 는 lerobot 0.4.4 에서 공장 기본값으로 캘리브레이션하므로 8-OMEN 의 두 팔은 `omx_follower` 하나를 같이 써도 내용이 같다.)
- 실행기 사전 검사는 **그 팔**(환경변수 `ARM_ID` 가 같거나 없는) 실행기만 막는다. 다른 팔 어댑터가 띄운 실행기는 다른 포트를 쓰므로 막지 않는다.

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
처음 실행하면 `~/.config/cobot/station.env` 만 만들고 멈춘다. 이 파일의 값(`ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, `CYCLONEDDS_URI`, `OMX_VENV_PY`)이 `~/.bashrc` 와 같은지, `COBOT_ARMS`·`COBOT_WORKER_ARMS` 가 이 PC 자리에 맞는지 확인한 뒤 같은 명령을 다시 실행한다. systemd 는 `~/.bashrc` 를 읽지 않기 때문이다. 이 파일은 커밋하지 않는다.

부팅 때 자동 시작까지 등록하려면 아래처럼 한다. `COBOT_ARMS` 의 팔마다 `cobot-arm-adapter@<팔>` 이 등록된다.
```bash
scripts/systemd/install_station_services.sh --enable
```

### 옛 단일 서비스에서 옮기기
템플릿 전에는 팔 서비스가 `cobot-arm-adapter` 하나였다 (OMEN-11 이 이렇게 등록됨). 저장소를 새로 받은 뒤 설치 스크립트를 다시 돌리면 옛 서비스를 끄고 지운다. `station.env` 에 `COBOT_ARMS` 가 없으면 옛 `COBOT_ARM_ID` 값을 팔 목록으로 쓴다. 옛 서비스가 꺼지므로 다시 켠다.
```bash
scripts/systemd/install_station_services.sh --enable
```
```bash
systemctl --user start cobot-arm-adapter@omx3
```

## 쓰기
`<팔>` 자리에 팔 이름을 넣는다. 아래는 8-OMEN 예시다.
```bash
systemctl --user start cobot-host-status cobot-arm-adapter@omx2
```
```bash
systemctl --user status 'cobot-arm-adapter@*'
```
```bash
journalctl --user -u cobot-arm-adapter@omx2 -f
```
팔 하나만 끈다.
```bash
systemctl --user stop cobot-arm-adapter@omx2
```
이 PC 팔을 모두 끈다.
```bash
systemctl --user stop 'cobot-arm-adapter@*'
```
사전 검사가 계속 실패해 재시작이 멈췄으면, 원인을 고친 뒤 `systemctl --user reset-failed cobot-arm-adapter@<팔>` 하고 다시 켠다.

## 주의
- 팔 어댑터는 꺼짐(DISARMED), `auto_start=false` 로 시작한다. 그래서 **부팅만으로는 팔이 움직이지 않는다.**
- backend=worker 이면 관제에서 '켜기'(START)를 누르면 실제 팔에 토크가 켜지고, PICK 단계를 보내면 팔이 움직인다. 관제 웹에는 아직 로그인이 없다. **팔 옆에 사람이 없으면 `cobot-arm-adapter@*` 를 끈다.**
- 끌 때는 SIGINT 를 보낸다. 터미널에서 Ctrl+C 한 것과 같아서, 켜져 있던 팔은 토크가 꺼진다. 팔을 받친다.
- 단독으로 띄운 실행기(`omx_fleet_worker.py`)가 그 팔 포트를 잡고 있으면 사전 검사에 실패해 서비스가 뜨지 않는다. 그 실행기를 먼저 끈다.
- `--symlink-install` 빌드를 그대로 쓴다. 이 저장소에서 브랜치를 바꾸거나 다시 빌드하면 서비스가 쓰는 코드도 바뀐다. 반영하려면 `systemctl --user restart` 한다.
- `ROS_DOMAIN_ID` 는 지금 쓰는 값을 옮길 뿐이고 바꾸지 않는다 ([D2](fms_decisions.md#d2)).

## 되돌리기
```bash
scripts/systemd/install_station_services.sh --uninstall
```
팔 서비스(`cobot-arm-adapter@*`, 옛 `cobot-arm-adapter` 포함)와 PC 상태 서비스를 끄고 서비스 파일을 지운다. `~/.config/cobot/station.env` 는 남는다.
