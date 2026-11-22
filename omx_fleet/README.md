# omx_fleet — 관제용 OMX 팔 실행기

관제(`cobot_manipulation` 의 `arm_adapter_node`, `backend:=worker`)가 팔 1대에 일을 시킬 때 쓰는 실행기다.
사람이 버튼을 누르는 대신 어댑터가 stdin/stdout JSON 으로 "집어", "멈춰" 를 보내고 결과를 받는다.

- LeRobot **0.4.4** (`~/venv/il`, Python 3.10). 이 브랜치의 `omx_recoder`(0.6.1)와 venv 가 다르다.
- 모델은 0.4.4 로 학습한 ACT. 기본은 관절 6 + top/wrist 카메라. 팔 설정 `robot_type` 으로 그리퍼 전류·MoGe depth 모델(omx_1031 E 등)도 된다 (아래 '로봇 타입·박스 번호').
- 2026-11-15 팔 1대(omx1) 기준. 실제 팔로는 아직 시험하지 않았다 (가짜 로봇·모델 로드만 확인).

## 왜 따로 있나

`inference.sh`(`lerobot-record`) 를 작업마다 새로 켜면 끝날 때와 다음 연결 때 lerobot 이 토크를 꺼서
**그 사이 팔이 떨어지고 잡은 물건을 놓친다**. 이 실행기는 켜질 때 한 번만 연결하고 모델을 미리 올린 뒤,
작업이 끝나도 토크를 유지한 채 다음 일을 기다린다.

## 파일

| 파일 | 내용 |
|---|---|
| `omx_fleet_worker.py` | 실행기. 대화 방식은 파일 맨 위 설명 |
| `fleet_runtime.py` | 로봇 타입(전류·depth)·박스 원핫·동작 성공 판단(`success_motion`)·그 작업 실행 루프 |
| `omx_chain.py`, `success_judge.py` | 대시보드 v2 (OMEN-11 `~/il_ws/omx_act_1027/dashboard_v2/`, 2026-11-17 팔 멈춤 판단·녹화 반영본) 에서 **고치지 않고 복사** (2026-11-18). 예전 복사본(a54637d)은 success.json 의 팔 멈춤 조건(`still_speed`·`rest_pose`)을 무시해 뚜껑을 누르는 중에도 성공을 낼 수 있었다. 바꿀 일이 있으면 원본과 함께 바꾼다 |
| `fleet_arms.example.yaml` | 팔별 설정 예시 (카메라·캘리브레이션 이름·쉬는 자세·action → 모델 경로 또는 번들·버전) |
| `fleet_arms.yaml` | 이 PC 의 실제 설정. git 에서 제외 |
| `torque_probe.py` | 모터 토크 켜짐(`Torque_Enable`)을 읽기만 한다. 팔 노드가 실행기가 없을 때 불러 관제에 실측을 보인다 |
| `read_pose.py` | 토크를 켜지 않고 관절 값을 읽는다 (쉬는 자세 재기용, `--save` 로 파일 저장). 실행기가 꺼져 있을 때만 |

## 모델 지정과 번들 (v0.2, 2026-11-17)

팔마다 모델·입력이 다르므로 공통으로 지킬 것만 정한다. 나머지(저장소 이름, 실행 코드, 입력 형식)는 각자 정한다.

### 모델을 적는 두 가지 방법 (`fleet_arms.yaml` 의 action 칸)
```yaml
actions:
  # ① 경로를 그대로 (어디에 받았든 상관없음. 관제에는 폴더 이름만 보인다)
  pick:
    model: ~/outputs/train/omx_1031_act_smolvla/models/act_1031_E_all_5000step
    seconds: 90
  # ② 번들·버전 (<bundles_dir>/<bundle>/<version>/models/<model>. 관제에 omx_pick_za@v1 처럼 보인다)
  load:
    bundle: omx_pick_za
    version: v1
    model: act          # models/ 아래 폴더가 하나면 생략
    seconds: 90
    # safe_pose: ~/il_ws/poses/load_safe_omx1.json   (선택)
```
- ② 는 맨 위 `bundles_dir` (기본 `~/il_ws/bundles`) 아래에서 찾는다. 번들·버전 폴더가 없거나, `model` 을 안 적었는데 `models/` 아래 폴더가 하나가 아니면 켜기 전에 오류를 낸다.
- 버전을 바꾸거나 되돌릴 때는 ① 경로 또는 ② `version` 만 고치고 팔을 다시 켠다.

