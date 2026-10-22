# FMS 맵 계약 (맵 정본 · map_hash · 맵 린트)

- 상태: 초안 (2026-10-22). 결정 D3(맵 정본, map_hash 입력 정의, 접근 자세, 맵 파일 위치)는 아직 `proposed` 다. 관제 담당이 팀에 공지하면 `decided` 로 바꾸고 결정자와 날짜를 적는다.
- 단계: 로드맵 S1 계약 고정 (`docs/fms_roadmap.md`). 규칙은 `docs/fms_dev_rules.md` 를 따른다.
- 관련 SR (인용만 한다): SR-04 자율주행 및 운송 기능, SR-08 정차 위치 확인 기능, SR-20 명령 유효성 검증 및 구 권한 차단 기능(맵 해시 일치 여부 검증). SR v5.0 원문의 맵 이름·크기와 정본이 다르다 (8절).
- 판단이 들어간 값은 '초안' 이라고 적었다. 특히 approach_pose 와 반경 6 cm 는 주행 담당 확인이 필요하다.

## 1. 한눈에 보기

| 항목 | 값 |
|---|---|
| 맵 정본 | `src/cobot_bringup/config/maps/map_shoe_store_1021_gate67.yaml` + `.pgm` (Floor Map 1021 도면 + 아래 벽에 붙은 67 cm 게이트) |
| 웨이포인트 자세·연계된 팔 | `src/cobot_bringup/config/maps/approach_poses.yaml` (초안) |
| 도구 | `src/cobot_control_center/cobot_control_center/map_contract.py` (`map_hash`, `map_lint`) |
| 시험 | `src/cobot_control_center/test/test_map_contract.py` |
| 지금 map_hash | `ecfa150600d7b3ccf3630010a4db22adc93e16081ee178366fa1608dcc7bb170` |
| 린트 반경 | 0.06 m (초안) |

## 2. 맵 정본의 위치와 출처

- 위치: `src/cobot_bringup/config/maps/`. 빌드하면 `install/cobot_bringup/share/cobot_bringup/config/maps/` 에 설치된다.
- 정본: **Floor Map 1021 도면 + 아래 벽에 붙은 67 cm 게이트** (사용자 결정 2026-10-22). 예전 팀 맵 `map_shoe_store_flat` (SR 브랜치 `feature/setup-fleet-msgs-structure` 의 `maps/`, 2.4 × 2.4 m, 중앙 벽이 y 0.84 m 부터 시작해 아레나 안쪽 벽 기준 개구 약 0.82 m) 은 정본이 아니다.
- 도면: `Floor Map 1021.html` (sha256 `c545a0331c74f6ad01ceba8f3fd4d47cbbf7082ceb79acfec0f1c2362f8d7c41`). 도면 파일은 레포에 넣지 않았다. 팀원이 도면을 받을 곳은 아직 정하지 않았다 (8절). 아래 경계는 도면 HTML·CSS 의 숫자만 읽어 m 로 바꾼 것이다 (도면 1 px = 0.0025 m, 스크립트는 실행하지 않았다). 현장 실측이 아니다.
- 칠하는 규칙: 1 cm 셀의 **중심**이 아래 표의 상자 안(경계 포함)에 있으면 점유(0), 아레나(0 < x < 2.5 m, 0 < y < 2.4 m) 밖이면 점유, 나머지는 자유(254). PGM 은 254 × 254 px 이다.

  | 이름 | [x0, x1, y0, y1] (m) | 비고 |
  |---|---|---|
  | 탈의실 1~4 | [0.0, 0.3, 1.98, 2.4] · [0.3, 0.6, …] · [0.6, 0.9, …] · [0.9, 1.2, …] | |
  | 진열대 A | [0.79, 1.17, 1.59, 1.75] | |
  | 고객 벤치 | [0.04, 0.54, 1.22, 1.40] | |
  | 계산대 | [0.02, 0.22, 0.03, 1.02] | |
  | 랙 A | [1.90, 2.50, 2.21, 2.40] | |
  | 랙 B | [1.90, 2.50, 1.6425, 1.8325] | |
  | 장애물 랙 1 | [1.55, 2.50, 0.93, 1.12] | 가로 배치 (도면 원안) |
  | 장애물 랙 2 | [1.30, 2.25, 0.45, 0.64] | 가로 배치 (도면 원안) |
  | 중앙 벽 | [1.20, 1.30, **0.67**, 2.40] | 도면 원안은 y 0.35 부터다. 사용자 결정으로 0.67 부터 → 아래 0~0.67 m 가 게이트 |

