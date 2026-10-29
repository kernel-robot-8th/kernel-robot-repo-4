# OMX 모방학습 데이터 수집 대시보드

OMX-AI 리더-팔로워 원격조종으로 모방학습 데이터를 녹화하고, LeRobot 데이터셋(v3.0)으로 저장하는 데스크톱 툴입니다. 학습(Docker)과 로봇 추론도 같은 화면에서 실행합니다.

---

## 1. 준비

**필요 환경**
- Ubuntu 22.04 / 24.04, Python 3.12
- LeRobot 0.6.1이 설치된 가상환경 (녹화·추론 공통, 학습은 Docker 안의 0.6.1)
- 리더암·팔로워암 USB 연결 (udev 설정 불필요: BringUp 때 모터 ID로 보드를 자동 감지)
- 팔로워암 전원(12V) 연결
- (학습 탭을 쓸 때) Docker + nvidia-container-toolkit, NVIDIA GPU — 아래 **Docker 설치** 참고

**설치**
```bash
# omx_recoder 폴더만 받기
git clone --filter=blob:none --sparse -b tool/omx-ai_record_dashboard \
  https://github.com/kernel-robot-8th/kernel-robot-repo-4.git
cd kernel-robot-repo-4
git sparse-checkout set omx_recoder omx_train   # 학습 탭은 omx_train을 씀
cd omx_recoder

# Python 3.12 가상환경 (LeRobot 0.6.1은 Python 3.12 이상 필요)
python3.12 -m venv ~/venv/il06
source ~/venv/il06/bin/activate
pip install -r requirements.txt     # lerobot 0.6.1 (core_scripts·dynamixel·smolvla) 포함, torch(CUDA) 수 GB
```
> 예전 `~/venv/il`(Python 3.10, LeRobot 0.4.4)은 이 버전의 대시보드를 실행할 수 없습니다. 0.4.4로 녹화한 데이터에는 0.6.1에서 그대로 이어서 녹화할 수 있습니다.

**실행**
```bash
python main.py
```

---

## 2. 처음 한 번만 설정

**설정 탭**에서 진행합니다.

1. `카메라 찾기` → 미리보기를 보고 각 카메라를 `wrist` / `top`으로 지정
   - udev 별칭(`/dev/cam_wrist`, `/dev/cam_top`, `~/il_ws/udev/install.sh`)이 있으면 역할이 미리 선택되고 별칭 경로로 저장됩니다. 경로 칸이 비어 있어도 별칭이 있으면 자동으로 연결합니다.
2. `로그인 확인` → Hugging Face 토큰 입력 (write 권한, HF 업로드할 때만 필요)
3. `설정 저장`

---

## 3. 데이터 수집

### ① 세션 시작
- **저장 경로**: 기본 `./output` (`폴더 선택`으로 변경 가능)
- **태스크명**: 영문·숫자·밑줄만 사용 (예: `shoe_box_pick`)
- `세션 시작` 클릭

> 같은 태스크명으로 다시 시작하면 기존 데이터에 **이어서** 저장됩니다.

### ② BringUp
- `BringUp` 클릭 → 팔로워 토크 ON → **리더·팔로워 모두** Init 자세로 이동 후 대기 (리더 관절 토크 ON)
- **처음 사용 시** Init 자세가 없습니다. 팔로워가 리더암 자세로 천천히 이동한 뒤 원격조종이 시작됩니다.
  리더암으로 원하는 자세를 만든 뒤 `리더 자세 → Init 저장` → 두 팔이 그 자세에서 대기합니다.
- 종료 자세도 쓰고 싶으면 원격조종 중에 `리더 자세 → Rest 저장` (없으면 Init 자세 사용)
- 대기 중에 녹화 없이 움직여 보려면 `리더암 해제 (녹화 없이 원격조종)`

### ③ Init 대기
- 화면에 **"Init 자세 · 리더암을 잡고 녹화"** 가 뜨면 리더·팔로워가 Init 자세에 고정된 상태입니다.
- 리더암은 토크로 고정되어 있으니 자세를 맞출 필요가 없습니다. 리더암을 잡은 채로 녹화를 시작하세요.
- 원격조종 중에 녹화를 누르면 두 팔이 먼저 Init 자세로 이동한 뒤 녹화가 시작됩니다.

### ④ 녹화
1. **태스크 문장** 입력 (예: `신발 상자를 핑키 위로 옮겨`) → `Enter`
   - 비워두면 이전 문장을 그대로 사용
