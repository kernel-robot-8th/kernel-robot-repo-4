# 천장 비전 기반 적재·추락 판정 및 이상 감지 파트 안내서 (발표자·에이전트용)

본 문서는 발표자와 발표자 측 AI 에이전트가 **천장 카메라 비전 AI 추론·적재 완료/상자 추락 판정·이상 감지 차등 정지·3D 가상 데이터(Isaac Sim) 학습·픽셀→지도 좌표 변환** 파트의 발표 자료와 실제 소스 코드를 한 번에 대조하고 확인할 수 있도록 정리한 안내서입니다.

---

## 1. 발표 슬라이드 및 핵심 문서 위치

* **발표자용 4장 요약 슬라이드 (Google Slides)**: https://docs.google.com/presentation/d/18cPtkz6lB8LvsoUzYIcLx5_TAZmEDweVAlLVieSklQo/edit
  * **1장**: 주요 담당 이력 정리표 (발표자 친화형)
  * **2장**: 담당 파트 핵심 정리표 (문제 → 만든 것 → 시행착오 → 개선 결과)
  * **3장**: 발표자용 20초 요약 대본 표 (그대로 읽는 발표 대본)
  * **4장**: 3D 시뮬레이션(Isaac Sim) 학습 및 실제 천장 YOLO 적재·이상 인식 화면
* **패키지별 상세 기술 문서**
  * 이상 감지 및 적재 판정 패키지 설명서: `src/cobot_anomaly_monitor/README.md`
  * 천장 비전 YOLO 발행 앱 설명서: `scripts/vision/homelab_vision/README.md`
  * MQTT 근거 메시지 명세서: `scripts/vision/homelab_vision/MQTT_MESSAGE_SPEC.md`
  * 홈랩 적재 검증 및 재생 안내: `src/cobot_anomaly_monitor/docs/homelab_verify_load.md`

---

## 2. 발표 핵심 주제와 실제 소스 코드 매핑표

발표자 에이전트는 아래 경로의 파일과 함수를 열람하여 발표 내용의 실제 구현 근거를 즉시 확인할 수 있습니다.

