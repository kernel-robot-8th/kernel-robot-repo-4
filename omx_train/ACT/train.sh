#!/usr/bin/env bash
# ACT training with every lerobot-train option (lerobot 0.6.1) listed.
#
#   주석이 없는 줄  = act_omx_1024_test_jihyeok_success 학습에 실제로 넘긴 값
#   주석(#) 처리된 줄 = 넘기지 않은 옵션. 적힌 값은 lerobot 기본값(또는 사용 예)이고,
#                      주석을 풀면 그 값으로 바뀝니다.
#
# Usage: [DATASET=omx_1024_test_jihyeok_success] [JOB_NAME=act_<DATASET>] [EPISODES="[0,1,...]"] ./train.sh [GPU] [extra args...]
#   DATASET  : DATA_DIR(기본 ./data) 아래 데이터셋 폴더 이름
#   EPISODES : 학습에 쓸 에피소드 목록 (평가용 에피소드를 뺄 때). 비우면 전체
#   뒤에 붙인 인자는 아래 값을 덮어씁니다. 예: ./train.sh 0 --steps=6742
#
# 참고: 입력으로 쓸 값을 고르는 옵션(예: --state)은 없습니다. 모델 입력은 데이터셋의
#   observation.state / observation.images.* 로 자동으로 정해집니다. 그리퍼 전류 같은 값을
#   입력에 추가하려면 데이터셋의 observation.state를 늘린 사본을 만들어야 합니다
#   (prepare_box_datasets.py 의 grip 단계 참고).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GPU="${1:-0}"; shift || true
DATASET="${DATASET:-omx_1024_test_jihyeok_success}"
JOB_NAME="${JOB_NAME:-act_$DATASET}"
IMAGE="${IMAGE:-omx-act:0.6.1}"
DATA_DIR="$(realpath "${DATA_DIR:-$HERE/data}")"
OUT_DIR="${OUT_DIR:-$HERE/outputs}"
[[ -d "$DATA_DIR/$DATASET/meta" ]] || { echo "dataset not found: $DATA_DIR/$DATASET" >&2; exit 1; }

