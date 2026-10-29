> 이력 문서입니다. 구역 3개·독립 이동·유휴 복귀의 최신 내용은 [`patrol_independent_move_prd.md`](patrol_independent_move_prd.md) 를 따릅니다.

# PRD: 순회주행 주석 처리 및 좌표 파라미터화

| 항목 | 내용 |
|---|---|
| 패키지 | `cobot_pinky_patrol` |
| 대상 파일 | `pinky_patrol_node_pinky1.py`, `pinky_patrol_node_pinky2.py`, `pinky_patrol_node_pinky3.py` |
| 목표 버전 | v1.1.0 (v1.0.0 = 이번 수정 전 기준선) |
| 상태 | R1·R2·R3 완료 (좌표 YAML 파라미터화, 검증 모듈 분리, launch/config 등록). R4~R6 중 코드 반영분(검증·주석)은 R3 에 포함, 최종 점검 남음. **R7(위험구역 2개) 코드·테스트 반영 완료, 구역 B 실측값 대기** |
| 담당 | 주행 (`cobot_navigation`) |

## 1. 목적 · 배경

1. **순회주행(`start`) 중단**: 현재 운영은 `goto` 중심이다. `start` 순회는 쓰지 않으므로 코드를 지우지 않고 주석 처리해 두었다가 필요할 때 되살린다.
2. **좌표 하드코딩 제거**: 지점 좌표가 노드 파일 3개에 같은 값으로 박혀 있다. 맵이 v6으로 바뀌면서 좌표를 다시 재야 할 수 있는데, 지금은 코드를 3곳 고치고 재배포해야 한다. 좌표를 파라미터(YAML)로 빼서 **코드 수정 없이 좌표만 교체**할 수 있게 한다.

CLAUDE.md 6번("매직 넘버·하드코딩 금지: `declare_parameter` + YAML 관리")에도 부합한다.

## 2. 범위

### 포함
- 순회주행(`start`) 관련 코드 주석 처리 (R1, R2)
- 모든 좌표 포인트 파라미터화 (R3, R4, R5)
- 관련 테스트 · README 갱신

### 제외
- `cobot_zone_traffic_control` 의 대기열 알고리즘, 슬롯 계산
- msg / srv / action 인터페이스 변경, 새 의존성 추가
- `goto` / `stop` / `emergency_stop` 동작 변경
- 좌표 **값**의 재측정 (이번에는 현재 값을 YAML로 그대로 옮긴다)
- LED 시간·`GOTO_WAIT_SEC`·`NAV_RETRIES` 등 좌표가 아닌 상수의 파라미터화 (후속 과제)

### 결정 사항 (사용자 확정)
- 주석 범위는 **start 전용만**. `P1~P7`, `ZONE_ENTRY`, `ZONE_EXIT`, `ZONE_STOP_EXIT` 는 `goto`/`stop` 이 쓰므로 주석 처리하지 않고 파라미터화한다.
- 파라미터는 **로봇별 YAML** 로 둔다.
- 좌표 파싱·검증은 공통 모듈 **`patrol_points_utils.py` 로 분리**한다. (3개 노드 파일에 같은 코드를 복사하지 않는다)
- 수정·신규 코드에는 **자세한 주석**을 남긴다. (R6)

## 3. 현황 (코드 근거)

3개 파일 모두 구조가 같고 `pinky_patrol_node_pinky1.py` 기준 줄 번호는 다음과 같다. (pinky2·3 은 1~2줄 차이)

| 구분 | 위치 | 내용 |
|---|---|---|
| 좌표 | `POINTS` (74~95줄) | `P1`~`P7`, `ZONE_ENTRY`, `ZONE_EXIT`, `ZONE_STOP_EXIT`. 클래스 상수 |
| 순회 경로 | `WAYPOINTS` (99줄) | pinky1: `P2→ZONE_ENTRY→P3→P6→ZONE_EXIT→P1`, pinky2·3: `ZONE_ENTRY→P3→P6→ZONE_EXIT→P7` |
| 순회 인덱스 | `ZONE_ENTRY_INDEX`, `ZONE_EXIT_INDEX` (114~115줄) | `WAYPOINTS` 순번 (pinky1 = 1·4, pinky2·3 = 0·3) |
| 순회 실행 | `_run_patrol` (755줄) | 별도 스레드에서 `WAYPOINTS` 순회 |
| 명령 수신 | `_cmd_cb` 의 `start` 분기 (269줄) | `_run_patrol` 스레드 시작 |
| goto 상수 | `HOME_NAME`, `GOTO_ALLOWED`, `ZONE_POINTS` | 홈: pinky1 = `P1`, pinky2·3 = `P7` (pinky3 은 임시, `TODO(pinky3)`) |