### init_pose.json 을 찾는 곳
두 방법 모두 **모델 폴더의 두 단계 위** (`<저장소>/models/<모델>` → `<저장소>/init_pose.json`) 를 본다.
- 시작 자세: 있으면 작업 전에 이 자세로 천천히 이동, 없으면 이동 없이 시작.
- 안전 자세 (작업 뒤 돌아올 자세): action 의 `safe_pose` → 없으면 위 `init_pose.json`. **둘 다 없으면 실행기가 켜지지 않는다** (`준비 실패`).
- 형식: `{"pose": {"shoulder_pan": .., "shoulder_lift": .., "elbow_flex": .., "wrist_flex": .., "wrist_roll": .., "gripper": ..}}` (lerobot 캘리브레이션 단위, 보통 학습 데이터 첫 프레임).

### 모델 저장소에 공통으로 둘 것
```text
<아무 이름>/
├── models/<모델 이름>/   lerobot pretrained_model 폴더 (config.json, model.safetensors, policy_*). 여러 개여도 됨
├── init_pose.json        시작 = 안전 자세
└── README.md             모델 카드: 하는 일, 데이터셋, 입력(카메라·추가 상태), 녹화한 팔·캘리브레이션
```
- 그 밖의 파일(실행 코드, 가중치, 평가 기록)은 자유롭게 둔다.
- 버전은 Hugging Face 태그나 커밋으로 고정하고, 받을 때 `--revision` 을 준다 (PC 마다 같은 모델이 깔리게).
- 입력이 관절 6 + `top`·`wrist` 가 아니면 (깊이 카메라, 그리퍼 전류 등) 모델 카드나 모델 폴더에 적는다.
  이 실행기는 지금 관절 6 + `top`·`wrist` 를 받는 lerobot 0.4.4 ACT 만 돌린다 (`omx_chain.check_inputs`).

### 받기 예
```bash
hf download Sungah/omx_1031_act_smolvla --revision <태그나 커밋> \
  --local-dir ~/il_ws/bundles/omx_1031_act_smolvla/v1     # ② 로 쓸 때. ① 이면 아무 곳
```

### 팔에 딸린 값 (모델 저장소에 넣지 않음)
카메라 경로, 캘리브레이션 이름(`robot_id`), 쉬는 자세(`rest_pose`, `~/il_ws/poses/rest_pose_<팔>.json`)는
현장에서 팔마다 정해 `fleet_arms.yaml` 에 적는다.

카메라는 경로(`top`·`wrist`) 대신 모델 ID(`top_model`·`wrist_model`, `lsusb` 의 `vid:pid`)로 적을 수 있다.
그러면 실행기가 보드(어댑터가 넘긴 시리얼 포트)가 꽂힌 USB 허브에서 그 모델 카메라를 찾는다 (`usb_cams.py`).
두 팔 카메라가 같은 기종이라 by-id 로는 구별되지 않고, by-path 는 다시 꽂으면 바뀌기 때문이다.
- 카메라는 그 팔 보드와 같은 허브에 꽂는다. 한 허브에 같은 기종이 둘이면 정하지 않는다
- 못 찾으면 팔에 연결하기 전에 `fatal`("카메라 찾기 실패: …")로 끝난다
- 확인: `python usb_cams.py /dev/serial/by-id/<보드> top=4c4a:4a55 wrist=0c45:6367`

### 관제에 보이는 것
`ready` 에 action 별 `models` (bundle·version·model_name·path·init_pose·success_judge 유무), `rest_pose`, `safe_tol` 이
실린다. 팔 카드에 `pick omx_pick_za@v1` (① 이면 폴더 이름) 으로 보이고, 작업 결과 `done` 에도 `model` 로 남는다.

## 한 작업의 순서

