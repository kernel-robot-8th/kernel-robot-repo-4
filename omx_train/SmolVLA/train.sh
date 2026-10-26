#!/usr/bin/env bash
# SmolVLA fine-tuning with every lerobot-train option (lerobot 0.4.4) listed.
#
#   주석이 없는 줄  = smolvla_box_merged_ho 학습(상자→핑키, 합친 데이터, 평가용 에피소드 제외)에
#                     실제로 넘긴 값
#   주석(#) 처리된 줄 = 넘기지 않은 옵션. --policy.path로 smolvla_base에서 시작하므로, 정책 값은
#                     smolvla_base 설정에서 실제로 적용된 값을 적었습니다(lerobot 클래스 기본값과
#                     다를 수 있음). 주석을 풀면 그 값으로 바뀝니다.
#   0.6.1에만 있는 옵션(eval_split, prefetch_factor, job.* 등)은 0.4.4에서 오류가 나므로 뺐습니다.
#
# Usage: [DATASET=box_merged] [JOB_NAME=smolvla_<DATASET>_ho] [EPISODES="[...]"] [KEEP_STEPS=002000] ./train.sh [GPU] [extra args...]
#   DATASET  : DATA_DIR(기본 ./data) 아래 데이터셋 폴더 이름
#   EPISODES : 학습에 쓸 에피소드 목록. 기본은 box_merged에서 평가용 8개를 뺀 목록, EPISODES= 로 비우면 전체
#   뒤에 붙인 인자는 아래 값을 덮어씁니다(--policy.path 제외: lerobot이 첫 값만 씀). 예: ./train.sh 0 --steps=10000
#   KEEP_STEPS: 남길 중간 체크포인트 (마지막은 항상 보관). 비우면(KEEP_STEPS=) 전부 보관
#
# 참고: 입력으로 쓸 값을 고르는 옵션(예: --state)은 없습니다. 모델 입력은 데이터셋의
#   observation.state / observation.images.* 로 자동으로 정해집니다. 그리퍼 전류 같은 값을
#   입력에 추가하려면 데이터셋의 observation.state를 늘린 사본을 만들어야 합니다
#   (prepare_box_datasets.py 의 grip 단계 참고, SmolVLA는 state 최대 32개).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GPU="${1:-0}"; shift || true
DATASET="${DATASET:-box_merged}"
JOB_NAME="${JOB_NAME:-smolvla_${DATASET}_ho}"
IMAGE="${IMAGE:-omx-smolvla:0.4.4}"
DATA_DIR="$(realpath "${DATA_DIR:-$HERE/data}")"
OUT_DIR="${OUT_DIR:-$HERE/outputs}"
[[ -d "$DATA_DIR/$DATASET/meta" ]] || { echo "dataset not found: $DATA_DIR/$DATASET" >&2; exit 1; }
KEEP_STEPS="${KEEP_STEPS-002000}"
# 학습에 쓸 에피소드: box_merged 72개 중 평가용 5,15,25,35,45,55,61,67 제외
EPISODES="${EPISODES-[0,1,2,3,4,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,23,24,26,27,28,29,30,31,32,33,34,36,37,38,39,40,41,42,43,44,46,47,48,49,50,51,52,53,54,56,57,58,59,60,62,63,64,65,66,68,69,70,71]}"

