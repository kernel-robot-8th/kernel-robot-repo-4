#!/usr/bin/env bash
# SmolVLA inference on the OMX robot with every lerobot-record option (lerobot 0.4.4) listed.
# Runs with the lerobot installed on this PC (activate its env first); no Docker.
# 필요: lerobot 0.4.4 (pip install "lerobot[dynamixel,smolvla]==0.4.4"), NVIDIA GPU
#
#   lerobot 0.4.4에는 lerobot-rollout이 없어서 lerobot-record --policy.path 로 정책을 실행합니다.
#   그래서 실행할 때마다 짧은 평가 데이터셋이 outputs/eval/ 아래에 녹화됩니다(Hub 업로드 안 함).
#   키보드: → 에피소드 일찍 끝내기 / ← 다시 녹화 / Esc 중지
#   lerobot 0.6.1로 학습한 모델(HF 번들 포함)은 config.json의 pretrained_revision 항목 때문에 0.4.4에서
#   읽히지 않습니다. 한 번 지우면 됩니다:
#     python -c "import json,sys;p=sys.argv[1]+'/config.json';c=json.load(open(p));c.pop('pretrained_revision',None);json.dump(c,open(p,'w'),indent=4)" <모델 폴더>
#
#   주석이 없는 줄  = 실기 실행 번들(Sungah/omx_box_smolvla)이 기본으로 넘기는 값을 0.4.4 옵션으로 옮긴 것
#                     (MODEL 기본값 = train.sh 기본 학습 결과)
#                     (단, --policy.device는 번들 기본 cpu 대신 cuda: CPU는 예측 1회 약 10초라 실시간 불가)
#   주석(#) 처리된 줄 = 넘기지 않은 옵션. 적힌 값은 lerobot 기본값(또는 사용 예)이고,
#                      주석을 풀면 그 값으로 바뀝니다.
#
# Usage: ./inference.sh [extra lerobot-record args...]
#   뒤에 붙인 인자는 아래 값을 덮어씁니다(--policy.path 제외: lerobot이 첫 값만 씀 → MODEL로 바꿀 것). 예: ./inference.sh --dataset.episode_time_s=60
#   먼저 아래 "현장 설정" 4줄을 이 PC에 맞게 고치세요 (find-port / find-cameras 결과).
#   환경변수로도 바꿀 수 있습니다. 예: MODEL=models/xxx ROBOT_PORT=/dev/ttyACM1 ./inference.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# ------------------------------------------------------------ 현장 설정
MODEL="${MODEL:-outputs/train/smolvla_box_merged_ho/checkpoints/last/pretrained_model}"   # 모델 폴더 (그리퍼 전류 모델이면 로봇 타입은 아래 auto가 맞춤)
ROBOT_PORT="${ROBOT_PORT:-/dev/ttyACM0}"   # lerobot-find-port 결과
TOP_CAM="${TOP_CAM:-/dev/video0}"   # 위쪽 카메라 (lerobot-find-cameras opencv 결과)
WRIST_CAM="${WRIST_CAM:-/dev/video2}"   # 손목 카메라

# 로봇 타입: auto = 모델 입력 state 크기로 결정 (6 → omx_follower, 7 → omx_follower_grip = 그리퍼 전류 모델)
ROBOT_TYPE="${ROBOT_TYPE:-auto}"
if [[ "$ROBOT_TYPE" == auto ]]; then
  sd="$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['input_features']['observation.state']['shape'][0])" "$MODEL/config.json" 2>/dev/null || echo 6)"
  ROBOT_TYPE=omx_follower; [[ "$sd" == 7 ]] && ROBOT_TYPE=omx_follower_grip
fi
echo "model: $MODEL | robot: $ROBOT_TYPE"

# 실행 기록 폴더 (lerobot-record는 이미 있는 폴더에 새로 녹화하지 못하므로 실행마다 새 이름)
EVAL_ROOT="${EVAL_ROOT:-outputs/eval/smolvla_$(date +%Y%m%d_%H%M%S)}"

