# OMX 모방학습 데이터 수집 대시보드

OMX-AI 리더-팔로워 원격조종으로 모방학습 데이터를 녹화하고, LeRobot 데이터셋(v3.0)으로 저장하는 데스크톱 툴입니다.

---

## 1. 준비

**필요 환경**
- Ubuntu 22.04
- LeRobot 0.4.4가 설치된 가상환경
- 리더암·팔로워암 USB 연결 (udev 설정 불필요: BringUp 때 모터 ID로 보드를 자동 감지)
- 팔로워암 전원(12V) 연결

**설치**
```bash
# omx_recoder 폴더만 받기
git clone --filter=blob:none --sparse -b tool/omx-ai_record_dashboard \
  https://github.com/kernel-robot-8th/kernel-robot-repo-4.git
cd kernel-robot-repo-4
git sparse-checkout set omx_recoder
cd omx_recoder

source ~/venv/il/bin/activate
pip install -r requirements.txt
```

**실행**
```bash
python main.py
```

---

## 2. 처음 한 번만 설정

**설정 탭**에서 진행합니다.

1. `카메라 찾기` → 미리보기를 보고 각 카메라를 `wrist` / `top`으로 지정
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