| 발표 주제 | 저장소 내 핵심 소스 경로 | 핵심 클래스·함수 및 역할 | 검증 테스트 파일 |
|---|---|---|---|
| **① 천장 카메라 적재·추락 판정**<br>(`VERIFY_LOAD` 3조건 판정) | `src/cobot_anomaly_monitor/cobot_anomaly_monitor/load_complete.py`<br>`src/cobot_anomaly_monitor/cobot_anomaly_monitor/manual_adapter.py`<br>`src/cobot_anomaly_monitor/cobot_anomaly_monitor/mqtt_evidence.py` | - `LoadComplete.judge()`: ① 팔 작업 완료·후퇴(`_arm`), ② 적재 유지 및 정지(`_run`, `_still`), ③ 주변 바닥 낙하물 없음(`_drop`) 3중 조건 판정<br>- `LoadComplete._tray_checks()`: 짐칸 바닥 마커(`ZA=31, ZB=30, ZC=32`) 가림 여부로 빈 로봇 오통과 차단<br>- `LoadComplete._filter_drop_boxes()`: 짐칸 내 `box_on_tray`와 겹치는 `box_on_floor` 오탐 제외<br>- `ManualAdapter`: `off / shadow / enforce` 모드별 `/fleet/work_result` 응답 제어 | `src/cobot_anomaly_monitor/test/test_load_complete.py`<br>`src/cobot_anomaly_monitor/test/test_vision_judge.py`<br>`src/cobot_anomaly_monitor/test/test_judge_node.py` |
| **② 사고 위험도별 맞춤 정지 제어** | `src/cobot_anomaly_monitor/cobot_anomaly_monitor/judgment.py`<br>`src/cobot_anomaly_monitor/cobot_anomaly_monitor/monitor_core.py`<br>`src/cobot_anomaly_monitor/cobot_anomaly_monitor/monitor_store.py` | - `judgment.py`: 이상 유형별 판정표 정본(`LOAD_FAIL_PERCHED`, `LOAD_FAIL_DROP`, `LANE_OBSTACLE`, `RUN_OVER_COLLISION`) 및 정지 범위(`ROBOT` vs `ALL`) 결정<br>- `MonitorCore.on_vision_event()`: 단일 로봇 일시정지(`pause`), 전체 일시정지(`pause`), 전체 비상정지(`estop`) 차등 요청 및 300초 재감지 묶음 처리<br>- `MonitorCore.on_tasks()`: 관제 스냅샷 정지 확인(`hold_seen`) 후 현장 복구 시 사건 자동 종료(`RESOLVED`) | `src/cobot_anomaly_monitor/test/test_judgment.py`<br>`src/cobot_anomaly_monitor/test/test_monitor_core.py`<br>`src/cobot_anomaly_monitor/test/test_scenario_cctv.py` |
| **③ 천장 카메라 YOLO 추론 및 3D 가상 데이터(Isaac Sim) 검증** | `scripts/vision/homelab_vision/app/main.py`<br>`scripts/vision/homelab_vision/app/detector.py`<br>`scripts/vision/homelab_vision/app/model_slots.py`<br>`scripts/vision/homelab_vision/zone/marker_zone.py`<br>`scripts/vision/homelab_vision/verify/golden_check.py` | - `Detector`: 핑키 적재 모델(`pinky_v2_final.pt`), 상자 이상 모델(`kneg_d_final.pt`), 선택 팔 모델(`arm_v1.pt`) `imgsz=960` GPU 10 FPS 추론<br>- `main.py`: 코너 마커(`40, 41, 42, 43`) 구역 판별 및 트레이 마커(`30, 31, 32`) 검출 결과를 MQTT(`relay/evidence/zones`, `boxes`)로 실시간 발행<br>- `golden_check.py`: 합성+실사 골든셋 기준 `IoU >= 0.98`, 오차 0건 무결성 검증 | `scripts/vision/homelab_vision/verify/test_config.py`<br>`scripts/vision/homelab_vision/verify/test_detector_slots.py`<br>`scripts/vision/homelab_vision/verify/test_model_slots.py`<br>`scripts/vision/homelab_vision/zone/test_marker_zone.py` |
| **④ 카메라 픽셀 → 지도 좌표 변환** | `src/cobot_anomaly_monitor/cobot_anomaly_monitor/pixel_map.py`<br>`src/cobot_anomaly_monitor/cobot_anomaly_monitor/pixel_event_node.py` | - `pixel_map.py`: 카메라 렌즈 왜곡 보정, 고정 호모그래피, 물체 중심 높이(`height_m`) 보정을 거쳐 원본 픽셀 bbox를 로봇 주행 지도(`cobot_map_v9`) 좌표로 변환<br>- 마커 유실·보정 불일치·유효 범위 이탈 시 `map_x, map_y = null`(`NO_POSITION`)을 반환해 오작동 정지 차단 | `src/cobot_anomaly_monitor/test/test_pixel_map.py` |

---

## 3.主要 담당 이력 정리표 (발표 슬라이드 1장)

