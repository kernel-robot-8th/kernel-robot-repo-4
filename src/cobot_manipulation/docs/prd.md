# cobot_manipulation PRD — Station PC 팔 노드

- 상태: 뼈대 (2026-11-14). 실제 팔 동작 백엔드가 아직 없다.
- 담당: 로봇팔 팀 (CODEOWNERS). 관제 계약 부분은 로봇 수행 관제 담당이 함께 본다.
- 공통 명세와 다르면 공통 명세(`docs/fms_interfaces.md`)를 따른다. 단, 지금 관제가 실제로 쓰는 계약은
  아래 1번이다. 정식 메시지(`ArmCommand`·`ArmStatus`·`HandoverTask`)로 옮기는 일은 팀이 따로 정한다.

## 0. 하는 일

관제를 띄우지 않는 Station PC 에서 팔 3대(omx1~3)를 맡는다.
관제 PC 의 `fleet_control_node` 가 보내는 작업 요청을 팔 1대씩 받아 처리하고 실측 결과를 돌려준다.

```text
[관제 PC] fleet_control_node
   │ /fleet/work_request (std_msgs/String JSON)
   ▼
[Station PC] omx1_adapter · omx2_adapter · omx3_adapter   (같은 실행 파일, arm_id 만 다름)
   │ 백엔드 (none / fake / 나중에 실제 팔)
   ▼ /fleet/work_result (std_msgs/String JSON)
```

## 1. 관제 계약 (정본: cobot_fleet_control 코드)

### 요청
`fleet_control_node.work()` 와 `scenario_runtime` 이 만든다. 이 노드는 `target` 이 자기 `arm_id` 인 것만 본다.

| 필드 | 뜻 |
|---|---|
| `request_id` | 요청 고유 번호. 같은 번호는 한 번만 실행 |
| `order_id`, `robot_id`, `stage` | 결과에 그대로 돌려준다 |
| `target` | 받을 팔 (`omx1` 등) |
| `action` | `pick`, `load`, `unload`, `warehouse_store`(반품 하차), `hold`, `release_hold` |
| `session_id`, `seq` | 관제 노드 실행마다 새 session. seq 는 target 별 증가 |
| `issued_at`, `ttl_sec` | [s] 관제 PC 시각, 유효 시간 (5 s) |
| `sku`, `quantity`, `attempt`, `route`, `timeout_sec` | 작업 정보 |

| stage | 팔 | action |
|---|---|---|
| `PICK` / `LOAD` | 상차 팔 (`route.pickup_arm`) | `pick` / `load` |
| `PICK_DROPOFF` / `UNLOAD` | 하차 팔 (`route.dropoff_arm`) | `pick` / `unload` 또는 `warehouse_store` |
| `SAFETY` | 경로의 팔 | `hold` / `release_hold` (관제는 결과를 기다리지 않음) |

### 결과
`scenario_runtime.receive()` 가 검사한다. 하나라도 틀리면 결과를 **조용히 버린다**.

```json
{"request_id": "...", "order_id": "...", "robot_id": "...", "stage": "...",
 "source": "omx1", "measured": true, "finished": true,
 "success": true, "detail": "(실패 이유, 선택)", "data": {"arm_safe": true}}
```

- 실패에 `data.retry_safe=true` 가 없으면 관제는 재시도하지 않고 주문을 보류한다.
  이 노드는 **팔을 움직이기 전에 거절한 경우에만** `retry_safe` 를 붙인다 (탐지 안 됨, 만료, 시계 차이, 정지 유지 중, 작업 중, 백엔드 없음).
- 작업 도중 `hold` 나 보드 연결 끊김으로 끝나면 팔 자세를 모르므로 `retry_safe` 없이 실패를 보낸다.

