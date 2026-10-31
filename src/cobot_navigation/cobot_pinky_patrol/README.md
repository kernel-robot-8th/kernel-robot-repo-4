# cobot_pinky_patrol

각 Pinky에서 같은 Python 실행기를 사용하고 공통·현장·로봇 설정을 조합합니다. 로봇 한 대마다 프로세스 하나가 실행됩니다. 관제 PC는 `patrol_cmd`로 요청하고 로봇은 Nav2로 주행한 뒤 `patrol_status`로 결과를 보고합니다.

## 설정의 관리 위치

```text
cobot_pinky_patrol/
├── config/
│   ├── common.yaml          # 주기·재시도·준비 제한·초기 회전·유휴 복귀 기본값
│   ├── sites/
│   │   └── lab.yaml         # 공통 map 좌표, 홈 좌표, 구역 소속, EXIT
│   └── robots/
│       ├── pinky1.yaml      # robot_id: pinky1, home_name: I1
│       ├── pinky2.yaml      # robot_id: pinky2, home_name: I2
│       └── pinky3.yaml      # robot_id: pinky3, home_name: I3
├── launch/
│   ├── patrol.launch.xml    # 설정을 선택하는 공통 launch
│   └── pinky{1,2,3}_patrol.launch.xml  # 기존 명령 호환용 include
└── cobot_pinky_patrol/
    ├── pinky_patrol_node.py # 공통 ROS 입출력·초기화·LED
    ├── patrol_controller.py # 명령·구역·정지·유휴 복귀 상태 기계
    ├── async_navigation.py  # 비동기 Nav2 목표 접수·취소·최종 결과
    └── patrol_points_utils.py # 좌표·구역·명령 검증
```

좌표 변경은 `config/sites/lab.yaml` 한 곳에서 합니다. 로봇별 파일에는 ID와 홈 이름을 두며 같은 현장 좌표를 복사하지 않습니다. 로봇을 추가할 때는 `config/robots/<robot_id>.yaml`과 현장에 맞는 홈을 등록합니다. fleet의 `robot_ids`, zone_manager의 `robot_ids`, 도메인 브릿지도 함께 구성해야 합니다.

현재 lab 설정에는 일반 지점 P1~P35가 있습니다. P36~P50의 예비 `[0.0, 0.0, 0.0]` 항목은 제거했으므로 해당 명령은 `unknown point`로 거절됩니다. 일반 지점 이름은 P50까지 지원하지만 실제 좌표를 등록한 지점만 이동할 수 있습니다. 좌표는 map 프레임의 `[x, y]` 또는 `[x, y, yaw]`이며 m·rad 단위, 소수점으로 작성합니다.

대기 앵커·슬롯은 `cobot_zone_traffic_control/config/zone_params.yaml`에서 관리합니다. 현장 파일의 `zone_names`와 해당 매니저의 구역 이름을 맞춥니다. 같은 현장에 배포하는 로봇은 같은 지도와 현장 설정을 사용해야 합니다.

### YAML이 실제로 적용되는 위치

`launch/patrol.launch.xml`이 아래 순서로 ROS 파라미터 파일을 전달합니다. 뒤 파일에서 같은 이름을 지정하면 그 값이 우선합니다.

```xml
<param from="$(find-pkg-share cobot_pinky_patrol)/config/common.yaml"/>
<param from="$(find-pkg-share cobot_pinky_patrol)/config/sites/$(var site).yaml"/>
<param from="$(find-pkg-share cobot_pinky_patrol)/config/robots/$(var robot_id).yaml"/>
```

각 YAML의 `pinky_patrol_node:`는 파일명·클래스명이 아닌 ROS 노드 이름입니다. launch의 `name="pinky_patrol_node"`와 대응하며 Python은 `declare_parameter()`와 `get_parameter()`로 값을 읽습니다. 좌표·구역은 `_load_points()`에서 검증합니다. 설정 누락을 기본 좌표로 채워서 주행하지 않습니다. `robot_id`도 명시해야 합니다.

설정은 시작할 때 읽습니다. 소스를 수정한 뒤 패키지를 재빌드하고 `install/setup.bash`를 source한 후 노드를 다시 실행합니다. 작업 중인 로봇의 설정을 실시간으로 바꾸는 기능은 없습니다.

## 빌드와 실행

Ubuntu 24.04 / ROS 2 Jazzy 기준입니다. 로봇의 드라이버·지도·Nav2 bringup, `pinky_interfaces`, `pinky_led`는 기존 장비 환경을 사용합니다.

```bash
# 로봇 워크스페이스 최상위에서
source /opt/ros/jazzy/setup.bash
colcon build --packages-select cobot_zone_traffic_control cobot_pinky_patrol
source install/setup.bash

# Nav2 bringup을 먼저 실행한 뒤 별도 터미널에서
ROS_DOMAIN_ID=10 ros2 launch cobot_pinky_patrol patrol.launch.xml robot_id:=pinky1 site:=lab
# pinky2: ROS_DOMAIN_ID=20, robot_id:=pinky2
# pinky3: ROS_DOMAIN_ID=30, robot_id:=pinky3
```

`robot_id`는 필수이고 `site` 기본값은 `lab`입니다. 기존 bringup에 LED 서버가 없으면 `start_led:=true`를 추가합니다. 기본값은 false이며 노드에서 서버를 자동 실행하지 않습니다. LED 응답이 지연되어도 주행·정지 콜백은 계속 처리합니다.

관제 PC에서는 기존 도메인 브릿지와 zone_manager를 실행합니다. 도메인은 관제 100, 로봇 10/20/30입니다. [전체 실행 안내](../README.md), [MQTT·관제 계약](../cobot_fleet_control/README.md)을 참고하세요.

