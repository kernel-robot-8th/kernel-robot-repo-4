# cobot_navigation

Pinky 주행과 중앙 시나리오를 담당합니다. 웹 UI 통신은
[`feature/control-center`](https://github.com/kernel-robot-8th/kernel-robot-repo-4/tree/feature/control-center)의
`cobot_control_center`를 그대로 사용합니다.

## 현재 통신 경로

```text
브라우저: cobot_control_center/web
  ├─ HTTP: 작업 생성·정지·해제·작업 명령 켜기
  └─ WebSocket: /ws/fleet, /ws/tasks
           ↕
control-center의 fleet_api_node / fleet_status_node
           ↕ ROS String JSON
/control_center/task_request → cobot_fleet_control
/control_center/task_events  ← 응답·작업 변경
/control_center/tasks        ← 작업 목록·실행기 상태
           ↕
기존 domain bridge → Pinky patrol → Nav2
```

웹 서버·정적 화면·카메라·상태 집계는 `cobot_control_center` 소유입니다.
`cobot_fleet_control`은 시나리오·실행 원장과 로봇 명령만 담당합니다.
MQTT 브로커·Paho·MQTT 명령 토픽은 사용하지 않습니다.
`src/cobot_gui/web`의 React 화면과 CI는 별도 구성이고, 여기서 실행하는 UI는
control-center 브랜치의 `src/cobot_control_center/web`입니다.

[구조·실행·검증·장치 연동 HTML](docs/central_scenario_control.html)

## 패키지 역할

| 폴더 | 역할 |
|---|---|
| `cobot_fleet_control` (`src/cobot_fleet_control/` 로 이동, 관제 담당) | 주문별 전체 BT·주행 BT, 웹 요청 호환, 실시간 BT 조회, SQLite 실행 원장 |
| `cobot_domain_bridge` | 관제 도메인 100과 로봇 10/20/30 사이 중계 |
| `cobot_zone_traffic_control` | 구역 진입·FIFO 슬롯·실제 이탈 전 점유 유지 |
| `cobot_pinky_patrol` | 로봇 측 Nav2 실행, 명령 ID·세션·통신 감시 |
| `map_view_pc` | 지도·좌표 확인 도구 |
| `ros2_network_test` | 네트워크 진단 도구 |

## 웹과 중앙 실행기 함께 기동

현재 브랜치의 `cobot_control_center`는 웹 실행 파일이 없는 이전 버전입니다.
먼저 **feature/control-center의 패키지를 별도 워크스페이스에서 빌드·source**하고,
그 위에 현재 navigation 패키지를 빌드·source해야 합니다. 이 변경은 해당 브랜치를 자동 병합하지 않습니다.
설치된 패키지에 `fleet_api.launch.xml`이 없으면 새 기동기는 원인을 출력하고 중단합니다.

```bash
# 관제 PC: ROS와 feature/control-center 설치 환경을 먼저 source
colcon build --packages-select cobot_fleet_control cobot_domain_bridge cobot_zone_traffic_control
source install/setup.bash
export ROS_DOMAIN_ID=100

# 읽기 전용 미리보기. 파일·서버·로봇을 실행하지 않음
ros2 launch cobot_fleet_control control_center_web.launch.xml \
  navigation_root:=/ws/kernel-robot-repo-4/src/cobot_navigation

# 실제 웹·상태 노드와 fleet 시작. 작업 명령은 꺼짐으로 시작
ros2 launch cobot_fleet_control control_center_web.launch.xml \
  navigation_root:=/ws/kernel-robot-repo-4/src/cobot_navigation mode:=execute
```

브릿지·zone_manager와 로봇 bringup/Nav2/patrol은 기존 순서대로 먼저 준비합니다.
이미 `fleet_startup`으로 fleet이 실행 중이면 `fleet:=existing`을 추가해 웹·상태 노드만 켭니다.
기존 fleet에도 지점 검증을 적용하려면 `patrol_config_dir`에 현재 `cobot_pinky_patrol/config`를 지정합니다.
화면 주소는 기본 `http://127.0.0.1:8080`입니다.

작업 노드는 `fleet_control_node` 하나입니다. 예전 `task_manager_node`(cobot_control_center)는 2026-11-09 삭제했고, 웹 HTTP·WebSocket 형식은 그대로입니다.
같은 도메인에 fleet 을 둘 띄우지 않습니다 (예: 컨테이너 fleet 과 bringup 의 fleet). fleet 은 요청 수신자·명령 발행자가 둘이면 명령을 거절합니다.

웹 지도는 기존 `<points_dir>/pinky1.yaml` 형식을 읽습니다. 기동기가 현재
`common.yaml + sites/lab.yaml + robots/pinkyN.yaml`을 조합해 사용자 캐시 폴더로 자동 내보냅니다.
원본 좌표를 두 곳에서 수동 관리하지 않습니다.

## 로봇 기동

| 로봇 | IP | 도메인 | 홈 |
|---|---|---|---|
| pinky1 | 192.168.45.21 | 10 | I1 |
| pinky2 | 192.168.45.22 | 20 | I2 |
| pinky3 | 192.168.45.23 | 30 | I3 |

```bash
# 각 로봇의 기존 vendor ROS 환경에서 순서대로 실행
ros2 launch pinky_bringup bringup_robot.launch.xml
ros2 launch pinky_navigation bringup_launch.xml map:="$HOME/cobot_map_v9.yaml"
ros2 launch cobot_pinky_patrol patrol.launch.xml robot_id:=pinky1 site:=lab
```

관제에서 SSH로 순차 기동하려면 `cobot_fleet_control/config/fleet_startup.yaml`의 계정을 채웁니다.
`ros2 launch cobot_fleet_control fleet_startup.launch.xml`은 미리보기이고,
`execute:=true`를 지정해야 실제 기동합니다. 자세한 절차는 [fleet README](../cobot_fleet_control/README.md)를 봅니다.

## 시나리오·추론 PC 경계

- 주문·배정·상하차 순서·수령·복귀는 fleet이 관리합니다.
- 비전·정밀 정차는 `/fleet/work_request`와 `/fleet/work_result` 계약을 사용합니다.
- **별도 추론 PC의 ACT 코드·모델은 이 패키지에 합치지 않습니다.** 그 PC에는 아직 통신 API가 없으며,
  논의한 원격 HTTP 제어 서버·클라이언트는 이번 웹 통신 정리와 별도 작업입니다.
- 현재 웹의 단일 작업 API는 연결됐고, 주문·수령·시나리오 복구 화면은 기존 웹 백엔드에 확장이 필요합니다.
- 실제 추론·팔·비전 완료를 가정해 성공 응답을 만들지 않습니다.

## 주행 설정·안전 동작

좌표 정본은 `cobot_pinky_patrol/config/sites/lab.yaml`, 로봇 식별은 `config/robots/`입니다.
P36~P50 같은 미등록 예비 지점은 사용할 수 없습니다.
중앙 모드 `central_controlled=true`에서는 문자열 CLI 이동을 받지 않고 자동 유휴 복귀를 하지 않습니다.
관제 하트비트 단절은 로봇 측 정지 래치로 이어지며, 통신 회복만으로 재개하지 않습니다.
구역 점유는 시간 초과만으로 풀지 않습니다.
배터리는 실제 5초 발행 주기에 맞춰 별도 만료 시간 `battery_stale_sec=10.0`을 사용합니다.

## 검증

`cobot_fleet_control/test`에는 실행 로직·웹 요청 계약·실제 control-center FastAPI/TaskStore와의
HTTP·WebSocket 호환 시험이 있습니다. 웹 통합 시험은 control-center 패키지와 FastAPI/httpx가 있을 때 실행합니다.
GitHub Actions `fleet-control` job은 같은 커밋의 `src/cobot_control_center`로 같은 시험을 실행합니다.
실제 ROS DDS 왕복 시험은 격리 도메인 77·localhost에서만 실행합니다.
