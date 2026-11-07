# 새 관제 PC의 Docker 설치·기동

Ubuntu 24.04 Linux 관제 PC에서 기존 웹, fleet, bridge, zone-manager를 같은 이미지로 실행합니다.
호스트에는 ROS·py_trees·FastAPI 설치나 workspace source가 필요 없습니다.
핑키의 드라이버·Nav2·patrol은 각 로봇에서 실행합니다.

## 최초 설치

저장소를 내려받은 뒤 다음 순서로 실행합니다. 호스트 설치기는 Docker 공식 apt 저장소를 사용합니다.
[Docker 공식 Ubuntu 설치 절차](https://docs.docker.com/engine/install/ubuntu/)

```bash
cd ~/ws/kernel-robot-repo-4/src/cobot_navigation
sudo bash cobot_fleet_control/config/docker/install_host.sh
sudo bash cobot_fleet_control/config/docker/install_host.sh --check
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh build
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh config
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh check
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh smoke
```

Docker 소켓 접근 권한이 이미 있으면 fleet_docker.sh의 sudo는 생략할 수 있습니다.
설치기는 기존 Docker·containerd 패키지를 자동 제거하지 않습니다.
Docker와 Compose가 이미 있으면 설치 대신 버전·데몬 접근을 확인합니다.
이미지 빌드에는 Ubuntu/ROS 패키지 저장소와 PyPI 접근이 필요합니다.
고정 웹 커밋이 로컬 Git에 없으면 build가 호스트에서 origin으로부터 가져옵니다.
웹 원본은 .docker-context/control-center에 추출하며 Git 인증을 이미지에 전달하지 않습니다.

`build`, `config`, `check`는 웹 서버나 로봇 통신 노드를 시작하지 않습니다.
`check`는 이미지의 Python·기존 웹 모듈을 import하고 지도·지점 설정으로 기동 계획을 검증합니다.

`smoke`는 외부 네트워크가 없는 임시 컨테이너(`--network none`)에서 도메인 77·localhost로
중앙 실행기·상태 수집기·웹 서버를 시작합니다. 웹 화면·지도·작업 목록의 HTTP 응답과
`/ws/fleet`·`/ws/tasks`의 실제 WebSocket 연결, 작업 명령 꺼짐 상태를 확인한 뒤 종료합니다.
운영 DB 볼륨과 호스트 포트를 연결하지 않으며, 테스트 DB는 컨테이너 종료 시 제거됩니다.

## Python 가상환경

Docker 빌드는 이미지 안에 `/opt/cobot/venv`를 자동 생성하고 `requirements.lock`의
의존성을 설치합니다. FastAPI·Uvicorn과 ROS는 이미지의 apt 패키지 경로를 공유합니다.
호스트의 `.venv`나 `build/fleet_runtime/venv`는 컨테이너 실행에 필요하지 않습니다.
Git에는 Dockerfile·설치 스크립트·의존성 목록을 저장하며 가상환경 파일 자체는 저장하지 않습니다.

## 실행과 종료

수동으로 실행한 bridge·zone_manager·fleet_control·기존 task_manager·웹은 먼저 정리합니다.
같은 도메인에서 명령을 처리하는 실행기는 fleet 하나만 유지합니다.
zone_manager가 점유 상태를 메모리에 보관하므로, 전환은 작업을 멈추고 실제 구역 상태를 확인한 뒤 진행합니다.

```bash
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh up
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh ps
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh logs --tail=100
# 종료: 실행 원장 볼륨 보존
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh down
```

관제 PC 브라우저: **http://127.0.0.1:8080**.
`up`은 bridge → zone-manager/fleet → web의 의존 관계에 따라 네 서비스를 실행합니다.
프로세스 기동 순서이며 로봇 준비 완료를 보장하는 검사는 아닙니다.
웹은 기존 fleet_api_node·fleet_status_node만 시작하고 `fleet:=existing`으로 fleet에 연결합니다.
기존 task_manager_node는 시작하지 않습니다. 작업 명령은 시작 시 꺼져 있습니다.
웹 healthcheck는 HTTP 응답만 확인하며 로봇의 통신·배터리·주행 준비 완료와 구분합니다.

기본 ROS 도메인은 관제 100, pinky1/2/3은 10/20/30입니다.
Linux host network/IPC를 사용하며 DDS 탐색 범위는 SUBNET입니다.
로봇과 같은 네트워크에서 DDS 통신이 가능해야 합니다. Docker가 Wi-Fi·방화벽·DDS 탐색 문제를 자동 해결하지는 않습니다.

기본 RMW는 Cyclone DDS이며 Fast DDS도 이미지에 설치합니다. 필요하면 전 서비스에 동일하게 적용합니다.

Cyclone DDS는 이미지의 `/opt/cobot/cyclonedds.xml`로 로봇망 `192.168.45.0`에 해당하는
관제 PC 인터페이스를 선택하고 핑키 IP `.21`·`.22`·`.23`을 피어로 등록합니다.
유선 인터넷과 로봇 Wi-Fi를 함께 쓰는 PC에서도 로봇망으로 DDS 주소를 알리기 위한 설정입니다.
다른 현장이면 `config/docker/cyclonedds.xml`의 네트워크·피어를 수정하고 이미지를 재빌드합니다.
`COBOT_CYCLONEDDS_URI`로 컨테이너 안의 다른 설정 경로나 인라인 XML을 지정할 수도 있습니다.
호스트 셸의 `CYCLONEDDS_URI`는 컨테이너에 자동 전달되지 않습니다.

```bash
sudo env COBOT_RMW_IMPLEMENTATION=rmw_fastrtps_cpp bash cobot_fleet_control/config/docker/fleet_docker.sh up
# 다른 PC에서 웹에 접속하려면 (기본은 관제 PC 내부 전용)
sudo env COBOT_WEB_HOST=0.0.0.0 COBOT_WEB_PORT=8080 bash cobot_fleet_control/config/docker/fleet_docker.sh up
```

## 포함되는 코드와 의존성

- 기존 웹: `versions.env`의 control-center 고정 커밋에서 cobot_control_center·cobot_patrol_interfaces를 가져와 수정 없이 빌드
- ROS Jazzy·C++ 브릿지 의존성, FastAPI·Uvicorn: 이미지 빌드 시 apt 설치
- py_trees·pydot·pyparsing·설치 도구: requirements.lock의 버전·해시로 venv에 설치
- 지도: map_view_pc/maps/cobot_map_v9.yaml·pgm
- 지점: cobot_pinky_patrol/config, 웹 기동 시 원본 설정에서 자동 내보내기
- fleet: 같은 지점 설정을 사용해 명령 전달 전 목적지 검증

새 PC에서는 호스트의 별도 `install/control_center_web/local_setup.bash`가 필요 없습니다.
기존 수동 설치 경로는 [전체 HTML](../../../docs/central_scenario_control.html#ui-transport)의 대안으로 유지합니다.
웹의 개별 이동·정지·해제 계약을 재사용하며 전체 주문·수령·복구 UI 추가 연결은 남아 있습니다.

## 버전·데이터와 조회

`versions.env`는 ROS 이미지 digest·관제 이미지 태그·control-center 커밋을 기록합니다.
완성 이미지는 같은 ID/digest로 배포하고 apt 설치 버전은 이미지 안 dpkg.tsv에 기록합니다.
현재 고정한 것은 ROS 베이스·웹 소스·Python lock이며 apt 저장소 전체를 시점 고정한 것은 아닙니다.

```bash
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh versions
# 브라우저: http://127.0.0.1:8091
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh view-bt
sudo bash cobot_fleet_control/config/docker/fleet_docker.sh export-bt command-id
```

SQLite 실행 원장은 fleet-data 볼륨의 `/var/lib/cobot/fleet_control.sqlite3`에 보존됩니다.
기존 호스트의 `~/.cobot/fleet_control.sqlite3`를 자동 이관하지 않습니다.
전환 전에 기존 미종료 작업을 확인해야 하며, UNKNOWN을 DB 수정으로 강제 해제하지 않습니다.
코드·지도·지점 설정을 변경하면 이미지를 다시 빌드하고 작업을 정리한 뒤 재기동합니다.

## 검증 범위

2026-11-07 관제 테스트 142개가 통과했으며 도메인 77·localhost의 격리 DDS 시험도 포함합니다.
Docker Engine에서 전체 이미지를 빌드하고 `check`와 `smoke`를 통과했습니다.
`smoke`에서 웹 화면·지도·작업 목록은 HTTP 200, 두 WebSocket은 101 응답과 초기 JSON을
확인했습니다. 작업 명령은 꺼진 상태였으며, 임시 실행기와 테스트 컨테이너는 종료했습니다.
Compose 구성 해석·shell 구문·변경 Python 파일의 flake8 검사도 통과했습니다.
GitHub Actions의 fleet-docker 작업은 전체 이미지를 빌드하고 `--network none`에서 웹 의존성·기동 계획을 검사합니다.
커밋 `903bbb6`은 전체 이미지 빌드와 컨테이너 내부 의존성·기동 계획 검사까지 통과했습니다.
같은 실행의 fleet-control·fms-contract·fms-web도 모두 통과했습니다.
[CI 검증 결과](https://github.com/kernel-robot-8th/kernel-robot-repo-4/actions/runs/42024585369)
실제 로봇과의 DDS 왕복·물리 주행은 별도 현장 검증이 필요합니다.
