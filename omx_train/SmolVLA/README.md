# SmolVLA 학습

LeRobot 0.6.1에서 [lerobot/smolvla_base](https://huggingface.co/lerobot/smolvla_base)를 미세조정하고 평가합니다.

## 준비물

- Linux + NVIDIA GPU (batch 64 기준 GPU 메모리 약 15GB)
- Docker + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- `hf` CLI (`pip install -U huggingface_hub`) — 데이터셋 다운로드용
- 첫 학습 때 사전학습 모델(smolvla_base, SmolVLM2)을 내려받으므로 인터넷 필요

## 파일

| 파일 | 역할 |
|---|---|
| `Dockerfile` | 학습 이미지 (python 3.12, lerobot[training,smolvla] 0.6.1) |
| `train.sh` | 학습 실행 |
| `keep_checkpoints.sh` | 학습 중 필요한 체크포인트만 남기기 (`KEEP_STEPS`로 자동 실행) |
| `tools.sh` | 아래 Python 도구를 학습 이미지 안에서 실행 |
| `eval_policy.py` | 학습에서 뺀 에피소드로 평가 (녹화 영상 기반) |
| `prepare_box_datasets.py` | 원본 데이터셋 → 학습용 데이터셋 변환 (재현용, 보통은 필요 없음) |

## 1. 이미지 빌드 (최초 1회)

```bash
cd omx_train/SmolVLA
docker build -t omx-smolvla:0.6.1 .
```

## 2. 데이터셋 받기

```bash
hf download Sungah/omx_box_merged --repo-type dataset --local-dir data/box_merged
hf download Sungah/omx_box_merged_grip --repo-type dataset --local-dir data/box_merged_grip
```

- `box_merged`: state = 관절 6개
- `box_merged_grip`: state = 관절 6개 + 그리퍼 전류 1개
- 72개 에피소드 (0–50: 환경 1022, 51–71: 환경 v1), 30fps, 카메라 `top` / `wrist`
- 작업 문장: `Pick up the box and place it on the white round robot.`

다른 곳에 데이터가 있으면 `DATA_DIR=/경로`로 지정합니다.

## 3. 학습

```bash
./train.sh 0                                     # GPU 0, data/box_merged
DATASET=box_merged_grip ./train.sh 0             # 그리퍼 전류 데이터
```

**실험에서 쓴 방식**: 평가용 에피소드를 빼고, 2k와 20k 체크포인트만 남김

```bash
EPISODES=$(python3 -c "h={5,15,25,35,45,55,61,67}; print('['+','.join(str(i) for i in range(72) if i not in h)+']')")
EPISODES=$EPISODES KEEP_STEPS=002000 JOB_NAME=smolvla_box_merged_ho ./train.sh 0 --save_freq=2000
```

**설정**

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `DATASET` | `box_merged` | `DATA_DIR` 아래 데이터셋 폴더 이름 |
| `JOB_NAME` | `smolvla_<DATASET>` | 결과 폴더 이름 |
| `EPISODES` | 전체 | 학습에 쓸 에피소드 목록 (`[0,1,2,...]`) |
| `CAM_RENAME` | top→camera1, wrist→camera2 | 데이터셋 카메라 이름을 기본 모델 입력 이름(`camera1`/`camera2`)에 연결. 데이터셋이 이미 `camera1`/`camera2`면 `CAM_RENAME=` |
| `KEEP_STEPS` | 없음 (전부 보관) | 남길 중간 체크포인트 (마지막은 항상 보관). 체크포인트 1개 약 1.3GB |
| `DATA_DIR` / `OUT_DIR` | `./data` / `./outputs` | 데이터·결과 위치 |

lerobot 옵션은 뒤에 붙이면 기본값을 덮어씁니다.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--steps` | 20000 | 총 학습 step (A6000 1장 약 4시간 50분) |
| `--batch_size` | 64 | |
| `--save_freq` | 5000 | 체크포인트 저장 간격 |
| `--policy.chunk_size` | 50 | 한 번에 예측하는 스텝 수 |
| `--resume=true` | | 중단된 학습 이어서. 같은 `JOB_NAME`으로 `--resume=true --config_path=/outputs/train/<JOB_NAME>/checkpoints/last/pretrained_model/train_config.json` 추가 |

**결과**: `outputs/train/<JOB_NAME>/checkpoints/<step>/pretrained_model/`

> 그리퍼 전류 데이터로 학습해도 저장된 `config.json`의 state 크기는 기본 모델 값(6)으로 남습니다. 학습·추론에는 실제 크기(7)가 쓰이지만, 로봇 실행 전에는 `input_features.observation.state.shape`를 `[7]`로 고쳐 주세요 (HF 번들은 이미 수정됨).

## 4. 평가 (처음 보는 에피소드)

```bash
M=/outputs/train/smolvla_box_merged_ho/checkpoints/020000/pretrained_model
./tools.sh 0 eval_policy.py --dataset_root /data/box_merged --episodes 5,15,25,35,45 \
    --horizon 50 --model smolvla=$M --out /outputs/eval/smolvla_1022.json   # 환경 1022
./tools.sh 0 eval_policy.py --dataset_root /data/box_merged --episodes 55,61,67 \
    --horizon 50 --model smolvla=$M --out /outputs/eval/smolvla_v1.json     # 환경 v1
```

- 컨테이너 안에서는 데이터가 `/data`, 결과가 `/outputs`입니다.
- SmolVLA는 결과가 매번 조금씩 달라서 시드 3개(`--seeds`)로 평균을 냅니다.
- 지표: 관절 오차(몸통 관절 5개 평균, lerobot 단위 1 ≈ 1.8°), 그리퍼 오차, 그리퍼 닫힘/열림 시점 차이(초), 부드러움
- 녹화 영상 기반 평가라 실물 로봇 성공률과는 다를 수 있습니다.

**참고 결과** (`smolvla_box_merged_ho` 20k, 실행 길이 50)

| 데이터 | 환경 1022 관절 / 그리퍼 | 환경 v1 관절 / 그리퍼 |
|---|---|---|
| box_merged | 1.99 / 0.74 | 1.65 / 1.26 |
| box_merged_grip | 2.04 / 0.59 | 1.74 / 1.17 |

## 5. 로봇에서 실행

학습된 모델과 학원 PC용 실행 스크립트는 [Sungah/omx_box_smolvla](https://huggingface.co/Sungah/omx_box_smolvla) 번들을 쓰세요.
CPU에서는 예측 1회에 약 10초라 실시간 실행이 안 되므로 NVIDIA GPU가 필요합니다.

## (선택) 원본 데이터에서 다시 만들기

```bash
hf download Yuzriha00/omx_1022_success --repo-type dataset --local-dir data/omx_1022_success
hf download Sungah/omx_v1 --repo-type dataset --local-dir data/omx_v1
./tools.sh 0 prepare_box_datasets.py all
```

`omx_v1` 에피소드 메타데이터 복구 → 작업 문장 통일 → 그리퍼 전류 버전 생성 → 두 데이터셋 병합 순으로 `data/box_*`를 만듭니다.