1. 그 모델의 `init_pose.json` 으로 천천히 이동 (없으면 생략)
2. 정책 실행 (최대 `seconds`, 성공 판단이 있으면 더 일찍 끝남)
3. 안전 자세로 이동 — **그리퍼는 그대로** (잡은 물건을 놓지 않게)
4. 관절을 다시 읽어 결과 보고

### 명령 하나로 이어서 실행 (`stages`, 2026-11-18)
대시보드 v2 연속 실행(추론1 → YOLO 판단 → 추론2)을 관제 명령 하나로 돌린다. action 칸에 `stages` 목록을 적는다.
```yaml
arrange_shoe:
  stages:
    - {bundle: omx_arrange_shoe_zc, version: v1, seconds: 90}   # YOLO+팔 멈춤 판단
    - {bundle: omx_load_zc, version: v1, seconds: 35}
```
- 단계마다 위 1~2 를 하고, 단계 사이에는 `--min-hold-s`(기본 1초) 토크를 유지한 채 멈춘다. 1단계 뒤 안전 자세로 돌아가지 않는다.
- 판단기가 있는 단계가 시간 안에 성공을 못 내면 다음 단계로 가지 않고 끝낸다 (`end_reason=timeout`).
- `success` 는 모든 단계를 끝까지 갔고 판단기가 있는 단계가 모두 성공일 때만 true.
- 마지막 단계 뒤에 3~4 (안전 자세 기본값 = 마지막 단계 번들의 `init_pose.json`).
- `done` 에 단계별 결과 `stages` (`name`·`end_reason`·`judge`·`seconds`) 가 붙고, `model` 은 `a@v1+b@v1`.
- 2단계부터만 전환 완화(`--ramp-s`)를 건다 (대시보드와 같음). 단계 하나짜리 action 은 예전처럼 늘 완화.
- 단계 시작·끝마다 `@fleet {"event":"progress", "id", "stage", "stages", "label", "state", "text"}` 를 낸다.
  `text` 는 관제 화면에 그대로 보일 한 줄이다: `신발 정리 진행 중 (1/2)` → `신발 정리 성공 (YOLO) → 신발 상차 진행`
  → `신발 상차 진행 중 (2/2)` → `신발 상차 완료 → 안전 자세로 이동`. 단계 이름은 stages 의 `label` (없으면 모델 폴더 이름).
  어댑터가 이 이벤트를 관제로 넘겨야 화면에 보인다 (어댑터·관제 웹 쪽 작업).

| 결과 | 기준 |
|---|---|
| `success` | 성공 판단이 성공을 낸 경우만 true: 번들 `success.json` YOLO (`success_basis=judge`) 또는 작업 설정 `success_motion` (`motion`). 둘 다 없으면 항상 false (`none`). `noop` 작업은 true (`noop`) |
| `arm_safe` | 그리퍼를 뺀 모든 관절 오차가 `--safe-tol`(기본 3, 약 5°) 이하. `hold` 로 끝나면 false |

## 로봇 타입·박스 번호·동작 성공 판단

omx_1031 번들(`Sungah/omx_1031_act_smolvla`)의 E 모델처럼 입력이 다른 모델을 위한 팔·작업 설정이다.

| 칸 | 어디 | 뜻 |
|---|---|---|
| `robot_type` | 팔 | `omx_follower`(기본) / `omx_follower_grip`(state + 그리퍼 전류) / `omx_follower_grip_depth`(+ MoGe `top_depth`) |
| `robot_code_dir` | 팔 | 전류·depth 로봇 코드(`omx_grip_robot.py`·`omx_depth_robot.py`)가 있는 번들 폴더 |
| `start_pose` | 팔 | 켜질 때(연결 직후, `ready` 전) 옮겨 둘 자세 (그리퍼는 자세 파일에 `gripper` 값이 있을 때만 옮김). 파일 경로 또는 action 이름(그 action 첫 단계 번들의 `init_pose.json`). 보통 학습 데이터 첫 자세. 없으면 옮기지 않는다 |
| `success_motion` | 작업 (또는 `stages` 의 단계) | 그리퍼 전류·회전으로 성공 판단 (아래). 전류가 있는 `robot_type` 에서만 |
| `noop: true` | 작업 | 팔을 움직이지 않고 바로 성공. 앞 작업 모델이 싣기까지 하는 경우의 `load` |

