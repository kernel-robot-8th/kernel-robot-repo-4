# omx_train

ROBOTIS OMX 로봇팔 모방학습(LeRobot 0.6.1) 학습·평가 코드입니다.
작업: **상자를 집어 핑키(흰색 원형 로봇) 위에 올리기**

| 폴더 | 정책 | 특징 |
|---|---|---|
| [`ACT/`](ACT/README.md) | ACT | 가벼움(52M), 처음부터 학습, CPU로도 실행 가능 |
| [`SmolVLA/`](SmolVLA/README.md) | SmolVLA | lerobot/smolvla_base 미세조정, 작업 문장 입력, GPU 필요 |

두 폴더는 각각 단독으로 쓸 수 있게 필요한 스크립트를 모두 담고 있습니다.

## 데이터와 모델 (Hugging Face)

| 종류 | 저장소 |
|---|---|
| 데이터셋 (관절 6) | [Sungah/omx_box_merged](https://huggingface.co/datasets/Sungah/omx_box_merged) |
| 데이터셋 (관절 6 + 그리퍼 전류) | [Sungah/omx_box_merged_grip](https://huggingface.co/datasets/Sungah/omx_box_merged_grip) |
| 학습된 ACT + 로봇 실행 번들 | [Sungah/omx_box_act](https://huggingface.co/Sungah/omx_box_act) |
| 학습된 SmolVLA + 로봇 실행 번들 | [Sungah/omx_box_smolvla](https://huggingface.co/Sungah/omx_box_smolvla) |

데이터셋·모델 가중치는 저장소에 커밋하지 않습니다 (`data/`, `outputs/`는 gitignore).
