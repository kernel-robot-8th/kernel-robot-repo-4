# SmolVLA 학습 · 추론

LeRobot 0.6.1에서 [lerobot/smolvla_base](https://huggingface.co/lerobot/smolvla_base)를 Docker로 미세조정·평가하고, 설치된 lerobot으로 OMX 로봇에서 추론합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `Dockerfile` | 학습 이미지 (python 3.12, lerobot[training,smolvla] 0.6.1) |
| `train.sh` | 학습. **lerobot-train 옵션 전체**가 들어 있고, 주석 없는 줄 = 마지막 학습에 쓴 값 |
| `inference.sh` | 로봇 추론. **lerobot-rollout 옵션 전체**가 들어 있고, 주석 없는 줄 = 기본 실행 값 |
| `keep_checkpoints.sh` | 학습 중 필요한 체크포인트만 남기기 (`KEEP_STEPS`로 자동 실행) |
| `omx_rollout.py` | lerobot-rollout 실행기 (+ 그리퍼 전류 로봇 타입) |
| `omx_grip_robot.py` | `omx_follower_grip` 로봇 타입 (관절 6 + 그리퍼 전류) |
| `tools.sh` | 아래 Python 도구를 학습 이미지 안에서 실행 |
| `eval_policy.py` | 학습에서 뺀 에피소드로 평가 (녹화 영상 기반) |
| `prepare_box_datasets.py` | 원본 데이터셋 → 학습용 데이터셋 변환 (재현용) |

## 1. 학습

**준비물**: Linux + NVIDIA GPU (batch 64 기준 GPU 메모리 약 15GB), Docker + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), `hf` CLI (`pip install -U huggingface_hub`), 첫 학습 때 사전학습 모델을 받으므로 인터넷

```bash
cd omx_train/SmolVLA
docker build -t omx-smolvla:0.6.1 .              # 최초 1회
hf download Sungah/omx_box_merged --repo-type dataset --local-dir data/box_merged
./train.sh 0                                     # GPU 0
```

`train.sh`의 기본값 = 마지막으로 학습한 설정(`smolvla_box_merged_ho`)입니다.

| 항목 | 값 |
|---|---|
| 시작 모델 | `lerobot/smolvla_base` |
| 데이터셋 | `box_merged` (상자→핑키, 시연 72개, 30fps, 카메라 top/wrist) |
| 학습 에피소드 | 평가용 5, 15, 25, 35, 45, 55, 61, 67을 뺀 64개 |
| 카메라 이름 연결 | top → camera1, wrist → camera2 (`--rename_map`) |
| batch / step | 64 / 20,000 |
| 체크포인트 | 2,000 step마다 저장, `KEEP_STEPS=002000`으로 2k와 20k만 남김 |
| 시간 | A6000 1장 약 4시간 50분 |

**`train.sh` 사용 예시**

```bash
# 1) 기본: 마지막 학습 설정 그대로 (box_merged, 평가용 8개 제외, batch 64, 20k, 2k·20k만 보관)
./train.sh 0

# 2) 다른 GPU, 결과 이름 지정
JOB_NAME=smolvla_try2 ./train.sh 1

# 3) 72개 에피소드 전부로 학습, 체크포인트 전부 보관 (5k마다 저장, 1개 약 1.3GB)
EPISODES= KEEP_STEPS= JOB_NAME=smolvla_box_merged_all ./train.sh 0 --save_freq=5000

# 4) 그리퍼 전류 데이터셋 (observation.state 7개)
DATASET=box_merged_grip JOB_NAME=smolvla_grip ./train.sh 0

# 5) 다른 데이터셋 (카메라가 top/wrist인 데이터), 전체 에피소드, 10k step
hf download Sungah/omx_1024_test_jihyeok_success --repo-type dataset --local-dir data/omx_1024_test_jihyeok_success
DATASET=omx_1024_test_jihyeok_success EPISODES= JOB_NAME=smolvla_1024 ./train.sh 0 --steps=10000

# 6) 데이터셋 카메라 이름이 이미 camera1/camera2이면 이름 연결 끄기
DATASET=<데이터셋 폴더> EPISODES= ./train.sh 0 --rename_map='{}'

# 7) 배치를 줄여 GPU 메모리 절약 (GPU 메모리가 15GB보다 적을 때)
./train.sh 0 --batch_size=32

# 8) 중단된 학습 이어서 (같은 JOB_NAME)
./train.sh 0 --resume=true --config_path=/outputs/train/smolvla_box_merged_ho/checkpoints/last/pretrained_model/train_config.json

# 9) 데이터·결과를 다른 위치에
DATA_DIR=/mnt/ssd/lerobot_data OUT_DIR=/mnt/ssd/omx_outputs ./train.sh 0

# 10) 끊긴 학습 이어서 (처음과 같은 DATASET·JOB_NAME, 마지막 체크포인트부터)
RESUME=1 JOB_NAME=smolvla_try2 ./train.sh 0

# 11) 백그라운드로 실행 (터미널을 닫아도 계속, 대시보드 학습 탭도 이 방식)
DETACH=1 JOB_NAME=smolvla_try2 ./train.sh 0
docker logs -f omx-train-smolvla_try2    # 로그 보기
docker stop omx-train-smolvla_try2       # 중지
docker rm omx-train-smolvla_try2         # 끝난 컨테이너 정리
```