- 넣지 않은 것: 도면의 팔 표식 OMX_1 [2.1375, 2.2975, 2.05, 2.21], OMX_2 [2.1375, 2.2975, 1.48, 1.64], OMX_3 [0.0725, 0.2325, 1.77, 1.93] 은 고형물이 아니라 표식이다. 팔 고정대의 외형·위치는 도면에 없다. 그래서 **지금 맵에서 팔 자리는 자유 셀**이다. 실물 주행 전에 고정대를 맵에 넣거나 Nav2 keepout 으로 막아야 한다 (8절).
- 카메라: 도면에는 카메라 1(항공뷰 2.15 m) [1.14~1.3375, 1.215~1.325] 와 카메라 2(측면 저각도 15 cm 높이, 도킹·게이트 통과 감시) [1.295~1.37, 0.3225~0.445] 아이콘이 있다. 맵에는 넣지 않았다. 카메라 2 는 관제 담당 확인(2026-10-22)에 따라 바닥 받침대 없이 게이트 벽체 상단(1.0~1.2 m)에서 내려다보게 설치할 예정이라 바닥 정차점과 겹치지 않는다. 도면의 '15 cm 높이' 와 다르다 (8절).
- 교차 확인 (2026-10-22): 관제 담당의 개인 시뮬레이션(MuJoCo)이 같은 도면으로 만든 67 cm 맵(가로 랙, 팔 고정대 3개를 가정해 넣음)과 셀 단위로 비교했다. 이 맵의 점유 셀은 그 맵에서도 모두 점유이고, 다른 셀은 가정한 고정대 세 자리(3,500셀)뿐이다.
- 파일 sha256

  | 파일 | sha256 |
  |---|---|
  | `map_shoe_store_1021_gate67.pgm` | `f4fb41c1a3e9f8a2bb098a874b8be278cdad0596d58cf3952b0f52a19a08f050` |
  | `map_shoe_store_1021_gate67.yaml` (LF) | `96ac285601dee5fb143a926bae89276103e8169afd64a8001bc501541cd49175` |

- PNG 는 넣지 않았다. PGM 에서 만든 그림(파생물)이라 두 벌을 맞춰야 하는 일이 생기기 때문이다 (CLAUDE.md §3-1 의 대용량·데이터 파일 규칙과 같은 취지). 맵을 눈으로 보려면 PGM 을 이미지 뷰어(예: GIMP)로 연다.
- 왜 `cobot_bringup` 인가: 아키텍처 설계서는 `cobot_navigation/config/` 를 권했다. 하지만 주행 담당 패키지를 요청 없이 고치지 않으려고(CLAUDE.md §9) 공통 패키지 `cobot_bringup` 의 `config/` 에 두었다 (CLAUDE.md §3-5: 팀 공통 설정은 bringup 의 `config/` 에서 관리). 공통 패키지라 PR 은 팀 리뷰를 받는다. 주행 담당이 원하면 옮길 수 있다. 옮길 때는 `map_contract.py` 의 `MAPS_RELPATH`·`BRINGUP_PACKAGE` 와 이 문서를 같은 PR 에서 고친다.
- 줄 끝: 이 폴더의 `.gitattributes`(`src/cobot_bringup/config/maps/.gitattributes`)가 PGM 은 바이너리로, YAML 은 LF 로 고정한다. 루트 `.gitattributes` 와 따로 두어 다른 PR 과 충돌하지 않게 했다. Windows(`core.autocrlf=true`)에서 받아도 바이트가 같다.
- `cobot_control_center` 는 `cobot_bringup` 의 코드를 가져다 쓰지 않는다. 설치된 맵 **파일**만 실행 때 읽는다 (CLAUDE.md §3-6 은 코드 의존을 막는 규칙이다).
- 그래도 `cobot_control_center` 의 `package.xml` 에 `cobot_bringup` 을 적지 않았다. bringup 은 나중에 각 패키지의 launch 를 include 하려고 `cobot_control_center` 같은 패키지에 의존하게 된다 (`bringup.launch.xml` 주석, CLAUDE.md §3-5·§7). 그때 control_center 도 bringup 에 의존하면 순환 의존이 된다. CLAUDE.md §3-6 은 순환 의존을 만들지 않도록 한다.
- 그래서 빌드할 때 두 패키지를 함께 고른다: `colcon build --symlink-install --packages-up-to cobot_bringup cobot_control_center`. `--packages-up-to cobot_control_center` 만 쓰면 bringup 이 빌드되지 않는다. 이때 도구는 소스 트리로 몰래 떨어지지 않고 종료 코드 2 로 멈춘다 (4.2절).
- 이 '파일만 읽는 의존' 은 D3 결정 기록에 예외로 적고 팀 확인을 받는다 (8절).

