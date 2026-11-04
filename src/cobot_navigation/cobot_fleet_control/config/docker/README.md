# 관제 PC Docker 실행 환경

호스트의 ROS 설치·venv·pip·colcon 작업을 이미지 빌드 안으로 옮깁니다. Linux Docker Engine + Compose 플러그인이 필요합니다. 기존 팀 `scripts/docker/dev.sh`는 격리 개발·시험용이며, 이 구성은 관제·브릿지·구역 매니저를 실제 네트워크에서 실행하는 용도입니다.

## 빠른 실행

저장소의 `src/cobot_navigation`에서 실행합니다. 호스트에 ROS나 Python 패키지를 설치할 필요가 없습니다.

```bash
cd /home/tory/ws/kernel-robot-repo-4/src/cobot_navigation

# 1. 이미지 빌드. 빌드만 하며 ROS 프로세스를 실행하지 않음
bash cobot_fleet_control/config/docker/fleet_docker.sh build

# 2-A. 로컬 MQTT 브로커도 필요한 개발 환경
bash cobot_fleet_control/config/docker/fleet_docker.sh up-local

# 2-B. 기존 브로커를 쓸 때는 2-A 대신 아래 명령
# MQTT_HOST=192.168.0.50 MQTT_PORT=1883 \
#   bash cobot_fleet_control/config/docker/fleet_docker.sh up

# 3. 관제 로그 / 이미지 내부 버전
bash cobot_fleet_control/config/docker/fleet_docker.sh logs -f fleet
# 로그 보기를 끝낸 뒤
bash cobot_fleet_control/config/docker/fleet_docker.sh versions

# 4. 종료. DB·브로커 데이터 볼륨은 보존
bash cobot_fleet_control/config/docker/fleet_docker.sh down
```

`up-local`은 호스트 loopback 1883 포트에 개발용 Mosquitto를 실행합니다. 기존 브로커가 이미 해당 포트를 쓰면 `up`을 사용합니다. 이 브로커는 익명·로컬 접속용이며 외부 UI용 TLS/ACL 브로커는 별도 운영 설정을 사용합니다. 계정이 필요한 브로커는 `COBOT_MQTT_USERNAME`, `COBOT_MQTT_PASSWORD`를 실행 환경으로 전달합니다. TLS CA 마운트가 필요하면 Compose override에서 읽기 전용 인증서 볼륨과 `COBOT_MQTT_CA`를 추가합니다.

기존 호스트의 관제·브릿지·zone_manager와 컨테이너를 중복 실행하지 않습니다. 작업과 구역 점유를 정리한 뒤 업데이트·종료합니다. 구역 매니저 점유 정보는 메모리 상태여서 재시작 시 초기화됩니다. 각 Pinky의 Nav2·새 순찰 실행기는 기존 로봇 실행 절차대로 켭니다.

## 무엇이 고정되나

| 항목 | 고정 방식 |
|---|---|
| ROS·Ubuntu 기반 | `versions.env`의 ROS 이미지 manifest digest |
| Python | ROS Jazzy/Ubuntu 24.04의 Python 3.12 계열 |
| BT·MQTT·하위 의존성 | `requirements.lock`: py_trees 2.2.3, paho-mqtt 2.1.0, pydot 2.0.0, pyparsing 3.1.4 |
| Python 설치 도구 | pip 25.0.1, setuptools 75.8.0과 wheel SHA-256 |
| 관제 코드 | 빌드 시 이미지에 복사. 호스트 소스 bind mount 없음 |
| 선택형 MQTT 브로커 | Mosquitto 2.0.22 이미지 digest |
| 빌드 출처 | OCI revision 라벨, dirty 여부, apt·Python 설치 버전 목록 |

베이스와 Python lock은 고정했지만, 추가 apt 패키지는 빌드 시점 저장소에서 설치합니다. 따라서 서로 다른 날짜에 재빌드한 결과가 완전히 같다고 보장하지 않습니다. **현장 배포는 검증한 완성 이미지 하나를 image ID/digest로 재사용**해야 전체 패키지 버전이 같습니다. `versions`로 실제 설치 내역을 확인합니다. 미커밋 변경이 있으면 revision만으로 소스를 재현할 수 없으므로 dirty=true로 기록합니다.

이미지 버전을 지정하려면 모든 명령에서 같은 `COBOT_IMAGE`를 사용합니다. 개발 기본 태그는 `cobot-fleet:jazzy-bt-v0.2.0`입니다.

```bash
# 배포 코드를 커밋한 뒤 그 커밋을 나타내는 고유 태그를 사용
export COBOT_IMAGE="cobot-fleet:nav-$(git rev-parse --short=12 HEAD)"
bash cobot_fleet_control/config/docker/fleet_docker.sh build

# 같은 머신에서는 build 결과를 그대로 사용
bash cobot_fleet_control/config/docker/fleet_docker.sh up

# 다른 PC에는 완성 이미지 자체를 전달. 아키텍처도 맞아야 함
# docker save -o /tmp/cobot-fleet.tar "$COBOT_IMAGE"
# 대상 PC: docker load -i /tmp/cobot-fleet.tar
```