ARGS=(
  # ============================================================ 데이터셋 (--dataset.*)
  --dataset.repo_id="local/$DATASET"                # 데이터셋 이름 (root를 쓰면 표시용)
  --dataset.root="/data/$DATASET"                   # 로컬 데이터셋 경로 (컨테이너 안 /data = DATA_DIR)
  # --dataset.repo_type=dataset                     # Hub 저장소 종류
  # --dataset.episodes="[0,1,2,3,4,5,6,7]"          # 학습에 쓸 에피소드 (기본: 전체). 평가용 에피소드를 뺄 때 사용
  # --dataset.revision=main                         # Hub 데이터셋 버전(브랜치/태그) (기본: 없음)
  # --dataset.use_imagenet_stats=true               # 이미지 정규화에 ImageNet 평균·표준편차 사용
  # --dataset.video_backend=torchcodec              # 영상 디코더 (torchcodec / pyav)
  # --dataset.return_uint8=false                    # 이미지를 0~255 정수로 반환
  # --dataset.depth_output_unit=mm                  # 깊이 영상 단위 (깊이 카메라용)
  # --dataset.streaming=false                       # Hub에서 내려받지 않고 스트리밍
  # --dataset.eval_split=0.0                        # 검증용으로 떼어 둘 비율 (0 = 검증 loss 없음)

  # ------------------------------------------------ 이미지 증강 (--dataset.image_transforms.*)
  # --dataset.image_transforms.enable=false         # 학습 이미지 무작위 증강 (밝기·대비·채도·색조·선명도·이동)
  # --dataset.image_transforms.max_num_transforms=3 # 한 프레임에 적용할 최대 증강 개수
  # --dataset.image_transforms.random_order=false   # 증강 순서를 섞을지
  # --dataset.image_transforms.tfs='{"brightness": {"weight": 1.0, "type": "ColorJitter", "kwargs": {"brightness": [0.8, 1.2]}}}'  # 증강 종류·강도 직접 지정

  # ============================================================ 정책 공통 (--policy.*)
  --policy.type=act                                 # 정책 종류 (act, diffusion, smolvla, vqbet, pi0 ...)
  --policy.device=cuda                              # cuda / cpu
  --policy.push_to_hub=false                        # 학습 끝나고 Hub 업로드 (기본 true)
  # --policy.repo_id=Sungah/my_act                  # 업로드할 Hub 저장소 (push_to_hub=true일 때 필요)
  # --policy.private=true                           # 업로드 저장소 비공개 여부
  # --policy.tags='["omx","act"]'                   # 업로드 태그
  # --policy.license=apache-2.0                     # 업로드 라이선스
  # --policy.pretrained_path=outputs/train/<job>/checkpoints/last/pretrained_model  # 학습된 가중치에서 시작 (미세조정)
  # --policy.pretrained_revision=main               # pretrained_path가 Hub일 때 버전
  # --policy.use_amp=false                          # 혼합 정밀도 (빠르고 메모리 적게, 정확도 영향 가능)
  # --policy.use_peft=false                         # LoRA 등 PEFT 학습 (아래 --peft.* 와 함께)
  # --policy.n_obs_steps=1                          # 입력으로 볼 과거 프레임 수 (ACT는 1만 지원)
  # --policy.normalization_mapping='{"VISUAL": "MEAN_STD", "STATE": "MEAN_STD", "ACTION": "MEAN_STD"}'  # 정규화 방식
  # --policy.input_features / --policy.output_features   # 데이터셋에서 자동으로 채워짐 (직접 지정할 일 거의 없음)

  # ------------------------------------------------ ACT 구조
  # --policy.chunk_size=100                         # 한 번에 예측하는 동작 스텝 수
  # --policy.n_action_steps=100                     # 예측 중 실제 실행할 스텝 수 (실행 때 바꿀 수 있음)
  # --policy.vision_backbone=resnet18               # 이미지 인코더
  # --policy.pretrained_backbone_weights=ResNet18_Weights.IMAGENET1K_V1  # 인코더 초기 가중치 (비우면 무작위)
  # --policy.replace_final_stride_with_dilation=false  # 인코더 마지막 층 해상도 유지 (느려짐)
  # --policy.pre_norm=false                         # 트랜스포머 pre-LayerNorm
  # --policy.dim_model=512                          # 트랜스포머 차원
  # --policy.n_heads=8                              # 어텐션 헤드 수
  # --policy.dim_feedforward=3200                   # FFN 차원
  # --policy.feedforward_activation=relu            # FFN 활성화 함수
  # --policy.n_encoder_layers=4                     # 인코더 층 수
  # --policy.n_decoder_layers=1                     # 디코더 층 수
  # --policy.use_vae=true                           # VAE(동작 다양성) 사용
  # --policy.latent_dim=32                          # VAE 잠재 차원
  # --policy.n_vae_encoder_layers=4                 # VAE 인코더 층 수
  # --policy.kl_weight=10.0                         # VAE KL loss 가중치
  # --policy.dropout=0.1                            # 드롭아웃
  # --policy.temporal_ensemble_coeff=0.01           # temporal ensembling (실행용, n_action_steps=1 필요) (기본: 없음)

  # ------------------------------------------------ ACT 최적화 (use_policy_training_preset=true일 때 사용)
  # --policy.optimizer_lr=1e-05                     # 학습률
  # --policy.optimizer_lr_backbone=1e-05            # 이미지 인코더 학습률
  # --policy.optimizer_weight_decay=0.0001          # weight decay

  # ============================================================ 학습 루프
  --output_dir="/outputs/train/$JOB_NAME"           # 결과 폴더 (컨테이너 안 /outputs = OUT_DIR)
  --job_name="$JOB_NAME"                            # 실행 이름 (로그·wandb 표시용)
  --batch_size=16                                   # 배치 크기 (기본 8)
  --steps=13484                                     # 총 학습 step (기본 100000) — 20 epoch
  --save_freq=3371                                  # 체크포인트 저장 간격 (기본 20000) — 5 epoch
  --log_freq=200                                    # 로그 출력 간격
  --num_workers=8                                   # 데이터 로딩 프로세스 수 (기본 4)
  # --seed=1000                                     # 난수 시드
  # --cudnn_deterministic=false                     # 완전 재현 가능 모드 (느려짐)
  # --save_checkpoint=true                          # 체크포인트 저장 여부
  # --save_checkpoint_to_hub=false                  # 체크포인트마다 Hub 업로드
  # --use_policy_training_preset=true               # 정책 기본 옵티마이저·스케줄러 사용 (false면 아래 --optimizer.* 직접 지정)
  # --resume=false                                  # 이어서 학습 (true면 --config_path 필요)
  # --config_path=/outputs/train/<job>/checkpoints/last/pretrained_model/train_config.json  # 설정 파일에서 불러오기 / 이어서 학습할 체크포인트
  # --rename_map='{"observation.images.top": "observation.images.camera1"}'  # 데이터셋 키 이름 바꾸기
  # --tolerance_s=0.0001                            # 프레임 시간 정렬 허용 오차(초)

  # ------------------------------------------------ 데이터 로더
  # --prefetch_factor=4                             # 워커당 미리 읽을 배치 수
  # --persistent_workers=true                       # 에폭이 바뀌어도 워커 유지
  # --dataloader_multiprocessing_context=spawn      # 워커 생성 방식 (spawn / fork)

  # ------------------------------------------------ 옵티마이저·스케줄러 직접 지정 (use_policy_training_preset=false일 때)
  # --optimizer.type=adamw                          # adam / adamw / sgd ... (ACT 기본 = adamw, lr 1e-5, grad_clip 10)
  # --optimizer.lr=1e-05
  # --optimizer.weight_decay=0.0001
  # --optimizer.grad_clip_norm=10.0
  # --scheduler.type=cosine_decay_with_warmup       # ACT 기본 = 스케줄러 없음 (학습률 고정)

  # ============================================================ 학습 기록 (--wandb.*)
  --wandb.enable=false                              # Weights & Biases 기록
  # --wandb.project=lerobot                         # wandb 프로젝트
  # --wandb.entity=my_team                          # wandb 팀/계정 (기본: 없음)
  # --wandb.notes="memo"                            # 실행 메모
  # --wandb.run_id=abc123                           # 이어서 기록할 run id
  # --wandb.mode=offline                            # online / offline / disabled (기본: 없음)
  # --wandb.disable_artifact=false                  # 체크포인트를 wandb에 올리지 않음
  # --wandb.add_tags=true                           # 설정값을 태그로 추가

  # ============================================================ 시뮬레이션 평가 (실물 로봇 데이터에는 해당 없음)
  # --env.type=pusht                                # 시뮬레이션 환경 (aloha, pusht, libero, metaworld ...)
  # --env_eval_freq=20000                           # 시뮬레이션 평가 간격
  # --eval.n_episodes=50                            # 평가 에피소드 수
  # --eval.batch_size=44                            # 동시에 돌릴 환경 수
  # --eval.use_async_envs=true                      # 비동기 환경
  # --eval.recording=false                          # 평가 영상 녹화
  # --eval.recording_repo_id=Sungah/eval_videos     # 녹화 업로드 저장소
  # --eval.recording_private=false
  # --eval_steps=0                                  # 데이터셋 검증 loss 계산 간격 (eval_split > 0 필요)
  # --max_eval_samples=0                            # 검증에 쓸 최대 샘플 수 (0 = 전부)

  # ============================================================ PEFT/LoRA (--peft.*, use_peft=true일 때)
  # --peft.method_type=LORA                         # PEFT 방식
  # --peft.r=16                                     # LoRA rank
  # --peft.lora_alpha=32                            # LoRA alpha (기본: 없음)
  # --peft.target_modules='["q_proj","v_proj"]'     # LoRA를 적용할 모듈 (기본: 없음)
  # --peft.full_training_modules='["action_head"]'  # LoRA 대신 전부 학습할 모듈 (기본: 없음)
  # --peft.init_type=gaussian                       # LoRA 초기화 (기본: 없음)

  # ============================================================ Hugging Face Jobs (원격 GPU에서 학습)
  # --job.target=a10g-small                         # 원격 GPU 종류 (설정하면 이 PC가 아닌 HF Jobs에서 학습)
  # --job.image=huggingface/lerobot-gpu:latest
  # --job.timeout=2d
  # --job.detach=false
  # --job.tags='["omx"]'

  # ============================================================ 샘플 가중치 · 보상 모델 (고급)
  # --sample_weighting.type=...                     # 프레임별 학습 가중치 (진행도 기반 등)
  # --sample_weighting.progress_path=...
  # --sample_weighting.head_mode=...
  # --sample_weighting.kappa=...
  # --sample_weighting.epsilon=...
  # --sample_weighting.extra_params='{}'
  # --reward_model.type=reward_classifier           # 보상 모델 학습용 (정책 학습에는 사용 안 함)
)

[[ -n "${EPISODES:-}" ]] && ARGS+=(--dataset.episodes="$EPISODES")
mkdir -p "$HERE/.home" "$OUT_DIR/train"
OUT_DIR="$(realpath "$OUT_DIR")"

docker run --rm --name "omx-train-$JOB_NAME" \
  --gpus "\"device=$GPU\"" \
  --user "$(id -u):$(id -g)" \
  --shm-size 16g \
  -v "$HERE:/workspace" -v "$DATA_DIR:/data:ro" -v "$OUT_DIR:/outputs" \
  "$IMAGE" \
  lerobot-train "${ARGS[@]}" "$@"
