# OMX 추론 worker

관제(OMEN) fleet의 주문 BT가 상차 `PICK` 단계에 오면 `/fleet/work_request`로 작업을 요청합니다.
추론 PC의 `omx_infer_worker_node`가 이 요청을 받아 `bash infer.sh <위치번호>`를 실행하고,
결과를 `/fleet/work_result`로 돌려줍니다.

```
fleet (OMEN, 도메인 100) ── /fleet/work_request ──▶ omx_infer_worker (추론 PC)
                         ◀── /fleet/work_result ──      └ bash infer.sh <slot>
```

## 처리 범위
- `target == arm_id`(기본 `omx1`)이고 `action`이 `actions`(기본 `[pick]`)에 있는 요청만 처리합니다.
- `load`는 처리하지 않습니다. 상차 성공 여부는 별도 통신(YOLO)이 판정합니다.
  fleet은 LOAD 결과의 `source`가 `omx1`인지 검사하므로 그 쪽도 `source: omx1`로 보내야 합니다.

## 요청 → 결과 계약
요청(fleet `scenario_runtime.py` `dispatch()`가 보냄, `slot`은 주문 DB 연동 후 추가 예정):
```json
{"request_id":"<uuid>","order_id":"order1","robot_id":"pinky1","stage":"PICK",
 "target":"omx1","action":"pick","sku":"...","timeout_sec":300.0,"slot":2}
```
결과(fleet `receive()`가 `request_id`·`robot_id`·`stage`·`source`를 대조):
```json
{"request_id":"<요청 값>","order_id":"order1","robot_id":"pinky1","stage":"PICK",
 "source":"omx1","measured":true,"finished":true,"success":true,
 "detail":"추론 종료","data":{"slot":2,"retry_safe":false}}
```

| 상황 | success | retry_safe | fleet 동작 |
|---|---|---|---|
| 종료 코드 0 | true | false | 다음 단계 진행 |
| `slot` 없음·범위 밖, 다른 요청 실행 중, 실행 불가 | false | true | 같은 단계 재시도 (팔 미동작) |
| 종료 코드 ≠ 0, 시간 초과 | false | false | 주문 중단 → 운영자 복구 |

- 시간 초과 기준은 요청 `timeout_sec - timeout_margin_sec`입니다. 초과하면 스크립트 프로세스 그룹 전체를 종료하므로 팔이 중간 자세로 멈출 수 있습니다.
- 스크립트는 stdin 없이 실행됩니다. 키보드 입력을 기다리지 않게 작성해야 합니다.
- 종료 코드 0은 "실행이 끝났다"는 뜻이며, 실제 집기·적재 성공은 뒤의 비전 검증 단계가 확인합니다.

## 실행 (추론 PC)
1. `config/omx_infer_worker.yaml`을 복사해 `command`의 두 번째 항목에 `infer.sh` 절대 경로를 적습니다.
2. 관제 fleet과 같은 ROS 설정을 씁니다. 도메인 값은 `docs/fms_interfaces.md`(D2)를 따릅니다.
   ```bash
   export ROS_DOMAIN_ID=100
   export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
   export CYCLONEDDS_URI=file:///<경로>/cyclonedds.xml   # Peers에 OMEN IP 포함
   ```
   관제 쪽 `cobot_fleet_control/config/docker/cyclonedds.xml` Peers에도 추론 PC IP가 있어야 합니다.
3. 실행합니다. **실제 팔이 움직이므로 주변 안전을 확인한 뒤 실행합니다.**
   ```bash
   ros2 launch cobot_manipulation omx_infer_worker.launch.xml params_file:=<수정한 yaml>
   ```
- worker는 팔 하나당 하나만 띄웁니다. 같은 `request_id`는 한 번만 실행합니다.

## 장치 없는 확인
```bash
export ROS_DOMAIN_ID=101 ROS_LOCALHOST_ONLY=1
ros2 run cobot_manipulation omx_infer_worker_node --ros-args \
  -p "command:=['sh','-c','echo slot={slot}']"
ros2 topic echo /fleet/work_result      # 다른 터미널
ros2 topic pub --once /fleet/work_request std_msgs/msg/String \
  "{data: '{\"request_id\":\"t1\",\"order_id\":\"o1\",\"robot_id\":\"pinky1\",\"stage\":\"PICK\",\"target\":\"omx1\",\"action\":\"pick\",\"timeout_sec\":30.0,\"slot\":1}'}"
```
