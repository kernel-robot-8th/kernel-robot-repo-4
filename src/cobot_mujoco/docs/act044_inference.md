# 오늘 학습한 LeRobot 0.4.4 모델 실행 안내

매 스텝 추론과 겹치는 행동 평균 설정은 [Temporal Ensembling 안내](act044_temporal_ensemble.md)를 참고한다.

## 추론 전 Init 자세 이동

실행기는 이제 기본적으로 대시보드에 저장된 Init 자세로 약 3초간 이동한 뒤 추론을 시작한다.
`scripts/manipulation/act044_init_pose.json`은 설정 당시
`/home/team11/omx-record-dashboard/omx_recoder/init_pose.yaml`의 `init` 복사본이다.
팔 관절 정규화 위치는 순서대로 `1.148, -29.621, 39.683, 44.127, 1.441`, 그리퍼는 `59.243`이다.
이 값은 현재 저장된 대시보드 자세이며 모든 학습 에피소드의 시작 자세가 동일하다는 뜻은 아니다.

연결 후 Init으로 이동하고 도달을 확인한 뒤 원본 LeRobot 0.4.4 추론 루프를 시작한다.
Init 이동 중에는 관절당 현재 위치 대비 명령 변화량을 3 이내로 제한한다.
설정 시간 후 목표 오차가 모두 3 이내인지 확인하며, 추가 3초 동안에도 도달하지 못하면
추론을 시작하지 않고 연결을 해제한다. 연결 해제 시 토크가 해제된다.
`--no-relative-target`은 추론 중 제한을 해제하는 옵션이며 Init 이동의 제한은 유지한다.

```bash
# 실제 구동: Init 이동 후 일반형 1번 추론, 앙상블 켬, 추론 중 목표 변화량 제한 해제
./run_act044.sh run 1 --step 20000 --action-steps 1 --temporal-ensemble \
  --no-relative-target --duration 50

# 명령만 확인: Init 이동도 실행하지 않음
./run_act044.sh run 1 --step 20000 --action-steps 1 --temporal-ensemble --dry-run

# 해당 실행에서 Init 이동 생략
./run_act044.sh run 1 --no-init-pose
```

설정 파일의 `ACT044_INIT_POSE=true`, `ACT044_INIT_POSE_DURATION=3`이 기본값이다.
다른 자세 파일은 `--init-pose-file /절대경로/pose.json`으로 선택한다.
`list`, `checkpoints`, `check`, `--dry-run`에서는 로봇 초기화 이동을 하지 않는다.
원본 LeRobot 설치 파일은 수정하지 않고 `act044_record.py`에서 연결 직후의 Init 이동만 추가한다.
HTML의 `.env` 없는 한 줄 명령도 같은 Init 보조 진입점으로 변경했다.
Init 기능을 추가하는 과정에서는 실제 로봇을 구동하지 않았으며 가짜 모터로 도달·실패를 검사했다.

## 파일 위치

- 실행기: `/home/team11/il_ws/run_act044.sh`
- 오늘 추론·장치 설정: `/home/team11/il_ws/act044_inference.env`
- 이 안내: `/home/team11/il_ws/ACT044_INFERENCE.md`
- 모델 저장 루트: `/home/team11/omx_sim_runs/retraining_044_20261026/jobs`

실행기·설정·안내는 Git 저장소의 원본으로 연결된다. 옛 번들의
`il_ws/outputs/hub/omx_1024_jihyeok_act/config.env`는 이번에 생성·수정하지 않았으며,
최종 실행기는 그 파일을 읽지 않는다. 장치 경로의 초깃값만 기존 로컬 설정에서 복사했다.
모델은 오늘의 0.4.4 실행 폴더와 버전 정보를 확인하며 어제의 0.6.1 실행 폴더는 거부한다.

## 실제 입력할 명령

```bash
cd ~/il_ws

# 번호·설정·현재 저장 현황 보기: 로봇 연결 없음
./run_act044.sh list

# 1번의 저장 step 목록 보기
./run_act044.sh checkpoints 1

# CPU에서 모델·전처리 로딩만 확인: 로봇·카메라 연결 없음
./run_act044.sh check 1

# 실행 명령만 확인: 로봇·카메라 연결 없음
./run_act044.sh run 1 --step 20000 --dry-run

# 여기부터 실제 로봇 구동: 기본 10초 점검
./run_act044.sh run 1 --step 20000

# 같은 모델로 50초 실행
./run_act044.sh run 1 --step 20000 --duration 50

# 경량형 chunk16, 50초 실행
./run_act044.sh run 7 --step 20000 --duration 50

# 일반형/경량형 중 현재 검증 점수가 가장 좋은 후보 자동 선택
./run_act044.sh run standard --duration 50
./run_act044.sh run light --duration 50
```

`--step`을 생략하면 해당 실험에서 현재 검증 MAE가 가장 낮은 체크포인트를 선택한다.
아직 검증 전이면 최신 완전 저장본을 선택하고 그 사실을 표시한다. `--latest`는 최신 저장본을
명시적으로 선택한다. 전체 학습·검증이 끝나기 전의 후보는 최종 추천이 아닐 수 있다.
학습 중인 모델도 저장 완료된 체크포인트는 실행할 수 있다. 아직 저장본이 없는 번호는 오류로
알려주며 다른 모델로 바꿔 실행하지 않는다.

## 숫자 번호와 학습 설정의 대응

숫자는 실험 식별자이며 `.sh list`에서 언제든 확인할 수 있다. 학습이 진행돼도 번호는 바뀌지 않는다.
아래 step은 계획 상한이며 실제 저장·검증 선택 step은 목록과 보고서에서 확인한다.