### 요청 판정 순서
1. `target` 이 다르면 무시. 필수 필드가 없으면 무시 (결과를 보낼 수 없다).
2. 이미 본 `request_id` 면 무시 (최근 `dedupe_size` 개).
3. `session_id` 가 바뀌면 seq 기록을 비운다. seq 가 줄면 무시.
4. 만료(`now > issued_at + ttl_sec`)나 미래 시각(`issued_at > now + ttl_sec`)이면 거절 (retry_safe).
5. 모르는 action 은 거절 (retry_safe 없음).
- `hold` 는 3·4번에 걸려도 실행한다. 멈춤을 거절하는 쪽이 더 위험하다 (D4 추천안).
- 시계 비교가 있으므로 두 PC 는 chrony 등으로 시계를 맞춘다.

## 2. 팔 탐지

- OpenRB-150 보드는 칩 고유 시리얼을 `/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_<시리얼>-if00` 로 드러낸다.
  어느 PC·포트에 꽂아도 같아서 udev 규칙·`sudo` 가 필요 없다. 노드는 **이름만 읽고 장치를 열지 않는다**.
- 등록표 `config/arm_registry.yaml` 은 '팔 자리 이름 ↔ 그 자리에 있어야 할 보드 시리얼' 이다.
  팔 자리 이름은 관제 `scenario.yaml` 의 `pickup_arm`·`dropoff_arm` 과 같다.
- READY 는 등록된 시리얼이 정확히 1개 보일 때뿐이다. 아래는 모두 UNKNOWN 이고 작업을 거절한다.
  시리얼 미등록, 연결 안 됨, 같은 시리얼이 여러 팔에 등록됨, 같은 시리얼이 여러 장치에서 보임.
- `detect_period_sec` 마다 다시 본다. 작업 중 보드가 사라지면 멈추고 실패로 끝낸다.
- 시리얼은 보드의 번호다. 보드를 다른 팔과 바꿔 끼우면 틀리게 판단하므로 보드와 팔에 같은 이름표를 붙인다.

새 팔 등록:
```bash
ls -l /dev/serial/by-id   # 시리얼을 읽어 arm_registry.yaml 의 빈 칸에 넣는다
```

## 3. 백엔드

| 이름 | 동작 | 쓰는 곳 |
|---|---|---|
| `none` (기본) | 모든 작업을 거절 (retry_safe) | 실제 백엔드가 생기기 전 실물 PC |
| `fake` | `fake_duration_sec` 뒤 성공, `data.fake=true` | 격리 도메인 시험만. 실물 도메인 0·10·12·20·30·100 이면 시작 거부 |

실제 팔 백엔드 추가 방법 (로봇팔 팀):
1. `arm_backend_utils.ArmBackend` 를 상속해 `start()`·`poll()`·`hold()`·`release_hold()` 를 구현한다.
   `poll()` 은 동작이 끝나고 **팔이 안전 자세로 물러난 것을 실측했을 때만** 결과를 돌려준다.
   `data` 에 `arm_safe` 등 실측 값을 담는다.
2. `make_backend()` 에 이름을 등록하고 launch 의 `backend` 인자로 고른다.
3. `start()` 에는 탐지된 포트(`/dev/serial/by-id/...`)가 넘어온다.

## 4. 실행

```bash
colcon build --symlink-install --packages-select cobot_manipulation
source install/setup.bash
# 관제 PC 와 같은 ROS_DOMAIN_ID. 시험은 격리 도메인 + fake
export ROS_DOMAIN_ID=101 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch cobot_manipulation arm_station.launch.xml backend:=fake
```

launch 인자: `backend`, `registry_file`, `enable_omx1`·`enable_omx2`·`enable_omx3`.
파라미터: `config/arm_adapter.yaml`.

## 5. 아직 안 된 것

- 실제 팔 동작 백엔드.
- 관제 `scenario.yaml` 에 omx3 경로가 없다 (omx3 역할 미정). 지금은 관제가 omx3 에 요청을 보내지 않는다.
- 관제 PC cyclonedds Peers 에 Station PC IP 추가.
- 정식 `ArmStatus` (`/manipulation/<arm_id>/status`) 발행.