- depth 모델: `depth_info.json` 은 그 작업 모델 폴더에서 찾는다. 정책이 새로 예측하는 프레임(ACT 50 프레임마다)에서만 MoGe 를 돌린다 (번들의 `depth_sync` 와 같은 방식). 켤 때 한 번 미리 돌린다.
- 박스 번호: 모델 폴더 `omx_info.json` 의 `box.mode` 가 `state` 면 그 작업은 `run` 에 `"box": 1..4` 가 있어야 한다. 없거나 범위 밖이면 팔을 움직이지 않고 `rejected`. 원핫을 `observation.state` 끝에 붙인다 (번들 `omx_box.py` 와 같은 값). 관제 팔 노드는 작업 요청의 `shelf_row` 를 `box` 로 넘긴다.
- **성공 기준은 팔마다 다르다.** `success_motion` 은 `arms.<팔>.actions.<작업>` 마다 따로 적는다. 아래 기본값은 omx2(ZB 상차, omx_1031 E 모델) 기준으로만 맞춰 둔 것이라, 다른 팔(omx1·omx3)은 그 팔 시연에서 다시 재서 값을 적거나 아직 기준이 없으면 칸을 비운다 (그러면 `success=false` 로 관제가 주문을 보류한다).
- `success_motion` 순서 (값은 omx_1031 시연 2번에서 잰 것, 칸으로 바꿀 수 있다):
  1. 잡음: 그리퍼 전류 ≤ `grip_closed_ma`(-150 mA) 가 `hold_s`(0.5 s) 이어짐 (잡는 동안 약 -330 mA)
  2. 놓음: 처음 회전값(`shoulder_pan`)에서 `pan_away`(20) 이상 돌아간 채 |전류| < `grip_open_ma`(80) 가 `hold_s` 이어짐
  3. 돌아옴: 처음 회전값 ± `pan_home_tol`(5) 안에 `hold_s` 머묾 → 성공, 그 단계를 바로 끝낸다
- `stages` 와 함께 쓸 때: 박스 번호·`success_motion` 은 단계마다 정해진다 (박스 원핫을 받는 단계가 하나라도 있으면 `run` 에 `box` 필요).
  박스·동작 판단·depth 를 쓰는 단계는 `fleet_runtime.run_job` 으로 돌고, 그 단계에서는 번들 `success.json` YOLO 판단을 쓰지 않는다 (켤 때 `주의:` 로그).
  `success_basis` 는 실제로 쓴 판단기: `judge`·`motion`·`judge+motion`·`none`.
- 설정·모델·입력 모양만 확인 (팔·카메라 연결 없음): `ARM_ID=omx1 ROBOT_PORT=<포트> python omx_fleet_worker.py --arms-file fleet_arms.yaml --dry-check`

## 다른 팔에 YOLO 흐름 붙이기 (2026-11-18)

omx3(ZC)의 "추론1 → YOLO 성공 판단 → 추론2" 와 같은 흐름을 아무 팔에나 붙이는 순서. 실행기 코드는 팔마다 바꾸지 않는다.
팔마다 다른 것은 **번들(모델·판단 설정)** 과 **`fleet_arms.yaml` 의 그 팔 칸** 뿐이다.

### 1. 번들에 판단 설정 넣기
```text
<bundles_dir>/<번들>/<버전>/
├── models/<모델>/        ACT
├── init_pose.json        시작 자세
├── success.json          성공 판단 설정 (없으면 그 단계는 시간 기준)
└── yolo/<가중치>.pt       YOLO (세그멘테이션·검출 다 됨). success.json 의 model 은 번들 기준 상대 경로
```
`success.json` 예 (규칙 뜻은 `success_judge.py` 맨 위). 클래스 이름은 YOLO 모델의 클래스와 같아야 한다.
```json
{"model": "yolo/best_pick.pt", "camera": "top", "conf": 0.5,
 "arm_class": "",
 "target": "box_on_shelf", "hold_s": 3.0, "min_ratio": 0.8,
 "forbid": {"box_on_floor": 0.1}, "gap_s": 1.0,
 "still_speed": 0}
```
- `arm_class`: 이 클래스가 `arm_s` 초 보여야 판단을 시작 (시작 직후 오검출 방지). 비우면 바로 시작.
- 성공 = `target` 이 `hold_s` 동안 `min_ratio` 이상 보이고, `forbid` 클래스는 각 비율 이하. `still_speed>0` 이면 팔 멈춤도 본다.
- 오프라인으로 규칙을 맞출 때는 대시보드 v2 의 `success_check.py` (녹화 영상에 규칙 돌려 보기).