## 3. 좌표계

- frame: `map`. 단위는 m. 웨이포인트 형식은 `[x (m), y (m), theta (도)]` 이다 (맵 YAML 의 waypoints 와 같다). ROS 메시지로 낼 때는 theta 를 라디안으로 바꾼다 (REP-103).
- 해상도 0.01 m/px. PGM 은 254 × 254 px 이다. 아레나 안쪽은 x 0 ~ 2.5 m, y 0 ~ 2.4 m 이고 그 밖은 점유 셀(벽)이다.
- 원점 `origin: [-0.02, -0.02, 0.0]` 은 PGM **왼쪽 아래** 픽셀의 왼쪽 아래 모서리가 map 좌표 (-0.02, -0.02) 이라는 뜻이다. 그래서 맵은 x, y 가 -0.02 ~ 2.52 m 인 곳을 덮는다. 아레나 왼쪽 아래 모서리가 map 좌표 (0, 0) 이다.
- 셀 번호 (mx, my): mx 는 왼쪽에서, my 는 **아래에서** 센다 (PGM 은 윗줄부터 저장하므로 my = 0 이 PGM 의 마지막 줄이다). 셀 중심은 `(-0.02 + (mx + 0.5) × 0.01, -0.02 + (my + 0.5) × 0.01)` 이다.
- 셀 판정 식은 nav2 map_server 의 trinary 와 같다. `occ = 1 − 픽셀/255` (negate 0. 255 는 PGM 최댓값). `occ > 0.65` 이면 점유, `occ < 0.196` 이면 자유, 그 사이는 미지. 값은 맵 YAML 의 `occupied_thresh`·`free_thresh`·`negate` 를 쓴다.
- 경계값만 다르다. 이 린트는 occ 가 문턱과 **딱 같으면** 미지로 본다. Jazzy 의 map_server 는 `occ >= occupied_thresh` 를 점유, `occ <= free_thresh` 를 자유로 본다 (navigation2 jazzy 브랜치 `nav2_map_server/src/map_io.cpp`). 미지는 린트 실패라서, 이 차이 때문에 린트가 더 엄격해질 뿐 덜 엄격해지지는 않는다. 시험 `test_threshold_boundary_is_unknown` 이 이 동작을 고정한다.
- 지금 PGM 에는 0(점유)과 254(자유)만 있어 경계값 셀이 없다. 그래서 지금 맵의 판정은 nav2 와 같다.

## 4. map_hash

### 4.1 정의

```
map_hash = sha256( sha256(PGM 바이트) ‖ sha256(LF 로 맞춘 맵 YAML 바이트) )
```

- `‖` 는 32바이트 다이제스트 두 개를 이어 붙인 것이다 (16진수 글자가 아니다). 결과는 소문자 16진수 64자다.
- 'LF 로 맞춘다' 는 줄 끝 CRLF(`\r\n`)를 LF(`\n`)로 바꾸는 것이다. 다른 바이트는 그대로 둔다. Windows 에서 받은 파일도 같은 값이 나오게 하려는 것이다.
- YAML 은 주석까지 바이트로 들어간다. 주석 한 글자를 바꿔도 map_hash 가 바뀐다.
- 입력은 **install 된 파일**이다. FMS 와 핑키 온보드 가드는 각자 `cobot_bringup` install 의 `config/maps/` 에서 맵을 읽고 map_hash 를 계산한다. 둘이 같은 커밋을 빌드해야 같은 값이 나온다.
- 지금 값: `ecfa150600d7b3ccf3630010a4db22adc93e16081ee178366fa1608dcc7bb170`

### 4.2 계산 명령

레포 루트에서 한다. ROS 가 없는 PC 에서도 Python 3 와 PyYAML 만 있으면 된다.

