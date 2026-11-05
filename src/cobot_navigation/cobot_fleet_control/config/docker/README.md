# ROS 중앙 실행기 Docker

이 이미지는 `fleet`, `bridge`, `zone-manager`만 실행합니다.
웹 HTTP·WebSocket 서버는 feature/control-center의 `cobot_control_center`를 사용하고
이 이미지에 화면·웹 서버를 다시 넣지 않습니다. MQTT 브로커도 사용하지 않습니다.

## 명령

```bash
# src/cobot_navigation에서 실행
bash cobot_fleet_control/config/docker/fleet_docker.sh build
bash cobot_fleet_control/config/docker/fleet_docker.sh config
bash cobot_fleet_control/config/docker/fleet_docker.sh up
bash cobot_fleet_control/config/docker/fleet_docker.sh logs
bash cobot_fleet_control/config/docker/fleet_docker.sh down
```

`build`와 `config`는 로봇 통신 프로세스를 시작하지 않습니다.
`up`은 관제 도메인 100에서 기존 브릿지·구역 관리자·중앙 실행기를 시작합니다.
호스트에서 같은 서비스를 중복 실행하지 않습니다.
`down`은 DB 볼륨을 보존합니다. 데이터 삭제 옵션을 자동으로 붙이지 않습니다.

## 웹 연결

호스트의 ROS·feature/control-center 환경에서 웹만 추가합니다.

```bash
export ROS_DOMAIN_ID=100
ros2 launch cobot_fleet_control control_center_web.launch.xml \
  navigation_root:=/ws/kernel-robot-repo-4/src/cobot_navigation \
  fleet:=existing mode:=execute
```

웹 서버와 컨테이너 fleet은 같은 ROS 도메인과 네트워크에서 세 토픽으로 연결됩니다.
`task_request`는 웹 → fleet, `task_events`와 `tasks`는 fleet → 웹입니다.
UI 프로세스에서 로봇 명령을 직접 발행하지 않습니다.
이미지에는 선택적 웹 기동기에 필요한 cobot_control_center가 포함돼 있지 않으므로
웹 기동 명령은 해당 패키지가 설치된 호스트/별도 웹 환경에서 실행합니다.

## 버전·데이터

- `versions.env`: ROS 베이스 이미지 digest와 관제 이미지 태그
- `requirements.lock`: py_trees·pydot·pyparsing과 설치 도구의 버전·해시
- `compose.yaml`: 동일 이미지, host network/IPC, fleet-data named volume
- `Dockerfile`: 비루트 UID 10001, 소스 revision·의존성 버전 기록
- `entrypoint.sh`: ROS·워크스페이스 환경을 source한 뒤 실행

SQLite 실행 원장은 `/var/lib/cobot/fleet_control.sqlite3`에 보존됩니다.
`fleet_docker.sh versions`로 실행 이미지의 버전 기록을 확인할 수 있습니다.
코드 변경은 이미지를 다시 빌드하고 작업을 정리한 뒤 재기동해야 반영됩니다.

## 실시간 BT·실행 기록

```bash
# 실행 중인 fleet 원장 조회, 브라우저 http://127.0.0.1:8091
bash cobot_fleet_control/config/docker/fleet_docker.sh view-bt

# 명령별 오프라인 JSON 기록
bash cobot_fleet_control/config/docker/fleet_docker.sh export-bt command-id
```

UNKNOWN 해제는 기존 웹 API의 최신 로봇 상태·시나리오 예약 검사를 거칩니다.
구역·화물이 미확정인 작업을 DB 수정만으로 강제 해제하지 않습니다.

이 환경에서는 Compose 해석과 명령 전달·데이터 보존 계약을 시험했습니다.
Docker 이미지 전체 빌드·실물 DDS 왕복은 현장 환경에서 별도 확인해야 합니다.
