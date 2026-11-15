# cobot_gazebo PRD

## 1. 목적
관제(control center)를 실물 로봇 없이 **지금 규격 그대로** 시험한다.
`cobot_mock` 은 상태만 흉내 내므로 Nav2 주행, 구역 대기열, 도메인 브릿지 경로는 검증하지 못한다.
이 패키지는 가제보 월드에 핑키 3대를 띄우고 실물과 같은 소프트웨어(Nav2, 실제 순찰 노드, 실제 브릿지·zone_manager)를 돌린다.

## 2. 기준 규격 (2026-11-03, 주행 코드 기준)
| 항목 | 실물 | 시뮬 |
|---|---|---|
| 관제 도메인 | 100 | 140 |
| pinky1/2/3 도메인 | 10/20/30 | 141/142/143 |
| 도메인 연결 | `cobot_domain_bridge` (`pinky_bridge_pinkyN.yaml`) | 같은 실행 파일, `config/domain_bridge_pinkyN.yaml` (도메인 숫자만 다름) |
| 명령·상태 | `/pinkyN/patrol_cmd`, `/pinkyN/patrol_status` (String JSON) | 같음 |
| 구역 | `/zone_manager/*` | 같음 (실제 `zone_manager_node`) |
| 순찰 노드 | `pinky_patrol_node_pinkyN` + `config/pinkyN.yaml` | 같음 (수정 없이, `use_sim_time` 만 켬) |
| Nav2 | 로봇 bringup, `nav2_params.yaml` | `config/nav2_sim.yaml` (복사본, sim time) |
| 지도 | `cobot_map_v9` | 같은 파일 복사본 + 지도에서 만든 월드 |
| 통신 범위 | 같은 망 | 이 PC 만 (`LOCALHOST`, `GZ_IP=127.0.0.1`) |

## 3. 범위
- 들어감: 월드(v9 벽), 단순 차동구동 핑키(라이다·오도메트리), 로봇별 Nav2, 가짜 LED 서비스, 가짜 배터리(고정값, 관제 online 판정용), 도메인 가드, 관제 노드 연결.
- 안 들어감: 배터리 방전·`/battery_state`·차선·카메라 토픽, 팔·비전, 실물 메시. 순찰 규격 v2(`cobot_patrol_interfaces`) 메시지 (실물 순찰 노드가 아직 v1 이라서).

## 4. 안전
- 실물 로봇 구동 없음. 도메인은 launch 에 고정하고, `sim_guard_node` 가 실물 도메인(0·10·12·20·30·100)·도메인 겹침·LOCALHOST 아님을 보면 시뮬 전체를 내린다.

## 5. 의존성 (팀 허락 필요)
- apt: `ros-jazzy-ros-gz`(가제보 Harmonic), `ros-jazzy-navigation2`, `ros-jazzy-nav2-bringup`, `ros-jazzy-xacro`, `ros-jazzy-robot-state-publisher`
- 파이썬 pip 의존성 없음.

## 6. 구조 예외
- `worlds/` 폴더는 CLAUDE.md §3-1 표준 폴더 목록에 없다. 가제보 월드 파일 자리로 이 패키지에만 둔다 (PR 에서 확인).
- `pinky_interfaces_stub/`(패키지명 `pinky_interfaces`) 는 시뮬 PC 전용이다.
