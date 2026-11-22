# 전체 시스템 켜는 순서

2026-11-22 기준입니다. 로봇 3대, Station PC(팔), 관제 PC 를 어떤 순서로 켜는지 한곳에 모았습니다.
자세한 설명은 각 절 끝의 원래 문서를 봅니다. 이 문서는 순서와 명령만 적습니다.

> 이 문서의 명령은 실제 로봇과 팔을 움직일 수 있습니다. 현장에 사람이 있고 주변이 안전한지 확인한 뒤 켭니다.

## 0. 한눈에

| 어디서 | 무엇 | `ROS_DOMAIN_ID` |
|---|---|---|
| pinky1 / pinky2 / pinky3 (192.168.45.21 / .22 / .23) | `cobot-robot` 서비스(전원 켜면 하드웨어 bringup → Nav2 → 순찰 노드 자동) | 10 / 20 / 30 |
| Station PC (8-OMEN: omx1·omx2, OMEN-11: omx3) | `cobot-host-status`, `cobot-arm-adapter@<팔>` (systemd 사용자 서비스) | 100 |
| 관제 PC | 도커 관제 `bash scripts/cobot.sh site up --execute` (브릿지·zone_manager·fleet·관제 화면 8080·고객 주문 화면 8081) | 100 |

순서: **① 로봇 전원(bringup·Nav2·순찰 노드 자동) → ② Station PC → ③ 관제 PC → ④ 화면에서 초기위치·주문 받기**

관제 PC 명령은 입구 하나 `scripts/cobot.sh` 로 모았습니다 (`bash scripts/cobot.sh help`). 실물 도메인에 닿는 명령은 미리보기가 기본이고 `--execute` 를 붙여야 실행합니다.

화면 포트 ([포트 표](ports.md)): 서비스용은 80xx(실물 관제 8080, 고객 주문 8081), 개발용은 81xx(개발 읽기 전용 8180, 가짜 핑키 8181, 가제보 8182)입니다.

## 1. 켜기 전에

- **관제 PC 는 한 대만** 켭니다. 두 대가 켜지면 브릿지와 zone_manager 가 두 벌이 되어 구역 토큰이 따로 나갑니다.
- 같은 도메인에 `fleet_control` 을 둘 띄우지 않습니다 (예: 도커 fleet 과 bringup fleet). 요청 수신자가 둘이면 명령을 거절합니다.
  이미 무엇이 떠 있는지는 `bash scripts/cobot.sh status` 로 봅니다 (도커·launch·포트·관제 상태).
- 관제 PC 는 `.venv` 파이썬으로 빌드해야 합니다. `bash scripts/cobot.sh build` 가 그렇게 합니다 (시스템 `colcon` 으로 빌드하면 관제 화면이 fastapi 를 못 찾아 뜨지 않음).

## 2. 각 로봇: 전원 켜기 (자동 기동)

로봇 3대에는 `cobot-robot` systemd 서비스가 깔려 있습니다. 전원을 켜면 `robot_startup` 이 하드웨어 bringup → Nav2(기본 `pinky_navigation`) → 순찰 노드를 차례로 띄웁니다.
로봇별 ID·도메인·지도·사이클론 DDS 설정은 로봇의 `/etc/cobot/robot.env` 에 있습니다.

