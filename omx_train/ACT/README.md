# ACT 학습 · 추론

LeRobot 0.4.4의 ACT 정책을 Docker에서 학습·평가하고, 설치된 lerobot으로 OMX 로봇에서 추론합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `Dockerfile` | 학습 이미지 (python 3.12, lerobot 0.4.4) |
| `train.sh` | 학습. **lerobot-train 옵션 전체**가 들어 있고, 주석 없는 줄 = 마지막 학습에 쓴 값 |
| `train_gradient_accumulation.sh` | `train.sh`와 같은 옵션으로 gradient accumulation 학습 (GPU 메모리가 부족할 때) |
| `train_gradient_accumulation.py` | lerobot-train 실행기 + gradient accumulation. `train_gradient_accumulation.sh`가 사용 |
| `inference.sh` | 로봇 추론. **lerobot-record 옵션 전체**가 들어 있고, 주석 없는 줄 = 기본 실행 값 (0.4.4에는 lerobot-rollout이 없음) |
| `omx_record.py` | lerobot-record 실행기 (+ 그리퍼 전류 로봇 타입, k스텝 앙상블). `inference.sh`가 사용 |
| `omx_rollout.py` | lerobot 0.6.1용 lerobot-rollout 실행기 (0.4.4에서는 사용 안 함) |
| `omx_grip_robot.py` | `omx_follower_grip` 로봇 타입 (관절 6 + 그리퍼 전류) |
| `act_ensemble.py` | k스텝 temporal ensembling |
| `tools.sh` | 아래 Python 도구를 학습 이미지 안에서 실행 |
| `eval_policy.py` | 학습에서 뺀 에피소드로 평가 (녹화 영상 기반) |
| `prepare_box_datasets.py` | 원본 데이터셋 → 학습용 데이터셋 변환 (재현용) |

## 1. 학습

**준비물**: Linux + NVIDIA GPU (batch 16 기준 GPU 메모리 약 7GB), Docker + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), `hf` CLI (`pip install -U huggingface_hub`)

```bash
cd omx_train/ACT
docker build -t omx-act:0.4.4 .                  # 최초 1회
hf download Sungah/omx_1024_test_jihyeok_success --repo-type dataset --local-dir data/omx_1024_test_jihyeok_success
./train.sh 0                                     # GPU 0
```

`train.sh`의 기본값 = 마지막으로 학습한 설정입니다.

| 항목 | 값 |
|---|---|
| 데이터셋 | `omx_1024_test_jihyeok_success` (시연 10개, 30fps, 카메라 top/wrist) |
| batch / step | 16 / 13,484 (20 epoch, 1 epoch = 674 step) |
| 체크포인트 | 3,371 step(5 epoch)마다 → 5·10·15·20 epoch |
| 시간 | A6000 1장 약 47분 |

**`train.sh` 사용 예시**

```bash
# 1) 기본: 마지막 학습 설정 그대로 (omx_1024_test_jihyeok_success, batch 16, 20 epoch, 5 epoch마다 저장)
./train.sh 0

# 2) 다른 GPU, 결과 이름 지정
JOB_NAME=act_try2 ./train.sh 1

# 3) 다른 데이터셋 + lerobot 기본 학습량 (batch 8, 100k step, 20k마다 저장)
DATASET=box_merged ./train.sh 0 --batch_size=8 --steps=100000 --save_freq=20000

# 4) 평가용 에피소드(5, 9) 빼고 학습
EPISODES="[0,1,2,3,4,6,7,8]" JOB_NAME=act_ho ./train.sh 0

# 5) epoch 단위로 저장: 1 epoch = 프레임 수 / batch (예: 10,787 / 16 = 674 step)
./train.sh 0 --steps=6742 --save_freq=1348              # 10 epoch까지, 2 epoch마다

# 6) 그리퍼 전류 데이터셋 (observation.state 7개)
DATASET=box_merged_grip JOB_NAME=act_grip ./train.sh 0

# 7) 이미지 증강 켜기 (train.sh 안의 주석을 푸는 것과 같음)
./train.sh 0 --dataset.image_transforms.enable=true

# 8) 중단된 학습 이어서 (같은 JOB_NAME)
./train.sh 0 --resume=true --config_path=/outputs/train/act_omx_1024_test_jihyeok_success/checkpoints/last/pretrained_model/train_config.json

# 9) 데이터·결과를 다른 위치에
DATA_DIR=/mnt/ssd/lerobot_data OUT_DIR=/mnt/ssd/omx_outputs ./train.sh 0
```

