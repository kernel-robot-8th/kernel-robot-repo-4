# omx_fleet — 관제용 OMX 팔 실행기

관제(`cobot_manipulation` 의 `arm_adapter_node`, `backend:=worker`)가 팔 1대에 일을 시킬 때 쓰는 실행기다.
사람이 버튼을 누르는 대신 어댑터가 stdin/stdout JSON 으로 "집어", "멈춰" 를 보내고 결과를 받는다.

- LeRobot **0.4.4** (`~/venv/il`, Python 3.10). 이 브랜치의 `omx_recoder`(0.6.1)와 venv 가 다르다.
- 모델은 0.4.4 로 학습한 ACT (관절 6 + top/wrist 카메라) 만 된다 (`omx_chain.check_inputs`).
- 2026-11-15 팔 1대(omx1) 기준. 실제 팔로는 아직 시험하지 않았다 (가짜 로봇·모델 로드만 확인).

## 왜 따로 있나

`inference.sh`(`lerobot-record`) 를 작업마다 새로 켜면 끝날 때와 다음 연결 때 lerobot 이 토크를 꺼서
**그 사이 팔이 떨어지고 잡은 물건을 놓친다**. 이 실행기는 켜질 때 한 번만 연결하고 모델을 미리 올린 뒤,
작업이 끝나도 토크를 유지한 채 다음 일을 기다린다.

## 파일

| 파일 | 내용 |
|---|---|
| `omx_fleet_worker.py` | 실행기. 대화 방식은 파일 맨 위 설명 |
| `omx_chain.py`, `success_judge.py` | `tool/omx-dashboard-v2` (a54637d) `omx_dashboard_v2/` 에서 **고치지 않고 복사**. 바꿀 일이 있으면 원본과 함께 바꾼다 |
| `fleet_arms.example.yaml` | 팔별 설정 예시 (카메라·캘리브레이션 이름·쉬는 자세·action → 모델 번들·버전) |
| `fleet_arms.yaml` | 이 PC 의 실제 설정. git 에서 제외 |

## 모델 번들 규격 (v0.1, 2026-11-16 제안)

학습한 모델은 아래 구조로 올린다. **작업 하나 = 번들 하나 = Hugging Face 저장소 하나**.

### 이름과 버전
- 저장소 이름: `<HF 계정>/omx_<작업>_<구역>`. 작업은 관제 action 이름(`pick`, `load`, `unload`…), 구역은 `za`·`zb`·`zc`.
  예: `Sungah/omx_pick_za`, `Sungah/omx_unload_zc`
- 버전: 새로 학습할 때마다 git 태그 `v1`, `v2`, … 를 새로 붙인다. 한 번 붙인 태그는 옮기거나 덮어쓰지 않는다.
  바꾼 이유는 모델 카드 맨 아래에 한 줄 (`v2: 에피소드 30 → 50`).

### 폴더
```text
omx_pick_za/
├── models/
│   └── act/                 pretrained_model 폴더 내용 그대로 (config.json, model.safetensors, policy_*)
├── init_pose.json           필수: 시작 자세 = 끝난 뒤 돌아오는 안전 자세 (학습 데이터 첫 프레임)
├── success.json             선택: YOLO 성공 판단 (형식은 success_judge.py 기본값)
├── yolo/<가중치>.pt          선택: success.json 의 model (번들 기준 상대 경로)
└── README.md                필수: 모델 카드
```
- `models/` 아래 모델 폴더는 하나만 둔다 (여럿이면 설정에 `model:` 로 골라야 한다).
- 모델: **lerobot 0.4.4 에서 읽히는 ACT**, 입력 `observation.state` [6] + `top`·`wrist` 카메라.
  0.6.1 로 학습했으면 `config.json` 의 `pretrained_revision` 을 지우고 올린다 (`omx_train/ACT/README.md`).
- `init_pose.json`: `{"pose": {"shoulder_pan": .., "shoulder_lift": .., "elbow_flex": .., "wrist_flex": .., "wrist_roll": .., "gripper": ..}}`
  (lerobot 캘리브레이션 단위). 없으면 `safe_pose` 를 따로 적지 않는 한 실행기가 시작을 거부한다.
- 쉬는 자세(`rest_pose`)는 번들에 넣지 않는다. 팔에 딸린 값이라 현장에서 팔마다 잰다.

### 모델 카드 (`README.md`)
```markdown
# omx_pick_za
| 항목 | 값 |
|---|---|
| 작업 / 구역 / 팔 | pick / ZA / omx1 |
| 하는 일 | 선반 2행에서 신발 상자 집기 |
| 데이터셋 | Sungah/omx_box_merged (에피소드 50개) |
| 학습 | ACT, 20k step, batch 8, lerobot 0.4.4 |
| 입력 | 관절 6 + top·wrist 카메라 |
| 녹화한 팔 / 캘리브레이션 | omx1 / omx_follower_arm |
| 최대 시간 | 90 s |
| 실물 시험 | 20회 중 17회 성공 (2026-11-20) |
| 상태 | 후보 / 검증됨 |
```

### 올리기 (학습 담당)
```bash
hf upload Sungah/omx_pick_za ./omx_pick_za .
huggingface-cli tag Sungah/omx_pick_za v1      # 새 CLI 는 hf repo tag create Sungah/omx_pick_za v1
```
올리기 전 확인: 이름 `omx_<작업>_<구역>` / `models/` 아래 모델 하나, 0.4.4 에서 열림 / `init_pose.json` 관절 6개 / 모델 카드 / 태그 `vN`.

