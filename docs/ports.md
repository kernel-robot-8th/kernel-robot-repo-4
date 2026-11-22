# 관제 PC 포트 표

2026-11-22 기준입니다. 관제 PC 에서 쓰는 웹·보조 포트를 이 문서 한곳에 모읍니다.
각 README·launch 주석의 포트 번호는 이 표를 따릅니다. 새 포트가 필요하면 먼저 이 표에서 빈 번호를 확인한 뒤 함께 고칩니다.

## 규칙

- **서비스용은 80xx** 를 씁니다. 현장 운영 화면이고 내부망에 공개합니다.
- **개발·시험용은 81xx** 를 씁니다. 실물을 보기만 하거나 격리 도메인에서 돕니다. 서비스 화면의 개발용 짝은 끝자리를 맞춥니다 (8080 → 8180).
- 관제 도커(`cobot_fleet_control/config/docker`)는 `network_mode: host` 라서 컨테이너가 쓰는 포트도 이 PC 포트를 그대로 차지합니다.
- 8080 은 **bringup 관제와 도커 관제(web) 중 하나만** 켭니다. 8081 도 직접 켠 `customer_gateway` 와 도커 `customer` 중 하나만 켭니다.
- 6000 등 크롬이 막는 포트(ERR_UNSAFE_PORT)는 쓰지 않습니다.

지금 무엇이 떠 있는지 볼 때:
```bash
ss -ltnp | grep -E ':8[01][0-9]{2}\b'
```
도커나 다른 사용자 프로세스는 이름이 안 보일 수 있습니다. 그때는 `docker ps` 와 `ps -eo pid,user,args | grep <포트>` 로 봅니다.

## 서비스용 80xx

| 포트 | 서비스 | 띄우는 것 | 도메인 | 담당 |
|---|---|---|---|---|
| 8080 | 실물 관제 화면 `fleet_api_node` | `cobot_bringup bringup.launch.xml` 또는 도커 `web` | 100 | 김지혜 |
| 8081 | 고객 주문 화면 `customer_gateway` (자리 QR `:8081/?loc=<자리>`) | `cobot_gui customer_gateway.launch.xml` 또는 도커 `customer` | 100 | 김성아 |
| 8082 | 비워 둠 (서비스용 예비) | – | – | – |
| 8083 | 이상 감지 콘솔 `anomaly_monitor` (127.0.0.1) | `cobot_anomaly_monitor` | – | 강건한 |
| 8084 | 자원 수집기 (중계 장비) | `cobot_gui/web` 자원 모니터링이 봄 | – | 강건한 |

## 개발용 81xx

| 포트 | 서비스 | 띄우는 것 | 도메인 | 담당 |
|---|---|---|---|---|
| 8180 | 개발 관제 (읽기 전용, 8080 의 개발 짝) | `cobot_control_center fleet_api_dev.launch.xml` | 100 (보기만) | 김지혜 |
| 8181 | 가짜 핑키 관제 | `cobot_mock mock_fleet.launch.xml` | 101 (LOCALHOST) | 김지혜 |
| 8182 | 가제보 시뮬 관제 | `cobot_gazebo sim_fleet.launch.xml` | 140~143 | 김지혜 |

2026-11-22 이전에는 가짜 핑키 8081, 가제보 8082, 개발 8083 이었습니다. 8081 은 고객 화면, 8083 은 이상 감지 콘솔과 겹쳐서 옮겼습니다.
즐겨찾기나 SSH 터널(`ssh -N -L 8181:127.0.0.1:8181 ...`)을 쓰던 분은 새 번호로 바꿉니다.

## 그 밖의 보조 도구

아직 위 규칙에 맞춰 옮기지 않은 포트입니다. 81xx 로 옮길지는 각 담당과 정합니다.

| 포트 | 쓰임 | 어디 |
|---|---|---|
| 8088 | ROS 2 네트워크 진단 화면 | `cobot_navigation/ros2_network_test/net_monitor.py` |
| 8091 (예비 8092) | BT 보기 | `cobot_navigation/cobot_fleet_control/bt_viewer.py` |
| 8785 (127.0.0.1) | AMCL 보정 HTTP 입력 | `cobot_navigation/cobot_amcl_corrector` |
| 8893 / 8554 | edge_view 화면 / RTSP 시험 | `scripts/vision/edge_view` |
| 5173 | 고객 웹 Vite 개발 서버 | `cobot_gui/web` |
| 1883 (127.0.0.1) | MQTT 브로커 (mosquitto) | `scripts/vision/homelab_vision` |
| 7400~ | DDS (ROS 2 자체) | – |

관제 PC 밖의 장치: 천장 CCTV MJPEG `http://192.168.0.7:18086/processed` (`fleet_api_node.yaml` 의 `cctv_url`, 관제가 받아서 8080 화면으로 중계).