### 2. 팔 칸 적기 (`fleet_arms.yaml`)
```yaml
arms:
  omx1:
    rest_pose: ~/il_ws/poses/rest_pose_omx1.json
    actions:
      pick:                                   # 관제가 보내는 이름
        safe_pose: ~/il_ws/poses/rest_pose_omx1.json   # 끝나면 쉬는 자세로 (관제 '끄기'가 되게)
        stages:
          - bundle: omx_pick_za
            version: v1
            seconds: 60
            label: 집기                         # 관제 진행 표시 이름
            judge:                             # (선택) 이 팔에서만 success.json 값을 바꿈
              rest_pose: ~/il_ws/poses/pick_end_omx1.json   # 팔 멈춤 끝 자세는 캘리브레이션마다 다름
              conf: 0.6
          - bundle: omx_load_za
            version: v1
            seconds: 35
            label: 싣기
```
- `judge` 칸: `success.json` 의 키를 덮어쓴다 (`model`·`target`·`conf`·`hold_s`·`rest_pose` …). 모르는 키는 켜기 전에 오류.
  `rest_pose` 는 숫자 6개 대신 `init_pose.json` 모양 파일 경로도 된다. 번들에 `success.json` 이 없으면 `judge` 칸만으로 만든다
  (`model`·`target` 필수, 신발 상자 기본 클래스는 물려받지 않음). `judge: false` 면 그 팔에서는 판단을 끄고 시간 기준.
- 같은 번들을 다른 팔이 그대로 쓸 때 **팔 멈춤 조건(`still_speed`·`rest_pose`)** 이 있으면 그 팔로 끝 자세를 다시 재서 `judge.rest_pose` 로 준다.
  관절 값이 캘리브레이션마다 달라 omx3 값으로는 성공이 안 뜰 수 있다.
- `safe_pose` 를 안 적으면 마지막 단계 번들의 `init_pose.json` 으로 돌아간다. 그게 쉬는 자세와 다르면 끝난 뒤 관제 '끄기'가 거절된다.

### 3. 그 PC 준비 (예: 8-OMEN)
```bash
cd <저장소> && git pull                       # 이 폴더의 omx_fleet_worker.py·omx_chain.py·success_judge.py
source ~/venv/il/bin/activate
python -c "import ultralytics" || pip install --no-deps ultralytics ultralytics-thop   # lerobot 의존성 안 건드리게
```
`--no-deps` 라 빠진 패키지가 있으면 4 의 확인이 `ultralytics 가 설치돼 있지 않음 (No module named …)` 으로 알려 준다. 그 이름만 `--no-deps` 로 더 넣는다.

### 4. 켜기 전 확인 (팔이 움직이지 않음)
```bash
ARM_ID=omx1 ~/venv/il/bin/python omx_fleet_worker.py --arms-file fleet_arms.yaml --check
```
로봇에 연결하지 않고 번들·ACT·YOLO 가중치·클래스 이름·`judge` 칸·안전 자세를 모두 불러 본 뒤, action 마다 단계·끝 조건·
"끝난 뒤 안전 자세 = 쉬는 자세인지" 를 출력한다. 틀리면 관제에서 켤 때와 같은 `준비 실패: …` 를 낸다.
통과하면 관제에서 그 팔 '켜기' → '작업 시험'.

## 켜기·끄기 (관제)

관제는 어댑터에 `ArmCommand` `CMD_START`·`CMD_RESET` 을 보낸다 (`cobot_manipulation/docs/prd.md` 5절).
어댑터는 START 에 이 실행기를 띄우고, RESET 에 `{"cmd":"release"}` 를 보낸다.