| 구분 | 슬라이드 표시 문구 (직관적 요약) | 기술 상세 내용 (질의응답용) | 발표자용 쉬운 풀이 (발표 대본) |
|---|---|---|---|
| **1. 천장 카메라 AI 인식 및 위치 파악** | **천장 CCTV로 로봇과 상자 위치를 실시간 파악** | - 천장 카메라 YOLO 추론 컨테이너(`homelab-vision`, GPU 10 FPS) 구축<br>- 경기장 네 모서리 마커(`40~43`)로 화면 왜곡을 펴고 상하차 구역(`ZA, ZB, ZC`) 판별<br>- 카메라 픽셀 좌표를 로봇 지도 좌표(`cobot_map_v9`)로 변환(`pixel_map.py`) | "천장에 달린 카메라 한 대로 경기장 전체를 내려다봅니다. 네 모서리 마커를 기준으로 로봇이 어느 구역에 있는지, 상자가 어디에 떨어졌는지 실제 지도 좌표로 실시간 계산합니다." |
| **2. 적재 성공·상자 추락 판정 (핵심)** | **로봇팔 신호만 믿지 않고 카메라로 적재·추락 최종 확인** | - `VERIFY_LOAD` 3중 조건 판정기(`load_complete.py`) 설계 및 현장 배포<br>- ① 로봇팔 작업 완료 및 후퇴(`arm_safe`) + ② 적재 상태 연속 유지 및 정지 + ③ 주변 바닥 낙하물 없음 동시 만족 시에만 출발 승인<br>- 트레이 마커(`30~32`) 가림 여부로 빈 로봇 오통과 차단 | "현장에서 로봇팔이 상자를 떨어뜨려도 팔 스스로는 성공이라고 보고하는 문제가 있었습니다. 그래서 카메라로 상자가 짐칸에 올라타 마커를 가렸는지, 바닥에 떨어진 상자는 없는지 끝까지 확인한 뒤에야 로봇을 출발시킵니다." |
| **3. 사고 유형별 맞춤 정지 제어** | **사고 위험도에 따라 해당 로봇만 멈추거나 전체 비상정지** | - 이상 감지 패키지(`cobot_anomaly_monitor`) 정지 범위(`ROBOT` vs `ALL`) 차등 설계<br>- 상자 걸림·단일 적재 실패는 해당 로봇만 일시정지(`ROBOT pause`)<br>- 주행 통로 낙하물은 전체 일시정지(`ALL pause`), 상자 충돌은 전체 비상정지(`ALL estop`) 후 복구 시 자동 해제 | "문제가 생겼다고 무조건 다 멈추면 물류가 마비됩니다. 상자가 짐칸에 살짝 걸린 정도면 그 로봇만 멈추고, 주행 통로에 상자가 떨어지거나 로봇이 상자를 치는 큰 사고일 때만 전체 로봇을 즉시 멈춥니다." |
| **4. 3D 가상 데이터로 AI 모델 학습** | **실제로 찍기 힘든 낙하·사고 장면을 3D 가상환경으로 학습** | - Isaac Sim으로 실제 경기장·조명·마커를 재현한 합성 데이터셋 구축<br>- 실제 촬영 데이터와 가상 데이터를 결합해 YOLO 모델 학습 및 현장 GPU 정합성 검증(추론 속도 장당 `12~14ms`) | "상자가 떨어지거나 로봇이 상자를 밟는 사고는 현장에서 수천 번 찍기 어렵습니다. 그래서 3D 가상 경기장을 만들어 다양한 각도와 조명에서 사고 장면을 대량으로 찍어내 AI를 학습시켰습니다." |
| **5. 현장 장비 배포 및 자동 시험** | **430개 이상의 자동 시험을 통과한 코드만 현장에 배포** | - MQTT(`Team11` 비전 서버) → ROS 2(`8-OMEN` 관제 서버) `0.06초` 실시간 근거 중계<br>- Jenkins 기반 비전 모델 배포·롤백 파이프라인 및 430+ `pytest` 자동 검증 체계 구축 | "카메라 컴퓨터에서 분석한 결과를 관제 컴퓨터로 0.06초 만에 전달합니다. 또 현장에서 오작동이 나지 않도록 430개가 넘는 자동 시험을 통과한 코드만 현장 장비에 올라가게 했습니다." |

---

## 4. 담당 파트 핵심 정리표: 문제 → 만든 것 → 시행착오 → 개선 결과 (발표 슬라이드 2장)

