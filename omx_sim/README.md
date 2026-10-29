# omx_sim — OMX 작업 환경 MuJoCo 시뮬레이터

ROBOTIS OMX-F(5축 + 그리퍼)의 공식 MuJoCo 모델 위에 상자 옮기기 작업 환경을 실측값과 녹화 영상에 맞춰 만든 시뮬레이터입니다.
작업 환경: 받침대, 흰 테이블, Pinky 원판, 상자, 위쪽·손목 카메라.
LeRobot 0.6.1로 녹화한 데이터셋과 학습한 정책(ACT, SmolVLA)을 확인하는 데 씁니다.

- ROS 2 패키지가 아닙니다. `src/cobot_simulation`(ROS 2 경량 아레나 시뮬레이션)과 따로 동작하고, 서로 import하지 않습니다.
- LeRobot·PyTorch가 필요해서 Docker 이미지(`docker/`) 안에서 실행합니다.
- 실물 로봇·카메라·시리얼은 열지 않습니다. 녹화된 데이터만 읽습니다.

## 할 수 있는 것
| 기능 | 스크립트 | 결과 |
|---|---|---|
| 시연 재생 | `sim/replay_episode.py` | 녹화된 관절값대로 팔을 움직이고, 그리퍼가 닫혀 있는 동안 상자를 함께 옮김. 실제와 시뮬 화면을 위쪽·손목 카메라별로 나란히 담은 mp4 |
| 모델 비교 (open-loop) | `sim/eval_open_loop.py` → `sim/render_comparison.py` | 일정 프레임마다 녹화 화면과 관절값을 모델에 넣어 동작을 예측하고, 시연과의 오차(metrics.json)·관절 그래프·비교 영상을 만듦 |
| 체크포인트 일괄 평가 | `sim/eval_policy.py` | 관절·그리퍼 오차, 그리퍼 닫힘·열림 시점 오차, 부드러움 |
| 여러 평가 결과 합치기 | `sim/merge_eval.py` | 데이터셋이 달라도 같은 시연이면 한 비교로 묶음 |

closed-loop(시뮬레이터 안에서 정책이 직접 집어 보기)는 아직 지원하지 않습니다. 아래 '한계'를 참고하세요.

## 준비물
1. **Docker 이미지** (차례대로 빌드)
   ```bash
   docker build -f docker/Dockerfile        -t omx-lerobot:0.6.1         docker
   docker build -f docker/Dockerfile.smolvla -t omx-lerobot-smolvla:0.6.1 docker
   docker build -f docker/Dockerfile.sim     -t omx-lerobot-sim:0.6.1     docker
   ```
   `Dockerfile.sim`은 MuJoCo 3.3과 CPU 렌더링(OSMesa)을 추가합니다.
2. **데이터셋**: LeRobot 형식 데이터셋을 `omx_sim/data/<이름>/`에 둡니다. 커밋하지 않습니다(`.gitignore`).
   - 10/27 환경: `omx_1027_jihyeok_train8`, `omx_1027_jihyeok_eval1` (ACT `_grip` 정책용은 `_grip` 버전)
   - 10/24 환경: `omx_1024_test_jihyeok_success`
   - heart_box: Hugging Face `Sungah/omx_heart_box` 등
3. **체크포인트**: `omx_sim/outputs/train/<실험>/checkpoints/<step>/pretrained_model`에 둡니다. 또는 HF 저장소 id를 그대로 넘겨도 됩니다(예: `Sungah/omx_box_act`).

## 실행
모든 명령은 `omx_sim/`에서 실행합니다.
```bash
R='docker run --rm --user '"$(id -u):$(id -g)"' -e HOME=/workspace/.home -v '"$PWD"':/workspace -w /workspace omx-lerobot-sim:0.6.1'

# 씬 다시 만들기 (calib/*.json -> sim/open_manipulator/.../mujoco/omx/workspace_scene*.xml)
$R python -I sim/build_scene.py --params sim/calib/scene_params_1027.json

# 시연 재생 -> outputs/sim_replay/ep000.mp4
$R python -I sim/replay_episode.py --params sim/calib/scene_params_1027.json --episode 0 \
    --out outputs/sim_replay/ep000.mp4

# 10/27 ACT 4개 모델 비교 (GPU 필요) -> outputs/eval/cmp_1027/
docker run --rm --gpus '"device=0"' --user "$(id -u):$(id -g)" -e HOME=/workspace/.home \
    -v "$PWD:/workspace" -w /workspace omx-lerobot-sim:0.6.1 bash scripts/cmp_1027_run.sh
```
`scripts/cmp_run.sh`, `scripts/cmp_all_run.sh`는 heart_box SmolVLA 비교 예시입니다(full / holdout / phases).

