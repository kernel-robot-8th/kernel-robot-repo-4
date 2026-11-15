# omx_fleet — 관제용 OMX 팔 실행기

관제(`cobot_manipulation` 의 `arm_adapter_node`, `backend:=worker`)가 팔 1대에 일을 시킬 때 쓰는 실행기다.
사람이 버튼을 누르는 대신 어댑터가 stdin/stdout JSON 으로 "집어", "멈춰" 를 보내고 결과를 받는다.

- LeRobot **0.4.4** (`~/venv/il`, Python 3.10). 이 브랜치의 `omx_recoder`(0.6.1)와 venv 가 다르다.
- 모델은 0.4.4 로 학습한 ACT (관절 6 + top/wrist 카메라) 만 된다 (`omx_chain.check_inputs`).
- 2026-11-15 팔 1대(omx1) 기준. 실제 팔로는 아직 시험하지 않았다 (가짜 로봇·모델 로드만 확인).

## 왜 따로 있나

`inference.sh`(`lerobot-record`) 를 작업마다 새로 켜면 끝날 때와 다음 연결 때 lerobot 이 토크를 꺼서
**그 사이 팔이 떨어지고 잡은 물건을 놓친다**. 이 실행기는 켜질 때 한 번만 연결하고 모델을 미리 올린 뒤,
작업이 끝나도 토크를 유지한 채 다음 일을 기다린다.

## 파일

| 파일 | 내용 |
|---|---|
| `omx_fleet_worker.py` | 실행기. 대화 방식은 파일 맨 위 설명 |
| `omx_chain.py`, `success_judge.py` | `tool/omx-dashboard-v2` (a54637d) `omx_dashboard_v2/` 에서 **고치지 않고 복사**. 바꿀 일이 있으면 원본과 함께 바꾼다 |
| `fleet_arms.example.yaml` | 팔별 설정 예시 (카메라·캘리브레이션 이름·action → 모델) |
| `fleet_arms.yaml` | 이 PC 의 실제 설정. git 에서 제외 |

## 한 작업의 순서

1. 그 모델 번들의 `init_pose.json` 으로 천천히 이동
2. 정책 실행 (최대 `seconds`, 성공 판단이 있으면 더 일찍 끝남)
3. 안전 자세로 이동 — **그리퍼는 그대로** (잡은 물건을 놓지 않게)
4. 관절을 다시 읽어 결과 보고

| 결과 | 기준 |
|---|---|
| `success` | 번들 `success.json` 의 YOLO 판단이 성공을 낸 경우만 true. 판단 모델이 없으면 항상 false (`success_basis=none`) |
| `arm_safe` | 그리퍼를 뺀 모든 관절 오차가 `--safe-tol`(기본 3, 약 5°) 이하. `hold` 로 끝나면 false |

## 실행

보통은 어댑터가 띄운다. `cobot_manipulation/config/arm_adapter.yaml` 의 `worker_command` 예:

```text
/home/team11/venv/il/bin/python <이 폴더>/omx_fleet_worker.py --arms-file <이 폴더>/fleet_arms.yaml
```

직접 띄우면 **팔에 연결해 토크를 켠다** (사람이 옆에 있을 때만):

```bash
source ~/venv/il/bin/activate
cp fleet_arms.example.yaml fleet_arms.yaml   # 처음 한 번, 값 고치기
ARM_ID=omx1 ROBOT_PORT=/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_<시리얼>-if00 \
  python omx_fleet_worker.py --arms-file fleet_arms.yaml
# stdin 에 한 줄씩: {"cmd":"run","id":"t1","action":"pick"}  /  {"cmd":"hold"}  /  {"cmd":"quit"}
```

`omx_chain.py` 의 다른 옵션(`--device`, `--n-action-steps`, `--max-relative-target` 등)은 뒤에 붙이면 그대로 넘어간다.

## 주의

- 연결할 때 lerobot `configure()` 가 토크를 잠깐 껐다 켠다. 켜고 끌 때 팔은 쉬는 자세로 둔다.
- `quit`·오류로 끝나면 연결을 끊으며 토크가 꺼진다 → 팔이 내려앉을 수 있다.
- 초기 자세·안전 자세 이동(수 초) 중에는 `hold` 가 이동이 끝날 때 먹는다. 정책 실행 중에는 바로 멈춘다.
- 안전 자세 이동은 학습된 동작이 아니라 보간이다. 팔이 상자 안에 있으면 걸릴 수 있다.
- `ACT_ENSEMBLE_K` (k스텝 섞기) 를 쓰려면 `act_ensemble.py` 가 이 폴더의 상위 폴더에 있어야 한다 (`omx_chain.py` 가 그렇게 찾는다). 지금은 없다.
