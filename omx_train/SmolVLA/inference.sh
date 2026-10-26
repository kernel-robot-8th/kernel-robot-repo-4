#!/usr/bin/env bash
# SmolVLA inference on the OMX robot with every lerobot-rollout option (lerobot 0.6.1) listed.
# Runs with the lerobot installed on this PC (activate its env first); no Docker.
# 필요: lerobot 0.6 이상 (pip install "lerobot[dynamixel]==0.6.1", SmolVLA는 lerobot[smolvla] 추가)
#
#   주석이 없는 줄  = 실기 실행 번들(Sungah/omx_box_smolvla)이 기본으로 넘기는 값
#                     (MODEL 기본값 = train.sh 기본 학습 결과)
#                     (단, --policy.device는 번들 기본 cpu 대신 cuda: CPU는 예측 1회 약 10초라 실시간 불가)
#   주석(#) 처리된 줄 = 넘기지 않은 옵션. 적힌 값은 lerobot 기본값(또는 사용 예)이고,
#                      주석을 풀면 그 값으로 바뀝니다.
#
# Usage: ./inference.sh [extra lerobot-rollout args...]
#   뒤에 붙인 인자는 아래 값을 덮어씁니다(--policy.path 제외: lerobot이 첫 값만 씀 → MODEL로 바꿀 것). 예: ./inference.sh --duration=60
#   필요: lerobot[smolvla] 설치, NVIDIA GPU
#   먼저 아래 "현장 설정" 4줄을 이 PC에 맞게 고치세요 (find-port / find-cameras 결과).
#   환경변수로도 바꿀 수 있습니다. 예: MODEL=models/xxx ROBOT_PORT=/dev/ttyACM1 ./inference.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# ------------------------------------------------------------ 현장 설정
MODEL="${MODEL:-outputs/train/smolvla_box_merged_ho/checkpoints/last/pretrained_model}"   # 모델 폴더 (그리퍼 전류 모델이면 --robot.type도 바꿀 것)
ROBOT_PORT="${ROBOT_PORT:-/dev/ttyACM0}"   # lerobot-find-port 결과
TOP_CAM="${TOP_CAM:-/dev/video0}"   # 위쪽 카메라 (lerobot-find-cameras opencv 결과)
WRIST_CAM="${WRIST_CAM:-/dev/video2}"   # 손목 카메라