```bash
PYTHONPATH=src/cobot_control_center python3 -m cobot_control_center.map_contract hash
```

ROS 환경에서는 이렇게 한다 (install 의 맵을 읽는다).

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-up-to cobot_bringup cobot_control_center
source install/setup.bash
ros2 run cobot_control_center map_hash
```

- 결과 값은 표준 출력에 한 줄로 나온다. 어느 파일을 읽었는지는 로그(표준 오류)에 나온다.
- 다른 폴더를 보려면 `--maps-dir <폴더>`, 맵 YAML 하나만 보려면 `--map-yaml <파일>` 을 준다.
- 종료 코드: 0 = 성공, 2 = 맵을 찾거나 읽지 못함.
- 맵 폴더는 이렇게 찾는다 (`--maps-dir`·`--map-yaml` 을 안 줬을 때).

  | 셸 | 읽는 곳 | 로그 |
  |---|---|---|
  | ROS 를 source 했고 `cobot_bringup` 이 install 됨 | install 의 `share/cobot_bringup/config/maps/` | INFO `맵 폴더 (install)` |
  | ROS 를 source 했는데 `cobot_bringup` install 이 없음 | 읽지 않고 **종료 코드 2** | ERROR (빌드 방법 안내) |
  | 위와 같은데 `--allow-source` 를 줌 | 소스 트리 `src/cobot_bringup/config/maps/` | **WARNING** `맵 폴더 (source)` |
  | ROS 를 source 하지 않음 (Python 만 있는 PC) | 소스 트리 | INFO `맵 폴더 (source)` |

  ROS 셸에서 멈추는 까닭: map_hash 의 입력은 install 된 파일이다. install 이 없는데 소스 트리 값을 조용히 내면, 로봇이 읽는 사본과 다른 파일의 값을 계약 값으로 오해할 수 있다.

Python 모듈 없이 확인하는 셸 한 줄 (같은 값이 나온다. `config/maps/` 안에서 돌린다):

```bash
{ sha256sum map_shoe_store_1021_gate67.pgm | cut -d' ' -f1 | xxd -r -p; \
  sed 's/\r$//' map_shoe_store_1021_gate67.yaml | sha256sum | cut -d' ' -f1 | xxd -r -p; } | sha256sum
