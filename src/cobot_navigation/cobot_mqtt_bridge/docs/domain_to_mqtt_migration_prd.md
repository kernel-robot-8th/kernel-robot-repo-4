# domain_bridge → mqtt_bridge 전환 PRD

작성일: 2026-11-16 · 원본: [Claude Docs](https://claude.ai/artifact/D9E2aRa4YU6QM3wZuqnegz)

## 개요

관제 PC와 핑키 3대 사이의 ROS 2 중계를 `cobot_domain_bridge`(DDS)에서 `cobot_mqtt_bridge`(MQTT)로 바꾼다. 로봇 접속이 어려운 기간을 고려해 로봇 없이 하는 A단계(A0~A5)를 먼저 끝내고, 실물 시험(B0~B4)을 마지막에 몰아서 한다. 로봇 도메인 ID는 **현 상태(10/20/30) 유지로 확정**했다(3절).

**확정 사항** (2026-11-16)

| 항목 | 결정 |
| --- | --- |
| 로봇 도메인 | pinky1/2/3 = 10/20/30 유지 |
| 관제 도메인 | 최종 100, 시험(A3~B3) 동안만 200 |
| 로봇 주소 | pinky1 `192.168.45.21`, pinky2 `192.168.45.22`, pinky3 `192.168.45.23` (SSH 계정 `pinky`) |
| 차선 토픽 | `lane`, `crossline` 사용하지 않음. 중계 목록에서 제거 |

**배경**

- 지금은 관제 PC의 `domain_bridge`가 Wi-Fi 너머 로봇 도메인(10/20/30)에 직접 DDS로 붙는다. 그래서 로봇 DDS가 LAN 전체로 열려 있어야 하고, 무선 구간에서 DDS 탐색 트래픽과 끊김 영향을 그대로 받는다.
- `cobot_mqtt_bridge`는 로봇 안에서 ROS 토픽을 MQTT로 바꿔 SSH 터널로 관제 PC 브로커에 보낸다. 로봇 DDS를 로봇 내부로 가둘 수 있고, cmd_vel 보호와 부하 차단 같은 안전장치가 있다.
- 현재 mqtt_bridge는 pinky1 읽기와 `goto` 명령만 실물로 확인됐다. 관제 스택(`cobot_bringup`, `fleet_status`, `fleet_control`)은 아직 domain_bridge를 전제로 한다.

**목표**

- 관제 PC 기본 실행(`cobot_bringup`)이 mqtt_bridge로 3대 모두와 통신한다.
- 지금 domain_bridge가 넘기는 토픽 중 실제로 쓰는 것을 빠짐없이 넘긴다. 특히 `fleet_heartbeat`, `/zone_manager/*`, `/initialpose`.
- 관제 화면의 브릿지 상태 표시가 mqtt_bridge 기준으로 정확하다.
- 문제가 생기면 launch 인자 하나로 domain_bridge로 되돌릴 수 있다.

**비목표**

- 가제보 시뮬레이션(`cobot_gazebo`)의 domain_bridge 교체. 시뮬레이션은 한 PC 안이라 DDS 직결이 더 단순하다.
- 로봇끼리 위치·경로를 공유하는 기능.
- 메시지 직렬화 방식 변경(JSON → CDR 등). 부하 측정 결과가 나쁠 때 따로 검토한다.

## 현황 비교

두 브릿지는 관제 도메인, 로봇 도메인, 넘기는 토픽 범위가 모두 달라 바로 바꿔 끼울 수 없다. 2026-11-16 `merge/submaster-20261112` 브랜치 기준이다.

| 항목 | cobot_domain_bridge (현재) | cobot_mqtt_bridge (feature/navigation) |
| --- | --- | --- |
| 방식 | 관제 PC에서 두 도메인에 DDS로 직접 참여 | 양쪽 노드가 JSON을 MQTT 브로커(관제 PC 127.0.0.1:1883)로 주고받음, 로봇은 SSH 역방향 터널 |
| 관제 도메인 | 100 | 200 (병행 시험용으로 분리) |
| 로봇 도메인 | pinky1/2/3 = 10/20/30 | 3대 모두 10 (YAML과 launch 기본값) |
| 실행 위치 | 관제 PC 프로세스 3개 | 관제 PC 노드 + 로봇마다 노드(ssh 또는 systemd) |
| 로봇 쪽 준비 | 없음 | 코드·YAML 복사, `python3-paho-mqtt`, 서비스 등록 |
| 관제→로봇 명령 | 항상 켜짐, 7개 토픽 | 기본 꺼짐. `mode:=cmd`여도 `patrol_cmd` 1개만 열림 |
| 로봇→관제 | 15개(pinky1), 12개(pinky2·3) | 같은 목록이나 `*/lane/*`, `*/crossline/*` 제외, `/tf` 30Hz 제한 |
| `fleet_heartbeat` | 넘김 | **목록에 없음** |
| 안전장치 | 없음 | cmd_vel 속도 상한·워치독, 도메인 확인, 부하 3.0 초과 시 자동 정지 |
| 실물 검증 | 3대 운영 중 | pinky1 읽기, `goto`만 |

**domain_bridge에 의존하는 곳** (전환 때 같이 고쳐야 함)

| 파일 | 의존 내용 |
| --- | --- |
| `src/cobot_bringup/launch/bringup.launch.xml` | `cobot_domain_bridge/launch/bridges.launch.xml` include, 도메인 100 전제 |
| `src/cobot_control_center/config/fleet_status_node.yaml` | `bridge_node_format: pinky_bridge_{robot}_only_{domain}`로 브릿지 생존 판단, `control_domain_id: 100` |
| `src/cobot_control_center/launch/fleet_api_dev.launch.xml` | `ROS_DOMAIN_ID=100` |
| `src/cobot_navigation/cobot_fleet_control/config/fleet_startup.yaml` | 로봇 `domain_id` 10/20/30 |
| `src/cobot_navigation/cobot_fleet_control/config/docker/Dockerfile` | `cobot_domain_bridge` 빌드 |
| `src/cobot_navigation/cobot_amcl_corrector` | `/initialpose`가 domain_bridge로 전달된다고 가정(주석) |
| `src/cobot_gazebo` | 자체 domain_bridge YAML 사용 (비목표, 그대로 둠) |

## 로봇 도메인 ID 정책 검토

**확정: 현 상태(pinky1/2/3 = 10/20/30)를 유지하고, 로봇 DDS를 로봇 내부(루프백)로 닫는 것을 추가 보호막으로 둔다.** 로봇 쪽 토픽(`/cmd_vel`, `/goal_pose`, `/initialpose`)에 네임스페이스가 없어서, 도메인을 통일하면 루프백 설정 하나가 틀렸을 때 한 로봇 명령이 다른 로봇을 움직일 수 있기 때문이다.

### 두 안

- **A. 통일(모두 10):** mqtt_bridge의 현재 기본값. 로봇 3대가 같은 설정을 쓰고, 격리는 각 로봇의 DDS 루프백 설정에만 기댄다.
- **B. 현 상태 유지(10/20/30):** 도메인 번호로 한 번, 루프백 설정으로 한 번 더 격리한다. mqtt_bridge가 로봇별 도메인을 받도록 조금 고친다.

### 비교

| 기준 | A. 통일(10) | B. 유지(10/20/30) |
| --- | --- | --- |
| 로봇 간 격리 | 루프백 설정 1겹. 빠지거나 틀리면 3대의 `/cmd_vel`이 섞임 | 도메인 + 루프백 2겹 |
| 디버깅 | 노트북에서 `ROS_DOMAIN_ID=10`으로 보면 어느 로봇인지 구분 불가(루프백이면 애초에 안 보임) | 도메인 번호로 로봇을 골라 볼 수 있음 |
| mqtt_bridge 수정 | 없음 (이미 이 방식) | `mqtt_topics_pinky2/3.yaml`의 10을 20/30으로, launch에 로봇별 `robot_domain`, 도메인 확인 값(`confirm_real_domain`) 로봇별 |
| 다른 패키지 수정 | `fleet_startup.yaml`, 로봇 3대의 `ROS_DOMAIN_ID`와 bringup 스크립트, 관련 문서·테스트 | 없음 |
| 롤백 | domain_bridge로 돌아가려면 로봇 도메인도 되돌려야 함 | launch 인자만 바꾸면 됨 (로봇 루프백은 풀어야 함) |
| 로봇 이미지 관리 | 3대 동일 설정 | 로봇마다 도메인 값 1개만 다름 (이미 그렇게 운영 중) |
| 실물 검증 상태 | pinky1(10)만 검증 | pinky1(10)은 같음, pinky2·3은 어차피 새로 시험 |

### 판단 근거

1. 통일안이 아끼는 것은 설정 값 1개뿐이다. 반면 실패하면 로봇이 엉뚱하게 움직이는 사고로 이어진다.
2. 유지안의 추가 작업은 mqtt_bridge 내부에 모여 있다(YAML 2개, launch 인자). 통일안은 로봇 3대와 `cobot_fleet_control`까지 건드린다.
3. 전환 기간에 domain_bridge로 되돌아갈 일이 생기는데, 로봇 도메인을 그대로 두면 롤백이 단순하다.
4. 나중에 통일이 필요하면 mqtt_bridge 전환이 안정된 뒤 따로 해도 된다. 반대 방향(통일 후 분리)보다 위험이 작다.

### 관제 도메인(100 vs 200)

**확정: 최종 관제 도메인은 100.** 병행 시험 동안은 mqtt 쪽을 **200**으로 두어 domain_bridge(100)와 겹치지 않게 한다. 전환 단계에서 `pc_domain:=100`으로 바꾼다. 관제 스택 3곳이 100을 전제하므로 최종 값은 100이 수정량이 가장 적다.

## 요구사항

전환 후에도 관제 시나리오(순찰, 구역 진입, 정지·비상정지, 위치 보정)가 지금과 같이 동작해야 한다.

| ID | 구분 | 요구사항 | 확인 방법 |
| --- | --- | --- | --- |
| F1 | 기능 | 로봇→관제: `/scan`, `/odom`, `/tf`, `/tf_static`, `/amcl_pose`, `/patrol_status`, 배터리 3종, `/zone_manager/request_entry·notify_exit·cancel_entry`를 `/pinkyN/...`(zone은 이름 그대로)으로 넘긴다 | 관제 도메인에서 `ros2 topic hz` |
| F2 | 기능 | 관제→로봇: `patrol_cmd`, `cmd_vel`, `goal_pose`, `initialpose`, `fleet_heartbeat`, `/zone_manager/grant_entry·queue_slot`을 넘긴다 | 로봇에서 `ros2 topic echo` |
| F3 | 기능 | 로봇별 도메인(10/20/30)을 launch 인자로 지정한다 | launch 시험 |
| F4 | 기능 | `cobot_bringup`에서 `bridge:=mqtt` / `bridge:=dds`로 브릿지를 고른다. 두 개를 동시에 띄우지 않는다 | launch 시험 |
| F5 | 기능 | `fleet_status`가 mqtt_bridge 생존을 판단한다 (노드 이름 형식 또는 MQTT status 토픽) | 관제 화면 브릿지 상태 |
| S1 | 안전 | 명령 방향(`cmd_vel` 포함)은 `mode:=cmd`에서만 열린다. `cmd_vel`은 워치독(500ms)을 반드시 거친다 | `mqtt_down.yaml` 리뷰, 터널 강제 종료 시험 |
| S2 | 안전 | 브로커·터널이 끊기면 로봇은 `fleet_heartbeat` 상실로 멈춘다 (현행 순찰 노드 동작) | 터널 강제 종료 시험 |
| S3 | 안전 | 관제 역할 노드는 로봇 도메인에 발행하지 않고, 로봇 노드는 자기 도메인에만 발행한다 | 단위 시험 (`relay_utils`) |
| S4 | 안전 | domain_bridge와 mqtt_bridge가 같은 관제 도메인에서 동시에 발행하지 않는다 | 시작 시 기존 발행자 확인 |
| O1 | 운영 | 로봇 쪽 브릿지는 systemd 서비스로 부팅 때 켜진다 (3대) | 로봇 재부팅 |
| O2 | 운영 | 로봇 IP·SSH 계정은 한 곳(`fleet_startup.yaml` 또는 브릿지 설정)에서 관리한다. 비밀번호는 저장소에 두지 않고 SSH 키로 접속한다 | 설정 리뷰 |
| O3 | 운영 | 3대 동시 60분 운영에서 `/amcl_pose` 지연 p95 ≤ 200ms, 로봇 load < 3.0 | 장시간 시험 기록 |
| O4 | 운영 | 브로커·터널·로봇 서비스 설치와 점검을 스크립트 3개(`setup_pc.sh`, `deploy_robot.sh`, `doctor.sh`)로 끝낸다. 다시 실행해도 안전하다 | 새 PC에서 처음부터 설치 |
| O5 | 운영 | `doctor.sh`가 네트워크~관제 토픽 8개 구간을 순서대로 점검해, 처음 실패한 구간과 원인 후보·해결 명령·장애 대응표 항목을 출력한다 | A3 장애 재현에서 진단 일치 |
| O6 | 운영 | `collect_logs.sh` 한 번으로 양쪽 journalctl, 브로커 로그, 토픽 주기, 짧은 rosbag, 로봇 load를 압축 파일 하나로 모은다 | A2 검증, B단계 중단 시 사용 |

O3의 200ms는 제안 값이다. B0에서 현재 domain_bridge 지연을 재서 기준을 확정한다.

## 단계별 전환 계획

로봇에 접속할 수 없는 기간에도 진행할 수 있도록 **A(로봇 없이) → B(실물) → C(정리)** 순서로 나눈다. 실물 시험에서 시간이 가장 많이 드는 일은 고치는 것보다 "어디가 고장 났는지" 찾는 것이다. 그래서 A단계에서 진단 도구(구간 점검, 로그 수집, 장애 대응표)를 먼저 만들고 시뮬에서 장애를 일부러 일으켜 검증한 뒤 실물로 넘어간다.

각 단계의 완료 기준을 통과해야 다음으로 넘어간다. B3까지는 domain_bridge가 기본이고, B4에서 기본값을 바꾼다.

| 단계 | 내용 | 실물 로봇 | 로봇 움직임 |
| --- | --- | --- | --- |
| A0 | 결정 | 불필요 | – |
| A1 | mqtt_bridge 패키지 보완 | 불필요 (가짜 모드) | – |
| A2 | 설치 자동화 스크립트와 진단 도구 | 불필요 (가짜 로봇 컨테이너) | – |
| A3 | 시뮬 명령 시험과 장애 재현 | 불필요 (가제보) | – |
| A4 | 연동 패키지 수정 | 불필요 | – |
| A5 | 실물 대비 리허설 | 불필요 (가제보) | – |
| B0 | 1대 시운전 | pinky1 | 아니오 |
| B1 | 3대 배포 | 3대 | 아니오 |
| B2 | 병행 읽기 시험 | 3대 | 아니오 |
| B3 | 명령 시험 | 한 대씩 | **예** |
| B4 | 전환 | 3대 | **예** |
| C | 정리 | 불필요 | – |

### A0. 결정

- [x] 로봇 도메인 정책: 10/20/30 유지
- [x] 최종 관제 도메인: 100 (병행 시험은 200)
- [x] 로봇 주소·계정: 개요의 확정 사항 표
- [x] 차선 토픽(`lane`, `crossline`): 사용하지 않음, 제거
- [x] 관제→로봇으로 열 토픽: domain_bridge와 같은 7개 모두 (`patrol_cmd`, `cmd_vel`, `initialpose`, `goal_pose`, `fleet_heartbeat`, `/zone_manager/grant_entry·queue_slot`)
- [x] cmd_vel 보호 값: 워치독만 유지 (`watchdog_ms` 500). 속도 상한은 핑키 최대 속도 수준(`max_linear` 0.3, `max_angular` 1.5, 추정값, B3에서 확인)으로 두어 사실상 제한 없음
- [x] `fleet_status` 브릿지 생존 판단: 노드 이름 형식 (`mqtt_bridge_{robot}`)

완료 기준: 위 7개가 이 문서 또는 팀 회의록에 기록됨. (2026-11-16 완료)

### A1. mqtt_bridge 패키지 보완

- `config/mqtt_topics_pinky1~3.yaml`에 `/pinkyN/fleet_heartbeat` → `/fleet_heartbeat` 추가
- `mqtt_topics_pinky2.yaml`은 로봇 도메인 20, `pinky3`은 30으로 수정
- `launch/mqtt_bridge.launch.xml`에 `pinky1_domain`/`pinky2_domain`/`pinky3_domain` 인자 추가, 로봇별 `robot_domain`과 `confirm_real_domain` 전달
- `mqtt_topics_pinky1.yaml`에서 `/pinky1/lane/*`, `/pinky1/crossline/*` 항목 3개를 삭제하고, `mqtt_bridge.yaml`·`mqtt_down.yaml`의 `exclude_patterns`에서 `*/lane/*`, `*/crossline/*`을 뺀다
- `config/mqtt_down.yaml`의 차단 목록을 비워 7개 모두 열고, 보호 값을 A0 결정대로 수정
- 토픽 방향 판정을 관제 도메인(`pc_domain`) 대신 로봇 도메인(`robot_domain`) 기준으로 바꾼다. 관제 도메인을 200→100으로 바꿀 때 모든 항목이 경고 없이 빠지는 문제를 막고, 로봇 도메인 값이 틀리면 노드가 시작하지 않게 한다
- 브릿지 노드 이름은 이미 `mqtt_bridge_{robot}`으로 고정되어 있음을 확인 (A4에서 `bridge_node_format`에 반영)
- 현장에서 조정할 값(`rate_limits`, 토픽 목록, cmd_vel 보호 값)은 모두 YAML에 두어, 다시 빌드하지 않고 YAML 수정과 서비스 재시작만으로 바꿀 수 있게 한다
- 단위 시험 추가: 도메인 20/30 YAML 파싱, heartbeat 방향 판정

완료 기준: `colcon test --packages-select cobot_mqtt_bridge` 통과, 가짜 모드(도메인 101/102)에서 F1·F2 토픽이 모두 통과.

### A2. 설치 자동화 스크립트와 진단 도구

브로커·터널·로봇 서비스 설치를 스크립트로 묶고, 실물에서 문제가 났을 때 원인 구간을 바로 찾는 진단 도구를 같이 만든다. 지금은 작업이 장비와 파일에 흩어져 있고, 서비스 파일에 pinky1 값이 박혀 있어 로봇마다 손으로 복사·수정해야 한다. 이 단계에서는 실물 대신 가짜 로봇 컨테이너로 검증하고, 실제 3대 배포는 B0·B1에서 같은 스크립트로 한다.

**현재 수작업**

| 위치 | 작업 | 문제 |
| --- | --- | --- |
| 관제 PC | `apt install mosquitto`, 포트 확인 | 확인 명령을 매번 따로 입력 |
| 관제 PC | 터널 서비스 설치 | `mqtt_bridge_tunnel.service`에 pinky1 IP와 `User=jinho` 하드코딩 |
| 관제 PC → 로봇 | SSH 키 등록 | 로봇마다 `ssh-copy-id` |
| 로봇 | 코드 복사, `python3-paho-mqtt` 설치, 서비스 등록 | `mqtt_bridge_robot.service`에 `pinky1`, 도메인 10 하드코딩 |
| 전체 | 로봇 IP | launch(`robot_host`), 터널 서비스, README에 흩어져 있음 |

**자동화 설계**

1. **로봇 정보 단일 파일:** `config/robots.yaml`에 로봇별 IP, SSH 계정, ROS 도메인을 적는다. 스크립트, 서비스, launch가 모두 이 파일을 읽는다 (O2). `cobot_fleet_control/config/fleet_startup.yaml`에도 IP·도메인이 있지만, 그 파일의 `ssh_user`를 채우면 fleet_control이 실제 SSH 기동을 할 수 있어 건드리지 않는다. 대신 두 파일의 IP·도메인이 같은지 시험으로 확인한다.
2. **systemd 템플릿 유닛:** 로봇 이름만 바꿔 쓴다. 로봇별 값은 `robots.yaml`에서 만든 환경 파일(`/etc/cobot_mqtt_bridge/<robot>.env`)로 넣는다.
    - 관제 PC: `mqtt_bridge_tunnel@pinky1~3.service`
    - 로봇: `mqtt_bridge_robot@pinkyN.service`
3. **mosquitto 설정 명시:** `/etc/mosquitto/conf.d/cobot_mqtt_bridge.conf`에 `listener 1883 127.0.0.1`과 `allow_anonymous true`를 적는다(mosquitto 2.x는 listener를 적으면 allow_anonymous가 없을 때 접속을 거부한다). Ubuntu 24.04의 mosquitto 2.x는 기본값도 localhost 전용이지만, 기본값이 바뀌어도 동작하도록 명시한다.
4. **스크립트 4개** (워크스페이스 최상위 `scripts/mqtt_bridge/`. CLAUDE.md 3-1이 패키지 안 `scripts/` 폴더를 허용하지 않아 `scripts/docker/`와 같은 방식으로 둔다)

| 스크립트 | 실행 위치 | 하는 일 |
| --- | --- | --- |
| `setup_pc.sh` | 관제 PC | mosquitto 설치·설정 파일, 3대 SSH 키 등록, 터널 3개 등록·시작 |
| `deploy_robot.sh <pinkyN\|all>` | 관제 PC | 코드·YAML 복사, `python3-paho-mqtt` 설치, 로봇 서비스 등록·시작 |
| `doctor.sh [pinkyN]` | 관제 PC | 구간별 점검. 처음 실패한 구간에서 멈추고 원인 후보와 해결 명령, 장애 대응표 항목을 출력 (O5) |
| `collect_logs.sh [pinkyN]` | 관제 PC | 문제 발생 시 진단 자료를 한 번에 모아 압축 파일 하나로 저장 (O6) |

**`doctor.sh` 구간 점검 순서**

| 순서 | 구간 | 확인 내용 |
| --- | --- | --- |
| 1 | 네트워크 | 로봇 IP ping |
| 2 | SSH | 키 접속(`BatchMode=yes`) 성공 |
| 3 | 브로커 | 관제 PC `127.0.0.1:1883` 응답 |
| 4 | 터널 | `mqtt_bridge_tunnel@pinkyN` 실행 중, 로봇 쪽 1883 포워딩 열림 |
| 5 | 로봇 서비스 | `mqtt_bridge_robot@pinkyN` 실행 중, 최근 재시작 횟수 |
| 6 | 로봇 ROS | 로봇 도메인에서 F1 원본 토픽이 발행 중 (도메인 값 일치 확인) |
| 7 | MQTT 수신 | `mqtt_bridge/<robot>/status`가 `online`, 메시지 수신 중 |
| 8 | 관제 토픽 | 관제 도메인에서 `/pinkyN/amcl_pose` 등 주기 확인 |

출력 예: `[FAIL] 4 터널: mqtt_bridge_tunnel@pinky2 inactive → 대응표 T-03, 해결: sudo systemctl restart mqtt_bridge_tunnel@pinky2`

**`collect_logs.sh` 수집 항목**

- 관제 PC와 로봇의 `journalctl` (브릿지·터널 서비스, 최근 30분)
- mosquitto 로그
- `doctor.sh` 결과
- F1 토픽 주기(`ros2 topic hz` 10초)
- 짧은 rosbag (F1 토픽 30초, `/scan` 제외 선택 가능)
- 로봇 `uptime`(load), 메모리, Wi-Fi 신호 세기

**스크립트 원칙**

- 여러 번 실행해도 결과가 같다. 코드를 고친 뒤 `deploy_robot.sh all`만 다시 돌리면 3대가 최신이 된다.
- 비밀번호를 스크립트나 저장소에 두지 않는다. 처음 한 번의 `sudo` 비밀번호와 SSH 키 등록 때 로봇 비밀번호는 실행 중에 입력받는다.
- 터널 서비스는 `BatchMode=yes`라서 비밀번호로 접속할 수 없다. 키 등록이 `setup_pc.sh`의 첫 단계다.
- 응답하지 않는 로봇은 키 등록·터널 시작을 건너뛰고 경고만 남긴다. 로봇 접속이 복구되면 같은 스크립트를 다시 실행한다.
- 로봇에 인터넷이 없을 때를 대비해 `python3-paho-mqtt` `.deb`를 관제 PC에서 받아(`apt-get download`) 복사·설치하는 경로를 둔다. 이 패키지는 아키텍처 무관(`all`)이다.
- 명령 방향(`enable_down`)은 서비스에 넣지 않는다. 지금처럼 launch의 `mode:=cmd`로만 켠다.

**가짜 로봇으로 검증**

- `ros:jazzy` 기반 컨테이너에 sshd와 계정 `pinky`를 두고 `deploy_robot.sh`의 복사·설치·서비스 등록 경로를 확인한다.
- systemd가 없는 컨테이너에서는 서비스 등록 단계를 `--dry-run`으로 확인한다.
- `doctor.sh`는 구간을 하나씩 일부러 끊어(컨테이너 정지, 터널 정지, 브로커 정지, 도메인 값 변경) 실패 구간을 맞게 짚는지 확인한다.

**검토한 다른 방법**

| 방법 | 장점 | 채택하지 않은 이유 |
| --- | --- | --- |
| Ansible | 장비가 늘어도 확장 쉬움 | 로봇 3대에 비해 도구 학습 부담이 큼 |
| mosquitto를 Docker로 실행 | 관제 PC 설치가 단순 | 로봇 쪽 작업은 그대로 남음 |
| SSH 터널 없이 로봇이 브로커에 직접 접속 | 터널 서비스 3개가 사라져 가장 단순 | 브로커를 LAN에 열어야 함. 인증·방화벽이 필요하고 현재 설계보다 덜 안전 |

**배포 대상**

| 로봇 | 주소 | SSH 계정 | ROS 도메인 |
| --- | --- | --- | --- |
| pinky1 | 192.168.45.21 | pinky | 10 |
| pinky2 | 192.168.45.22 | pinky | 20 |
| pinky3 | 192.168.45.23 | pinky | 30 |

비밀번호는 3대가 같으며 팀 내부에서 따로 공유한다(저장소에 적지 않음).

완료 기준:
- 관제 PC에서 `setup_pc.sh` 성공 (로봇 미응답은 경고로 통과)
- 가짜 로봇 컨테이너 대상으로 `deploy_robot.sh`를 두 번 실행해 결과가 같음
- `doctor.sh`가 일부러 끊은 구간을 모두 맞게 짚음
- `collect_logs.sh`가 위 항목이 든 압축 파일 하나를 만듦

### A3. 시뮬 명령 시험과 장애 재현

실물 명령 시험(B3)과 같은 시나리오를 가제보에서 먼저 돌리고, 실물에서 날 만한 장애를 일부러 일으켜 대응을 미리 겪어본다.

- `cobot_gazebo`(핑키 3대, Nav2, 실제 순찰 노드, 시뮬 도메인 140~143)의 로봇 도메인에 mqtt_bridge 로봇 노드를 붙이고, 관제는 도메인 200에서 띄운다. 가제보 자체 domain_bridge와 같은 관제 도메인에서 함께 발행하지 않게 한다 (S4).
- 터널은 localhost SSH로 구성해 실물과 같은 경로(터널 → 브로커)를 탄다.
- 명령 시나리오: `goto`, `stop`, `emergency_stop`, 구역 진입, 위치 보정 (3대)

**장애 재현 목록**

| 장애 | 재현 방법 | 기대 동작 | 진단 확인 |
| --- | --- | --- | --- |
| 지연·손실 | `tc netem`으로 브로커 포트 구간에 지연 100~300ms, 손실 1~5% | 주기 저하는 있으나 명령 유실 없음, 자동 정지 기준 동작 | `doctor.sh` 8번에서 주기 저하 표시 |
| 터널 끊김 | `systemctl stop mqtt_bridge_tunnel@pinkyN` | heartbeat 상실로 로봇 정지 (S2), 재연결 후 자동 이동 재개 없음 | 4번 FAIL |
| 브로커 재시작 | `systemctl restart mosquitto` | 3대 재접속, 읽기 정상 복귀 | 3번 FAIL → 복구 |
| 로봇 서비스 종료 | 로봇 노드 강제 종료 | 해당 로봇만 정지, 서비스 자동 재시작 | 5번 FAIL |
| 도메인 불일치 | `robot_domain` 값을 일부러 틀리게 | `confirm_real_domain`으로 시작 거부 또는 토픽 없음 | 6번 FAIL |
| CPU 부하 | `stress-ng`로 부하 3.0 초과 | 로봇 쪽 중계 자동 중단(`load_abort`) | 7번 offline + 원인 로그 |

완료 기준: 3대 명령 시나리오 통과, 장애 목록 전부에서 기대 동작과 `doctor.sh` 진단이 일치, 결과를 장애 대응표(A5)에 반영. 시뮬 통과는 실물 통과를 뜻하지 않으므로 B3는 그대로 필수다(Wi-Fi, 로봇 CPU는 실물에서만 확인 가능).

### A4. 연동 패키지 수정

- `cobot_bringup/launch/bringup.launch.xml`: `bridge` 인자 추가 (기본 `dds`), `mqtt`이면 `mqtt_bridge.launch.xml` include
- `cobot_control_center/config/fleet_status_node.yaml`: 브릿지 종류별 `bridge_node_format`
- `cobot_fleet_control/config/docker/Dockerfile`: `cobot_mqtt_bridge` 빌드 추가
- `cobot_amcl_corrector` 주석과 관련 README 갱신

기본값을 `dds`로 두므로 실물 운영에는 영향이 없다.

완료 기준: `bridge:=dds`·`bridge:=mqtt` launch 테스트 통과, 가제보 또는 가짜 모드에서 두 경우 모두 관제 화면 정상. 실물 관제 화면 확인은 B3에서 한다.

### A5. 실물 대비 리허설

- **장애 대응표** `docs/mqtt_bridge_troubleshooting.md` 작성. 항목마다 `ID | 증상 | doctor 구간 | 원인 | 확인 명령 | 해결`. 처음 넣을 항목:
    - SSH 키 미등록, 1883 포트 사용 중, 터널 끊김, 도메인 불일치
    - paho 버전 차이, 로봇에 인터넷 없음, 시계 차이, `load_abort` 발동, Wi-Fi 끊김
    - A3 장애 재현에서 나온 항목
- **B단계 점검표** (실물 시험 시작 전 확인):
    - 3대 SSH 접속, OS·ROS 버전, `dpkg --print-architecture`
    - 인터넷 여부(없으면 `.deb` 경로), 시계 동기(`timedatectl`), 디스크 여유
    - 로봇 bringup(Nav2, AMCL) 정상
    - 로봇 도메인에서 `patrol_cmd`를 발행하는 다른 노드 여부
    - 움직이는 시험이면 전원을 끌 수 있는 사람 지정
- **예행연습:** 가제보에서 B0~B3 절차를 같은 스크립트·점검표로 한 번 끝까지 돌리고, 단계별 걸린 시간을 기록해 실물 일정을 잡는다.

완료 기준: 대응표와 점검표 작성, 예행연습 1회 완료, 단계별 소요 시간 기록.

### 실물 시험 운영 규칙 (B단계 공통)

- 시험마다 통과/중단 기준과 제한 시간(제안: 20분)을 둔다. 넘기면 그 자리에서 디버깅을 이어가지 않고 `collect_logs.sh` 실행 → domain_bridge로 복귀 → 관제 PC에서 분석한 뒤 다음 일정에 다시 한다.
- 현장 조정은 YAML 수정과 서비스 재시작까지만 한다. 코드 수정이 필요하면 그날 해당 시험을 멈추고, A단계(가짜 모드·가제보)에서 재검증한 뒤 다시 한다.
- 새로 본 증상은 그날 바로 장애 대응표에 추가한다.
- 로봇이 움직이는 시험(B3, B4)은 전원을 끌 수 있는 사람이 옆에 있을 때만 한다.

### B0. 1대 시운전 (pinky1, 읽기만, 30분)

- B단계 점검표 확인
- `setup_pc.sh` 재실행(키 등록, 터널) → `deploy_robot.sh pinky1` → `doctor.sh pinky1`
- domain_bridge(100)는 그대로 두고 mqtt_bridge를 `mode:=read`, 관제 200으로 켜서 F1 토픽 확인
- domain_bridge의 `/amcl_pose` 지연을 재서 O3 기준을 확정한다

완료 기준: pinky1이 `doctor.sh` 전 구간 통과, F1 토픽 수신, 여기서 나온 환경 문제를 대응표에 반영.

### B1. 3대 배포

- `deploy_robot.sh all` → `doctor.sh`

완료 기준: 3대의 pc·robot이 모두 `online`. 같은 스크립트를 두 번 실행해도 결과가 같음.

### B2. 병행 읽기 시험 (관제 200)

- domain_bridge(100)는 그대로 두고, mqtt_bridge를 `mode:=read`, 관제 200으로 3대 모두 켠다
- 같은 토픽을 100과 200에서 동시에 재서 주기·지연을 비교한다
- 로봇 load, 브로커 CPU, Wi-Fi 트래픽을 기록한다

완료 기준: F1 토픽 주기가 domain_bridge 대비 90% 이상, O3 기준 충족, 60분 동안 자동 정지(load_abort) 없음. 기준 미달이면 `collect_logs.sh` 자료로 A1(주기 제한·토픽 목록)로 돌아가 조정한다.

### B3. 명령 시험 (로봇 한 대씩)

- domain_bridge를 끄고, 관제 스택을 도메인 200에서 띄운다 (`control_domain_id:=200`, `bridge:=mqtt`)
- pinky1 → pinky2 → pinky3 순서로 `goto`, `stop`, `emergency_stop`, 구역 진입, 위치 보정을 시험한다
- 터널을 강제로 끊어 로봇이 멈추는지 확인한다 (S2)
- 브로커를 재시작해 재접속과 이동 자동 재개 없음을 확인한다
- 실물 관제 화면의 브릿지 상태 표시를 확인한다 (F5)
- 끝난 뒤 양쪽에 `mqtt_bridge_node`가 남지 않는지 확인한다

완료 기준: 3대 모두 시나리오 통과, 시험 기록을 `docs/mqtt_bridge_prd.md`에 추가.

### B4. 전환

- 관제 도메인을 100으로 되돌리고(`pc_domain:=100`), `bringup`의 `bridge` 기본값을 `mqtt`로 바꾼다
- 로봇 DDS를 루프백으로 닫는다 (`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 또는 CycloneDDS 설정)
- 3대 60분 운영 시험을 다시 한다

완료 기준: 1주일 운영 동안 롤백 없음.

### C. 정리

- 실물용 `cobot_domain_bridge/config/pinky_bridge_pinky*.yaml`과 `bridges.launch.xml`을 deprecated로 표시 (가제보용 패키지는 유지)
- `bringup`의 `bridge:=dds` 선택지는 한 달 뒤 제거 여부 결정

## 시험 계획과 롤백

로봇이 움직이는 시험은 B3부터이며, 전원을 끌 수 있는 사람이 옆에 있을 때만 한다.

| 단계 | 시험 | 실물 | 로봇 움직임 | 통과 기준 |
| --- | --- | --- | --- | --- |
| A1 | 단위 시험 + 가짜 모드(101/102) | 아니오 | 아니오 | F1·F2 토픽 모두 통과 |
| A2 | 가짜 로봇 컨테이너 배포·구간 점검 | 아니오 | 아니오 | 재실행 결과 동일, 끊은 구간을 모두 맞게 진단 |
| A3 | 시뮬 명령 시나리오 | 아니오 | 시뮬 | 3대 모두 통과 |
| A3 | 시뮬 장애 재현 (지연·손실, 터널, 브로커, 서비스, 도메인, CPU) | 아니오 | 시뮬 | 기대 동작과 진단 일치 |
| A4 | launch 테스트 (`bridge:=dds/mqtt`) | 아니오 | 아니오 | 둘 다 관제 화면 정상 |
| A5 | B0~B3 예행연습 (가제보) | 아니오 | 시뮬 | 끝까지 완료, 소요 시간 기록 |
| B0 | pinky1 시운전 (읽기) | 1대 | 아니오 | 전 구간 통과, F1 수신 |
| B2 | 병행 읽기 60분 (100 vs 200) | 3대 | 아니오 | 주기 90% 이상, O3 충족 |
| B3 | 명령 시나리오 (goto, stop, emergency_stop, 구역, 위치 보정) | 한 대씩 | 예 | 3대 모두 통과 |
| B3 | 터널 강제 종료 | 한 대씩 | 예 | 로봇 정지 · 잠금 |
| B3 | 브로커 재시작 | 한 대씩 | 예 | 재접속 후 다시 읽기 정상, 이동 자동 재개 없음 |
| B4 | 3대 60분 운영 (관제 100, 루프백) | 3대 | 예 | O3 충족, 롤백 없음 |

**롤백 절차** (B4 이후)

1. 로봇 3대 `emergency_stop`, 관제 launch 종료
2. 로봇: `sudo systemctl stop mqtt_bridge_robot@pinkyN`, DDS 루프백 설정 해제 후 bringup 재시작
3. 관제 PC: `ros2 launch cobot_bringup bringup.launch.xml bridge:=dds`
4. `ROS_DOMAIN_ID=100 ros2 topic echo /pinky1/amcl_pose --once`로 복구 확인

로봇 도메인을 10/20/30으로 유지하기 때문에 2번에서 도메인을 바꿀 필요가 없다.

## 위험 요소와 미결정 사항

가장 큰 위험은 브로커가 한 곳이라는 점과 JSON 변환 부하다. A3(시뮬)에서 먼저 확인하고 B2에서 실물 수치로 확정한다. 실물 시험을 뒤로 미룬 만큼 실물에서만 드러나는 문제가 늦게 나오는 위험이 새로 생긴다.

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 관제 PC 브로커(mosquitto) 장애 | 3대 동시 통신 단절 | heartbeat 상실로 로봇 정지(S2), systemd 자동 재시작 |
| `/scan`·`/tf` JSON 변환 부하 | 지연 증가, load 3.0 초과 시 로봇 쪽 중계 자동 중단 | 주기 제한(`rate_limits`), 필요하면 `/scan` 제외 검토 |
| SSH 터널 끊김 | 해당 로봇 통신 단절 | 터널 서비스 자동 재연결, 브릿지 재접속(1~30초) |
| 두 브릿지 동시 실행 | 명령 이중 발행 | 도메인 분리(100/200), 시작 시 기존 발행자 확인(S4) |
| 로봇 도메인 10에서 `patrol_cmd`를 발행하는 다른 노드 | 명령 충돌 | B단계 점검표에서 발행자 목록 조사 |
| 3대 공통 비밀번호 | 한 대가 노출되면 3대 모두 노출 | SSH 키 접속으로 전환 후 비밀번호 로그인 비활성화 검토 |
| 실물 문제를 늦게 발견 (Wi-Fi, 로봇 CPU, 로봇 환경) | B단계에서 재작업, 일정 지연 | A3 장애 재현, B0 1대 시운전, 구간 점검(O5)·로그 수집(O6), 시험별 제한 시간 |
| 로봇 접속 불가 상태가 길어짐 | B단계 시작 지연 | A단계를 모두 끝내 두고, 접속 복구 시 B0부터 시작 |
| 로봇에 인터넷 없음 | `python3-paho-mqtt` 설치 실패 | `.deb`를 관제 PC에서 받아 복사·설치 |

**미결정 사항**

- [ ] O3 지연 기준 (B0에서 domain_bridge 수치 측정 후)
- [ ] A3 장애 재현용 `stress-ng` 설치 승인 (관제 PC, 시험용 새 의존성)

**확정됨** (2026-11-16): 로봇 도메인 10/20/30 유지, 최종 관제 도메인 100, 로봇 주소·계정, 차선 토픽 제거, 관제→로봇 7개 모두 열기, cmd_vel 워치독만 유지, 브릿지 생존 판단은 노드 이름 형식.

## 진행 상황과 다음 작업 (인계)

작업 PC 구분: 개인 PC(ROS 없음)에서 코드·문서를 작성하고, GitHub를 거쳐 ROS 2가 설치된 작업용 PC에서 빌드·시험·이어서 작업한다.

| 단계 | 상태 | 커밋 |
| --- | --- | --- |
| A0 결정 | 완료 (2026-11-16) | `c787f7b` |
| A1 패키지 보완 | 코드 완료, **작업용 PC 검증 대기** | `c787f7b` |
| A2 설치 자동화·진단 도구 | 계획 확정, 작성 전 | – |
| A3 이후 | 시작 전 | – |

### 작업용 PC에서 먼저 할 일: A1 검증

개인 PC에는 ROS가 없어 순수 파이썬 시험 66건만 간이 실행기로 통과시켰다. 아래는 아직 실행하지 않았다.

```bash
source /opt/ros/jazzy/setup.bash
cd <ws>
colcon build --symlink-install --packages-select cobot_mqtt_bridge
colcon test --packages-select cobot_mqtt_bridge
colcon test-result --verbose            # flake8·pep257·copyright 포함
```

가짜 모드(101/102): README "2. 가짜 모드" 절차로 pinky1 F1 토픽 통과를 확인하고, 관제 쪽에서 7개 하향 토픽이 로봇 역할 노드에 도착하는지 본다. pinky2·3로 시험할 때는 `-p robot_domain:=20`(pinky3은 30)을 붙인다. 하향 시험은 `-p enable_down:=true --params-file config/mqtt_down.yaml`을 양쪽에 준다.

### A2 작성 계획 (확정)

새로 만들 파일:

| 파일 | 내용 |
| --- | --- |
| `cobot_mqtt_bridge/config/robots.yaml` | pinky1~3의 host, ssh_user(`pinky`), ssh_port, domain |
| `cobot_mqtt_bridge/config/mqtt_bridge_tunnel@.service` | PC 터널 템플릿. 주소는 `/etc/cobot_mqtt_bridge/%i.env`, `User`는 설치 때 현재 사용자로 채움 |
| `cobot_mqtt_bridge/config/mqtt_bridge_robot@.service` | 로봇 서비스 템플릿. `-p robot:=%i -p robot_domain:=${ROS_DOMAIN_ID}`, 구독 전용 유지 |
| `cobot_mqtt_bridge/config/mosquitto_cobot_mqtt_bridge.conf` | `listener 1883 127.0.0.1`, `allow_anonymous true` |
| `scripts/mqtt_bridge/setup_pc.sh` | mosquitto·mosquitto-clients 설치·설정, SSH 키 생성·등록, 터널 등록. 응답 없는 로봇은 경고 후 건너뜀 |
| `scripts/mqtt_bridge/deploy_robot.sh <pinkyN\|all>` | 코드·YAML 복사, paho 설치(인터넷 없으면 `.deb`), env 파일·템플릿 서비스 등록, 예전 `mqtt_bridge_robot.service` 끄기, `--robots <파일>`·`--no-systemd` 옵션 |
| `scripts/mqtt_bridge/doctor.sh [pinkyN]` | A2의 8개 구간 점검 |
| `scripts/mqtt_bridge/collect_logs.sh [pinkyN]` | `~/mqtt_bridge_logs/<시각>.tar.gz` |
| `scripts/mqtt_bridge/fake_robot/Dockerfile`, `robots_fake.yaml` | `ros:jazzy-ros-base` + sshd + 계정 `pinky`, 127.0.0.1:2222, 도메인 101 |
| `cobot_mqtt_bridge/test/test_robots_config.py` | robots.yaml ↔ 토픽 YAML·launch 기본값·fleet_startup 도메인/IP 일치, 스크립트 `bash -n` |

수정할 파일:
- `config/mqtt_bridge_tunnel.service`, `config/mqtt_bridge_robot.service`: 템플릿으로 대체 후 삭제
- `launch/mqtt_bridge.launch.xml`: 서비스 실행 여부 검사를 `mqtt_bridge_robot@pinky1`로
- `setup.py`: `config/*.conf` 설치 추가, 서비스 glob이 `@.service`를 포함하는지 확인
- `test/test_service_files.py`: 템플릿 기준으로 수정
- `README.md`: 설치 절을 스크립트 3줄로

검증(작업용 PC): `colcon test` → 가짜 로봇 컨테이너에 `deploy_robot.sh --robots robots_fake.yaml --no-systemd` 두 번(결과 동일) → 컨테이너 안 로봇 노드로 터널·브로커·관제(102) 통과 → 컨테이너·터널·브로커·도메인 값을 하나씩 끊어 `doctor.sh` 진단 일치 → `collect_logs.sh` 압축 파일 생성.

작업용 PC가 실제 관제 PC가 아니면 mosquitto·터널도 도커 안에서만 시험하고, 실제 `setup_pc.sh`는 B0 때 관제 PC에서 실행한다.
