# domain_bridge → mqtt_bridge 전환 PRD

작성일: 2026-11-16 · 원본: [Claude Docs](https://claude.ai/artifact/D9E2aRa4YU6QM3wZuqnegz)

## 개요

관제 PC와 핑키 3대 사이의 ROS 2 중계를 `cobot_domain_bridge`(DDS)에서 `cobot_mqtt_bridge`(MQTT)로 7단계에 걸쳐 바꾼다. 로봇 도메인 ID는 **현 상태(10/20/30) 유지로 확정**했다(3절).

**확정 사항** (2026-11-16)

| 항목 | 결정 |
| --- | --- |
| 로봇 도메인 | pinky1/2/3 = 10/20/30 유지 |
| 관제 도메인 | 최종 100, 병행 시험(3~4단계) 동안만 200 |
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
| F2 | 기능 | 관제→로봇: `patrol_cmd`, `fleet_heartbeat`, `/zone_manager/grant_entry·queue_slot`, `initialpose`를 넘긴다 | 로봇에서 `ros2 topic echo` |
| F3 | 기능 | 로봇별 도메인(10/20/30)을 launch 인자로 지정한다 | launch 시험 |
| F4 | 기능 | `cobot_bringup`에서 `bridge:=mqtt` / `bridge:=dds`로 브릿지를 고른다. 두 개를 동시에 띄우지 않는다 | launch 시험 |
| F5 | 기능 | `fleet_status`가 mqtt_bridge 생존을 판단한다 (노드 이름 형식 또는 MQTT status 토픽) | 관제 화면 브릿지 상태 |
| S1 | 안전 | `cmd_vel`은 계속 기본 차단. 열 경우 속도 상한·워치독 값은 팀 합의 값 사용 | `mqtt_down.yaml` 리뷰 |
| S2 | 안전 | 브로커·터널이 끊기면 로봇은 `fleet_heartbeat` 상실로 멈춘다 (현행 순찰 노드 동작) | 터널 강제 종료 시험 |
| S3 | 안전 | 관제 역할 노드는 로봇 도메인에 발행하지 않고, 로봇 노드는 자기 도메인에만 발행한다 | 단위 시험 (`relay_utils`) |
| S4 | 안전 | domain_bridge와 mqtt_bridge가 같은 관제 도메인에서 동시에 발행하지 않는다 | 시작 시 기존 발행자 확인 |
| O1 | 운영 | 로봇 쪽 브릿지는 systemd 서비스로 부팅 때 켜진다 (3대) | 로봇 재부팅 |
| O2 | 운영 | 로봇 IP·SSH 계정은 한 곳(`fleet_startup.yaml` 또는 브릿지 설정)에서 관리한다. 비밀번호는 저장소에 두지 않고 SSH 키로 접속한다 | 설정 리뷰 |
| O3 | 운영 | 3대 동시 60분 운영에서 `/amcl_pose` 지연 p95 ≤ 200ms, 로봇 load < 3.0 | 장시간 시험 기록 |

O3의 200ms는 제안 값이다. 현재 domain_bridge 지연을 먼저 재서 기준을 확정한다.

## 단계별 전환 계획

7단계로 나누고, 각 단계의 완료 기준을 통과해야 다음으로 넘어간다. 5단계까지는 domain_bridge가 기본이고, 6단계에서 기본값을 바꾼다.

### 0단계. 결정

- [x] 로봇 도메인 정책: 10/20/30 유지
- [x] 최종 관제 도메인: 100 (병행 시험은 200)
- [x] 로봇 주소·계정: 개요의 확정 사항 표
- [x] 차선 토픽(`lane`, `crossline`): 사용하지 않음, 제거
- [ ] 관제→로봇으로 열 토픽 확정 (F2 목록, `cmd_vel`·`goal_pose` 포함 여부)
- [ ] cmd_vel 보호 값 합의 (제안: `watchdog_ms` 500, `max_linear` 0.15, `max_angular` 0.4)

완료 기준: 위 6개가 이 문서 또는 팀 회의록에 기록됨.

### 1단계. mqtt_bridge 패키지 보완

- `config/mqtt_topics_pinky1~3.yaml`에 `/pinkyN/fleet_heartbeat` → `/fleet_heartbeat` 추가
- `mqtt_topics_pinky2.yaml`은 로봇 도메인 20, `pinky3`은 30으로 수정
- `launch/mqtt_bridge.launch.xml`에 `pinky1_domain`/`pinky2_domain`/`pinky3_domain` 인자 추가, 로봇별 `robot_domain`과 `confirm_real_domain` 전달
- `mqtt_topics_pinky1.yaml`에서 `/pinky1/lane/*`, `/pinky1/crossline/*` 항목 3개를 삭제하고, `mqtt_bridge.yaml`·`mqtt_down.yaml`의 `exclude_patterns`에서 `*/lane/*`, `*/crossline/*`을 뺀다
- `config/mqtt_down.yaml`의 차단 목록을 0단계 결정대로 수정 (`/zone_manager/*`, `/initialpose` 허용)
- 브릿지 노드 이름을 `fleet_status`가 알 수 있는 형식으로 고정 (예: `mqtt_bridge_{robot}`)
- 단위 시험 추가: 도메인 20/30 YAML 파싱, heartbeat 방향 판정

완료 기준: `colcon test --packages-select cobot_mqtt_bridge` 통과, 가짜 모드(도메인 101/102)에서 F1·F2 토픽이 모두 통과.

### 2단계. 인프라 (pinky2, pinky3)

- 관제 PC: 로봇별 SSH 역방향 터널 서비스 (`mqtt_bridge_tunnel.service`를 로봇별로 나누거나 템플릿화)
- 로봇: 코드·YAML 복사, `python3-paho-mqtt` 설치, `mqtt_bridge_robot.service` 등록 (`ROS_DOMAIN_ID` 20/30)
- 로봇 IP·SSH 계정을 한 곳에 정리 (O2). 현재 pinky1 IP는 launch(`robot_host`)와 터널 서비스 파일에 하드코딩되어 있다
- 관제 PC에서 3대 모두 `ssh-copy-id`로 SSH 키를 등록한다. 터널 서비스가 `BatchMode=yes`라서 비밀번호로는 접속할 수 없다

| 로봇 | 주소 | SSH 계정 | ROS 도메인 |
| --- | --- | --- | --- |
| pinky1 | 192.168.45.21 | pinky | 10 |
| pinky2 | 192.168.45.22 | pinky | 20 |
| pinky3 | 192.168.45.23 | pinky | 30 |

비밀번호는 3대가 같으며 팀 내부에서 따로 공유한다(저장소에 적지 않음).

완료 기준: `mosquitto_sub -t 'mqtt_bridge/+/status/#'`에서 3대의 pc·robot이 모두 `online`.

### 3단계. 병행 읽기 시험 (관제 200)

- domain_bridge(100)는 그대로 두고, mqtt_bridge를 `mode:=read`, 관제 200으로 3대 모두 켠다
- 같은 토픽을 100과 200에서 동시에 재서 주기·지연을 비교한다
- 로봇 load, 브로커 CPU, Wi-Fi 트래픽을 기록한다

완료 기준: F1 토픽 주기가 domain_bridge 대비 90% 이상, O3 기준 충족, 60분 동안 자동 정지(load_abort) 없음.

### 4단계. 명령 시험 (로봇 한 대씩)

- domain_bridge를 끄고, 관제 스택을 도메인 200에서 띄운다 (`control_domain_id:=200`)
- pinky1 → pinky2 → pinky3 순서로 `goto`, `stop`, `emergency_stop`, 구역 진입, 위치 보정을 시험한다
- 터널을 강제로 끊어 로봇이 멈추는지 확인한다 (S2)
- 끝난 뒤 양쪽에 `mqtt_bridge_node`가 남지 않는지 확인한다

완료 기준: 3대 모두 시나리오 통과, 시험 기록을 `docs/mqtt_bridge_prd.md`에 추가.

### 5단계. 연동 패키지 수정

- `cobot_bringup/launch/bringup.launch.xml`: `bridge` 인자 추가 (기본 `dds`), `mqtt`이면 `mqtt_bridge.launch.xml` include
- `cobot_control_center/config/fleet_status_node.yaml`: 브릿지 종류별 `bridge_node_format`
- `cobot_fleet_control/config/docker/Dockerfile`: `cobot_mqtt_bridge` 빌드 추가
- `cobot_amcl_corrector` 주석과 관련 README 갱신

완료 기준: `bridge:=dds`와 `bridge:=mqtt` 둘 다 관제 화면이 정상, launch 테스트 통과.

### 6단계. 전환

- 관제 도메인을 100으로 되돌리고(`pc_domain:=100`), `bringup`의 `bridge` 기본값을 `mqtt`로 바꾼다
- 로봇 DDS를 루프백으로 닫는다 (`ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` 또는 CycloneDDS 설정)
- 3대 60분 운영 시험을 다시 한다

완료 기준: 1주일 운영 동안 롤백 없음.

### 7단계. 정리

- 실물용 `cobot_domain_bridge/config/pinky_bridge_pinky*.yaml`과 `bridges.launch.xml`을 deprecated로 표시 (가제보용 패키지는 유지)
- `bringup`의 `bridge:=dds` 선택지는 한 달 뒤 제거 여부 결정

## 시험 계획과 롤백

로봇이 움직이는 시험은 4단계부터이며, 전원을 끌 수 있는 사람이 옆에 있을 때만 한다.

| 단계 | 시험 | 로봇 움직임 | 통과 기준 |
| --- | --- | --- | --- |
| 1 | 단위 시험 + 가짜 모드(101/102) | 아니오 | F1·F2 토픽 모두 통과 |
| 3 | 병행 읽기 60분 (100 vs 200) | 아니오 | 주기 90% 이상, O3 충족 |
| 4 | 명령 시나리오 (goto, stop, emergency_stop, 구역, 위치 보정) | 예 | 3대 모두 통과 |
| 4 | 터널 강제 종료 | 예 | 로봇 정지 · 잠금 |
| 4 | 브로커 재시작 | 예 | 재접속 후 다시 읽기 정상, 이동 자동 재개 없음 |
| 5 | launch 테스트 (`bridge:=dds/mqtt`) | 아니오 | 둘 다 관제 화면 정상 |
| 6 | 3대 60분 운영 (관제 100, 루프백) | 예 | O3 충족, 롤백 없음 |

**롤백 절차** (6단계 이후)

1. 로봇 3대 `emergency_stop`, 관제 launch 종료
2. 로봇: `sudo systemctl stop mqtt_bridge_robot`, DDS 루프백 설정 해제 후 bringup 재시작
3. 관제 PC: `ros2 launch cobot_bringup bringup.launch.xml bridge:=dds`
4. `ROS_DOMAIN_ID=100 ros2 topic echo /pinky1/amcl_pose --once`로 복구 확인

로봇 도메인을 10/20/30으로 유지하기 때문에 2번에서 도메인을 바꿀 필요가 없다.

## 위험 요소와 미결정 사항

가장 큰 위험은 브로커가 한 곳이라는 점과 JSON 변환 부하다. 둘 다 3단계에서 수치로 확인한다.

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 관제 PC 브로커(mosquitto) 장애 | 3대 동시 통신 단절 | heartbeat 상실로 로봇 정지(S2), systemd 자동 재시작 |
| `/scan`·`/tf` JSON 변환 부하 | 지연 증가, load 3.0 초과 시 로봇 쪽 중계 자동 중단 | 주기 제한(`rate_limits`), 필요하면 `/scan` 제외 검토 |
| SSH 터널 끊김 | 해당 로봇 통신 단절 | 터널 서비스 자동 재연결, 브릿지 재접속(1~30초) |
| 두 브릿지 동시 실행 | 명령 이중 발행 | 도메인 분리(100/200), 시작 시 기존 발행자 확인(S4) |
| 로봇 도메인 10에서 `patrol_cmd`를 발행하는 다른 노드 | 명령 충돌 | 3단계 전에 발행자 목록 조사 |
| 3대 공통 비밀번호 | 한 대가 노출되면 3대 모두 노출 | SSH 키 접속으로 전환 후 비밀번호 로그인 비활성화 검토 |

**미결정 사항**

- [ ] 관제→로봇으로 열 토픽과 `cmd_vel` 보호 값
- [ ] `fleet_status`의 브릿지 생존 판단 방식 (노드 이름 vs MQTT status)
- [ ] O3 지연 기준 (현재 domain_bridge 수치 측정 후)

**확정됨** (2026-11-16): 로봇 도메인 10/20/30 유지, 최종 관제 도메인 100, 로봇 주소·계정, 차선 토픽 제거.
