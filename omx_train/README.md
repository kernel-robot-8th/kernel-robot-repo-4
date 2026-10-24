# omx_train

ROBOTIS OMX 로봇팔 모방학습(LeRobot 0.6.1) 학습·평가·로봇 추론 코드입니다.

| 폴더 | 정책 | 특징 |
|---|---|---|
| [`ACT/`](ACT/README.md) | ACT | 가벼움(52M), 처음부터 학습, CPU로도 실행 가능 |
| [`SmolVLA/`](SmolVLA/README.md) | SmolVLA | lerobot/smolvla_base 미세조정, 작업 문장 입력, GPU 필요 |

두 폴더는 각각 단독으로 쓸 수 있게 필요한 스크립트를 모두 담고 있습니다.

- `train.sh`: Docker 학습. lerobot-train 옵션 전체가 들어 있고, 주석 없는 줄 = 마지막 학습에 쓴 값
- `inference.sh`: 로봇 PC에서 설치된 lerobot으로 추론. lerobot-rollout 옵션 전체가 들어 있고, 주석 없는 줄 = 기본 실행 값

## 데이터와 모델 (Hugging Face)

| 종류 | 저장소 |
|---|---|
| 데이터셋 (상자→흰 바구니, 시연 10개) | [Sungah/omx_1024_test_jihyeok_success](https://huggingface.co/datasets/Sungah/omx_1024_test_jihyeok_success) |
| 데이터셋 (상자→핑키, 관절 6) | [Sungah/omx_box_merged](https://huggingface.co/datasets/Sungah/omx_box_merged) |
| 데이터셋 (상자→핑키, 관절 6 + 그리퍼 전류) | [Sungah/omx_box_merged_grip](https://huggingface.co/datasets/Sungah/omx_box_merged_grip) |
| 학습된 ACT + 로봇 실행 번들 | [Sungah/omx_1024_jihyeok_act](https://huggingface.co/Sungah/omx_1024_jihyeok_act), [Sungah/omx_box_act](https://huggingface.co/Sungah/omx_box_act) |
| 학습된 SmolVLA + 로봇 실행 번들 | [Sungah/omx_box_smolvla](https://huggingface.co/Sungah/omx_box_smolvla) |

데이터셋·모델 가중치는 저장소에 커밋하지 않습니다 (`data/`, `outputs/`는 gitignore).