| 주제 | 1. 문제 (왜 필요했나?) | 2. 만든 것 (무엇을 만들었나?) | 3. 만들던 때의 시행착오 (실제 겪은 난관과 해결) | 4. 개선 결과 (어떻게 좋아졌나?) |
|---|---|---|---|---|
| **① 천장 카메라 적재·추락 판정**<br>*(핵심)* | 로봇팔이 상자를 떨어뜨려도 팔 스스로는 "작업 성공"으로 보고해, 빈 로봇이 출발하거나 바닥 상자를 밟는 문제가 발생 | 천장 카메라가 위에서<br>1) 팔 후퇴 완료<br>2) 짐칸 상자 적재 유지<br>3) 주변 바닥 상자 없음<br>3가지를 모두 확인한 뒤에만 출발 신호를 주는 판정기 구현 | - **빈 로봇 착각:** 위에서 내려다보니 빈 짐칸도 실린 것으로 착각 → 짐칸 바닥에 마커(`30~32`)를 붙여 마커가 가려질 때만 적재로 인정<br>- **바닥 상자 겹침:** 실린 상자를 바닥 상자로 중복 검출 → 로봇 테두리 안에서 짐칸 상자와 겹치는 것은 추락에서 제외 | - 팔이 상자를 떨어뜨리고 성공이라 거짓 보고해도 카메라가 추락을 잡아 출발 차단<br>- 빈 로봇은 마커가 보여 적재 성공 오통과 `99% 이상` 차단 |
| **② 사고 위험도별 맞춤 정지 제어** | 상자가 살짝 걸리든 통로에 떨어지든 구분 없이 멈추거나, 사람이 복구해도 사건 기록이 안 닫히는 문제가 발생 | 사고 위험도를 분류해<br>- 상자 걸림·단일 실패: 그 로봇만 일시정지<br>- 통로 낙하물: 전체 일시정지<br>- 상자 충돌: 전체 비상정지<br>로 차등 제어하는 안전장치 구현 | - **명령 충돌:** 감시 노드가 로봇에 직접 정지 명령을 보내면 관제와 충돌 → 관제에 정지 요청만 보내도록 일원화<br>- **재감지 전체 마비:** 멈춘 로봇 옆 바닥 상자를 다시 보고 전체를 멈춤 → 5분간 해당 로봇 사건으로 묶어 타 로봇 주행 유지 | - 한 대만 멈춰도 되는 상황에서 전체 물류가 마비되는 문제 해결<br>- 현장에서 상자를 치우고 정지를 풀면 사건 기록도 자동 완료 처리 |
| **③ 3D 가상환경 (Isaac Sim) 사고 데이터 학습** | AI에게 상자 추락·걸침·깔림 모습을 가르쳐야 하나, 실제 현장에서 수천 번 사고를 내며 촬영할 수 없음 | 3D 가상환경(Isaac Sim)에 실제 경기장·조명·마커를 그대로 만들고, 사고 장면을 대량으로 자동 촬영해 AI 모델 학습 | - **가상·실물 색감 차이:** 가상 사진만 학습하니 실제 카메라에서 인식 흔들림 → 실제 천장 사진과 빈 경기장 사진을 섞어 재학습<br>- **작은 마커 깨짐:** 화면 축소 시 마커 미인식 → 마커는 원본 화질로 읽고 AI 추론 해상도를 `960`으로 상향 | - 현장에서 찍기 힘든 희귀 사고 장면까지 안정적으로 인식<br>- 현장 GPU에서 초당 10장(장당 `0.013초`), 전달 지연 `0.06초` 실시간 동작 |
| **④ 카메라 픽셀 → 지도 좌표 변환** | 카메라는 화면 몇 번째 점(픽셀)인지만 알아서, 실제 로봇 지도 어디에 떨어졌는지·어느 로봇 근처인지 알 수 없음 | 경기장 네 모서리 마커(`40~43`)를 기준으로 카메라 픽셀 좌표를 실제 로봇 주행 지도 좌표(미터 단위)로 바꾸는 변환기 구현 | - **가장자리 위치 틀어짐:** 볼록한 렌즈 왜곡과 상자 높이 때문에 구석 위치가 밀림 → 렌즈 왜곡을 먼저 펴고 물체 높이를 반영해 바닥 중심 계산<br>- **마커 가림 시 오작동:** 마커가 안 보일 때 억지로 좌표를 찍으면 엉뚱한 로봇 정지 → 불확실 시 `null` 처리 | - 상자가 떨어진 위치를 로봇 지도 좌표로 정확히 찍어 어느 구역·어느 로봇 사고인지 즉시 판별<br>- 마커 가림 시 오작동 원천 차단 |

---

## 5. 발표자용 20초 요약 대본 표 (발표 슬라이드 3장)