- 뒤에 붙인 옵션은 `train.sh` 안의 값을 덮어씁니다. `train.sh` 안의 주석(`#`) 줄을 풀어도 됩니다 (적힌 값 = lerobot 기본값 또는 예시)
- 컨테이너 안에서는 데이터가 `/data`(= `DATA_DIR`), 결과가 `/outputs`(= `OUT_DIR`)입니다

입력으로 쓸 값을 고르는 옵션(`--state` 같은)은 없습니다. 모델 입력은 데이터셋의 `observation.state`와 카메라 영상으로 정해지므로, 그리퍼 전류 등을 추가하려면 데이터셋 state를 늘린 사본이 필요합니다 (`prepare_box_datasets.py`의 grip 단계).

**결과**: `outputs/train/<JOB_NAME>/checkpoints/<step>/pretrained_model/`

### (선택) GPU 메모리가 부족할 때: gradient accumulation

batch를 여러 조각으로 나눠 계산한 gradient를 모았다가 한 번에 업데이트합니다. lerobot에는 이 옵션이 없어서 `train_gradient_accumulation.py`가 학습 한 step만 바꿔 끼우고 나머지는 lerobot-train 그대로 실행합니다.

```bash
# GPU 메모리는 batch 16만큼 쓰고, 업데이트는 batch 32와 같음
GRAD_ACCUM=2 ./train_gradient_accumulation.sh 0 --batch_size=32
```

- `--batch_size` = 업데이트 1번에 쓰는 전체 batch, GPU에는 `batch_size / GRAD_ACCUM`씩 올라갑니다
- `--steps`, `--save_freq`, lr 스케줄은 업데이트 횟수 기준이라 `train.sh`와 같은 값을 쓰면 됩니다
- 옵션 목록은 `train.sh`의 `ARGS`를 그대로 읽어 오므로 기본값은 `train.sh`에서 바꿉니다
- 메모리가 충분하면 `--batch_size`를 직접 올리는 편이 빠릅니다 (조각 수만큼 forward/backward를 더 함)

## 2. 평가 (처음 보는 에피소드, 녹화 영상 기반)

평가용 에피소드를 빼고 학습한 모델만 의미가 있습니다.

```bash
M=/outputs/train/<JOB_NAME>/checkpoints/last/pretrained_model
./tools.sh 0 eval_policy.py --dataset_root /data/<DATASET> --episodes 5,9 --horizon 50 --model act=$M --out /outputs/eval/act.json
```

지표: 관절 오차(몸통 관절 5개, lerobot 단위 1 ≈ 1.8°), 그리퍼 오차, 그리퍼 닫힘/열림 시점 차이(초), 부드러움.
`--horizon N`은 N스텝마다 다시 예측, `--ensemble_k k`는 k스텝마다 예측하고 겹치는 예측을 평균합니다.

## 3. 로봇에서 추론 (`inference.sh`)

로봇 PC에서 **Docker 없이**, 설치된 lerobot으로 실행합니다.

```bash
pip install "lerobot[dynamixel]==0.4.4"          # 로봇 PC에 lerobot이 없을 때
lerobot-find-port                                 # → ROBOT_PORT
lerobot-find-cameras opencv                       # → TOP_CAM(위쪽), WRIST_CAM(손목). 사진으로 구분
lerobot-calibrate --robot.type=omx_follower --robot.port=/dev/ttyACM0 --robot.id=omx_follower  # 최초 1회
MODEL=outputs/train/act_omx_1024_test_jihyeok_success/checkpoints/013484/pretrained_model \
  ROBOT_PORT=/dev/ttyACM0 TOP_CAM=/dev/video0 WRIST_CAM=/dev/video2 ./inference.sh
```

`inference.sh`의 기본 실행 값:

| 항목 | 값 |
|---|---|
| 모델 (`MODEL`) | `outputs/train/act_omx_1024_test_jihyeok_success/checkpoints/last/pretrained_model` |
| 카메라 | `top` / `wrist` 640×480 30fps (모델 입력 이름과 같아야 함) |
| 장치 | `cpu` (GPU면 `--policy.device=cuda`) |
| 실행 길이 | `--policy.n_action_steps=50` (CPU 예측 1회 약 0.6~1.0초. GPU면 10까지 줄이면 반응이 빠름) |
| 안전 | `--robot.max_relative_target=10` (한 스텝 최대 이동량) |
| 실행 시간 | 30초 1회 (`--dataset.episode_time_s=30 --dataset.num_episodes=1`) |
| 실행 기록 | `outputs/eval/<시각>/`에 평가 데이터셋으로 저장 (Hub 업로드 안 함). 키보드 → 일찍 끝내기 / ← 다시 / Esc 중지 |