2. 리더암을 잡고 `녹화` 또는 **Space** → 리더 토크 OFF, 원격조종과 녹화가 함께 시작
3. 동작이 끝나면 결과 선택

| 버튼 | 단축키 | 저장 |
|---|---|---|
| Success | **S** | `success/` 폴더에 저장 |
| Fail | **F** | `fail/` 폴더에 저장 |
| Discard | **D** | 저장하지 않고 버림 |

4. 리더·팔로워가 자동으로 Init 자세로 돌아갑니다 → ③부터 반복

### ⑤ 종료
- `Servo OFF` 클릭 → 리더·팔로워가 Rest 자세로 이동 후 토크 OFF (**두 팔을 받쳐 주세요**)
- 녹화 중에는 Servo OFF가 눌리지 않습니다.

### ⑥ HF Hub 업로드 (선택)
- `HF Hub 업로드` 클릭 → `<계정>/<태스크명>_success`, `<계정>/<태스크명>_fail` 로 업로드
- 기본은 **비공개(private)** 입니다.

### ⑦ 학습 (선택)
**학습 탭**은 `omx_train/<정책>/train.sh`(Docker, LeRobot 0.6.1)를 실행하는 화면입니다. 터미널에서 `./train.sh`로 학습하는 것과 같은 스크립트·같은 결과 폴더를 씁니다. 기본으로는 녹화한 `success/` 데이터를 쓰고, `fail/` 데이터는 쓰지 않습니다.

0. **학습 환경** 칸에서 Docker 상태를 확인합니다. 처음에는 `이미지 빌드`를 한 번 누릅니다 (정책별, 수 분 걸림).
1. 학습할 데이터를 정합니다.
   - **기본**: `데이터 폴더` 칸을 비워 두면 현재 세션(`<저장 경로>/<태스크명>/success`)을 씁니다.
   - **다른 데이터**: `폴더 선택`으로 LeRobot 데이터셋 폴더(`meta/info.json`이 있는 폴더)를 지정합니다. HF에 있는 데이터는 `hf download <저장소> --repo-type dataset --local-dir <폴더>`로 먼저 받아 둡니다 (비공개 저장소는 `hf auth login` 필요).
   - **평가용 제외 에피소드**: `5,9`나 `3-5`처럼 적으면 그 에피소드를 학습에서 뺍니다 (train.sh의 `EPISODES`).
2. 학습 설정을 고릅니다.
   - 정책: `ACT` 또는 `SmolVLA` (`omx_train/ACT`, `omx_train/SmolVLA`)
   - step·batch·체크포인트 주기 등은 처음에 train.sh에 적힌 값(마지막 학습 설정)으로 채워지고, 바꾼 값은 train.sh 뒤에 덮어쓰는 인자로 넘어갑니다. `train.sh 값으로`로 되돌립니다.
   - **epoch → step**: epoch 수를 넣고 `step에 적용`을 누르면 step 수를 채웁니다 (1 epoch = 학습 프레임 수 / batch).
   - **추가 인자**: 화면에 없는 lerobot-train 옵션을 `--이름=값` 형식으로 적습니다. 예: `--policy.chunk_size=50 --seed=7`
   - 위 값들(step·batch 등, 이미지 증강, 추가 인자)은 **정책마다 따로 저장**됩니다. 정책을 바꾸면 그 정책에서 마지막으로 쓴 값이 다시 채워집니다.
   - GPU 메모리 16GB에서 SmolVLA 기본 batch 64(약 15GB)는 빠듯하니 batch를 줄이세요.
3. `학습 시작`을 누르면 train.sh가 Docker 컨테이너(`omx-train-<태스크>_<정책>_<시각>`)를 띄웁니다. 진행률, loss, 로그가 화면에 표시됩니다. 로그 첫 줄은 같은 학습을 터미널에서 실행하는 명령입니다.
4. **대시보드를 꺼도 학습은 계속됩니다.** 다시 켜면 실행 중인(또는 그사이 끝난) 학습에 자동으로 다시 연결합니다. 터미널에서는 `docker logs -f omx-train-<이름>`으로 볼 수 있습니다.
5. `중지`로 멈춥니다 (`docker stop`). 체크포인트가 저장된 학습은 목록에서 골라 `이어서 학습`으로 마지막 체크포인트부터 다시 시작합니다.
6. 결과는 `omx_train/<정책>/outputs/train/<이름>/`에 저장됩니다. 학습된 정책은 `checkpoints/last/pretrained_model/`에 있고, 옆의 `<이름>.run.json`에 데이터 경로·제외한 에피소드·실행 명령이 남습니다. 오프라인 평가는 [omx_train](../omx_train/README.md)을 참고하세요.