## 구조
```
omx_sim/
├── docker/                      # 이미지 3단계 (lerobot -> smolvla -> sim)
├── scripts/                     # 모델 비교 실행 예시
└── sim/
    ├── calib/                   # 환경별 씬 파라미터 (맞춘 값과 근거 'source' 포함)
    │   ├── scene_params.json        # 10/24 환경
    │   └── scene_params_1027.json   # 10/27 환경
    ├── open_manipulator/        # ROBOTIS 모델 (Apache 2.0, NOTICE.md) + 생성된 씬 xml
    ├── build_scene.py           # 파라미터 -> MuJoCo 씬
    ├── replay_episode.py        # 시연 재생
    ├── eval_open_loop.py, eval_policy.py, merge_eval.py, render_comparison.py   # 모델 비교
    └── (보정) calibrate_*.py, fit_*.py, anchor_kinematics.py
```

## 좌표와 관절 변환
- **좌표**: 원점은 로봇 바닥 중심(받침대 윗면)입니다. x = 로봇 앞, y = 왼쪽, z = 위. 단위는 m, 도.
- **관절 변환**(lerobot 값 → 각도):
  - 몸 관절: 값 × 1.8°
  - 그리퍼: (값 − 50) × 3.6°, 0~100° 범위로 자름
  - 근거: lerobot `omx_follower` 공장 기본 캘리브레이션(raw 0~4095 = 360°, raw 2048 = 0°)
  - 녹화된 `aux.ee_pose`와 시뮬레이터 계산 그리퍼 끝 위치가 1 mm 이내로 일치

## 환경 값을 정한 방법 (10/27)
줄자 값과 영상 값이 다르면 영상 값을 씁니다. 각 값의 근거는 `sim/calib/scene_params_1027.json`의 `source`에 적혀 있습니다.

| 항목 | 방법 |
|---|---|
| 받침대·테이블 앞뒤·좌우·상자 크기 | 줄자 |
| 테이블 높이, 상자 시작 위치 | 상자를 잡는 순간의 그리퍼 끝 위치(정기구학) |
| Pinky 원판 | 위쪽 영상의 흰 원판 모양에 맞춤 (겹침 0.94) |
| 위쪽 카메라 | 위쪽 영상 속 팔 모양에 맞춤 (`fit_top_camera_1027.py`, 겹침 0.64. 줄자 위치로는 0.50) |
| 손목 카메라 | 10/24 값 그대로 (`fit_wrist_camera_1027.py`로 다시 맞춘 결과가 0.3대라 반영하지 않음) |

겹침(IoU)은 실제 화면과 시뮬레이터 화면에서 같은 물체 영역이 겹치는 비율입니다. 1이면 완전히 일치합니다.

## 한계
- 줄자로 잰 테이블 높이(받침대 기준 22 cm)와 정기구학으로 구한 높이(15.6 cm)가 6.5 cm 다릅니다. 관절 영점을 영상으로 다시 맞춰도 3.6° 이하라서 줄자 측정을 다시 확인할 필요가 있습니다.
- 실제 손목 카메라는 광각 렌즈이고 시뮬레이터는 핀홀 카메라라 손목 화면이 맞지 않습니다. 손목 영상을 보고 움직이는 정책의 closed-loop 평가는 아직 믿을 수 없습니다.
- 재생은 물리 없이 관절값을 직접 넣는 방식(kinematic)입니다. 상자는 잡는 동안 그리퍼에 붙여 옮기고, 놓으면 아래 물체 위에 내려놓습니다.