**`inference.sh` 사용 예시**

```bash
# 1) 기본: 스크립트의 "현장 설정"(MODEL, ROBOT_PORT, TOP_CAM, WRIST_CAM)을 고친 뒤
./inference.sh

# 2) 체크포인트·포트·카메라를 환경변수로 지정 (5 epoch 체크포인트)
MODEL=outputs/train/act_omx_1024_test_jihyeok_success/checkpoints/003371/pretrained_model \
  ROBOT_PORT=/dev/ttyACM1 TOP_CAM=/dev/video4 WRIST_CAM=/dev/video6 ./inference.sh

# 3) Hugging Face 번들의 모델 사용
hf download Sungah/omx_1024_jihyeok_act --local-dir omx_1024_jihyeok_act
MODEL=omx_1024_jihyeok_act/models/act_ep20 ./inference.sh

# 4) GPU로, 10스텝마다 다시 예측 (반응이 빠름)
./inference.sh --policy.device=cuda --policy.n_action_steps=10

# 5) 60초 동안, 안전 제한을 조금 풀어서 (동작이 너무 느릴 때)
./inference.sh --dataset.episode_time_s=60 --robot.max_relative_target=20

# 6) k스텝 temporal ensembling: 5스텝마다 예측하고 겹치는 예측을 평균 (부드럽지만 반응이 느림)
ACT_ENSEMBLE_K=5 ACT_ENSEMBLE_M=0.01 ./inference.sh --policy.n_action_steps=100

# 7) lerobot 내장 temporal ensembling: 매 스텝 예측 (GPU 권장)
./inference.sh --policy.device=cuda --policy.temporal_ensemble_coeff=0.01 --policy.n_action_steps=1

# 8) 그리퍼 전류로 학습한 모델 (관절 6 + 그리퍼 전류)
MODEL=outputs/train/act_grip/checkpoints/last/pretrained_model ./inference.sh --robot.type=omx_follower_grip

# 9) 카메라·관절 값을 실시간 화면으로 보면서
./inference.sh --display_data=true

# 10) 연속 5회 실행·녹화 (회당 30초, 사이에 15초 정리 시간)
./inference.sh --dataset.num_episodes=5 --dataset.episode_time_s=30 --dataset.reset_time_s=15
```

- **lerobot 0.6.1로 학습한 모델**(아래 Hugging Face 번들 포함)은 `config.json`의 `pretrained_revision` 항목 때문에 0.4.4에서 읽히지 않습니다. 한 번 지우고 쓰세요:
  `python -c "import json,sys;p=sys.argv[1]+'/config.json';c=json.load(open(p));c.pop('pretrained_revision',None);json.dump(c,open(p,'w'),indent=4)" <모델 폴더>`
- 모델은 반드시 `MODEL`로 바꾸세요. `--policy.path`를 뒤에 붙이면 lerobot이 첫 값만 써서 적용되지 않습니다
- 그 밖의 옵션은 뒤에 붙이면 덮어씁니다 (`--robot.type`, `--dataset.*`도 마지막 값이 적용됨)
- 9)·10)은 실물 로봇에서 확인하지 않은 기능입니다

학습된 모델은 Hugging Face에도 있습니다: [Sungah/omx_1024_jihyeok_act](https://huggingface.co/Sungah/omx_1024_jihyeok_act), [Sungah/omx_box_act](https://huggingface.co/Sungah/omx_box_act)

**현장 체크리스트**: 카메라 위치·조명·물체를 녹화 때와 비슷하게 / 처음엔 `max_relative_target=10` 유지, 전원을 바로 끌 수 있게 준비 / 체크포인트마다 같은 배치에서 10회씩 실행해 성공률 비교

## (선택) 원본 데이터에서 상자→핑키 데이터셋 다시 만들기

```bash
hf download Yuzriha00/omx_1022_success --repo-type dataset --local-dir data/omx_1022_success
hf download Sungah/omx_v1 --repo-type dataset --local-dir data/omx_v1
./tools.sh 0 prepare_box_datasets.py all
```

`omx_v1` 에피소드 메타데이터 복구 → 작업 문장 통일 → 그리퍼 전류 버전 생성 → 두 데이터셋 병합 순으로 `data/box_*`를 만듭니다.