현재 좌표 값 (3개 파일 동일, 단위 m / rad):

| 이름 | 값 | 설명 |
|---|---|---|
| `P1` | (0.00, 0.00) | 원점 / pinky1 홈 |
| `P2` | (0.65, 0.15) | 원점과 우측 사이 중간 |
| `P3` | (1.55, -0.40) | 우측 아래 끝 (구역 안) |
| `P4` | (1.00, -0.40) | 중앙-우측 아래 (구역 안) |
| `P5` | (1.00, 0.10) | 중앙-우측 위 (구역 안) |
| `P6` | (1.55, 0.06) | 우측 위 끝 (구역 안) |
| `P7` | (0.00, -0.60) | 원점 아래 / pinky2·3 홈 |
| `ZONE_ENTRY` | (1.0, -0.7, 0.0) | 대기열 앵커 (`zone_params.yaml` 의 `queue_anchor` 와 같아야 함) |
| `ZONE_EXIT` | (0.5, -0.4, 3.14) | 락 반납 출구 |
| `ZONE_STOP_EXIT` | (0.5, -0.4, 3.14) | stop 후 후퇴 지점 (`ZONE_EXIT` 와 같은 점) |

## 4. 요구사항

### R1. 순회주행 주석 처리
- 아래를 **삭제하지 않고 주석 처리**한다. 되살릴 때 주석만 풀면 되도록 `# [비활성: v1.1.0 순회 중단]` 표지를 붙인다.
  - `WAYPOINTS`, `ZONE_ENTRY_INDEX`, `ZONE_EXIT_INDEX`
  - `_run_patrol` 메서드 전체
  - `_cmd_cb` 의 `start` 분기
- `start` 명령을 받았을 때의 동작: `알 수 없는 명령` 경고로 떨어지게 두지 않고, **"순회 비활성화" 경고 로그 + `FAILED`(detail `start disabled`) 상태 발행**으로 처리한다. 관제 쪽에서 왜 안 움직이는지 알 수 있게 하기 위해서다. (승인 시 확정)

### R2. start 전용 요소 정리
- 주석 처리 대상: `WAYPOINTS` 와 두 `*_INDEX` 상수, 이들만 참조하던 코드.
- **유지 대상**: `POINTS` 안의 모든 지점, `ZONE_ENTRY_NAME`, `ZONE_EXIT_NAME`, `STOP_EXIT_NAME`, `ZONE_POINTS`, `GOTO_ALLOWED`, `HOME_NAME`, `_queue_and_enter`, `_leave_zone`, `_retreat_after_stop`, `_run_route`. (goto/stop 이 사용)
- 파일 맨 위 docstring 의 `start` 설명과 "파일 구성" 목록, `pinky_patrol_flow.svg` 설명을 현재 동작에 맞춘다.

### R3. 모든 좌표 포인트 파라미터화
- 하드코딩된 `POINTS` 를 제거하고 `declare_parameter` 로 선언해 YAML 에서 읽는다.
- 로봇별 파일: `config/pinky1.yaml`, `config/pinky2.yaml`, `config/pinky3.yaml`
- 단위: 좌표 [m], yaw [rad]. 값은 `[x, y]` 또는 `[x, y, yaw]` 를 허용한다. (현재 `POINTS` 와 같은 형식)
- 좌표뿐 아니라 로봇별로 다른 **홈 지점 이름**(`home_name`)도 같은 YAML 에 둔다. (pinky3 의 임시 홈 `TODO` 를 YAML 에서 해결)

### R4. 파라미터 검증
- 노드 시작 시 다음을 확인하고 하나라도 어긋나면 **오류 로그를 남기고 시작하지 않는다.**
  - 필수 지점 누락: `ZONE_ENTRY`, `ZONE_EXIT`, `ZONE_STOP_EXIT`, `home_name` 이 가리키는 지점, `GOTO_ALLOWED` 에 들어가는 지점
  - 값 길이가 2·3 이 아님, 숫자가 아님, NaN/inf