ARGS=(
  # ============================================================ 실행 방식 (--strategy.*)
  --strategy.type=base                              # base: 실행만 / sentry: 계속 녹화·업로드 / highlight: 버튼으로 구간 저장 / episodic: 에피소드 단위 녹화 / dagger: 사람이 개입해 교정
  # --strategy.upload_every_n_episodes=5            # [sentry, dagger] 몇 에피소드마다 Hub 업로드
  # --strategy.target_video_file_size_mb=200        # [sentry, dagger] 영상 파일 목표 크기 (기본: 없음)
  # --strategy.ring_buffer_seconds=10.0             # [highlight] 최근 몇 초를 메모리에 보관
  # --strategy.ring_buffer_max_memory_mb=1024       # [highlight] 보관 메모리 한도
  # --strategy.save_key=s                           # [highlight] 저장 키
  # --strategy.push_key=h                           # [highlight] Hub 업로드 키
  # --strategy.reset_to_initial_position=true       # [episodic] 에피소드 사이에 시작 자세로 복귀
  # --strategy.smooth_leader_to_follower_handover=true  # [episodic] 리더→팔로워 전환을 부드럽게
  # --strategy.smooth_handover=true                 # [episodic, dagger] 사람↔정책 전환을 부드럽게
  # --strategy.num_episodes=20                      # [dagger] 교정 에피소드 수 (기본: 없음)
  # --strategy.record_autonomous=false              # [dagger] 정책이 혼자 움직인 구간도 녹화
  # --strategy.input_device=keyboard                # [dagger] keyboard / pedal
  # --strategy.keyboard.pause_resume=space          # [dagger] 일시정지·재개 키
  # --strategy.keyboard.correction=tab              # [dagger] 사람 교정 시작 키
  # --strategy.keyboard.upload=enter                # [dagger] 업로드 키
  # --strategy.pedal.device_path=/dev/input/by-id/usb-PCsensor_FootSwitch-event-kbd  # [dagger] 발판 장치
  # --strategy.pedal.pause_resume=KEY_A
  # --strategy.pedal.correction=KEY_B
  # --strategy.pedal.upload=KEY_C

  # ============================================================ 추론 엔진 (--inference.*)
  --inference.type=sync                             # sync: 묶음을 다 쓰면 다음 예측 / rtc: 실행 중에 다음 묶음을 미리 예측 (끊김 감소, SmolVLA 지원)
  # --inference.queue_threshold=30                  # [rtc] 남은 동작이 이 개수 아래면 다음 예측 시작
  # --inference.rtc.enabled=true                    # [rtc]
  # --inference.rtc.prefix_attention_schedule=LINEAR  # [rtc]
  # --inference.rtc.max_guidance_weight=10.0        # [rtc] 앞부분을 이전 동작에 맞추는 강도
  # --inference.rtc.execution_horizon=10            # [rtc] 이전 동작과 맞출 앞부분 길이
  # --inference.rtc.debug=false                     # [rtc]
  # --inference.rtc.debug_maxlen=100                # [rtc]

  # ============================================================ 정책 (--policy.*)
  --policy.path="$MODEL"                            # 실행할 모델 폴더
  --policy.device=cuda                              # cuda 권장 (cpu는 예측 1회 약 10초)
  # --policy.n_action_steps=50                      # 한 번 예측 후 실행할 스텝 수 (모델 기본 50)
  # --policy.num_steps=10                           # flow matching 생성 단계 수 (줄이면 빠르지만 품질 저하 가능)
  # --policy.rtc_config.execution_horizon=10        # RTC 설정은 --inference.rtc.* 로 지정
  # --device=cuda                                   # 정책 장치 (--policy.device와 같은 역할)
  # --rename_map='{"observation.images.top": "observation.images.camera1", "observation.images.wrist": "observation.images.camera2"}'  # 로봇 카메라 이름 → 모델 입력 이름 (아래 카메라를 top/wrist로 부를 때)

  # ============================================================ 로봇 (--robot.*)
  --robot.type=omx_follower                         # omx_follower / omx_follower_grip(그리퍼 전류 모델용, omx_grip_robot.py)
  --robot.port="$ROBOT_PORT"                        # 시리얼 포트
  --robot.id=omx_follower                           # 캘리브레이션 파일 이름
  --robot.cameras="{camera1: {type: opencv, index_or_path: $TOP_CAM, width: 640, height: 480, fps: 30}, camera2: {type: opencv, index_or_path: $WRIST_CAM, width: 640, height: 480, fps: 30}}"  # 이름은 모델 입력과 같아야 함 (camera1 = 위쪽, camera2 = 손목)
  --robot.max_relative_target=10                    # 한 스텝 최대 이동량 (안전장치, 기본: 제한 없음). 관절 1 ≈ 1.8°
  # --robot.calibration_dir=~/.cache/huggingface/lerobot/calibration/robots/omx_follower  # 캘리브레이션 폴더 (기본: 자동)
  # --robot.disable_torque_on_disconnect=true       # 끝날 때 모터 힘 풀기
  # --robot.use_degrees=false                       # 관절 값을 각도로 (학습 데이터가 -100~100 단위라 false 유지)

  # ============================================================ 실행 제어
  --fps=30                                          # 제어 주기 (학습 데이터 fps와 같아야 함)
  --task="Pick up the box and place it on the white round robot."  # 작업 문장 (학습 때와 같아야 함)
  --duration=30                                     # 실행 시간(초) (기본 0 = 무한)
  --play_sounds=false                               # 음성 안내 (기본 true)
  # --return_to_initial_position=true               # 끝나면 시작 자세로 천천히 복귀
  # --interpolation_multiplier=1                    # 동작 사이를 보간해 더 촘촘히 보냄 (2면 제어 주기 2배)
  # --resume=false                                  # 녹화 데이터셋 이어서 쓰기

  # ============================================================ 화면 표시
  # --display_data=false                            # 카메라·관절 실시간 표시
  # --display_mode=rerun                            # rerun / foxglove
  # --display_ip=127.0.0.1                          # 원격 표시 서버 주소 (기본: 없음)
  # --display_port=9876                             # 원격 표시 포트 (기본: 없음)
  # --display_compressed_images=false               # 이미지를 압축해서 표시

  # ============================================================ 속도 (torch.compile)
  # --use_torch_compile=false
  # --torch_compile_backend=inductor
  # --torch_compile_mode=default
  # --compile_warmup_inferences=2

  # ============================================================ 실행 녹화 (--dataset.*, sentry/highlight/episodic/dagger에서 사용)
  # --dataset.repo_id=Sungah/eval_omx_smolvla       # 녹화 데이터셋 이름
  # --dataset.single_task="Pick up the box and place it on the white round robot."
  # --dataset.root=outputs/rollout_recordings       # 로컬 저장 위치 (기본: 없음)
  # --dataset.fps=30
  # --dataset.episode_time_s=60                     # 에피소드 길이(초)
  # --dataset.reset_time_s=60                       # 에피소드 사이 정리 시간(초)
  # --dataset.num_episodes=50
  # --dataset.video=true                            # 이미지를 영상으로 저장
  # --dataset.push_to_hub=true                      # Hub 업로드
  # --dataset.private=true                          # (기본: 없음)
  # --dataset.tags='["omx","eval"]'                 # (기본: 없음)
  # --dataset.num_image_writer_processes=0
  # --dataset.num_image_writer_threads_per_camera=4
  # --dataset.video_encoding_batch_size=1
  # --dataset.streaming_encoding=false              # 녹화하면서 바로 인코딩
  # --dataset.encoder_queue_maxsize=30
  # --dataset.encoder_threads=2                     # (기본: 없음)
  # --dataset.no_stamp=false
  # --dataset.rgb_encoder.vcodec=libsvtav1          # 영상 코덱
  # --dataset.rgb_encoder.pix_fmt=yuv420p
  # --dataset.rgb_encoder.g=2                       # 키프레임 간격
  # --dataset.rgb_encoder.crf=30                    # 화질 (낮을수록 고화질)
  # --dataset.rgb_encoder.preset=8                  # (기본: 없음)
  # --dataset.rgb_encoder.fast_decode=0
  # --dataset.rgb_encoder.video_backend=pyav
  # --dataset.rgb_encoder.extra_options='{}'
  # --dataset.depth_encoder.vcodec=hevc             # 깊이 카메라용 (OMX에는 해당 없음)
  # --dataset.depth_encoder.pix_fmt=gray12le
  # --dataset.depth_encoder.g=2
  # --dataset.depth_encoder.crf=30
  # --dataset.depth_encoder.preset=8                # (기본: 없음)
  # --dataset.depth_encoder.fast_decode=0
  # --dataset.depth_encoder.video_backend=pyav
  # --dataset.depth_encoder.extra_options='{"x265-params": "lossless=1"}'
  # --dataset.depth_encoder.depth_min=0.01
  # --dataset.depth_encoder.depth_max=10.0
  # --dataset.depth_encoder.shift=3.5
  # --dataset.depth_encoder.use_log=true

  # ============================================================ 텔레오퍼레이션 장치 (--teleop.*, dagger 등에서 사람이 개입할 때)
  # --teleop.type=omx_leader                        # 리더 팔
  # --teleop.port=/dev/ttyACM1
  # --teleop.id=omx_leader

  # ============================================================ 설정 파일
  # --config_path=rollout_config.yaml               # 위 옵션을 파일에서 불러오기
)

# SmolVLM2 config/tokenizer/weights for offline use (shipped in hf_hub/)
if [[ -d "$HERE/hf_hub" ]]; then
  hf="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
  mkdir -p "$hf" && cp -rn "$HERE"/hf_hub/. "$hf/"
fi

# omx_rollout.py = lerobot-rollout + omx_follower_grip robot type
python "${OMX_ROLLOUT:-$HERE/omx_rollout.py}" "${ARGS[@]}" "$@"