### 기존 실행 명령과 설정 경로 이전

아래 launch 명령은 계속 사용할 수 있으며 공통 launch에 로봇 ID를 전달합니다. `site`와 `start_led` 옵션도 전달됩니다.

```bash
ros2 launch cobot_pinky_patrol pinky1_patrol.launch.xml
ros2 launch cobot_pinky_patrol pinky2_patrol.launch.xml
ros2 launch cobot_pinky_patrol pinky3_patrol.launch.xml
```

`pinky_patrol_node_pinky1/2/3` 실행 이름은 같은 `pinky_patrol_node:main`의 별칭으로 유지합니다. 로봇별 Python 파일은 제거했습니다. 로봇 식별은 실행 이름이 아니라 설정으로 지정합니다.

예전 `config/pinkyN.yaml`은 공통·현장·로봇 파일로 분리되어 제거됐습니다. 직접 `ros2 run`하는 스크립트는 단일 예전 파일 대신 세 파일을 전달하도록 변경합니다.

```bash
PATROL_SHARE="$(ros2 pkg prefix --share cobot_pinky_patrol)"
ros2 run cobot_pinky_patrol pinky_patrol_node --ros-args \
  --params-file "$PATROL_SHARE/config/common.yaml" \
  --params-file "$PATROL_SHARE/config/sites/lab.yaml" \
  --params-file "$PATROL_SHARE/config/robots/pinky1.yaml"
```

## 명령과 상태

### 관제의 원격 통합 기동

관제는 이 패키지의 `robot_startup` 실행기를 SSH로 호출해 `pinky_bringup/bringup_robot.launch.xml` → `pinky_navigation/bringup_launch.xml map:=...` → 공통 패트롤 launch를 순서대로 시작할 수 있습니다. 각 단계의 최소 간격과 준비 검사·시간 제한을 적용하며 세 프로세스를 계속 관리합니다. [관제 통합 기동·IP·SSH 설정](../cobot_fleet_control/README.md#관제에서-로봇까지-순차-기동)을 참고하세요.

기본 workspace는 `/ws/kernel-robot-repo-4`, 지도는 로봇의 `~/cobot_map_v9.yaml`입니다. 기존 vendor setup과 이 workspace의 setup을 source한 환경에서 로봇 한 대를 직접 순차 기동하려면 다음 명령을 사용합니다. 이 명령은 실제 프로세스를 시작합니다.

```bash
ros2 run cobot_pinky_patrol robot_startup --robot-id pinky1 --domain-id 10
```

지도 YAML·이미지·vendor 패키지 존재를 먼저 확인합니다. SSH 세션 종료 또는 Ctrl+C 시 이 실행기가 시작한 프로세스를 역순 정리합니다. 이미 수동으로 실행한 bringup·Nav2·패트롤과 함께 중복 실행하지 않습니다.

### 업무 명령

기존 문자열 명령과 관제의 JSON 명령을 모두 처리합니다. JSON은 `{"command_id":"job1","command":"goto:P1,P2"}` 형태이며 최종 응답에 같은 ID와 `task_finished=true`를 붙입니다.

| 명령 | 동작 |
|---|---|
| `goto:P1,P2` | 등록된 구역 밖 일반 지점 또는 자기 홈으로 순서대로 이동 |
| `zone:ZA` | 구역 허가 후 지점 1개로 이동하고 토큰 유지 |
| `leave` | 보유 구역의 EXIT에 도착한 뒤 토큰 반납 |
| `home` | 보유 구역을 EXIT로 나온 뒤 자기 홈으로 이동 |
| `stop` | 이전 액션 종료를 확인하고, 구역 보유 중이면 EXIT 후퇴 |
| `emergency_stop` | 주행 취소, 보유 구역 기억 유지, 유휴 복귀 중단 |
| `start` | 비활성, `start disabled`로 거절 |

구역 밖 지점 이동은 완료 즉시 홈으로 돌아가지 않습니다. 성공 후 `idle_return_sec`(기본 120초) 동안 새 명령이 없으면 복귀합니다. 0 이하이면 유휴 복귀를 끕니다. 실패·정지 후에는 자동 복귀를 예약하지 않습니다.

정지 요청은 `CANCELING`에서 이전 액션의 최종 결과를 기다립니다. 취소 ACK이나 거절만으로 다음 목표를 시작하지 않습니다. 결과가 유실되면 busy를 유지하며 관제 작업은 UNKNOWN이 될 수 있습니다. 구역 관리자의 기존 강제 만료 정책은 별도로 유지됩니다.

관제 PC에서 기존 CLI를 사용할 수 있습니다. fleet의 작업 접수·기록을 사용하려면 MQTT로 요청합니다.

```bash
export ROS_DOMAIN_ID=100
CLIENT=src/cobot_navigation/cobot_pinky_patrol_cmd/pinky_control_client.py
python3 "$CLIENT" pinky1 monitor
python3 "$CLIENT" pinky1 goto P1 P2
python3 "$CLIENT" pinky1 zone ZA
python3 "$CLIENT" pinky1 leave
python3 "$CLIENT" pinky1 home
```

## 검증

`src/cobot_navigation`에서 실행합니다.

```bash
python3 -m pytest cobot_pinky_patrol/test -q
# ROS 액션·토픽 통합 시험은 격리 환경에서만 실행
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest cobot_pinky_patrol/test -q
```

ROS 없는 환경에서는 좌표·명령·상태 기계·설정·설치 등록 검사를 실행하고 ROS 로딩·액션 시험은 건너뜁니다. 테스트의 가짜 Nav2는 실제 현장 주행·브릿지 왕복을 대신하지 않습니다.
