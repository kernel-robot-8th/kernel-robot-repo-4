# 학습 데이터 만들기 · 학습 스크립트 (shoebox, lerobot 0.4.4)

이 저장소 모델(ACT a / b / ab, 각각 MoGe 있음·없음)을 만들 때 쓴 코드입니다. 원본 데이터셋 2개에서 학습 데이터를 만들고, 같은 설정으로 다시 학습하고, val loss를 다시 계산할 수 있습니다.

```
training/
├─ make_datasets.sh                 원본 2개 → 합친 데이터 + MoGe + 학습용(val 시연 뺀) 데이터 6개
├─ train_act.sh                     ACT 학습 (a | b | ab | a_moge | b_moge | ab_moge)
├─ train_gradient_accumulation.py   lerobot-train + gradient accumulation
└─ tools/
   ├─ merge_datasets.py             데이터셋 합치기
   ├─ delete_episodes.py            시연 빼기 (val 시연)
   ├─ make_depth_dataset.py         MoGe-2 depth 영상(top_depth) 추가
   └─ val_loss.py                   체크포인트마다 val loss 계산
```

## 설치

```bash
pip install "lerobot[dynamixel]==0.4.4"
# MoGe (depth 데이터를 만들 때): PyPI에 없어서 GitHub에서 설치
pip install opencv-python-headless scipy trimesh
pip install --no-deps git+https://github.com/EasternJournalist/utils3d.git git+https://github.com/microsoft/MoGe.git
```

## 1. 학습 데이터 만들기

```bash
hf download Sungah/omx_shoebox_act --include "training/*" --local-dir omx_shoebox
cd omx_shoebox
DATA=$PWD/data bash training/make_datasets.sh
```

- 원본 [Yuzriha00/shoebox_a](https://huggingface.co/datasets/Yuzriha00/shoebox_a), [Yuzriha00/shoebox_b](https://huggingface.co/datasets/Yuzriha00/shoebox_b)가 `data/`에 없으면 먼저 받습니다.
- 단계마다 새 폴더를 만들고 원본은 고치지 않습니다. 이미 있는 폴더는 건너뜁니다.
- MoGe 단계는 GPU가 필요합니다. 첫 실행 때 `Ruicheng/moge-2-vitb-normal` 가중치를 받습니다.

| 만들어지는 폴더 | 만드는 방법 | 시연 | 프레임 | 영상 | 쓰는 모델 |
|---|---|---|---|---|---|
| `shoebox_ab` | `merge_datasets.py` a + b | 20 (a = 0~9, b = 10~19) | 26,873 | top, wrist | val loss 계산 |
| `shoebox_ab_moge` | `make_depth_dataset.py` (ViT-B, 토큰 1200) | 20 | 26,873 | top, **top_depth**, wrist | val loss 계산 |
| `shoebox_a_tr` / `_moge_tr` | `delete_episodes.py` 9~19 | 9 | 9,693 | | ACT a / a_moge |
| `shoebox_b_tr` / `_moge_tr` | `delete_episodes.py` 0~9, 19 | 9 | 14,491 | | ACT b / b_moge |
| `shoebox_ab_tr` / `_moge_tr` | `delete_episodes.py` 9, 19 | 18 | 24,184 | | ACT ab / ab_moge |

- 두 원본은 같은 작업(상자 안에 신발 넣기)을 **시연자만 바꿔** 녹화한 것입니다. 30 fps, 카메라 `top`(위쪽)·`wrist`(손목), state 6(관절 5 + 그리퍼 위치).
- **val 시연**: a의 9번(1,094프레임), b의 9번(합친 데이터에서 19번, 1,595프레임). 둘 다 길이가 중간쯤인 시연입니다. 학습에는 쓰지 않습니다.
- **MoGe depth**: 위쪽 카메라 모든 프레임에 MoGe-2로 거리(m)를 추정해, [near, far] 범위로 잘라 흑백 영상 `observation.images.top_depth`로 저장합니다(가까울수록 흰색).
  - 범위는 합친 데이터 거리 분포의 1%~99% 값(**0.79~2.65 m**)이고 `meta/depth_info.json`에 적힙니다.
  - a·b·ab 모두 이 한 범위를 씁니다. 추론 때도 이 범위로 depth를 만듭니다.

## 2. 학습

```bash
bash training/train_act.sh a          # a | b | ab | a_moge | b_moge | ab_moge
```

- 결과는 `outputs/train/act_shoebox_<이름>/checkpoints/<step>/pretrained_model`에 저장됩니다.
- 위치는 `DATA=`, `OUT=`로 바꿀 수 있고, 뒤에 `lerobot-train` 옵션을 더 붙이면 덮어씁니다.

| 항목 | 값 |
|---|---|
| 시작점 | ResNet18 ImageNet 가중치 |
| batch | 256 = GPU에 32씩 × 8번 나눠 계산 (`GRAD_ACCUM=8`) |
| step · 저장 | a 3600 / b 5400 / ab 9000 (모두 데이터 약 95회 반복) · 600마다 |
| chunk | 100 |
| 학습률 | AdamW, cosine 최대 4e-5(이미지 인코더 1e-5), warmup 100 → 1e-6, grad clip 10 |
| 기타 | 이미지 증강 켬, 그리퍼 전류 안 씀 |

- **gradient accumulation**: batch 256을 한 번에 GPU에 올리지 못해서, 작게 나눠 계산한 뒤 합쳐서 한 번 업데이트합니다. 결과는 batch 256과 같습니다.
  - 메모리가 모자라면 `GRAD_ACCUM=16`(GPU에는 16씩, 업데이트는 그대로 batch 256).
  - 11/03 학습에서 ab, a_moge, b_moge는 GPU를 다른 학습과 나눠 써서 `GRAD_ACCUM=16`으로 돌렸습니다.

## 3. val loss 계산

```bash
python -I training/tools/val_loss.py --dataset_root data/shoebox_ab --episodes 0,9,10,19 \
    --ckpts outputs/train/act_shoebox_a/checkpoints --out outputs/eval/val_shoebox.json
# MoGe 모델은 --dataset_root data/shoebox_ab_moge
```

- loss = 모델이 예측한 동작 100스텝이 시연과 얼마나 다른지(L1, 정규화 단위). 학습 loss의 L1 항과 같은 계산입니다.
- 실물에서 돌릴 때와 같은 방식으로 계산합니다: 무작위 요소 없음, 이미지 증강 없음.
  - 학습 로그의 loss는 KL 항(×10)이 더해져 있어서 이 값과 바로 비교할 수 없습니다.
- 시연 4개를 따로 계산합니다: 0 = a 학습, 9 = a val, 10 = b 학습, 19 = b val. 각 시연에서 2프레임마다 한 번 예측합니다.