| 번호 | ACT 구조 | 학습 chunk | 주 학습률 | Weight decay | 계획 최대 step |
|---|---|---:|---:|---:|---:|
| 1 | 일반형 | 16 | 0.00001 | 0.0001 | 20,000 |
| 2 | 일반형 | 32 | 0.00001 | 0.0001 | 20,000 |
| 3 | 일반형 | 64 | 0.00001 | 0.0001 | 20,000 |
| 4 | 일반형 | 100 | 0.00001 | 0.0001 | 20,000 |
| 5 | 일반형 | 32 | 0.00003 | 0.0001 | 10,000 |
| 6 | 일반형 | 32 | 0.00001 | 0.001 | 10,000 |
| 7 | 경량형 | 16 | 0.00001 | 0.0001 | 20,000 |
| 8 | 경량형 | 32 | 0.00001 | 0.0001 | 20,000 |
| 9 | 경량형 | 64 | 0.00001 | 0.0001 | 20,000 |
| 10 | 경량형 | 100 | 0.00001 | 0.0001 | 20,000 |
| 11 | 경량형 | 32 | 0.00003 | 0.0001 | 10,000 |
| 12 | 경량형 | 32 | 0.00001 | 0.001 | 10,000 |

두 구조 모두 ResNet18·Transformer와 640×480 두 카메라를 사용한다. 추론 중 위 표의 학습률·감쇠는
다시 적용하지 않는다. 해당 설정으로 만들어진 가중치를 고르는 것이다.

## 추론 세부 설정을 바꾸는 곳

```bash
nano ~/il_ws/act044_inference.env
```

| 설정 키 | 기본값 | 실행 시 덮어쓰기 | 의미 |
|---|---|---|---|
| `ACT044_RUN_DIR` | 오늘 0.4.4 학습 루트 | `--run-dir` | 선택할 학습 결과 폴더 |
| `ACT044_DURATION` | 10 | `--duration 50` | 한 번 구동하는 시간(초) |
| `ACT044_ACTION_STEPS` | 5 | `--action-steps 10` | 예측한 행동을 몇 스텝 실행한 뒤 다시 예측할지 |
| `ACT044_TEMPORAL_ENSEMBLE` | false | `--temporal-ensemble` / `--no-temporal-ensemble` | 겹치는 예측 평균; 켜면 action steps 1 필요 |
| `ACT044_TEMPORAL_ENSEMBLE_COEFF` | 0.01 | `--temporal-ensemble-coeff 0.01` | 앙상블 가중 계수; 활성화 옵션과 함께 사용 |
| `ACT044_MAX_RELATIVE_TARGET` | 3 | `--max-relative-target 3` | 현재 관절 대비 한 스텝 목표 변화 제한 |
| `ACT044_DEVICE` | cuda | `--device cpu` | 추론 장치 |
| `ACT044_DISPLAY` | false | `--display` / `--no-display` | 원본 LeRobot Rerun 화면 표시 |
| `ROBOT_PORT`, `ROBOT_ID` | 기존 장치 경로·ID 복사 | `--port`, `--robot-id` | 팔로워 연결 |
| `FRONT_CAM`, `WRIST_CAM` | 기존 안정적인 by-id 경로 복사 | `--top`, `--wrist` | 상부·손목 카메라 |
| `FRONT_CAM_FPS`, `WRIST_CAM_FPS` | 22 / 30 | `--top-fps`, `--wrist-fps` | 카메라 요청 FPS; 제어 루프는 30Hz |

파일에 저장하면 이후 실행에도 적용한다. 명령 옵션은 해당 실행에서만 파일의 값을 덮어쓴다.

```bash
./run_act044.sh run 1 --duration 30 --action-steps 10 --max-relative-target 3
```

`ACTION_STEPS=5`는 학습 chunk를 5로 바꾸는 설정이 아니다. 예를 들어 chunk16 모델에서 16개를
예측하고 앞의 5개를 실행한 뒤 다시 예측한다. 반드시 `1 <= action-steps <= 모델 chunk`여야 한다.
모델의 Transformer 크기·학습 chunk·가중치를 바꾸려면 다른 번호의 모델을 골라야 한다.

최대 목표 변화량의 단위는 LeRobot 모터 위치 단위이며 도·라디안이 아니다. 학습 당시 초기 자세·카메라·
박스 배치에서 사용한다. 종료 시 0.4.4 드라이버는 토크를 해제하므로 팔을 지지할 준비가 필요하다.
이 실행기를 만든 과정에서는 실제 모터를 구동하지 않았으며, 실물 성공률은 아직 검증되지 않았다.

관절 목표 변화량 제한을 해당 실행에서 해제하려면 `--no-relative-target`을 추가한다.
이는 원본 드라이버에 `--robot.max_relative_target=null`을 전달한다. 설정 파일의 기본값 3은 유지된다.

```bash
# 실제 구동: 1번 모델, Temporal Ensembling, 목표 변화량 제한 해제, 10초
./run_act044.sh run 1 --step 20000 --action-steps 1 --temporal-ensemble \
  --no-relative-target --duration 10
```

## 기록·검사 범위

0.4.4의 원본 `lerobot-record --policy.path=...`로 실행한다. 실행 영상·관절·행동 기록은
`~/il_ws/outputs/act044_real_eval/`에 저장하고 `push_to_hub=false`로 외부 업로드를 하지 않는다.
기존 캘리브레이션 파일이 없으면 자동 재보정을 진행하지 않고 종료한다.

일반형·경량형 CPU 모델 로딩, 전처리·후처리 로딩, 원본 0.4.4 CLI의 인자 파싱,
번호·경로 선택, 저장 중 파일 제외, dry run의 비구동 동작, 셸 구문·린트 검사를 수행했다.
