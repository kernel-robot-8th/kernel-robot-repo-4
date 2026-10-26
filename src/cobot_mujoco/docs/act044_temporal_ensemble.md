# ACT 0.4.4 추론: 실행 구간 1과 Temporal Ensembling

## 적용할 설정

오늘 학습한 ACT 모델에서 **매 스텝 다시 예측하고, 겹치는 행동 예측을 평균**하려면 다음을 함께 사용한다.

```text
n_action_steps = 1
temporal_ensemble_coeff = 0.01
```

LeRobot 0.4.4 원본에는 `execution_horizon=true`나 `temporal_ensemble=true`라는 ACT 설정이 없다.
실행 구간(execution horizon)은 `n_action_steps`로 지정한다. Temporal Ensembling은
`temporal_ensemble_coeff`에 숫자를 지정하면 켜지고, `null`이면 꺼진다.
오늘 만든 실행기의 `--temporal-ensemble` 또는 `.env`의 `true`는 이 숫자 설정을 전달하는 편의 옵션이다.

## 설정 파일에 저장하는 방법

```bash
nano ~/il_ws/act044_inference.env
```

아래 세 줄을 설정한다. 기존 실행 기본값은 action steps 5, 앙상블 false이므로 원하는 경우 직접 변경한다.

```bash
ACT044_ACTION_STEPS=1
ACT044_TEMPORAL_ENSEMBLE=true
ACT044_TEMPORAL_ENSEMBLE_COEFF=0.01
```

이 파일은 오늘의 0.4.4 전용 실행기에서 읽는다. 옛 모델 번들의
`outputs/hub/omx_1024_jihyeok_act/config.env`를 수정할 필요는 없다.

## 명령어로 한 번만 적용하는 방법

```bash
cd ~/il_ws

# 번호와 저장본 확인: 장치 연결 없음
./run_act044.sh list
./run_act044.sh checkpoints 1

# 먼저 전달할 옵션 확인: 장치 연결·구동 없음
./run_act044.sh run 1 --step 20000 --action-steps 1 \
  --temporal-ensemble --temporal-ensemble-coeff 0.01 --dry-run

# 실제 로봇 구동: 일반형 chunk16, 10초
./run_act044.sh run 1 --step 20000 --duration 10 --action-steps 1 \
  --temporal-ensemble --temporal-ensemble-coeff 0.01

# 실제 로봇 구동: 경량형 chunk16, 10초
./run_act044.sh run 7 --step 20000 --duration 10 --action-steps 1 \
  --temporal-ensemble --temporal-ensemble-coeff 0.01
```

명령 옵션은 해당 실행에서만 `.env`보다 우선한다. `--temporal-ensemble`만 켜고 action steps를
5로 두면 실행기가 오류로 중단한다. 앙상블을 끄려면 `--no-temporal-ensemble`을 사용한다.
모델 번호 전체 대응표는 [기본 실행 안내](act044_inference.md)에 있다.

Dry run에 다음 원본 옵션이 모두 표시되는지 확인한다.

```text
--policy.n_action_steps=1
--policy.temporal_ensemble_coeff=0.01
```

재학습이나 체크포인트 파일 수정은 필요하지 않다. 추론 시 옵션으로 덮어쓰며 학습 chunk 크기는 유지한다.

## 실행 구간과 앙상블의 차이

| 설정 | 새 관측으로 추론하는 시점 | 실행 행동 선택 |
|---|---|---|
| action steps 5, 앙상블 끔 | 큐의 5개 행동을 소진한 뒤 | 새 chunk 앞의 5개를 차례로 실행 |
| action steps 1, 앙상블 끔 | 매 제어 스텝 | 새 chunk의 첫 행동만 실행 |
| action steps 1, 앙상블 켬 | 매 제어 스텝 | 현재 시점에 해당하는 과거·현재 chunk 예측을 가중 평균 |

예를 들어 chunk16 모델은 매번 미래 16스텝을 예측한다. 앙상블을 켠 경우 시점 t의 행동은
t에서 방금 예측한 첫 행동, t−1에서 예측한 두 번째 행동 등 같은 시점을 겨냥한 예측을 모아 계산한다.
시작 직후에는 과거 예측이 적고, 이후 최대 chunk 크기만큼 겹친다. 매번 16개를 즉시 모두 실행하는 것은 아니다.

제어 목표가 30Hz일 때 실행 구간 1은 매 제어 스텝 약 33ms마다 새 추론을 시도한다는 뜻이다.
이는 카메라가 매번 새 프레임을 보장하거나 실제 추론이 반드시 30Hz라는 뜻은 아니다.
현재 상부 카메라 요청은 22FPS, 손목은 30FPS이며, 추론·촬영·통신 시간이 목표 주기를 넘으면
실제 제어 속도는 낮아진다. action steps 5보다 추론 호출 횟수가 늘어난다.

## 계수의 의미와 비교 방법

설치된 0.4.4 구현은 오래된 예측부터 i=0을 붙이고 `exp(-계수 × i)`를 정규화해 가중치로 쓴다.

| 계수 | 효과 |
|---|---|
| `null` | 앙상블 끔 |
| `0` | 겹치는 예측을 동일 가중치로 평균; 앙상블은 켜짐 |
| `0.01` | 원본 코드가 안내하는 ACT 계수; 과거 예측에 조금 더 큰 가중치 |
| 양수 증가 | 과거 예측을 더 강하게 반영 |
| 음수 | 최근 예측에 더 큰 가중치 |

`true`를 계수에 넣지 않는다. 실행기의 `ACT044_TEMPORAL_ENSEMBLE=true`와
숫자 `ACT044_TEMPORAL_ENSEMBLE_COEFF=0.01`을 구분한다.

같은 모델·체크포인트·초기 자세·물체 배치에서 아래 세 조건을 비교하면 기능 차이를 보기 쉽다.

1. action steps 5, 앙상블 끔.
2. action steps 1, 앙상블 끔.
3. action steps 1, 앙상블 켬, 계수 0.01.

성공 여부, 소요 시간, 움직임의 떨림, 물체 이동에 대한 반응 지연, 실제 제어 주기를 함께 기록한다.
앙상블은 예측 변화의 완화를 기대할 수 있으나 잘못된 행동도 평균할 수 있어 성공률 향상을 보장하지 않는다.
기존 검증 MAE만으로 이 폐루프 실행 방식의 효과를 판단할 수는 없다.

## 확인한 근거와 범위

설치된 LeRobot 0.4.4 소스 기준이다.

- `~/il_ws/src/lerobot/src/lerobot/policies/act/configuration_act.py`:
  `temporal_ensemble_coeff`와 `n_action_steps=1` 제약.
- `~/il_ws/src/lerobot/src/lerobot/policies/act/modeling_act.py`:
  `ACTPolicy.select_action`, `ACTTemporalEnsembler`의 겹치는 예측 평균·가중치 구현.
- 저장소 `scripts/manipulation/act044_launch.py`:
  전용 실행기의 편의 옵션을 원본 LeRobot 인자로 변환.

실행 명령과 0.4.4 설정 파싱을 장치 연결 없이 검사했다. 이 문서 작성 중 실제 로봇을 구동하지 않았다.
실제 구동 시 학습 당시 자세·카메라·배치를 맞춰 사용하며, 종료 시 토크가 해제되는 점을 고려한다.
