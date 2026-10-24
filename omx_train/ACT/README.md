# ACT 학습 · 추론

LeRobot 0.6.1의 ACT 정책을 Docker에서 학습·평가하고, 설치된 lerobot으로 OMX 로봇에서 추론합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `Dockerfile` | 학습 이미지 (python 3.12, lerobot[training] 0.6.1) |
| `train.sh` | 학습. **lerobot-train 옵션 전체**가 들어 있고, 주석 없는 줄 = 마지막 학습에 쓴 값 |
| `inference.sh` | 로봇 추론. **lerobot-rollout 옵션 전체**가 들어 있고, 주석 없는 줄 = 기본 실행 값 |
| `omx_rollout.py` | lerobot-rollout 실행기 (+ 그리퍼 전류 로봇 타입, k스텝 앙상블) |
| `omx_grip_robot.py` | `omx_follower_grip` 로봇 타입 (관절 6 + 그리퍼 전류) |
| `act_ensemble.py` | k스텝 temporal ensembling |
| `tools.sh` | 아래 Python 도구를 학습 이미지 안에서 실행 |
| `eval_policy.py` | 학습에서 뺀 에피소드로 평가 (녹화 영상 기반) |
| `prepare_box_datasets.py` | 원본 데이터셋 → 학습용 데이터셋 변환 (재현용) |

## 1. 학습

**준비물**: Linux + NVIDIA GPU (batch 16 기준 GPU 메모리 약 7GB), Docker + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html), `hf` CLI (`pip install -U huggingface_hub`)

```bash
cd omx_train/ACT
docker build -t omx-act:0.6.1 .                  # 최초 1회
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

**바꾸는 방법**

- 다른 데이터셋: `DATASET=box_merged ./train.sh 0` (`data/box_merged` 필요)
- 평가용 에피소드 빼기: `EPISODES="[0,1,2,3,4,6,7,8]" ./train.sh 0`
- 옵션 덮어쓰기: 뒤에 붙이면 됩니다. 예: `./train.sh 0 --batch_size=8 --steps=100000 --save_freq=20000`
- `train.sh` 안의 주석(`#`) 줄을 풀면 그 옵션이 적용됩니다 (적힌 값 = lerobot 기본값 또는 예시)
- 데이터·결과 위치: `DATA_DIR`(기본 `./data`), `OUT_DIR`(기본 `./outputs`). 컨테이너 안에서는 `/data`, `/outputs`
- 이어서 학습: 같은 `JOB_NAME`으로 `--resume=true --config_path=/outputs/train/<JOB_NAME>/checkpoints/last/pretrained_model/train_config.json`

입력으로 쓸 값을 고르는 옵션(`--state` 같은)은 없습니다. 모델 입력은 데이터셋의 `observation.state`와 카메라 영상으로 정해지므로, 그리퍼 전류 등을 추가하려면 데이터셋 state를 늘린 사본이 필요합니다 (`prepare_box_datasets.py`의 grip 단계).

**결과**: `outputs/train/<JOB_NAME>/checkpoints/<step>/pretrained_model/`

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
pip install "lerobot[dynamixel]==0.6.1"          # 로봇 PC에 lerobot이 없을 때
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
| 실행 시간 | 30초, 끝나면 시작 자세로 복귀 |

- 모델·포트·카메라는 환경변수(`MODEL`, `ROBOT_PORT`, `TOP_CAM`, `WRIST_CAM`)나 스크립트 위쪽 "현장 설정"에서 바꿉니다. `--policy.path`를 뒤에 붙이면 lerobot이 첫 값만 써서 적용되지 않습니다.
- 그 밖의 옵션은 뒤에 붙이거나 주석을 풉니다. 예: `./inference.sh --duration=60`
- k스텝 temporal ensembling: `ACT_ENSEMBLE_K=5 ./inference.sh --policy.n_action_steps=100` (k스텝마다 예측해 겹치는 예측을 평균, 부드럽지만 반응이 느림)
- 그리퍼 전류로 학습한 모델: `./inference.sh --robot.type=omx_follower_grip`

학습된 모델은 Hugging Face에도 있습니다: [Sungah/omx_1024_jihyeok_act](https://huggingface.co/Sungah/omx_1024_jihyeok_act), [Sungah/omx_box_act](https://huggingface.co/Sungah/omx_box_act)

**현장 체크리스트**: 카메라 위치·조명·물체를 녹화 때와 비슷하게 / 처음엔 `max_relative_target=10` 유지, 전원을 바로 끌 수 있게 준비 / 체크포인트마다 같은 배치에서 10회씩 실행해 성공률 비교

## (선택) 원본 데이터에서 상자→핑키 데이터셋 다시 만들기

```bash
hf download Yuzriha00/omx_1022_success --repo-type dataset --local-dir data/omx_1022_success
hf download Sungah/omx_v1 --repo-type dataset --local-dir data/omx_v1
./tools.sh 0 prepare_box_datasets.py all
```

`omx_v1` 에피소드 메타데이터 복구 → 작업 문장 통일 → 그리퍼 전류 버전 생성 → 두 데이터셋 병합 순으로 `data/box_*`를 만듭니다.