### 현장에 두기 (Station PC)
```bash
hf download Sungah/omx_pick_za --revision v1 --local-dir ~/il_ws/bundles/omx_pick_za/v1
```
```text
~/il_ws/
├── bundles/<번들>/<vN>/     받은 번들 (예전 버전은 되돌리기용으로 남긴다)
└── poses/rest_pose_<팔>.json 쉬는 자세 (saverest 로 만듦)
```
`fleet_arms.yaml` 의 action 에 `bundle`·`version` 을 적는다 (`fleet_arms.example.yaml`). 관제 팔 카드에는
`pick omx_pick_za@v1` 처럼 보이고, 작업 결과에도 `model` 로 남는다.

## 한 작업의 순서

1. 그 모델 번들의 `init_pose.json` 으로 천천히 이동
2. 정책 실행 (최대 `seconds`, 성공 판단이 있으면 더 일찍 끝남)
3. 안전 자세로 이동 — **그리퍼는 그대로** (잡은 물건을 놓지 않게)
4. 관절을 다시 읽어 결과 보고

| 결과 | 기준 |
|---|---|
| `success` | 번들 `success.json` 의 YOLO 판단이 성공을 낸 경우만 true. 판단 모델이 없으면 항상 false (`success_basis=none`) |
| `arm_safe` | 그리퍼를 뺀 모든 관절 오차가 `--safe-tol`(기본 3, 약 5°) 이하. `hold` 로 끝나면 false |

## 켜기·끄기 (관제)

관제는 어댑터에 `ArmCommand` `CMD_START`·`CMD_RESET` 을 보낸다 (`cobot_manipulation/docs/prd.md` 5절).
어댑터는 START 에 이 실행기를 띄우고, RESET 에 `{"cmd":"release"}` 를 보낸다.

- `release`: 지금 자세가 `rest_pose` 에서 그리퍼를 뺀 관절 `--safe-tol` 안이면 `released` 를 알리고 연결을 끊는다 (토크 꺼짐).
  아니면 `release_refused` 로 거절한다. **팔을 옮기지 않는다** (관제는 팔 모션을 시작하지 않는다).
  - 예외: 팔 설정 `release_move: true` (기본 false) 면 녹화기 Servo OFF 처럼 `release_moving` (예상 시간 `seconds`) 을 알리고
    그리퍼를 뺀 관절을 쉬는 자세로 옮긴 뒤 다시 잰다. 도착했으면 `released`, 아니면 `release_refused` (토크 유지).
    충돌 검사가 없고, 이동 중 온 hold 는 이동이 끝난 뒤 처리된다. `rest_pose` 를 실측한 뒤에만 켠다.
- `state`: 대기 중 관절 값을 `state` 로 알린다. 어댑터가 1초마다 물어 `ArmStatus` 에 싣는다.
- `rest_pose` 가 없으면 `release` 는 늘 거절된다. 처음 값은 shoebox_d 시작 자세이므로 실제 팔로 재서 바꾼다.
  팔을 쉬는 자세에 두고 켠 뒤 관제 저장소 `scripts/arm_console.py` 의 `saverest` 로 `rest_pose_omx1.json` 을 만든다
  (`~/il_ws/poses/` 로 옮기거나 경로를 인자로 준다).
- `ready` 에는 action 별 모델 정보(`models`: bundle·version·model_name·path·init_pose·success_judge 유무),
  `rest_pose`, `safe_tol` 이 실린다. 어댑터가 이것을 관제에 넘겨 팔 카드에 보인다. `done` 에는 `model` (`omx_pick_za@v1`).

## 실행

보통은 어댑터가 띄운다. `cobot_manipulation/config/arm_adapter.yaml` 의 `worker_command` 예:

```text
/home/team11/venv/il/bin/python <이 폴더>/omx_fleet_worker.py --arms-file <이 폴더>/fleet_arms.yaml
```

직접 띄우면 **팔에 연결해 토크를 켠다** (사람이 옆에 있을 때만):

```bash
source ~/venv/il/bin/activate
cp fleet_arms.example.yaml fleet_arms.yaml   # 처음 한 번, 값 고치기
ARM_ID=omx1 ROBOT_PORT=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_<시리얼>-if00 \
  python omx_fleet_worker.py --arms-file fleet_arms.yaml
# stdin 에 한 줄씩: {"cmd":"run","id":"t1","action":"pick"} / {"cmd":"hold"} / {"cmd":"state"}
#                  {"cmd":"release"} / {"cmd":"quit"}
```

`omx_chain.py` 의 다른 옵션(`--device`, `--n-action-steps`, `--max-relative-target` 등)은 뒤에 붙이면 그대로 넘어간다.

## 주의

- 연결할 때 lerobot `configure()` 가 토크를 잠깐 껐다 켠다. 켜고 끌 때 팔은 쉬는 자세로 둔다.
- `quit`·오류로 끝나면 연결을 끊으며 토크가 꺼진다 → 팔이 내려앉을 수 있다.
- 초기 자세·안전 자세 이동(수 초) 중에는 `hold` 가 이동이 끝날 때 먹는다. 정책 실행 중에는 바로 멈춘다.
- 안전 자세 이동은 학습된 동작이 아니라 보간이다. 팔이 상자 안에 있으면 걸릴 수 있다.
- `ACT_ENSEMBLE_K` (k스텝 섞기) 를 쓰려면 `act_ensemble.py` 가 이 폴더의 상위 폴더에 있어야 한다 (`omx_chain.py` 가 그렇게 찾는다). 지금은 없다.