```

`xxd: command not found` 가 나오면 `xxd` 가 없는 것이다 (도커 개발 이미지에도 없을 수 있다). 그때는 아래 한 줄을 쓴다. 도구 모듈을 쓰지 않고 표준 라이브러리 `hashlib` 로만 계산한다.

```bash
python3 -c 'import hashlib as h; p=open("map_shoe_store_1021_gate67.pgm","rb").read(); y=open("map_shoe_store_1021_gate67.yaml","rb").read().replace(b"\r\n",b"\n"); print(h.sha256(h.sha256(p).digest()+h.sha256(y).digest()).hexdigest())'
```

## 5. 맵 린트

### 5.1 규칙

- 자세 하나마다 점 (x, y) 둘레 반경 r 원을 그린다. **셀 중심이 원 안(거리 ≤ r)에 있는 셀이 모두 자유**여야 한다. 점이 든 셀은 반경과 관계없이 늘 본다.
- 점유·미지·맵 밖 셀이 하나라도 있으면 그 웨이포인트는 실패다.
- r 은 `approach_poses.yaml` 의 `clearance_radius_m` (초안 0.06 m) 이다. 아키텍처 설계서 §9.1 의 값이고 핑키 외형 실측이 아니다. 명령에서 `--radius` 로 바꿔 볼 수 있다.
- 기본은 `approach_pose` 를 본다. `--poses work_pose` 는 원래 좌표를 보는 확인용이다 (지금은 실패가 정상이다).
- 반경 원 말고도 함께 본다.
  1. `approach_poses.yaml` 형식 (모르는 키, 빠진 키, 자세는 수 3개).
  2. 매니페스트: `map` 블록의 `pgm_sha256`, `yaml_lf_sha256`, `map_hash` 가 실제 파일과 같은가. 맵을 바꾸고 값을 안 고치면 실패한다.
  3. `work_pose` 가 맵 YAML 의 `waypoints` 와 같은가 (ID 목록과 좌표).
  4. 맵 YAML 과 PGM 은 같은 폴더의 파일 이름으로만 가리킨다 (경로 금지).
- 종료 코드: 0 = 통과, 1 = 린트 실패, 2 = 파일을 찾거나 읽지 못함.
- `--suggest` 를 주면 실패한 웨이포인트마다 '가장 가까운 자유 점(초안 후보)' 을 로그로 알려 준다. 반경을 크게 주면 오래 걸려서 기본으로는 하지 않는다.
- 맵 폴더는 4.2절 표대로 찾는다. ROS 셸에서는 install 을 읽으므로, 맵이나 `approach_poses.yaml` 을 고친 뒤에는 다시 `colcon build` 한다 (`--symlink-install` 이면 바로 반영된다). 고친 소스를 바로 보려면 `--maps-dir src/cobot_bringup/config/maps` 를 준다.

### 5.2 명령

```bash
PYTHONPATH=src/cobot_control_center python3 -m cobot_control_center.map_contract lint                      # 0 이어야 한다
PYTHONPATH=src/cobot_control_center python3 -m cobot_control_center.map_contract lint --poses work_pose    # 지금은 1 이 정상
PYTHONPATH=src/cobot_control_center python3 -m cobot_control_center.map_contract lint --poses work_pose --suggest   # 정차점 후보 안내
PYTHONPATH=src/cobot_control_center python3 -m pytest src/cobot_control_center/test/test_map_contract.py
```

ROS 환경에서는 `ros2 run cobot_control_center map_lint` 이고, 시험은 `colcon test --packages-select cobot_bringup cobot_control_center` 뒤 `colcon test-result --verbose` 로 본다.

- 로그를 보는 시험은 `module_log` fixture 를 쓴다. ROS 를 source 한 셸에서는 pytest 가 `launch_testing` 플러그인을 저절로 불러온다. 이 플러그인이 불러오는 `launch.logging` 은 그 뒤에 만들어지는 로거를 `propagate=False` 로 만들어서, pytest 의 `caplog` 가 이 도구의 로그를 받지 못한다. 그래서 시험 동안만 propagate 를 켠다. 명령을 직접 돌릴 때는 `launch.logging` 을 불러오지 않아 상관없다.

### 5.3 지금 결과 (반경 0.06 m, 2026-10-22 계산)

| 웨이포인트 | work_pose | work_pose 린트 | approach_pose (초안) | 옮긴 거리 |
|---|---|---|---|---|
| WP_HOME_1 | [1.41, 2.05375, 270] | 통과 | 같음 | 0 |
| WP_HOME_2 | [1.41, 1.8575, 270] | 통과 | 같음 | 0 |
| WP_HOME_3 | [1.41, 1.66125, 270] | 통과 | 같음 | 0 |
| WP_LOAD_1 | [2.015, 2.105, 0] | 통과 | 같음 | 0 |
| WP_LOAD_2 | [2.015, 1.5375, 0] | 통과 | 같음 | 0 |
| WP_GATE_TRANSIT | [1.25, 0.335, 180] | 통과 | [1.25, 0.225, 180] | y 쪽 0.11 m (관제 담당 승인 2026-10-22) |
| WP_UNLOAD | [0.415, 1.85, 180] | 통과 | 같음 | 0 |
| WP_BENCH_DELIVERY | [0.29, 1.31, 90] | **실패** — 점이 벤치 위, 원 안 112셀 모두 점유 | [0.29, 1.16, 90] | y 쪽 0.15 m (벤치 아래쪽) |

- 좌표는 도면의 웨이포인트 중심이다. WP_GATE_TRANSIT 은 도면에 없어 게이트 중심으로 더했다 (사용자 요청). 예전 맵의 WP_RETURN 은 이 도면에 없어 뺐다.
- theta 는 도면에 없다. 작업 대상을 바라보는 방향으로 둔 초안이다 (HOME 은 예전 맵 값 270). 트레이 방향이 정해지면 고친다. theta 는 맵 YAML 안에 있어서 고치면 map_hash 가 바뀐다 (7절 절차, 모든 장비를 다시 빌드한다). 한 번에 모아 고친다.
- approach_pose 로 린트하면 반경 0.06 m 에서 8개 모두 통과한다.
- 주의: 옮긴 벤치 정차점은 반경 0.06 m 에서 **겨우** 통과한다 (여유 5.2 mm). 반경 0.066 m 부터 실패한다 (0.065 m 까지만 통과). 반경 0.11 m (6 cm + SR-08 의 1차 정차 오차 ±5 cm) 로 보면 WP_LOAD_1·WP_LOAD_2 도 실패한다. 둘 다 랙 A·B 아래 면에서 0.105 m 떨어져 있다. 시험 `test_wider_radius_fails_moved_approach_poses` 가 이 사실을 고정한다.

  ```bash
  PYTHONPATH=src/cobot_control_center python3 -m cobot_control_center.map_contract lint --radius 0.11   # 지금은 1
  ```

- 그러니 로드맵 S1 출구 검사 3 의 '정본에서 통과' 는 반경 6 cm 기하 검사를 통과했다는 뜻이다. 그 자리로 주행해도 된다는 근거가 아니다. 반경 6 cm 는 핑키 외형 실측도 아니다.
- 게이트 정차점: 장애물 랙 2 [1.30~2.25, 0.45~0.64] 가 중앙 벽 동쪽 면(x 1.30)에 붙어 있다. 그래서 창고 쪽에서 본 게이트의 실제 통행 높이는 게이트 폭 0.67 m 가 아니라 y 0~0.45 m 다. 게이트 중심 [1.25, 0.335] 는 랙 2 모서리에서 0.132 m 라 여유가 가장 좁은 자리다. 정차점(approach_pose)을 통행대 중심 [1.25, 0.225, 180] 으로 내렸다 (관제 담당 승인 2026-10-22). 가장 가까운 비자유 셀까지 0.230 m (아래 벽), 반경 6 cm 여유 170 mm 다. 작업점(work_pose)은 사용자가 요청한 게이트 중심 그대로다.
- 도면의 '핑키사이즈' 상자는 0.16 × 0.12 m 다 (외접 반경 0.10 m, 실측 아님). 반경 0.10 m 로 린트하면 벤치 정차점만 실패한다. 이때 여유는 WP_LOAD_2 7.5 mm, WP_LOAD_1 10.0 mm, WP_HOME_1~3 15 mm 다.
- 통로 폭 참고 계산 (린트 항목이 아니다): 반경 r 원이 셀 중심을 따라(8방향) 지나갈 수 있는 가장 큰 r 을 쟀다.

  | 구간 | 가장 큰 r | 병목 |
  |---|---|---|
  | 창고 빈 곳 [1.75, 1.35] → 게이트 중심 | 약 0.125 m | 장애물 랙 1·2 의 끝과 벽·중앙 벽 사이 틈 약 0.25 m |
  | 게이트 중심 → 매장 빈 곳 [0.70, 0.60] | 약 0.125 m | 게이트 바로 옆 장애물 랙 2 (게이트 중심에서 0.13 m) |

  게이트 폭(0.67 m)이 아니라 **가로 장애물 랙 둘레 틈(약 0.25 m)이 창고→게이트 병목**이다. 핑키 + 적재 상자 외형이 이보다 크면 이 배치로는 지나갈 수 없다. 개인 시뮬레이션(MuJoCo)도 이 배치에서 계획 여유 30 mm 조건으로 창고→게이트 경로를 찾지 못했다. 장애물 랙을 세로로 돌린 대안에서는 같은 계산으로 약 0.195 m 다. 랙 배치는 팀 결정이다 (8절).

## 6. work_pose 와 approach_pose

- **work_pose (작업점)**: 원래 웨이포인트 좌표. 팔이 박스를 집거나 놓는 자리라서 탁자 위(점유 셀)일 수 있다. 맵 YAML 의 `waypoints` 와 같아야 한다.
- **approach_pose (정차점)**: 핑키가 Nav2 로 멈추는 자리. 둘레가 비어 있어야 한다. SR-08 의 1차 Nav2 정차가 여기다.
- **arm_id (연계된 팔, 선택)**: 그 지점에서 일하는 팔. 이름은 인터페이스 계약의 `omx_1`~`omx_3` 이다. 팔이 없는 지점은 적지 않는다 (메시지로 낼 때는 빈 문자열). 초안 값은 도면의 팔 표식 OMX_1/2/3 바로 옆 웨이포인트에 붙였다: WP_LOAD_1 → `omx_1`, WP_LOAD_2 → `omx_2`, WP_UNLOAD → `omx_3`. 관제 코어(fms_core, S2)가 `MapInfo.waypoints[].arm_id` 를 채울 때 이 값을 쓴다 (출발 게이트의 '연계된 팔'). 웨이포인트와 팔의 연계는 이 파일 하나에만 적는다. 린트는 글자 규칙(영문자로 시작, 영문자·숫자·`_`)만 본다.
- 이번 초안의 approach_pose 는 이렇게 정했다.
  - work_pose 가 린트를 통과하면 그대로 쓴다 (7개). 그중 WP_GATE_TRANSIT 은 관제 담당이 승인해 통행대 중심으로 내렸다 (5.3절).
  - 실패하면 work_pose 에서 0.01 m 간격 격자점 가운데 반경 원이 모두 비는 **가장 가까운 점**을 쓴다 (1개). theta 는 work_pose 와 같게 두었다.
  - 같은 거리의 점이 여럿이면 y 가 가장 작은 (아래쪽) 점, 그다음 x 가 가장 작은 (왼쪽) 점을 고른다. 벤치 웨이포인트에는 같은 거리(0.15 m) 후보가 둘 있다: 아래 [0.29, 1.16], 위 [0.29, 1.46] (여유는 둘 다 5.2 mm). 규칙대로 아래를 골랐다. 어느 쪽에서 접근할지는 주행·매장 쪽 결정이다 (시험 `test_bench_has_equidistant_candidate_above` 가 이 사실을, `test_nearest_free_point_tie_break` 가 규칙을 고정한다).
- 이 값은 기하만 본 것이다. 주행 담당이 아래를 확인해야 한다.
  1. 반경 여유 (가장 가까운 비자유 셀 중심까지 거리 − 0.06 m): WP_BENCH_DELIVERY 정차점 5.2 mm, WP_LOAD_2 47.5 mm, WP_LOAD_1 50.0 mm, WP_GATE_TRANSIT 정차점 170 mm. SR-08 의 1차 정차 허용(±5 cm)을 생각하면 벤치 정차점은 모자란다 (5.3절).
  2. 진입 방향(theta)과 팔 도달 거리. 벤치 정차점은 work_pose 바로 아래(진행 방향 뒤쪽)라 진입 방향은 그대로다. 팔 고정대가 맵에 없으므로 WP_LOAD_1·WP_LOAD_2·WP_UNLOAD 는 고정대를 놓은 뒤 다시 본다.
  3. 경로 연결. 참고 계산으로, 반경 6 cm 를 지킨 채 8개 정차점은 모두 한 덩어리의 빈 공간에 있다 (8방향 연결). 더 큰 외형은 5.3절의 통로 폭 표를 본다. 이 검사는 린트 항목이 아니다.
  4. 핑키 외형으로 정한 린트 반경 (지금 6 cm 는 설계서 값이다).
- 이 확인은 S1 머지 조건이 아니다. 실물 핑키에 이 정차점을 Nav2 goal 로 보내기 전 (늦어도 S3 주행 시험 전) 에 끝나야 하는 선결 조건이다.
- 확인이 끝나면 `approach_poses.yaml` 의 `status` 를 `confirmed` 로 바꾼다. 정차점 값을 고치면 5.3절과 시험 `test_wider_radius_fails_moved_approach_poses` 도 같은 PR 에서 고친다.

## 7. 맵을 바꾸는 절차

1. 주행 담당이 브랜치를 만들고 `src/cobot_bringup/config/maps/` 의 PGM·YAML 을 고친다. 공통 패키지라 PR 은 팀 리뷰를 받는다.
2. map_hash 를 다시 계산해 `approach_poses.yaml` 의 `map` 블록(`pgm_sha256`, `yaml_lf_sha256`, `map_hash`)을 고친다. 웨이포인트가 바뀌었으면 `work_pose`·`approach_pose`·`arm_id` 도 고친다.
3. `test_map_contract.py` 의 고정 값을 새 맵에 맞게 고친다: sha256(`CANON_PGM_SHA256`, `CANON_YAML_SHA256`), 실패 목록(`EXPECTED_WORK_POSE_FAILURES`, `EXPECTED_WIDE_RADIUS_FAILURES`), 옮긴 정차점(`EXPECTED_MOVED_APPROACH`), 팔 연계(`EXPECTED_ARM_IDS`), 벽·게이트 좌표(`PARTITION_BOUNDS_M`, `GATE_BOUNDS_M`, `test_gate_is_67cm_at_bottom_wall` 의 셀 수), 아레나 검사점(`test_arena_is_2_5_by_2_4`), 벤치 후보 좌표(`test_bench_has_equidistant_candidate_above`). 이 문서의 '지금 값' 과 결과 표도 같은 PR 에서 고친다.
4. `map_lint` 가 0, 시험이 통과하는지 본다. PR 본문에 새 map_hash 를 적고 팀에 알린다.
5. 머지 뒤에는 FMS PC 와 핑키가 **같은 커밋**을 받아 `colcon build` 한다. 맵 파일을 장비마다 복사해 나르지 않는다. 각 장비에서 `ros2 run cobot_control_center map_hash` 로 값이 같은지 본다. 다르면 펜싱(SR-20)에서 이동 명령이 거부된다.

## 8. 남은 결정과 할 일

- D3 를 `decided` 로 바꾼다 (관제 담당 공지 뒤, 결정자·날짜 기록).
- D3 공지와 결정 기록에 '옮긴 정차점 1건(벤치)은 기하만 본 초안이고, 반경 6 cm 는 핑키 외형 실측이 아니다' 를 적는다 (5.3절).
- **장애물 랙 배치**를 정한다: 도면 원안(가로)이면 창고→게이트 병목이 약 0.25 m 다 (5.3절). 세로로 돌리면 맵을 바꾼다 (7절). 핑키 + 적재 상자 외형 실측이 함께 필요하다.
- **팔 고정대 위치·외형**을 정해 맵에 넣거나 Nav2 keepout 으로 막는다 (2절). 지금 맵에서 팔 자리는 자유 셀이다. 넣으면 WP_LOAD_1·WP_LOAD_2·WP_UNLOAD 정차점을 다시 본다.
- **SR 대조**: SR v5.0 원문의 SR-04 는 '2.4×2.4m 평면 맵(`map_shoe_store_flat`)', SR-05 는 0.8 m 통로를 적는다. 정본(2.5 × 2.4 m, 67 cm 게이트)과 다르다. SR 정본은 SR_v2(Confluence 5406727)로 관제 담당이 정했다 (결정 D17 에 기록, 2026-10-22). 원문 대조는 아직이다. 대조한 뒤 이 줄과 머리의 SR 인용을 고친다.
- **도면 파일을 받는 곳**을 정한다 (팀 Confluence 첨부나 공유 폴더). 지금은 sha256 과 2절의 경계 표만 있다. 작은 파일이면 `docs/` 에 HTML 을 그대로 커밋해 sha256 과 대조할 수도 있다.
- **카메라 2 설치**: 도면은 15 cm 저각도, 관제 담당 계획은 게이트 벽체 상단(1.0~1.2 m) 하향이다. 카메라 구성(D10)에서 확정하고 도면을 고친다. 바닥 받침대가 생기면 맵에 넣고 게이트 정차점을 다시 본다 (도면 아이콘이 게이트 중심에서 0.045 m).
- D3 결정 기록(`docs/fms_decisions.md` 의 D3)에 '`cobot_control_center` → `cobot_bringup` 은 맵 파일만 읽는 의존이고 `package.xml` 에 적지 않는다 (순환 방지)' 를 예외로 적고 팀 확인을 받는다 (2절).
- approach_pose 와 반경 6 cm 를 주행 담당이 확인한다 (6절). S1 머지 조건이 아니라 실물 주행 전 선결 조건이다.
- `cobot_bringup` 에는 `.py` 가 없어 `ament_copyright` 가 검사하는 파일이 0개다. `CMakeLists.txt`·`package.xml`·launch XML 의 라이선스 머리 주석은 리뷰로 본다.
- 맵 YAML 의 `waypoints` 는 팀이 더한 키다. nav2 map_server 는 이 키를 읽지 않는다.
- 회전한 맵(origin yaw ≠ 0)과 trinary 가 아닌 mode 는 아직 지원하지 않는다 (린트가 오류로 막는다).
- 도달 가능성(경로 연결)·통로 폭 검사는 린트에 없다 (5.3절의 표는 참고 계산이다).
- CLAUDE.md §2 구조도·담당표에 `cobot_bringup`·`cobot_control_center` 를 더하는 일은 접두사 `cobot_` 확정(D1) 뒤 규칙 PR 에서 한다.