레지스트리를 사용하는 배포에서는 `COBOT_IMAGE=registry/이미지@sha256:검증한_digest`로 설정하고 `up`을 실행할 수 있습니다. 태그 이름만으로 이미지 불변성이 보장되는 것은 아닙니다. 이 도구는 레지스트리 push나 태그 생성을 자동으로 수행하지 않습니다.

## 서비스와 네트워크

- `bridge`: 기존 `bridges.launch.xml`. 관제 100 ↔ 로봇 10/20/30.
- `zone-manager`: 기존 구역 FIFO·토큰 관리자 1개.
- `fleet`: 관제 BT·MQTT·SQLite. 기존 launch와 같은 노드를 `ros2 run`으로 실행하고 DB·MQTT 파라미터만 컨테이너 경로에 맞게 지정합니다.
- `broker`: `up-local`에서만 켜는 선택형 개발 브로커.

ROS 서비스는 `network_mode: host`와 `ipc: host`를 사용합니다. Fast DDS 공유 메모리는 동일 UID 10001인 관제 컨테이너끼리 공유합니다. Linux 관제 PC와 로봇 사이의 DDS multicast·방화벽·실제 토픽 왕복 확인이 필요합니다. `depends_on: service_started`는 프로세스 실행 순서이며 ROS 탐색·MQTT 연결 완료를 보장하지 않습니다. `logs`, MQTT 이벤트, 실제 로봇 상태로 준비 상태를 확인합니다.

자동 재시작은 기본으로 끕니다. 작업 중 서버 재시작 시 기존 명령은 UNKNOWN이 될 수 있으며 물리 동작이 자동으로 정지되는 것은 아닙니다. 하드웨어 비상정지는 별도로 유지합니다.

## DB와 BT 기록

DB는 Docker named volume의 `/var/lib/cobot/fleet_control.sqlite3`에 저장합니다. 컨테이너를 교체하거나 기본 `down`을 실행해도 남습니다. 기존 호스트 `~/.cobot/fleet_control.sqlite3`를 자동 복사하지는 않습니다.

```bash
# 컨테이너 내부 DB를 읽고 결과 JSON만 호스트 파일로 받음
bash cobot_fleet_control/config/docker/fleet_docker.sh export-bt job-run-001 \
  > /tmp/bt_trace.json

# 브라우저에서 HTML을 열고 /tmp/bt_trace.json 선택
xdg-open docs/control_server_bt_report.html
```

`export-bt`는 실행 중 fleet 컨테이너가 필요합니다. 새 셸에서도 ROS 환경이 로드되도록 컨테이너 entrypoint를 거쳐 실행합니다. HTML은 기록 재생이며 컨테이너 시작과 함께 자동으로 열리거나 실시간 갱신되지는 않습니다.

## 파일과 검증 범위

- `Dockerfile`: 세 패키지 설치·빌드, 일반 사용자, 설치 버전 기록.
- `compose.yaml`: 같은 이미지로 세 관제 서비스 실행, 선택형 브로커와 데이터 볼륨.
- `versions.env`, `requirements.lock`: 이미지·Python 버전 고정.
- `entrypoint.sh`: ROS와 workspace 환경 로드 후 exec.
- `fleet_docker.sh`: 빌드·실행·로그·버전·BT 내보내기 진입점.
- `mosquitto.conf`: 로컬 개발 브로커 설정.
- 저장소 내 `cobot_navigation/.dockerignore`: 관제 패키지 외 지도·venv·Git·비밀 파일을 build context에서 제외.

확인한 것: 공식 registry digest 조회, 실제 wheel의 SHA-256 고정 설치, 같은 Python lock 환경에서 관제·교통 제어·C++ 브릿지 네이티브 빌드, 관제 BT 회귀 테스트, 공식 Compose 파서의 기본/로컬 브로커 프로필 해석, 실행 스크립트 인자·DB 보존 계약.

현재 작업 환경에는 Docker CLI·데몬이 없어 **이미지 전체 빌드와 컨테이너 기동, Docker에서 실물 DDS 연결은 미검증**입니다. Docker가 있는 Linux PC에서 `build → up/up-local → logs → MQTT 명령·결과 확인`으로 최종 검증해야 합니다.

참고: [Docker 이미지 digest 고정](https://docs.docker.com/build/building/best-practices/), [Compose 네트워크](https://docs.docker.com/compose/how-tos/networking/), [Compose 실행 순서](https://docs.docker.com/compose/how-tos/startup-order/).