| 발표 순서 (주제) | 핵심 한 줄 메시지 | 발표자가 그대로 읽는 20초 대본 |
|---|---|---|
| **1번 주제 (20초)**<br>천장 카메라 적재·추락 판정 | 로봇팔 보고만 믿지 않고 카메라로 마커 가림과 낙하물을 최종 확인 | "저희가 현장에서 겪은 가장 큰 문제는 로봇팔이 상자를 떨어뜨려도 팔 스스로는 '성공'이라고 보고한다는 점이었습니다. 그래서 천장 카메라로 팔이 빠졌는지, 상자가 실렸는지, 바닥에 떨어진 건 없는지 3가지를 다시 확인하게 만들었습니다. 처음엔 위에서 내려다보니 빈 로봇도 상자가 실린 걸로 착각했는데, 짐칸 바닥에 마커를 붙여서 상자가 그 마커를 가렸을 때만 진짜 실린 것으로 판정하게 해서 해결했습니다." |
| **2번 주제 (20초)**<br>사고 위험도별 맞춤 정지 제어 | 작은 문제는 해당 로봇만, 통로 낙하물은 전체 로봇을 정지 | "두 번째는 사고가 났을 때 똑똑하게 멈추는 기능입니다. 처음에는 상자 하나만 떨어져도 남은 상자를 계속 장애물로 인식해서 전체 로봇이 다 멈춰버리는 시행착오가 있었습니다. 그래서 해당 로봇 작업 중에 생긴 문제는 그 로봇만 일시정지시키고, 주행 통로에 장애물이 떨어지거나 로봇이 상자를 밟는 큰 사고일 때만 전체를 멈추도록 개선해 물류 전체가 멈추는 일을 막았습니다." |
| **3번 주제 (20초)**<br>3D 가상 데이터 (Isaac Sim) 학습 | 실제로 찍기 힘든 사고 장면을 3D 가상환경과 실제 사진으로 학습 | "세 번째는 AI 학습입니다. 상자가 추락하거나 로봇에 치이는 사고를 실제 현장에서 수천 번씩 일부러 낼 수가 없어서, 3D 가상 경기장(Isaac Sim)을 만들어 사고 장면을 대량으로 만들어냈습니다. 처음엔 가상 사진만 썼더니 실제 현장에서 인식이 흔들렸지만, 실제 현장 사진과 섞어 학습시키고 해상도를 높여서 지금은 1초에 10장씩 실시간으로 정확하게 잡아냅니다." |
| **4번 주제 (20초)**<br>카메라 픽셀 → 지도 좌표 변환 | 렌즈 왜곡과 상자 높이를 보정해 실제 로봇 지도 위치로 정확히 변환 | "마지막으로 카메라 화면 속 위치를 실제 로봇 지도 위치로 바꾸는 작업입니다. 처음엔 카메라 렌즈가 볼록해서 화면 구석으로 갈수록 위치가 틀어지는 문제가 있었는데, 렌즈 왜곡을 펴고 상자 높이까지 계산에 넣어서 해결했습니다. 덕분에 상자가 어디에 떨어졌는지 지도 위에서 정확히 알고 바로 대응할 수 있습니다." |

---

## 6. 에이전트용 빠른 코드·테스트 검증 명령어

발표자 에이전트가 로컬에서 판정 규칙과 비전 설정을 즉시 검증할 때 아래 명령어를 실행합니다.

```bash
# 1) 천장 비전 설정·슬롯·구역 판별 단위 시험 (ROS 불필요)
python3 scripts/vision/homelab_vision/verify/test_config.py --app-dir scripts/vision/homelab_vision/app
python3 scripts/vision/homelab_vision/verify/test_detector_slots.py --app-dir scripts/vision/homelab_vision/app
python3 scripts/vision/homelab_vision/verify/test_model_slots.py --app-dir scripts/vision/homelab_vision/app
python3 scripts/vision/homelab_vision/zone/test_marker_zone.py
python3 scripts/vision/homelab_vision/zone/test_zone_evidence_msg.py

# 2) 적재 완료 3조건 판정·이상 감지·좌표 변환 단위 시험 (ROS 없는 순수 파이썬 시험)
PYTHONPATH=src/cobot_anomaly_monitor:src/cobot_navigation/cobot_amcl_corrector python3 -m pytest \
  src/cobot_anomaly_monitor/test/test_load_complete.py \
  src/cobot_anomaly_monitor/test/test_judgment.py \
  src/cobot_anomaly_monitor/test/test_pixel_map.py -q
```