### ⑧ 추론 (로봇 실행)
**추론 탭**은 `omx_train/<정책>/inference.sh`(`lerobot-rollout`)를 대시보드와 같은 venv로 실행합니다. 터미널에서 `./inference.sh`로 실행하는 것과 같은 스크립트입니다.

> ⚠️ **로봇이 정책대로 움직입니다.** 로봇 주변을 비우고, 언제든 `중지`를 누를 수 있게 하세요. `inference.sh`의 `--robot.max_relative_target`(한 스텝 최대 이동량)이 안전장치입니다.

1. 대시보드에서 BringUp 중이면 **먼저 Servo OFF** 합니다. 추론이 팔로워 포트와 카메라를 직접 열기 때문에, 추론하는 동안 대시보드 카메라 미리보기는 꺼집니다.
2. **정책**과 **모델**을 고릅니다. 모델 목록은 `omx_train/<정책>/outputs/train/*/checkpoints/*/pretrained_model`(최신 학습, `last` 먼저)이고, 다른 위치의 모델은 `폴더 선택`으로 지정합니다 (HF 모델은 `hf download <저장소> --local-dir <폴더>`로 먼저 받기).
3. 실행 설정을 정합니다. 비워 둔 값은 `inference.sh`에 적힌 값을 씁니다.
   - **작업 문장**: SmolVLA는 학습 데이터의 문장과 같아야 합니다. ACT는 쓰지 않습니다.
   - **실행 시간**: 0이면 `중지`를 누를 때까지 실행합니다.
   - **장치**: ACT는 `cpu`도 되고, SmolVLA는 `cuda`가 필요합니다 (CPU는 예측 1회 약 10초).
   - **앙상블** (ACT 전용): k 스텝마다 다시 예측하고 겹치는 예측을 가중 평균합니다 (`act_ensemble.py`).
   - **추가 인자**: 그 밖의 `lerobot-rollout` 옵션. 예: `--policy.n_action_steps=20 --robot.max_relative_target=5`
4. 포트·카메라·로봇 id는 **설정 탭 값**을 씁니다. 팔로워 포트가 `auto`면 자동으로 찾고, 카메라 경로가 비어 있으면 `/dev/cam_top`, `/dev/cam_wrist` 별칭을 씁니다. 로봇 id(`follower_id`)를 녹화 때와 같게 두어야 같은 캘리브레이션을 씁니다.
5. `추론 시작` → 확인 창에서 `Yes`. 로그 첫 줄은 같은 추론을 터미널에서 실행하는 명령입니다.
6. `중지`는 Ctrl+C와 같습니다. lerobot이 로봇 연결을 정리하고 끝나며, 10초 안에 끝나지 않으면 강제 종료합니다. 추론 중에 앱을 닫으면 추론을 먼저 중지합니다.

> 추론 설정은 앱을 끌 때 `config.yaml`의 `infer:` 항목에 정책별로 저장됩니다.

> 학습 설정은 앱을 끌 때 `config.yaml`의 `train:` 항목에 저장됩니다. `train.omx_train_dir`로 omx_train 위치를 바꿀 수 있습니다 (기본 `../omx_train`).