- `ZONE_ENTRY` 는 `cobot_zone_traffic_control/config/zone_params.yaml` 의 `queue_anchor` 와 같아야 한다. 노드끼리 import 하지 못하므로(CLAUDE.md 3-6) **테스트에서만** 두 YAML 을 읽어 비교한다.

### R5. 실행 방법 호환
- 기존 `ros2 run cobot_pinky_patrol pinky_patrol_node_pinkyN --ros-args -p robot_id:=pinkyN` 형태는 유지한다.
- 좌표 YAML 은 launch(`launch/pinkyN_patrol.launch.xml`) 로 지정하거나 `--params-file` 로 준다.
- YAML 을 주지 않으면 필수 지점이 비어 R4 에 따라 시작되지 않는다. (조용히 기본 좌표로 동작하지 않음)

### R6. 코드 주석 규칙
CLAUDE.md 6번("'무엇'보다 '왜'를 설명")을 따르되, 이번 수정은 좌표·동작이 바뀌는 작업이므로 아래 수준으로 자세히 남긴다.

- **한국어**로 쓰고, 코드를 그대로 읽어 주는 주석이 아니라 **왜 그렇게 했는지**를 적는다.
- **docstring**: 모듈, 클래스, 모든 신규 함수에 둔다. 입력·반환값·예외, 좌표 단위(m, rad)를 적는다.
- **주석 처리한 순회 코드**: 블록마다 아래 네 가지를 붙인다.
  1. 표지 `# [비활성: v1.1.0 순회 중단]`
  2. 비활성 이유 (운영이 goto 중심이라 쓰지 않음, 삭제하지 않고 보관)
  3. 되살리는 절차 (주석을 풀 위치 목록)
  4. 함께 되돌릴 항목 (`WAYPOINTS` 상수, `*_INDEX`, `_cmd_cb` 분기, skip 한 테스트)
- **파라미터 선언부**: 이름, 형식(`[x, y]` / `[x, y, yaw]`), 단위, 누락 시 동작(시작 거부)을 적는다.
- **검증 실패 오류 메시지**: 어떤 키가 무엇 때문에 틀렸는지, 어떻게 고치는지 한 줄로 알려 준다.
- **YAML 파일**: 항목마다 좌표의 의미와 단위를 적고, `ZONE_ENTRY` 는 `zone_params.yaml` 의 `queue_anchor` 와 같아야 한다는 주의를 맨 위에 둔다.
- 기존 파일의 설명 주석(대기열, LED, stop 후퇴 등)은 지우지 않고, 좌표 출처가 바뀐 곳만 고친다.

## 5. 설계

### 5-1. 파라미터 스키마

| 파라미터 | 타입 | 예 | 설명 |
|---|---|---|---|
| `robot_id` | string | `pinky1` | 기존과 같음 |
| `home_name` | string | `P1` | goto 경로 완료 후 복귀 지점 이름 |
| `points.<이름>` | double[] | `[0.0, 0.0]` | `[x, y]` 또는 `[x, y, yaw]` |

### 5-2. YAML 예시 (`config/pinky1.yaml`, 현재 값을 그대로 이전)

```yaml
pinky_patrol_node:
  ros__parameters:
    robot_id: pinky1
    home_name: P1
    points:
      P1: [0.00, 0.00]
      P2: [0.65, 0.15]
      P3: [1.55, -0.40]
      P4: [1.00, -0.40]
      P5: [1.00, 0.10]
      P6: [1.55, 0.06]
      P7: [0.00, -0.60]
      ZONE_ENTRY: [1.0, -0.7, 0.0]
      ZONE_EXIT: [0.5, -0.4, 3.14]
      ZONE_STOP_EXIT: [0.5, -0.4, 3.14]
```

노드 이름은 현재 코드와 같은 `pinky_patrol_node` 를 쓴다. `pinky2.yaml`, `pinky3.yaml` 은 `robot_id` 와 `home_name` (`P7`)만 다르고 좌표는 같다.