ARGS=(
  # ============================================================ 시작 모델
  --policy.path=lerobot/smolvla_base                # 사전학습 모델에서 미세조정 (처음부터면 --policy.type=smolvla)
  # --policy.pretrained_path=lerobot/smolvla_base   # --policy.path가 자동으로 채우는 값 (직접 쓸 일 없음)

  # ============================================================ 데이터셋 (--dataset.*)
  --dataset.repo_id="Sungah/$DATASET"               # 데이터셋 이름 (root를 쓰면 표시용)
  --dataset.root="/data/$DATASET"                   # 로컬 데이터셋 경로 (컨테이너 안 /data = DATA_DIR)
  --rename_map='{"observation.images.top": "observation.images.camera1", "observation.images.wrist": "observation.images.camera2"}'  # 데이터셋 카메라 이름 → smolvla_base 입력 이름
  # --dataset.revision=main                         # Hub 데이터셋 버전 (기본: 없음)
  # --dataset.use_imagenet_stats=true               # ImageNet 통계 (SmolVLA는 이미지 정규화를 IDENTITY로 써서 영향 없음)
  # --dataset.video_backend=torchcodec              # 영상 디코더 (torchcodec / pyav)
  # --dataset.streaming=false                       # Hub에서 내려받지 않고 스트리밍

  # ------------------------------------------------ 이미지 증강 (--dataset.image_transforms.*)
  # --dataset.image_transforms.enable=false         # 학습 이미지 무작위 증강 (밝기·대비·채도·색조·선명도·이동)
  # --dataset.image_transforms.max_num_transforms=3 # 한 프레임에 적용할 최대 증강 개수
  # --dataset.image_transforms.random_order=false   # 증강 순서를 섞을지
  # --dataset.image_transforms.tfs='{"brightness": {"weight": 1.0, "type": "ColorJitter", "kwargs": {"brightness": [0.8, 1.2]}}}'  # 증강 종류·강도 직접 지정

  # ============================================================ 정책 공통 (--policy.*)
  --policy.device=cuda                              # cuda / cpu
  --policy.push_to_hub=false                        # 학습 끝나고 Hub 업로드 (기본 true)
  # --policy.repo_id=Sungah/my_smolvla              # 업로드할 Hub 저장소 (push_to_hub=true일 때 필요)
  # --policy.private=true                           # 업로드 저장소 비공개 여부
  # --policy.tags='["omx","smolvla"]'               # 업로드 태그
  # --policy.license=apache-2.0                     # 업로드 라이선스
  # --policy.use_amp=false                          # 혼합 정밀도 (빠르고 메모리 적게, 정확도 영향 가능)
  # --policy.use_peft=false                         # LoRA 등 PEFT 학습 (아래 --peft.* 와 함께)
  # --policy.n_obs_steps=1                          # 입력으로 볼 과거 프레임 수
  # --policy.normalization_mapping='{"VISUAL": "IDENTITY", "STATE": "MEAN_STD", "ACTION": "MEAN_STD"}'  # 정규화 방식
  # --policy.input_features / --policy.output_features   # smolvla_base 설정 + 데이터셋에서 채워짐 (직접 지정할 일 거의 없음)

  # ------------------------------------------------ 동작 예측
  # --policy.chunk_size=50                          # 한 번에 예측하는 동작 스텝 수
  # --policy.n_action_steps=50                      # 예측 중 실제 실행할 스텝 수 (실행 때 바꿀 수 있음)
  # --policy.num_steps=10                           # flow matching 생성 단계 수 (줄이면 빠르지만 품질 저하 가능)
  # --policy.max_state_dim=32                       # 받을 수 있는 최대 state 크기 (작으면 0으로 채움)
  # --policy.max_action_dim=32                      # 최대 action 크기
  # --policy.min_period=0.004                       # 시간 임베딩 최소 주기
  # --policy.max_period=4.0                         # 시간 임베딩 최대 주기

  # ------------------------------------------------ 입력 처리
  # --policy.resize_imgs_with_padding='[512, 512]'  # 이미지를 비율 유지 + 패딩으로 이 크기로
  # --policy.empty_cameras=0                        # 빈 카메라 입력 개수 (카메라가 모자랄 때 채움)
  # --policy.tokenizer_max_length=48                # 작업 문장 최대 토큰 수
  # --policy.pad_language_to=max_length             # 문장 패딩 방식 (longest / max_length)
  # --policy.add_image_special_tokens=false         # 이미지 앞뒤 특수 토큰 추가
  # --policy.adapt_to_pi_aloha=false                # ALOHA 로봇 관절 변환 (OMX에는 해당 없음)
  # --policy.use_delta_joint_actions_aloha=false    # ALOHA 상대 관절 동작 (OMX에는 해당 없음)

  # ------------------------------------------------ 모델 구조 (smolvla_base와 다르게 바꾸면 사전학습 효과가 줄어듦)
  # --policy.vlm_model_name=HuggingFaceTB/SmolVLM2-500M-Video-Instruct  # 언어·비전 백본
  # --policy.load_vlm_weights=true                  # VLM 사전학습 가중치 불러오기
  # --policy.num_vlm_layers=16                      # 사용할 VLM 층 수
  # --policy.num_expert_layers=0                    # 동작 전문가 층 수 (0 = VLM 층 수와 같게)
  # --policy.expert_width_multiplier=0.75           # 동작 전문가 폭 (VLM 대비)
  # --policy.attention_mode=cross_attn              # VLM-전문가 연결 방식
  # --policy.self_attn_every_n_layers=2             # n층마다 self-attention
  # --policy.prefix_length=0                        # 접두 토큰 길이
  # --policy.use_cache=true                         # 추론 시 KV 캐시

  # ------------------------------------------------ 학습 범위
  # --policy.freeze_vision_encoder=true             # 이미지 인코더 고정
  # --policy.train_expert_only=true                 # 동작 전문가만 학습 (VLM 고정)
  # --policy.train_state_proj=true                  # 관절 값 입력층 학습

  # ------------------------------------------------ 최적화 (use_policy_training_preset=true일 때 사용)
  # --policy.optimizer_lr=0.0001                    # 최대 학습률
  # --policy.optimizer_betas='[0.9, 0.95]'          # AdamW betas
  # --policy.optimizer_eps=1e-08                    # AdamW eps
  # --policy.optimizer_weight_decay=1e-10           # weight decay
  # --policy.optimizer_grad_clip_norm=10.0          # 기울기 자르기
  # --policy.scheduler_warmup_steps=1000            # 학습률 워밍업 step (총 step이 decay보다 작으면 비율대로 줄어듦)
  # --policy.scheduler_decay_steps=30000            # 학습률 감소 구간 (총 step에 맞춰 자동 축소)
  # --policy.scheduler_decay_lr=2.5e-06             # 최종 학습률

  # ------------------------------------------------ 속도
  # --policy.compile_model=false                    # torch.compile 사용
  # --policy.compile_mode=max-autotune              # torch.compile 모드

  # ------------------------------------------------ RTC (Real-Time Chunking, 실행 단계 설정 — 0.4.4 lerobot-record에서는 사용 안 함)
  # --policy.rtc_config.enabled=true
  # --policy.rtc_config.prefix_attention_schedule=LINEAR
  # --policy.rtc_config.max_guidance_weight=10.0
  # --policy.rtc_config.execution_horizon=10
  # --policy.rtc_config.debug=false
  # --policy.rtc_config.debug_maxlen=100

  # ============================================================ 학습 루프
  --output_dir="/outputs/train/$JOB_NAME"           # 결과 폴더 (컨테이너 안 /outputs = OUT_DIR)
  --job_name="$JOB_NAME"                            # 실행 이름 (로그·wandb 표시용)
  --batch_size=64                                   # 배치 크기 (lerobot 기본 8)
  --steps=20000                                     # 총 학습 step (lerobot 기본 100000)
  --save_freq=2000                                  # 체크포인트 저장 간격 (lerobot 기본 20000)
  --log_freq=100                                    # 로그 출력 간격 (기본 200)
  --num_workers=8                                   # 데이터 로딩 프로세스 수 (기본 4)
  # --seed=1000                                     # 난수 시드
  # --save_checkpoint=true                          # 체크포인트 저장 여부
  # --use_policy_training_preset=true               # 정책 기본 옵티마이저·스케줄러 사용 (false면 아래 --optimizer.* 직접 지정)
  # --resume=false                                  # 이어서 학습 (true면 --config_path 필요)
  # --config_path=/outputs/train/<job>/checkpoints/last/pretrained_model/train_config.json  # 이어서 학습할 체크포인트 (로컬 경로만)
  # --tolerance_s=0.0001                            # 프레임 시간 정렬 허용 오차(초)

  # ------------------------------------------------ 옵티마이저·스케줄러 직접 지정 (use_policy_training_preset=false일 때)
  # --optimizer.type=adamw                          # SmolVLA 기본 = adamw (lr 1e-4, betas 0.9/0.95, wd 1e-10, grad_clip 10)
  # --optimizer.lr=0.0001
  # --optimizer.weight_decay=1e-10
  # --optimizer.grad_clip_norm=10.0
  # --scheduler.type=cosine_decay_with_warmup       # SmolVLA 기본 (워밍업 1000, 감소 30000, 최종 2.5e-6)

  # ============================================================ 학습 기록 (--wandb.*)
  --wandb.enable=false                              # Weights & Biases 기록
  # --wandb.project=lerobot                         # wandb 프로젝트
  # --wandb.entity=my_team                          # wandb 팀/계정 (기본: 없음)
  # --wandb.notes="memo"                            # 실행 메모
  # --wandb.run_id=abc123                           # 이어서 기록할 run id
  # --wandb.mode=offline                            # online / offline / disabled (기본: 없음)
  # --wandb.disable_artifact=false                  # 체크포인트를 wandb에 올리지 않음

  # ============================================================ 시뮬레이션 평가 (실물 로봇 데이터에는 해당 없음)
  # --env.type=libero                               # 시뮬레이션 환경 (aloha, pusht, libero, metaworld ...)
  # --eval_freq=20000                               # 시뮬레이션 평가 간격 (0.6.1의 env_eval_freq)
  # --eval.n_episodes=50                            # 평가 에피소드 수
  # --eval.batch_size=50                            # 동시에 돌릴 환경 수
  # --eval.use_async_envs=false                     # 비동기 환경

  # ============================================================ PEFT/LoRA (--peft.*, use_peft=true일 때)
  # --peft.method_type=LORA                         # PEFT 방식
  # --peft.r=16                                     # LoRA rank
  # --peft.target_modules='["q_proj","v_proj"]'     # LoRA를 적용할 모듈 (기본: 없음)
  # --peft.full_training_modules='["action_out_proj"]'  # LoRA 대신 전부 학습할 모듈 (기본: 없음)
  # --peft.init_type=gaussian                       # LoRA 초기화 (기본: 없음)

  # ============================================================ RA-BC 보상 가중 학습 (고급, 0.6.1의 --sample_weighting.*)
  # --use_rabc=false                                # 진행도(SARM) 기반 프레임별 학습 가중치
  # --rabc_progress_path=/data/<dataset>/sarm_progress.parquet  # 진행도 파일 (기본: 데이터셋 폴더에서 자동)
  # --rabc_kappa=0.01                               # 고품질 샘플 기준값
  # --rabc_epsilon=1e-06                            # 수치 안정용 작은 값
  # --rabc_head_mode=sparse                         # sparse / dense
)

[[ -n "$EPISODES" ]] && ARGS+=(--dataset.episodes="$EPISODES")  # 학습에 쓸 에피소드 (평가용 제외)
mkdir -p "$HERE/.home" "$OUT_DIR/train"
OUT_DIR="$(realpath "$OUT_DIR")"

docker run --rm --name "omx-train-$JOB_NAME" \
  --gpus "\"device=$GPU\"" \
  --user "$(id -u):$(id -g)" \
  --shm-size 16g \
  -v "$HERE:/workspace" -v "$DATA_DIR:/data:ro" -v "$OUT_DIR:/outputs" \
  "$IMAGE" \
  lerobot-train "${ARGS[@]}" "$@" &
pid=$!

if [[ -n "$KEEP_STEPS" ]]; then
  sleep 60  # let the container start before watching it
  # shellcheck disable=SC2086
  "$HERE/keep_checkpoints.sh" "$OUT_DIR/train/$JOB_NAME/checkpoints" "omx-train-$JOB_NAME" $KEEP_STEPS &
fi
wait $pid