#### Docker 설치 (학습 PC에서 한 번, sudo 필요)
Ubuntu 기준입니다. 자세한 내용은 [Docker](https://docs.docker.com/engine/install/ubuntu/), [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) 문서를 따르세요.
```bash
# 1) Docker Engine
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER        # 로그아웃 후 다시 로그인해야 적용 (sudo 없이 docker 실행)

# 2) NVIDIA Container Toolkit (컨테이너에서 GPU 사용)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker

# 3) 확인
docker run --rm --gpus all ubuntu nvidia-smi
```
> docker 그룹에 들어가면 그 계정은 사실상 root 권한을 갖습니다. 여러 사람이 쓰는 PC라면 관리자와 상의하세요.

---

## 4. 주의 사항

- **실행 직후 대시보드가 꺼질 때**: Python 3.10.22 / PySide6 6.12.0 환경에서
  `Fatal Python error: none_dealloc: deallocating None` 종료를 재현했습니다.
  `QLabel.setText()` 반복 호출만으로도 발생하며, PySide6 6.8.3에서는 같은 현상이
  발생하지 않았습니다. `requirements.txt`의 검증 버전을 사용하세요.
  활성화된 가상환경에서 `python -m pip install -r requirements.txt`로 설치합니다.
  별도 설치된 `PySide6-Pdf` / `PySide6-WebEngine`이 6.12.0을 요구하는 환경에서는
  해당 패키지의 의존성도 함께 정리해야 합니다. 이 대시보드는 두 패키지를 사용하지 않습니다.
  다른 종료 원인을 확인하려면 터미널에서 `python -X faulthandler main.py`로 실행하세요.
- **단축키가 안 먹을 때**: 입력창에 커서가 있는 상태입니다. `Enter` 또는 `Esc`로 빠져나오세요.
- **녹화 버튼이 안 켜질 때**: Init 자세가 저장되지 않았거나, 이동 중이거나, 이전 에피소드를 저장하는 중입니다.
- **영상 저장이 느릴 때**: 설정 탭 `비디오 코덱`을 `h264`로 바꾸세요.
- **"데이터 구성이 다릅니다" 오류**: 기존 데이터와 카메라 구성·해상도·녹화 주기가 다를 때 납니다. 설정을 맞추거나 새 태스크명을 쓰세요.
- **EE 포즈가 실제와 다를 때**: 설정 탭 `EE 포즈 보정`에서 방향이 반대인 관절은 부호를 `-1`로, 0점이 어긋나면 오프셋(도)을 조정하세요.
- **설정 파일**: 설정은 앱을 끌 때 `config.yaml`에 자동 저장되고, 다음 실행 때 그대로 불러옵니다. `config.yaml`은 PC마다 다르므로 git에서 제외되어 있으며, 처음 실행하면 `config.example.yaml`을 복사해 만듭니다. 팀 공통 기본값을 바꿀 때만 `config.example.yaml`을 수정하세요. 설정을 초기화하려면 앱을 끈 상태에서 `config.yaml`을 지우고 다시 실행하세요.
- **GPU 메모리 부족(`CUDA out of memory`)으로 학습이 멈출 때**: 학습 탭에서 `batch size`를 줄이세요.
- **학습과 녹화를 동시에 할 때**: 학습이 CPU·GPU를 많이 써서 녹화 주기(루프 Hz)가 흔들릴 수 있습니다. 학습 중에 BringUp을 누르면 확인 창이 뜹니다. 가능하면 녹화를 마친 뒤 학습하세요.
- **녹화 데이터(`output/`)는 git에서 제외됩니다.** 데이터는 HF Hub 업로드 등 별도 경로로 공유하세요.

---

## 5. 저장 구조

```
output/<태스크명>/
├── success/        # 성공 에피소드 (LeRobot 데이터셋)
│   ├── data/       # parquet
│   ├── videos/     # wrist, top 영상
│   └── meta/
└── fail/           # 실패 에피소드 (같은 구조)

omx_train/<ACT|SmolVLA>/outputs/train/     # 학습 결과 (학습 탭·train.sh 공통)
├── <태스크>_<정책>_<날짜_시각>.run.json   # 데이터 경로, 제외 에피소드, 실행 명령
└── <태스크>_<정책>_<날짜_시각>/
    └── checkpoints/
        ├── <step>/pretrained_model/
        └── last/pretrained_model/         # 가장 최근 체크포인트
```

**주요 데이터**

| 키 | 내용 |
|---|---|
| `action` | 팔로워에 보낸 목표 관절값 |
| `observation.state` | 팔로워 관절 위치 |
| `observation.images.wrist` / `top` | 카메라 영상 |
| `aux.leader_action` | 리더암 관절값 |
| `aux.velocity`, `aux.current`, `aux.gripper_current` | 속도, 전류 |
| `aux.temperature`, `aux.voltage` | 모터 온도, 전압 |
| `aux.ee_pose` | 그리퍼 끝 위치·방향 (x, y, z, roll, pitch, yaw) |
| `episode_success` | 성공 1 / 실패 0 |

- `aux.*`, `episode_success`는 LeRobot 학습 시 정책 입력에 자동으로 들어가지 않습니다.
- 에피소드별 기록(성공 여부, 태스크 문장, 길이): `meta/collector_episodes.jsonl`
- 각 데이터의 단위: `meta/collector_info.json`