### 5-3. 코드 구조
- `POINTS` 를 **클래스 상수에서 인스턴스 속성**(`self.points`)으로 바꾼다. `__init__` 에서 `_load_points()` 가 파라미터를 읽어 `{이름: (x, y[, yaw])}` 로 만든다.
- 이름 목록은 `declare_parameter` 가 YAML 에 있는 키만 인식하므로 `declare_parameters` + 필수 이름 목록으로 선언한다.
- `HOME_NAME`, `ZONE_POINTS`, `GOTO_ALLOWED` 는 이름 상수이므로 코드에 남긴다. 좌표가 아니기 때문이다. (홈 이름만 파라미터)
- **공통 로더 분리 (확정)**: 좌표 파싱·검증을 `cobot_pinky_patrol/patrol_points_utils.py` 로 분리하고 3개 노드가 import 한다.
  - ROS 를 import 하지 않는 순수 함수만 둔다. (CLAUDE.md 3-2) 그래서 ROS·로봇 없이 단위 테스트가 가능하다.
  - 같은 패키지 안의 import 이므로 패키지 간 직접 import 금지(CLAUDE.md 3-6)에 해당하지 않는다.
  - 노드 파일은 "파라미터를 읽어서 이 모듈에 넘기는 일"만 하고, 규칙은 한곳에서 고친다.

| 이름 | 종류 | 역할 |
|---|---|---|
| `PointsConfigError` | 예외 | 좌표 설정이 잘못됐을 때 발생. 메시지에 키 이름과 원인을 담는다 |
| `parse_point(name, value)` | 함수 | 값 하나를 `(x, y)` 또는 `(x, y, yaw)` 튜플로 변환. 길이 2·3 아님, 숫자 아님, NaN/inf 이면 예외 |
| `parse_points(raw)` | 함수 | `{이름: 값}` 전체를 변환 (노드가 읽은 파라미터 딕셔너리를 받음) |
| `validate_points(points, required, home_name)` | 함수 | 필수 지점 누락과 `home_name` 이 가리키는 지점의 존재를 확인 |

### 5-4. `start` 비활성화 후 상태 흐름
`start` → 경고 로그 → `patrol_status` 에 `{"state":"FAILED","detail":"start disabled"}` → 노드는 계속 `IDLE`, `goto`/`stop` 은 정상 동작.

## 6. 등록 절차

| 항목 | 내용 |
|---|---|
| 새 폴더 | `config/`, `launch/` (CLAUDE.md 3-1 표준 이름) |
| 새 파일 | `cobot_pinky_patrol/patrol_points_utils.py` (소스 폴더, 별도 등록 불필요), `test/test_patrol_points_utils.py` |
| `setup.py` | `data_files` 에 `config/*.yaml`, `launch/*.launch.xml` 추가 (`glob` 사용) |
| `package.xml` | 변경 없음 (새 의존성 없음) |
| launch | `launch/pinky{1,2,3}_patrol.launch.xml` 은 노드 실행 + 해당 YAML 지정만 한다 |
| `--symlink-install` | 새 파일·`setup.py` 변경이므로 재빌드 필요 |

## 7. 영향 범위

- **인터페이스**: 변경 없음. 토픽 `patrol_cmd`, `patrol_status` 형식 유지. `start` 에 대한 응답만 `FAILED` 로 달라진다.
- **관제 쪽**: `cobot_pinky_patrol_cmd/pinky_control_client.py` 의 `start` 명령은 남아 있지만 동작하지 않는다. 안내 문구 수정이 필요한지 확인한다. GUI(`cobot_gui`)에 `start` 버튼이 있으면 담당자에게 알린다.
- **`cobot_zone_traffic_control`**: `queue_anchor` 와 `ZONE_ENTRY` 의 일치 조건은 유지된다. 코드 변경 없음.
- **테스트** (`test/test_patrol_queue.py`): 클래스 상수 `POINTS`, `WAYPOINTS` 를 직접 읽는 테스트를 고쳐야 한다.

| 테스트 | 조치 |
|---|---|
| `test_waypoint_indexes_match_door_names` | `WAYPOINTS` 주석 처리로 삭제/skip |
| `test_pinky2_start_path_uses_corrected_indexes`, `test_pinky1_start_path_waits_in_queue` | 순회 전용이므로 skip 처리 (주석과 함께 되살릴 수 있게) |
| `test_no_hardcoded_queue_coordinates`, `test_zone_entry_matches_yaml_anchor`, `test_zone_exit_is_shared_and_red_points_removed`, `test_stop_exit_point_equals_zone_exit` | `cls.POINTS` 대신 `config/pinkyN.yaml` 을 읽어 검사하도록 변경 |
| 통합 테스트 `env` 이하 (`POINTS['P3']`, `POINTS['ZONE_STOP_EXIT']` 사용) | 가짜 환경에서 YAML 로 노드를 만들도록 변경 |
| 신규 `test/test_patrol_points_utils.py` | `parse_point`/`parse_points`/`validate_points` 단위 테스트 (정상, 2값·3값, 길이 오류, 숫자 아님, NaN, 필수 지점 누락, 홈 지점 누락). ROS 없이 실행 |
| 신규 (`test_patrol_queue.py`) | `start` 수신 시 `FAILED(start disabled)` 발행 테스트 |

