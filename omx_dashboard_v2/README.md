# OMX 대시보드 v2 (OMX Studio v2)

OMX 매니퓰레이터 모방학습(LeRobot 0.4.4)용 데스크톱 대시보드입니다. 모델 추론과 데이터 녹화를 한 창에서 합니다.
GPU PC(Ubuntu 24.04, RTX 5080)에서 실기로 쓰고 있는 버전을 그대로 올렸습니다.

## 설치 위치

이 폴더는 HF 번들 `Sungah/omx_act_1027` 안에 두고 쓰는 구조입니다 (`act_ensemble.py`, `inference.sh` 를 상위 폴더에서 찾음).

```bash
# 예: 번들이 ~/il_ws/omx_act_1027 에 있을 때
cp -r omx_dashboard_v2 ~/il_ws/omx_act_1027/dashboard_v2
```

모델은 `~/il_ws/<번들>/models/` (옆에 `inference.sh` 가 있는 번들)과 `~/il_ws/models/` 에서 자동으로 찾습니다.
바꾸려면 환경변수 `OMX_MODEL_DIRS`(`:`로 구분), `OMX_IL_WS`, `OMX_VENV`(기본 `~/venv/il`) 를 씁니다.

## 실행

```bash
source ~/venv/il/bin/activate
cd ~/il_ws/omx_act_1027/dashboard_v2
python app.py          # 프로그램 창 (PySide6 6.8.3)
python server.py       # 브라우저 모드, http://127.0.0.1:8765
```

바탕화면 아이콘은 `start.sh` 를 실행하면 됩니다 (로그: `~/.cache/omx_dashboard_v2.log`).

## 기능

**모델 추론 탭**
- 01 태스크 선택 + "초기 자세로 이동 후 대기" (번들의 `init_pose.json` 자세로 이동한 뒤 토크 유지)
- 02 학습 체크포인트 선택
- 03 단일 실행 (번들 `inference.sh` → lerobot-record)
- 04 연속 실행 (`omx_chain.py`): shoebox_d → move_in_success 두 모델을 로봇 연결·토크를 유지한 채 이어서 실행.
  "다음" 버튼, 자동 넘김 토글, 단계 사이 초기 자세 이동, 전환 직후 이동량 제한
- 실행 설정(포트·카메라·MJPG·연산 장치·동작 섞기 등), 상단 실행 시간 시계, 정지·토크 끄기

**데이터 녹화 탭**: 팀 수집 대시보드 `omx_recoder` 를 끼워 넣고 v2 레이아웃(`recorder/ui/studio_window.py`)만 입혔습니다.

## 성공 판단으로 자동 넘김 (선택)

연속 실행 1단계를 시간이 아니라 top 카메라 화면으로 성공을 판단해서 끝낼 수 있습니다.
모델 번들 폴더에 `success.json` 이 있고 `model` 에 YOLO 세그멘테이션 가중치(`.pt`, Ultralytics)가 들어 있으면 켜집니다.
예시: [`examples/omx_shoebox_d.success.json`](examples/omx_shoebox_d.success.json) → `~/il_ws/omx_shoebox_d/success.json`

- 클래스: `closed_box`, `inside_box`(상자 안쪽·뚜껑 안쪽 빨간 면), `shoe`
- 규칙: `inside_box` 가 1초 보이면 판단 시작 → `closed_box` 가 5초 이어지고 최근 5초 동안 closed_box ≥80%, inside_box·shoe ≤10% 이면 성공
- 성공하면 1단계를 끝내고 자동 넘김. 시간 안에 성공이 안 나오면 자동 넘김이 켜져 있어도 버튼을 기다림
- `model` 이 비어 있으면 기존처럼 시간 기준. 경로가 있는데 파일이나 ultralytics 가 없으면 로봇 연결 전에 멈춤

관련 도구 (로봇 필요 없음):
- `extract_frames.py` — 데이터셋 top 영상에서 라벨링용 프레임 추출 (에피소드당 구간별 8장 + 그리퍼 순간 2장, 검증용 에피소드는 `split.json` 에 따로 뺌)
- `success_check.py` — 녹화 에피소드에 같은 규칙을 돌려 성공 시점 확인 (`--out` 으로 검출 결과 영상 저장)

ultralytics 는 lerobot 의존성과 꼬이지 않게 `pip install ultralytics --no-deps` 후 `pip install ultralytics-thop polars matplotlib scipy psutil` 로 설치합니다.

## 파일

| 파일 | 역할 |
|---|---|
| `app.py` | PySide6 창. `server.py` 를 내부 스레드로 띄우고 추론 탭(`index.html`)과 녹화 탭(`recorder/`)을 한 창에 |
| `server.py` | HTTP 백엔드: 모델 스캔, 실행 파라미터, 명령 생성, 프로세스 관리 |
| `index.html` | 추론 화면 |
| `omx_chain.py` | 연결 유지형 연속 실행기 (초기 자세 대기, 자동 넘김, 성공 판단) |
| `success_judge.py` | 성공 판단 규칙·YOLO 검출·판단 스레드 |
| `record_ctl.py`, `rec_embed.py`, `recorder/` | 녹화 탭 |
| `theme.py`, `window_chrome.py`, `icon.svg` | 창 테마·프레임 |
| `UI_V2.md` | v2 화면 설명 |

## 출처

- `recorder/`: 팀 `omx_recoder` (브랜치 `tool/omx-ai_record_dashboard`, 커밋 f747a25) 복사본 + `ui/studio_window.py` 추가. 자세한 내용은 [`recorder/SOURCE.md`](recorder/SOURCE.md)
- 추론 스크립트·`act_ensemble.py`·모델 번들: HF `Sungah/omx_act_1027`, `Sungah/omx_shoebox_d`, `Sungah/omx_move_in_success` (이 저장소에는 넣지 않음)
- `recorder/config.yaml`, `recorder/init_pose.yaml` 은 컴퓨터마다 달라서 올리지 않았습니다 (처음 실행 때 `config.example.yaml` 로 만들어짐)