상태와 로그는 로봇에서 봅니다. 준비가 끝나면 로그에 `COBOT_ROBOT_READY` 가 찍힙니다.
```bash
ssh pinky1 'systemctl status cobot-robot --no-pager'
```
```bash
ssh pinky1 'journalctl -u cobot-robot -f'
```
- 다시 떠도 혼자 움직이지 않습니다. 관제 하트비트·세션이 확인되기 전에는 이동 명령을 거절합니다.
- 실패하면 10초 뒤 다시 시도하고, 10분에 5번 넘게 실패하면 멈춥니다. 로그를 보고 고친 뒤 `sudo systemctl restart cobot-robot` 합니다.
- **자동 기동하는 로봇에는 손으로 bringup·Nav2·순찰 노드를 띄우지 않습니다.** 관제의 SSH 기동(`fleet_startup execute:=true`)도 같은 기동기 잠금에 걸려 실패하므로 쓰지 않습니다.
- 서비스 설치·끄기·자동 기동 해제 방법: [순찰 README 자동 기동](../src/cobot_navigation/cobot_pinky_patrol/README.md#전원을-켜면-자동-기동-systemd)

### 서비스를 끈 로봇에서 손으로 켤 때

`sudo systemctl stop cobot-robot` 으로 서비스를 끈 로봇에서만 씁니다. SSH 로 들어가서 차례로 켭니다 (pinky1 예시).
```bash
ros2 launch pinky_bringup bringup_robot.launch.xml
```
```bash
ros2 launch pinky_navigation bringup_launch.xml map:="$HOME/cobot_map_v9.yaml"
```
- 장애물 회피나 사람 정지까지 쓰려면 Nav2 대신 `cobot_obstacle_avoidance bringup.launch.xml` 을 씁니다 ([launch 머리말](../src/cobot_navigation/cobot_obstacle_avoidance/launch/bringup.launch.xml)). 지금 서비스는 기본 Nav2 로만 띄웁니다.
- 순찰 노드는 5절 명령으로 켭니다.

원래 문서: [주행 README 로봇 기동](../src/cobot_navigation/README.md#로봇-기동)

## 3. Station PC: 팔

서비스로 켭니다. 8-OMEN 예시입니다 (OMEN-11 은 `@omx3`).
```bash
systemctl --user start cobot-host-status cobot-arm-adapter@omx1 cobot-arm-adapter@omx2
```
```bash
systemctl --user status 'cobot-arm-adapter@*'
```
- 어댑터는 꺼짐(DISARMED) 상태로 시작해서 켜기만으로는 팔이 움직이지 않습니다.
- `COBOT_WORKER_ARMS` 에 들어 있는 팔(8-OMEN 은 omx1·omx2)은 관제에서 '켜기'를 누르면 토크가 켜지고 작업 때 실제로 움직입니다. **팔 옆에 사람이 없으면 서비스를 끕니다.**
- 이 PC 의 팔 설정은 `~/.config/cobot/station.env` 에 있습니다.

원래 문서: [station_pc_services.md](station_pc_services.md)

## 4. 관제 PC: 도커 관제

현장은 도커 관제 하나로 켭니다. 컨테이너 다섯 개(브릿지·zone_manager·fleet·관제 화면 8080·고객 주문 화면 8081)가 지금 커밋으로 만든 이미지 하나로 뜹니다.
```bash
bash scripts/cobot.sh site up
```
미리보기에서 프로젝트 이름과 주문·재고 DB 볼륨(`<프로젝트>_fleet-data`)을 확인한 뒤 실행합니다.
```bash
bash scripts/cobot.sh site up --execute
```
- 지금 커밋 이미지가 없으면 먼저 `bash scripts/cobot.sh site rebuild --execute` (빌드 → 격리 스모크 → 켜기, 몇 분).
- 프로젝트 이름은 떠 있는 것(없으면 가장 최근 것)을 이어 씁니다. 프로젝트마다 주문·재고 DB 가 따로라서, 바꿀 때만 `COBOT_PROJECT=<이름>` 을 줍니다.
- 주문 받기(작업 명령)는 **꺼짐**으로 시작합니다. 로그는 `bash scripts/cobot.sh site logs fleet`.
- 도커 자체(설치·`fleet_docker.sh` 명령)는 [`cobot_fleet_control/config/docker/README.md`](../src/cobot_navigation/cobot_fleet_control/config/docker/README.md).

### 대신 bringup 으로 켤 때 (개발)

도커와 같은 8080·도메인을 쓰므로 도커를 먼저 내립니다 (`bash scripts/cobot.sh site down --execute`). 고객 주문 화면은 7절처럼 따로 켭니다.
보기만 할 때(작업 노드 없음)는 `bash scripts/cobot.sh view --execute` 입니다. 주문까지 처리하려면 아래처럼 직접 켭니다.
```bash
source /opt/ros/jazzy/setup.bash && source .venv/bin/activate && source install/setup.bash
```
```bash
export ROS_DOMAIN_ID=100
```
```bash
ros2 launch cobot_bringup bringup.launch.xml
```
한 번에 뜨는 것:
- 도메인 브릿지 3개 (100 ↔ 10 / 20 / 30), `zone_manager`
- `fleet_status_node`, `fleet_api_node` (화면 8080, 내부망 공개)
- `fleet_api_node` 와 함께: `arm_command_node`, `teleop_node`, `net_status_node`, `host_status_node`
- 작업 노드 `fleet_control_node` (작업 명령 **꺼짐**으로 시작)

| 인자 | 기본값 | 쓰임 |
|---|---|---|
| `pinky1` / `pinky2` / `pinky3` | `true` | 일부 로봇만 켤 때 `pinky2:=false` |
| `host` | `0.0.0.0` | 이 PC 에서만 보려면 `127.0.0.1` |
| `controller` | `fleet` | 보기만 하고 명령 노드는 띄우지 않으려면 `none` |
| `fleet_api` | `true` | `.venv` 가 없는 환경이면 `false` |

원래 문서: [관제 README 실행](../src/cobot_control_center/README.md#실행), [bringup.launch.xml](../src/cobot_bringup/launch/bringup.launch.xml)

## 5. 각 로봇: 순찰 노드

자동 기동하는 로봇은 서비스가 이미 띄웠으므로 아래 명령을 쓰지 않습니다. 서비스를 끈 로봇에서만 손으로 켭니다.
```bash
source ~/ws/kernel-robot-repo-4/install/setup.bash
```
```bash
ros2 launch cobot_pinky_patrol patrol.launch.xml robot_id:=pinky1 site:=lab
```
- 순찰 노드는 켜질 때 움직이지 않고 `IDLE` 만 냅니다. Nav2 가 뜬 뒤라면 관제보다 먼저 켜도 됩니다.
- **첫 명령 때 위치를 덮어씁니다.** `restore_pose: true`(`cobot_pinky_patrol/config/common.yaml`) 라서, 첫 명령을 받으면
  지난번 끌 때 저장한 위치(로봇의 `~/.pinky_last_pose.json`)를 `initialpose` 로 보내고 **제자리에서 4 초 돕니다**.
  그래서 6절에서 넣은 초기위치가 저장 위치로 바뀔 수 있습니다. 끈 뒤 로봇을 옮겼다면 첫 명령 뒤 화면 위치를 다시 확인합니다.
  (코드: `cobot_pinky_patrol/pinky_patrol_node.py` 의 `_advance_preparation`)

## 6. 관제 화면에서 시작

엔지니어 화면 `http://<관제 PC>:8080/` 에서 준비하고 ([화면 사용법](../src/cobot_control_center/docs/screen_guide.md)), 영업은 매장 관리화면 `http://<관제 PC>:8080/service/` 에서 봅니다 ([관리화면 사용법](../src/cobot_control_center/docs/service_screen.md)).

1. **초기위치**: 로봇 카드의 **초기위치** 를 누르면 순찰 설정의 홈 좌표가 `/pinkyN/initialpose` 로 나갑니다. 로봇은 움직이지 않고, 작업 명령을 켜지 않아도 됩니다. 홈이 아닌 곳이면 상세 화면 **좌표 지정**으로 찍습니다.
2. **작업 명령 켜기**: 화면 상단에서 켭니다 (현장 확인 후). 정지·비상정지는 꺼져 있어도 됩니다.
3. 가까운 지점으로 `goto` → 이동 중 정지 → `home` 순서로 확인합니다. 끝나면 **작업 명령 끄기**.
4. 영업: 매장 관리화면 위쪽 **주문 받기** (엔지니어 화면의 작업 명령 켜기와 같은 스위치). 멈춘 주문·상차 확인·정지 해제는 관리화면 '할 일'에서 합니다.

화면의 `연결` 은 배터리나 위치를 받고 있다는 뜻까지만입니다. Nav2·순찰 노드가 떴는지는 로봇 터미널 로그로 확인합니다.

원래 문서: [관제 README 실물 시험 순서](../src/cobot_control_center/README.md#실물-시험-순서), [명령 켜기](../src/cobot_control_center/README.md#명령-켜기)

## 7. (bringup 일 때만) 고객 주문 화면

도커 관제는 고객 주문 화면(8081)을 함께 켭니다. bringup 으로 켰을 때만 관제 PC(`fleet_control` 과 같은 PC)에서 따로 켭니다. 먼저 `src/cobot_gui/web` 에서 `npm run build` 를 하고 `colcon build` 를 해야 화면이 install 됩니다.
```bash
ros2 launch cobot_gui customer_gateway.launch.xml
```
- 화면은 `http://<관제 PC>:8081/` 입니다 (자리 QR 은 `:8081/?loc=<자리>`). 도커 관제(`fleet_docker.sh up`)는 같은 8081 로 이미 켜 두므로 둘을 함께 켜지 않습니다.

## 8. 끄는 순서

1. 화면에서 **작업 명령 끄기**. 진행 중인 주문·이동이 없고 로봇이 모두 멈췄는지 봅니다.
   움직이던 로봇은 관제가 꺼지면 하트비트가 끊긴 것을 3 초 안에 알고(`central_timeout_sec`) 멈춘 뒤 **정지 잠금**이 걸립니다.
   잠금은 다음에 켤 때 화면에서 복구해야 합니다. 멈춰 있던 로봇은 잠기지 않습니다.
2. 관제 PC: 도커 관제는 `bash scripts/cobot.sh site down --execute` (주문·재고 DB 볼륨은 남김). 이 PC 에서 띄운 것(bringup·가짜 핑키·가제보·도커)을
   한 번에 내리려면 `bash scripts/cobot.sh stop` (미리보기) → `--execute` 를 씁니다.
3. 각 로봇: `ssh -t pinky1 'sudo systemctl stop cobot-robot'` 처럼 서비스를 끕니다. 서비스가 순찰 노드 → Nav2 → bringup 순서로 정리하고 다시 띄우지 않습니다.
   손으로 켠 로봇은 같은 순서로 **Ctrl+C** 로 끕니다.
   순찰 노드는 정상 종료(서비스 stop 또는 Ctrl+C)될 때 이동을 취소하고 0 속도를 보낸 뒤 **지금 위치를 `~/.pinky_last_pose.json` 에 저장**합니다.
   다음에 켜서 첫 명령을 받을 때 이 위치를 되살립니다 (5절). 서비스를 끄지 않고 전원부터 끄면 위치가 저장되지 않아
   그 전에 저장된 위치가 남고, 다음 첫 명령 때 엉뚱한 위치로 덮어쓸 수 있습니다.
   (코드: `cobot_pinky_patrol/pinky_patrol_node.py` 의 `close`, `_save_pose`)
4. Station PC 팔: 켜져 있던 팔은 끌 때 토크가 꺼지므로 팔을 받칩니다.
   ```bash
   systemctl --user stop 'cobot-arm-adapter@*'
   ```
5. 로봇 전원을 끕니다. 네트워크가 끊긴 채 껐다면 노드가 남았는지 확인합니다.
   ```bash
   ssh pinky2 'pgrep -af "ros2 launch"'
   ```

급할 때는 끄기 전에 화면의 **전체 비상정지**를 먼저 누릅니다. 로봇·팔이 모두 멈추고 작업 명령도 꺼집니다.

## 9. 로봇 없이 시험할 때

아래 중 **하나만** 켭니다. 모두 실물 도메인과 겹치지 않는 도메인을 쓰고, 이 PC 안에서만 통신합니다.

| 방식 | 명령 | 화면 |
|---|---|---|
| 가짜 핑키 + 가짜 팔 3대 | `bash scripts/cobot.sh mock` (도메인 101, 이 PC 안. 명령 시험은 `--manual`, 팔 빼기 `arms:=false`) | 8181 |
| 가제보 시뮬 (핑키 3대 + Nav2 + 실제 순찰 노드 + 관제) | `bash scripts/cobot.sh sim` (도메인 140~143 고정, 화면 없이 `--headless`) | 8182 |
| 팔 어댑터만 가짜로 | `ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ros2 launch cobot_manipulation arm_station.launch.xml backend:=fake` | – |
| 실물을 보면서 화면 개발 (읽기 전용) | `ROS_DOMAIN_ID=100 ros2 launch cobot_control_center fleet_api_dev.launch.xml` | 8180 |

원래 문서: [관제 README 로봇 없이 시험하기](../src/cobot_control_center/README.md#로봇-없이-시험하기)