- **문서**: `cobot_pinky_patrol/README.md` (start 설명·실행 방법·"프로젝트 구조"·ZONE_EXIT 좌표 표기), `src/cobot_navigation/README.md` (실행 순서 4·5번), `docs/pinky_patrol_flow.svg` 갱신 여부 확인.
- 같은 PR 에서 문서를 함께 고친다. (CLAUDE.md 4-2)

## 8. 리스크

| 리스크 | 대응 |
|---|---|
| 맵 v6 좌표계가 바뀌어 기존 좌표가 실제로 다른 위치를 가리킬 수 있음 | `map_view_pc` 로 v6 에서 각 지점이 free 인지 확인 후 YAML 값 확정. 이번 PRD 에서는 값을 바꾸지 않음 |
| `~/.pinky_last_pose.json` 의 낡은 값으로 첫 초기 위치가 어긋남 | 맵 변경 후 로봇에서 파일 삭제(사용자 확인 후) 또는 초기 위치 재설정 |
| YAML 오타·누락으로 시작 실패 | R4 검증과 명확한 오류 메시지. 시작하지 않는 쪽이 잘못된 좌표로 움직이는 것보다 안전 |
| 3개 YAML 이 서로 어긋남 | `ZONE_ENTRY`/`ZONE_EXIT` 공통 값은 테스트가 3개 파일 일치를 검사 |
| 순회 코드를 되살릴 때 인덱스와 좌표가 틀어짐 | 주석에 되살리는 절차와 `test_waypoint_indexes...` 복구 안내를 남김 |
| `ZONE_ENTRY` 와 `queue_anchor` 불일치 | 테스트 유지. 앵커를 바꿀 때는 pinky1·2·3 YAML 과 `zone_params.yaml` 을 함께 수정 |

## 9. 검증 방법

CLAUDE.md 5번에 따라 빌드 → 테스트 → 린트 순으로 한다.

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select cobot_pinky_patrol
source install/setup.bash
colcon test --packages-select cobot_pinky_patrol
colcon test-result --verbose          # ament_flake8, ament_pep257 포함

