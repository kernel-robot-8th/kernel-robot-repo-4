# 🦾 OMX Teleoperation & LeRobot Dataset Studio [PT-23]

> **스프린트:** Sprint 2 (P0 긴급, 기한: 2026-10-24)  
> **목적:** OpenManipulator-F 5+1자유도 로봇팔 원격 텔레옵(LiveKit WebRTC & MJPEG) 및 HuggingFace LeRobot(ACT) 모방학습 데이터셋 즉시 수집  
> **연계 계획서:** [`docs/planning/PT23_OMX_LIVEKIT_TELEOP_LEROBOT_IMPLEMENTATION_PLAN.md`](../docs/planning/PT23_OMX_LIVEKIT_TELEOP_LEROBOT_IMPLEMENTATION_PLAN.md)

---

## 1. 빠른 시작 (1-Click Run)

로컬 가상환경(`.venv`)이 이미 세팅되어 있어 명령어 한 줄로 즉시 구동됩니다:

```bash
cd teleop_omx_studio
./run_studio.sh
```

웹 브라우저를 열고 **`http://localhost:8080`**에 접속하면 스튜디오 화면이 표시됩니다.

* **실물 로봇이 연결되지 않은 경우**: 자동으로 **MOCK (SIM) 모드**로 동작하여 가상 6개 모터와 시뮬레이션 카메라로 모든 제어 및 레코딩을 테스트할 수 있습니다.
* **실물 로봇이 연결된 경우**: `/dev/ttyUSB0` (1,000,000 bps) 포트로 DYNAMIXEL 모터 6대를 실시간 제어합니다.

---

## 2. 주요 기능

### ① 듀얼 카메라 실시간 스트리밍
* **Top Camera (720p)**: 작업대 전체 조감 뷰
* **Wrist Camera (480p)**: 손목 Eye-in-Hand 파지 정밀 뷰
* 우측 하단 작은 화면(PiP)을 클릭하면 메인 화면과 **원클릭 화면 전환**됩니다.

### ② 관절 및 모터 파라미터 전체 제어
* **6개 관절 슬라이더**: Base, Shoulder, Elbow, Wrist Pitch, Wrist Roll, Gripper (각도 ° 및 mm 단위)
* **±5° Jog 버튼**: 미세 위치 조정
* **원클릭 프리셋**: `Home (0°)`, `Ready 대기`, `Pick 접근`, `Retract 안전퇴피 (Z≥280mm)`
* **토크 해제(Lead-through Teaching)**: 상단 `[TORQUE: ON]` 버튼을 누르면 토크가 풀려 사람이 손으로 직접 로봇을 잡고 움직이며 교시할 수 있습니다.
* **실시간 진단**: 모터 평균 온도(°C), 인가 전압(V), 부하 전류(mA) 모니터링.

### ③ LeRobot 표준 1-Click 에피소드 레코더
김성아 님의 모방학습 작업 절차서와 100% 호환되는 규격으로 30Hz 동기화 수집을 지원합니다:

| 조작 | 키보드 단축키 | 게임패드 버튼 | 동작 |
| :--- | :---: | :---: | :--- |
| **녹화 시작** | `Space` | `R1` | 관절 상태(12D) + 액션(6D) + 영상 동기화 수집 시작 |
| **저장 완료** | `Enter` | `L1` | Parquet 테이블 및 MP4 비디오 자동 인코딩 저장 |
| **불량 폐기** | `Backspace` | `B (Circle)` | 조작 실패 시 메모리 버퍼 즉시 폐기 (디스크 오염 방지) |

* **데이터셋 저장 경로**: `~/.cache/huggingface/lerobot/pinky_omx_tasks/`
  * `data/chunk-000/episode_XXXXXX.parquet`
  * `videos/observation.images.top/chunk-000/episode_XXXXXX.mp4`
  * `videos/observation.images.wrist/chunk-000/episode_XXXXXX.mp4`
  * `meta/info.json` & `meta/episodes.jsonl`

### ④ 게임패드(Gamepad) 조작 매핑
USB 또는 블루투스 게임패드(PS5 / Xbox 등)를 PC에 연결하면 자동 감지됩니다:
* **좌측 아날로그 스틱 (Left Stick)**: Base 회전 (X축) / Shoulder 회전 (Y축)
* **우측 아날로그 스틱 (Right Stick)**: Wrist Pitch 회전 (X축) / Elbow 회전 (Y축)
* **R2 트리거**: 그리퍼 비례 제어 (누르는 깊이에 따라 점진적 닫힘)
* **R1 버튼**: 녹화 시작
* **L1 버튼**: 저장 완료
* **B 버튼**: 폐기 및 재시도

---

## 3. LeRobot 모방학습(ACT) 모델 학습 연계

수집된 데이터는 Hugging Face LeRobot 표준 형식이므로, 별도의 전처리 없이 LeRobot 저장소에서 즉시 학습 스크립트를 실행할 수 있습니다:

```bash
# 1. 수집된 에피소드 시각화 및 검수
python lerobot/scripts/visualize_dataset.py --repo-id pinky_omx_tasks

# 2. ACT 정책 모델 학습 시작
python lerobot/scripts/train.py \
    --policy.type=act \
    --dataset.repo_id=pinky_omx_tasks \
    --batch_size=8 \
    --eval.n_episodes=10 \
    --output_dir=outputs/train/act_pinky_omx
```

---

## 4. 단위 및 E2E 테스트 실행

모든 하드웨어 인터페이스, 레코더, API 엔드포인트는 자동화 테스트로 검증되어 있습니다:

```bash
cd teleop_omx_studio
./test_all.sh
```

* 총 11개 테스트 항목(하드웨어 Mock, 관절 한계 클램핑, 위치 수렴, 파라미터 튜닝, API 엔드포인트, Parquet 및 MP4 생성 무결성, Discard 무결성) 전원 통과(11 Passed).