ARGS=(
  # ============================================================ 정책 (--policy.*)
  --policy.path="$MODEL"                            # 실행할 모델 폴더
  --policy.device=cuda                              # cuda 권장 (cpu는 예측 1회 약 10초)
  # --policy.n_action_steps=50                      # 한 번 예측 후 실행할 스텝 수 (모델 기본 50)
  # --policy.num_steps=10                           # flow matching 생성 단계 수 (줄이면 빠르지만 품질 저하 가능)
  # --policy.use_amp=false                          # 혼합 정밀도 추론 (cuda일 때)

  # ============================================================ 로봇 (--robot.*)
  --robot.type="$ROBOT_TYPE"              # 위 ROBOT_TYPE (auto: 모델에 맞춰 omx_follower / omx_follower_grip)
  --robot.port="$ROBOT_PORT"                        # 시리얼 포트
  --robot.id=omx_follower                           # 캘리브레이션 파일 이름
  --robot.cameras="{camera1: {type: opencv, index_or_path: $TOP_CAM, width: 640, height: 480, fps: 30}, camera2: {type: opencv, index_or_path: $WRIST_CAM, width: 640, height: 480, fps: 30}}"  # 이름은 모델 입력과 같아야 함 (camera1 = 위쪽, camera2 = 손목)
  --robot.max_relative_target=10                    # 한 스텝 최대 이동량 (안전장치, 기본: 제한 없음). 관절 1 ≈ 1.8°
  # --robot.calibration_dir=~/.cache/huggingface/lerobot/calibration/robots/omx_follower  # 캘리브레이션 폴더 (기본: 자동)
  # --robot.disable_torque_on_disconnect=true       # 끝날 때 모터 힘 풀기
  # --robot.use_degrees=false                       # 관절 값을 각도로 (학습 데이터가 -100~100 단위라 false 유지)

  # ============================================================ 실행 제어 · 기록 (--dataset.*)
  # 0.6.1 lerobot-rollout과 대응: --fps → --dataset.fps, --task → --dataset.single_task,
  #   --duration → --dataset.episode_time_s (+ num_episodes=1), --rename_map → --dataset.rename_map
  --dataset.fps=30                                  # 제어 주기 (학습 데이터 fps와 같아야 함)
  --dataset.single_task="Pick up the box and place it on the white round robot."  # 작업 문장 (학습 때와 같아야 함)
  --dataset.episode_time_s=30                       # 실행 시간(초) (기본 60)
  --dataset.num_episodes=1                          # 실행 횟수 (기본 50)
  --dataset.repo_id=local/eval_omx_smolvla              # 기록 데이터셋 이름 (정책을 쓸 때는 eval_로 시작해야 함)
  --dataset.root="$EVAL_ROOT"                       # 기록 저장 위치 (기본: ~/.cache/huggingface/lerobot/<repo_id>)
  --dataset.push_to_hub=false                       # Hub 업로드 (기본 true)
  --play_sounds=false                               # 음성 안내 (기본 true)
  # --dataset.reset_time_s=60                       # 에피소드 사이 정리 시간(초) (마지막 에피소드 뒤에는 없음)
  # --dataset.rename_map='{"observation.images.top": "observation.images.camera1", "observation.images.wrist": "observation.images.camera2"}'  # 로봇 카메라 이름 → 모델 입력 이름 (위 카메라를 top/wrist로 부를 때)
  # --dataset.video=true                            # 이미지를 영상으로 저장
  # --dataset.private=false                         # Hub 비공개 업로드
  # --dataset.tags='["omx","eval"]'                 # (기본: 없음)
  # --dataset.num_image_writer_processes=0
  # --dataset.num_image_writer_threads_per_camera=4
  # --dataset.video_encoding_batch_size=1
  # --dataset.vcodec=libsvtav1                      # 영상 코덱 (h264 / hevc / libsvtav1 / auto)
  # --dataset.streaming_encoding=false              # 녹화하면서 바로 인코딩 (끝난 뒤 저장이 빨라짐)
  # --dataset.encoder_queue_maxsize=30
  # --dataset.encoder_threads=2                     # (기본: 없음)
  # --resume=false                                  # 기존 기록 데이터셋에 이어서 쓰기

  # ============================================================ 화면 표시
  # --display_data=false                            # 카메라·관절 실시간 표시 (rerun)
  # --display_ip=127.0.0.1                          # 원격 rerun 서버 주소 (기본: 없음)
  # --display_port=9876                             # 원격 rerun 포트 (기본: 없음)
  # --display_compressed_images=false               # 이미지를 압축해서 표시

  # ============================================================ 텔레오퍼레이션 장치 (--teleop.*, 에피소드 사이 리셋을 리더 팔로 할 때)
  # --teleop.type=omx_leader                        # 리더 팔
  # --teleop.port=/dev/ttyACM1
  # --teleop.id=omx_leader
  # --teleop.gripper_open_pos=60.0                  # 리더 그리퍼 열림 위치

  # ============================================================ 설정 파일
  # --config_path=record_config.yaml                # 위 옵션을 파일에서 불러오기

  # ------------------------------------------------------------ 0.6.1 lerobot-rollout에만 있고 0.4.4에는 없는 옵션
  #   --strategy.* (sentry/highlight/episodic/dagger), --inference.* (sync/rtc — SmolVLA RTC 포함), --duration,
  #   --return_to_initial_position, --interpolation_multiplier, --display_mode,
  #   --use_torch_compile 등, --dataset.rgb_encoder.* / depth_encoder.*
)

# SmolVLM2 config/tokenizer/weights for offline use (shipped in hf_hub/)
if [[ -d "$HERE/hf_hub" ]]; then
  hf="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
  mkdir -p "$hf" && cp -rn "$HERE"/hf_hub/. "$hf/"
fi

# omx_record.py = lerobot-record + omx_follower_grip robot type
python "${OMX_RECORD:-$HERE/omx_record.py}" "${ARGS[@]}" "$@"