- 뒤에 붙인 옵션은 `train.sh` 안의 값을 덮어씁니다 (`--policy.path`만 예외: lerobot이 첫 값만 씀). `train.sh` 안의 주석(`#`) 줄을 풀어도 됩니다 (정책 값 = smolvla_base에서 실제로 적용된 값)
- 작업 문장은 데이터셋에 저장된 문장이 그대로 쓰입니다
- 컨테이너 안에서는 데이터가 `/data`(= `DATA_DIR`), 결과가 `/outputs`(= `OUT_DIR`)입니다

입력으로 쓸 값을 고르는 옵션(`--state` 같은)은 없습니다. 그리퍼 전류 등을 추가하려면 데이터셋 state를 늘린 사본이 필요합니다 (`prepare_box_datasets.py`의 grip 단계, SmolVLA는 state 최대 32개).

> 그리퍼 전류 데이터로 학습해도 저장된 `config.json`의 state 크기는 smolvla_base 값(6)으로 남습니다. 로봇 실행 전에 `input_features.observation.state.shape`를 `[7]`로 고쳐 주세요 (HF 번들은 이미 수정됨).

**결과**: `outputs/train/<JOB_NAME>/checkpoints/<step>/pretrained_model/`

## 2. 평가 (처음 보는 에피소드, 녹화 영상 기반)

```bash
M=/outputs/train/smolvla_box_merged_ho/checkpoints/020000/pretrained_model
./tools.sh 0 eval_policy.py --dataset_root /data/box_merged --episodes 5,15,25,35,45 --horizon 50 --model smolvla=$M --out /outputs/eval/smolvla_1022.json
./tools.sh 0 eval_policy.py --dataset_root /data/box_merged --episodes 55,61,67 --horizon 50 --model smolvla=$M --out /outputs/eval/smolvla_v1.json
```

지표: 관절 오차(몸통 관절 5개, lerobot 단위 1 ≈ 1.8°), 그리퍼 오차, 그리퍼 닫힘/열림 시점 차이(초), 부드러움. SmolVLA는 시드 3개(`--seeds`) 평균.

참고 결과 (20k, 실행 길이 50): 환경 1022 관절 1.99 / 그리퍼 0.74, 환경 v1 관절 1.65 / 그리퍼 1.26

## 3. 로봇에서 추론 (`inference.sh`)

로봇 PC에서 **Docker 없이**, 설치된 lerobot으로 실행합니다. **NVIDIA GPU가 필요합니다** (CPU는 예측 1회 약 10초).

```bash
pip install "lerobot[dynamixel,smolvla]==0.6.1"  # 로봇 PC에 lerobot이 없을 때
lerobot-find-port                                 # → ROBOT_PORT
lerobot-find-cameras opencv                       # → TOP_CAM(위쪽), WRIST_CAM(손목). 사진으로 구분
lerobot-calibrate --robot.type=omx_follower --robot.port=/dev/ttyACM0 --robot.id=omx_follower  # 최초 1회
MODEL=outputs/train/smolvla_box_merged_ho/checkpoints/020000/pretrained_model \
  ROBOT_PORT=/dev/ttyACM0 TOP_CAM=/dev/video0 WRIST_CAM=/dev/video2 ./inference.sh
```

`inference.sh`의 기본 실행 값:

| 항목 | 값 |
|---|---|
| 모델 (`MODEL`) | `outputs/train/smolvla_box_merged_ho/checkpoints/last/pretrained_model` |
| 카메라 | `camera1`(위쪽) / `camera2`(손목) 640×480 30fps (모델 입력 이름과 같아야 함) |
| 장치 | `cuda` |
| 작업 문장 | `Pick up the box and place it on the white round robot.` (학습 때와 같아야 함) |
| 실행 길이 | 모델 기본 50스텝 |
| 안전 | `--robot.max_relative_target=10` (한 스텝 최대 이동량) |
| 실행 시간 | 30초, 끝나면 시작 자세로 복귀 |

**`inference.sh` 사용 예시**

```bash
# 1) 기본: 스크립트의 "현장 설정"(MODEL, ROBOT_PORT, TOP_CAM, WRIST_CAM)을 고친 뒤
./inference.sh

# 2) 체크포인트·포트·카메라를 환경변수로 지정 (2k 체크포인트)
MODEL=outputs/train/smolvla_box_merged_ho/checkpoints/002000/pretrained_model \
  ROBOT_PORT=/dev/ttyACM1 TOP_CAM=/dev/video4 WRIST_CAM=/dev/video6 ./inference.sh

# 3) Hugging Face 번들의 모델 사용
hf download Sungah/omx_box_smolvla --local-dir omx_box_smolvla
MODEL=omx_box_smolvla/models/smolvla_merged ./inference.sh

# 4) RTC: 실행하는 동안 다음 동작을 미리 예측해 끊김을 줄임
./inference.sh --inference.type=rtc --inference.rtc.execution_horizon=10

# 5) 생성 단계를 줄여 예측을 빠르게 (품질이 떨어질 수 있음)
./inference.sh --policy.num_steps=5

# 6) 60초 동안, 안전 제한을 조금 풀어서 (동작이 너무 느릴 때)
./inference.sh --duration=60 --robot.max_relative_target=20

# 7) 그리퍼 전류로 학습한 모델 (config.json의 state 크기를 7로 고친 모델)
MODEL=outputs/train/smolvla_grip/checkpoints/last/pretrained_model ./inference.sh --robot.type=omx_follower_grip

# 8) 다른 작업 문장으로 학습한 모델 (학습 데이터와 같은 문장)
MODEL=outputs/train/smolvla_1024/checkpoints/last/pretrained_model \
  ./inference.sh --task="상자를 짚어서 흰 바구니 안에 넣는다."

# 9) 카메라·관절 값을 실시간 화면으로 보면서
./inference.sh --display_data=true

# 10) 실행하면서 에피소드 단위로 녹화 (5회, 회당 30초, 사이에 15초 정리 시간)
./inference.sh --strategy.type=episodic --duration=0 \
  --dataset.repo_id=Sungah/eval_omx_smolvla --dataset.single_task="Pick up the box and place it on the white round robot." \
  --dataset.root=outputs/rollout_recordings/eval_smolvla --dataset.num_episodes=5 \
  --dataset.episode_time_s=30 --dataset.reset_time_s=15 --dataset.push_to_hub=false
```

- 모델은 반드시 `MODEL`로 바꾸세요. `--policy.path`를 뒤에 붙이면 lerobot이 첫 값만 써서 적용되지 않습니다
- 그 밖의 옵션은 뒤에 붙이면 덮어씁니다 (`--robot.type`, `--strategy.type`, `--inference.type`도 마지막 값이 적용됨)
- 4)·9)·10)은 실물 로봇에서 확인하지 않은 기능입니다

학습된 모델은 Hugging Face에도 있습니다: [Sungah/omx_box_smolvla](https://huggingface.co/Sungah/omx_box_smolvla)

**현장 체크리스트**: 카메라 위치·조명·물체를 녹화 때와 비슷하게 / 처음엔 `max_relative_target=10` 유지, 전원을 바로 끌 수 있게 준비 / 체크포인트마다 같은 배치에서 10회씩 실행해 성공률 비교

## (선택) 원본 데이터에서 상자→핑키 데이터셋 다시 만들기

```bash
hf download Yuzriha00/omx_1022_success --repo-type dataset --local-dir data/omx_1022_success
hf download Sungah/omx_v1 --repo-type dataset --local-dir data/omx_v1
./tools.sh 0 prepare_box_datasets.py all
```

`omx_v1` 에피소드 메타데이터 복구 → 작업 문장 통일 → 그리퍼 전류 버전 생성 → 두 데이터셋 병합 순으로 `data/box_*`를 만듭니다.