# 통합 테스트는 격리 도메인에서만
ROS_DOMAIN_ID=77 ROS_LOCALHOST_ONLY=1 python3 -m pytest cobot_pinky_patrol/test/test_patrol_queue.py -q
```

- 수동 확인 (실제 로봇은 사용자 확인 후): YAML 로 노드를 띄운 뒤 `goto P2`, `goto P3`, 구역 안 `stop`, `start`(→ `FAILED`) 를 순서대로 시험한다.
- YAML 키를 일부러 지워 노드가 시작을 거부하는지 확인한다.
- **실제 로봇 구동 여부**: 구현·테스트 단계는 가짜 navigator 로 진행한다. 실물 시험은 별도 확인 후 진행하며 이 PRD 작성 자체는 로봇을 구동하지 않는다.

## 10. 수용 기준

- [ ] `start` 순회 관련 코드가 3개 파일 모두 주석 처리되고 `start` 수신 시 `FAILED(start disabled)` 가 발행된다.
- [ ] 3개 파일에 좌표 리터럴이 없고, 좌표는 `config/pinkyN.yaml` 에서만 온다.
- [ ] YAML 필수 키 누락·형식 오류 시 노드가 시작하지 않고 원인을 로그로 알려 준다.
- [ ] 이전과 같은 좌표 값으로 `goto`, `stop`, 구역 대기열 동작이 기존과 동일하다.
- [ ] `ZONE_ENTRY` = `queue_anchor` 검사 테스트가 통과한다.
- [ ] `patrol_points_utils.py` 가 ROS 를 import 하지 않고, `test_patrol_points_utils.py` 가 ROS 없이 통과한다.
- [ ] 수정·신규 코드가 R6 주석 규칙을 만족한다. (docstring, 비활성 표지·되살리는 절차, 파라미터 설명, YAML 주석)
- [ ] `colcon build` / `colcon test` / 린트 통과.
- [ ] README 와 통합 README 가 갱신되었다.

## 11. 일정 · 버전

| 단계 | 내용 |
|---|---|
| 1 | 이 PRD 검토·확인 (공통 로더 분리·주석 규칙은 확정, 12번 기본값에 이의가 없는지 확인) |
| 2 | 구현 계획 승인 후 코드 수정 (3개 파일 + `patrol_points_utils.py` + config/launch + setup.py), 코드·YAML 주석은 R6 기준으로 함께 작성 |
| 3 | 테스트 수정, 빌드·테스트·린트 |
| 4 | README 갱신, 커밋·push |
| 5 | v1.1.0 태그는 구현·검증이 끝난 뒤 사용자 요청 시 `git tag -a v1.1.0` 후 push |

## 12. 결정 현황

### 확정
| 항목 | 결정 |
|---|---|
| 주석 범위 | start 전용만 |
| 파라미터 형태 | 로봇별 YAML |
| 공통 로더 | `patrol_points_utils.py` 로 분리 |
| 코드 주석 | 자세히 남김 (R6) |

### 기본값 적용 중 (이의가 있으면 구현 전에 알려 주세요)
| 항목 | 기본값 |
|---|---|
| `start` 수신 시 | `FAILED(start disabled)` 상태 발행 |
| pinky3 홈 지점 | 임시값 `P7` 를 YAML 로 그대로 이전하고 `TODO` 주석 유지 (실측 후 전용 지점으로 변경) |
| 맵 v6 좌표 재측정 | v1.1.0 에서 제외 (별도 작업). 값은 현재 좌표 그대로 |

---

## R7. 위험구역 2개 지원 (R3 이후 추가 결정)

R3 은 위험구역이 1개라는 전제로 `ZONE_ENTRY` / `ZONE_EXIT` / `ZONE_STOP_EXIT` 를 한 벌만 두었다. 위험구역이 2개로 확정되어 아래처럼 바꿨다.

| 항목 | R3 | R7 |
|---|---|---|
| 토큰·대기열 | 매니저 1세트 | 구역(`A`, `B`)마다 따로. 한 구역의 점유가 다른 구역을 막지 않음 |
| 구역 소속 지점 | 노드 상수 `ZONE_POINTS` | YAML `zone_names` / `zone_points.<구역>` 파라미터 |
| 진입·출구 좌표 | `ZONE_ENTRY`, `ZONE_EXIT`, `ZONE_STOP_EXIT` | `ZONE_<구역>_ENTRY`, `ZONE_<구역>_EXIT` (구역마다 한 쌍). `ZONE_STOP_EXIT` 는 항상 EXIT 와 같은 값이어서 제거, stop 후퇴는 현재 구역 EXIT |
| 대기열 앵커 | `queue_anchor` | `zone_<구역>.queue_anchor` (매니저가 구역별로 슬롯 좌표를 줌, 로봇은 앵커=ENTRY 만 보유) |
| 메시지 | `<robot>:...` | 맨 앞에 구역 이름: `<zone>:<robot>:...` (토픽 이름 불변, 브릿지 설정 변경 없음) |
| 경로 | 구역 밖 <-> 안 | 구역이 바뀌면 이전 구역 EXIT 에서 반납한 뒤 다음 구역 ENTRY 요청 (한 번에 토큰 1개, 교착 방지) |

- 호환성: 메시지 형식이 바뀌어 구형 노드와 섞을 수 없다. 매니저 → 로봇 3대 순서로 함께 배포한다.
- 검증 규칙(`patrol_points_utils.validate_zones`): 구역마다 소속 지점이 있고 `points` 에 존재, 한 지점이 두 구역에 속하지 않음, 홈은 구역 밖, ENTRY/EXIT 는 소속 지점이 될 수 없음, 구역 이름은 영문·숫자.
- **확정(2026-10-26)**: 구역 A = `P2,P3`, 구역 B = `P4`, 홈 pinky1 = `P1`. `ZONE_A_ENTRY (0.0,0.6,0.0)`, `ZONE_A_EXIT (0.4,-0.7,0.0)`, `ZONE_B_ENTRY (-0.8,-0.2,-0.7)`, `ZONE_B_EXIT (-0.4,-0.4,0.7)`, 매니저 앵커는 각 ENTRY 와 동일.
- **미결(실측 필요)**: 신규 앵커 뒤쪽(`queue_back_dir` -x) 슬롯 위치의 안전 여부, pinky2·3 의 P2~P4 좌표(옛 값)와 pinky3 전용 홈.