- `release`: 지금 자세가 `rest_pose` 에서 그리퍼를 뺀 관절 `--safe-tol` 안이면 `released` 를 알리고 연결을 끊는다 (토크 꺼짐).
  아니면 `release_refused` 로 거절한다. **팔을 옮기지 않는다** (관제는 팔 모션을 시작하지 않는다).
  - 예외: 팔 설정 `release_move: true` (기본 false) 면 녹화기 Servo OFF 처럼 `release_moving` (예상 시간 `seconds`) 을 알리고
    그리퍼를 뺀 관절을 쉬는 자세로 옮긴 뒤 다시 잰다. 도착했으면 `released`, 아니면 `release_refused` (토크 유지).
    충돌 검사가 없고, 이동 중 온 hold 는 이동이 끝난 뒤 처리된다. `rest_pose` 를 실측한 뒤에만 켠다.
- 켤 때 자세 (선택, 팔 설정 `start_pose`): 연결 직후 그 자세로 천천히 옮긴 뒤 `ready` 를 알린다. 그리퍼는 자세 파일에 `gripper` 값이 있으면 옮기고, 없으면 그대로 둔다 (그리퍼를 두려면 `gripper` 를 뺀 자세 파일을 준다).
  action 이름을 주면 그 action 첫 단계 번들의 `init_pose.json`. 없으면 예전처럼 지금 자세 유지.
- `state`: 대기 중 관절 값을 `state` 로 알린다. 어댑터가 1초마다 물어 `ArmStatus` 에 싣는다.
- `rest_pose` 가 없으면 `release` 는 늘 거절된다. 처음 값은 shoebox_d 시작 자세이므로 실제 팔로 재서 바꾼다.
  팔을 쉬는 자세에 두고 켠 뒤 관제 저장소 `scripts/arm_console.py` 의 `saverest` 로 `rest_pose_omx1.json` 을 만든다
  (`~/il_ws/poses/` 로 옮기거나 경로를 인자로 준다).
  - 켜면 토크가 켜지고 시작 자세로 옮겨지므로 손으로 놓은 자세를 재기 어렵다. 그때는 토크를 푼 뒤 손으로 놓고,
    실행기가 꺼진 상태에서 `read_pose.py --port <보드> --robot-id <robot_id> --arm omx2 --save ~/il_ws/poses/rest_pose_omx2.json`
    으로 잰다 (모터에 쓰지 않음).
- 실행기를 `--release-without-rest` 로 띄우면 `rest_pose` 가 없는 팔은 거절 대신 바로 끊는다 (팔이 내려앉을 수 있음).
  쉬는 자세를 재기 전 임시 수단이다.
- 실행기가 강제로 꺼지면(kill) 토크를 끄지 못한 채 남는다. 팔 노드는 실행기가 없을 때 `torque_probe.py` 로 재서
  info 토픽 `torque` 칸에 싣고, 관제는 꺼짐인데 켜져 있으면 `torque_left_on` 경고를 띄운다.
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
# stdin 에 한 줄씩: {"cmd":"run","id":"t1","action":"pick"} (박스 모델이면 "box": 1..4) / {"cmd":"hold"} / {"cmd":"state"}
#                  {"cmd":"release"} / {"cmd":"quit"}
```

`omx_chain.py` 의 다른 옵션(`--device`, `--n-action-steps`, `--max-relative-target` 등)은 뒤에 붙이면 그대로 넘어간다.

## 주의

- 연결할 때 lerobot `configure()` 가 토크를 잠깐 껐다 켠다. 켜고 끌 때 팔은 쉬는 자세로 둔다.
- `quit`·오류로 끝나면 연결을 끊으며 토크가 꺼진다 → 팔이 내려앉을 수 있다.
- 초기 자세·안전 자세 이동(수 초) 중에는 `hold` 가 이동이 끝날 때 먹는다. 정책 실행 중에는 바로 멈춘다.
- 안전 자세 이동은 학습된 동작이 아니라 보간이다. 팔이 상자 안에 있으면 걸릴 수 있다.
- `ACT_ENSEMBLE_K` (k스텝 섞기) 를 쓰려면 `act_ensemble.py` 가 이 폴더의 상위 폴더에 있어야 한다 (`omx_chain.py` 가 그렇게 찾는다). 지금은 없다.
