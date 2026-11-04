# Isaac Sim / Gazebo 1:1 Digital Twin Map5 Textures

팀11 `team11_map5` 규격 (가로 2.36m x 세로 1.28m, 외벽 높이 10cm) 실측 기반 텍스처 에셋입니다.

## 파일 구성
- `map5_arena_texture.png`: 2360 x 1280 (1mm/pixel) PBR 바닥 Albedo 텍스처. 사람/로봇/삼각대 인페인팅 및 차선 테이프 연결 복원.
- `map5_ground_truth_ortho.png`: 2360 x 1280 (1mm/pixel) 최신 실측 사진 기반 기준 마커(ArUco 40, 41, 42, 43) 1:1 직교 투영 원본.
- `map5_texture_manifest.json`: ROS 2 `/map` 좌표계 및 Isaac Sim USD 규격 매핑 메타데이터.
- `map5_texture_preview.jpg`: 빠른 열람용 경량 프리뷰.

## 좌표계 정합
- 아레나 크기: 2.36m x 1.28m
- 기준 마커 위치 (간격 2.0m x 1.0m):
  - ID 40 (좌상): `(-1.00, -0.50)` -> pixel `(180, 140)`
  - ID 41 (우상): `(+1.00, -0.50)` -> pixel `(2180, 140)`
  - ID 42 (우하): `(+1.00, +0.50)` -> pixel `(2180, 1140)`
  - ID 43 (좌하): `(-1.00, +0.50)` -> pixel `(180, 1140)`

## PRD_3 신발 매장 장면 — 목적과 현재 상태 (2026-10-27 갱신)

`CHECK_RECEIPT.txt`와 `check_map5_texture_assets.py`는 **위 map5 텍스처/ArUco 검사**다. 파일이 같은 폴더에 있어도 PRD_3 상자 배송·파지·카메라 인식을 확인한 영수증이 아니다.

### 목적 (목표 아키텍처)

목표 아키텍처에서 낙하·충돌 결과의 원천은 MuJoCo 다. 이 장면도 PhysX 스텝은 돌지만 그 결과를 물리 증거로 쓰지 않는다. `shoe_store_scene.py` 의 목표 역할은 **MuJoCo 가 물리 시뮬레이션으로 찾은 이상상황(바닥 낙하·림 걸림) 좌표·자세를 주입받아, 사람 확인용 비전 AI 학습 데이터셋(RGB·BBox·Segmentation)을 고화질로 대량 합성(SDG, Synthetic Data Generation)하는 Omniverse 디지털 트윈 장면**이다. 전체 파이프라인과 1단계 산출물은 [U4 보고서 §6](../../../docs/shoe_store/U4-DROP-AND-CAMERA-REVALIDATION.md)에 있다.

실행 자리는 DEV 서버 GPU0 이다. `robot_jobs` 분리 설계 v1.1 §4.3(2026-09-09 사용자 결정, 이 레포 밖 설계 문서)이 GPU0 을 Isaac, GPU1 을 영상분석 AI 서빙으로 배정했고(2026-10-14 갱신으로 GPU1 에 OMX 학습·렌더 추가), SDG 를 GPU0 에서 돌리는 것은 이 배정과 맞는다. 다만 GPU0 전용 여부는 확정되지 않았고, 2026-10-14 실측에서 임베딩 서비스가 GPU0 에 같이 있다.

### 현재 구현 상태 (2026-10-27, `544b3da` 이후 코드 기준)

목적은 위와 같지만 이 파일에는 SDG 가 구현되지 않았다. **SDG 구현 기반은 이 레포 밖의 `isaac_sdg_v0`(Replicator rgb + bbox_2d_tight, 로컬 구축·DEV 미실행)이다**(사용자 결정 2026-10-27). 코드 기준으로 다음과 같다.

| 항목 | 상태 |
| :--- | :--- |
| headless 기동(`SimulationApp`) · Cobot_map_v6 4개 블록 · 카메라 prim 6개(관제 3 + 팔 상부 3) | 코드 있음. 카메라는 위치(translate)만 넣고 `rot` 값은 적용하지 않는다 → USD 카메라 기본 방향(로컬 −Z)이라 6대 모두 수직 하향이다. 'CAM-2/3 하향 65°'는 실제로 적용되지 않는다 |
| 장면 실행 기록 | 2026-10-17 13:03–13:09 UTC DEV 감사 실행(보고 정리 2026-10-18 KST)에서 이 파일의 장면 생성부를 관측 하네스로 감싸 돌린 기록이 있다. 지도를 읽지 않는 수작업 2.4 m 평판 형상 그대로였고, 천장 외 카메라 8대는 거의 단색이었다(레포 밖 기록). 이 장면으로 만든 학습 데이터는 없다 |
| 실행 명령 | docstring 의 `docker run … --gpus all` 은 GPU0 을 고정하지 않는다 |
| MuJoCo 이벤트 주입 | `--events-json` 은 파일을 읽고 개수만 출력한다(사용 0건). 실제 이벤트 파일은 최상위가 dict 라 'Loaded 2' 가 찍힌다. 좌표계 변환·yaw 처리 없음. r3 이벤트는 다른 배치(floor1021_r3)에서 나왔고, v6 용 이벤트는 `simulation/shoe_store/cobot_v6/drop/` 에 새로 만들었다 |
| Replicator 출력 (RGB · BBox · Segmentation writer) | 없음. `--output-dir` 은 선언만 있고 쓰이지 않는다 |
| 관제 카메라 3대 | 천장 CAM-1 [1.25, 1.20, 2.15] 만 다른 기록과 같다. CAM-2(상차 웹캠 [1.45, 1.65, 0.60])·CAM-3(하차 노트3 Neo [0.95, 1.72, 0.60])는 이 코드에만 있는 값이라 현장 거치 실측으로 확정해야 한다. 코드 렌즈 값(aperture 20.955 mm · focal 18.8 mm)의 HFOV 는 약 58° 로 주석의 65° 와 다르다. 좌표는 sim 프레임(X_v6 = X_sim − 1.400, Y_v6 = Y_sim − 1.596) |
| 아레나·상자 형상 | 2.50 × 2.40 m, Cobot_map_v6 4개 블록, 받침대 250×200×85, 랙 230×150×200(꽉 찬 블록), 상자 60×60×43 mm 40 g — 상자는 2026-10-27 정정으로 랙 상면(Z 0.200 m) 위에서 생성된다(이전에는 랙 내부 Z 0.095). Pinky 는 0.22×0.16×0.14 큐보이드(CAD 외곽 118×110×148 mm 아님), 라이다 상단 트레이는 모델에 없다. 런타임 실행 기록 없음 |
| Pinky/OMX CAD·URDF 형상 | 참조하지 않는 대체 형상. [모델·증거 대조](../../../docs/shoe_store/MODEL_AND_EVIDENCE_REVIEW.md)와 [새 모델 계약](../../../simulation/shoe_store/README.md)을 따른다 |

따라서 이 장면의 기존 실행 결과를 새 물리 폐루프 결과나 합성 학습 데이터로 표시하지 않는다. SDG 를 구현하려면 위의 이벤트 주입 · Replicator 출력 · 확정 카메라 배치 · 현재 맵/상자/CAD 형상 반영이 먼저 필요하다.
