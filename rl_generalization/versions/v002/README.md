# v002 — 신발 한 개 파지 SAC: 학습 파이프라인 초판

실행 가능한 **toy 전용** SAC 학습/평가 코드다. 실물 OMX 학습기 완성본이나 물리 simulator가 아니다. 정책은 fixed-orientation xyz 이동+그리퍼 4차원이며 관측은 oracle 좌표 기반 16차원이다. 관절 6차원 ACT와 직접 호환되지 않는다.

- [새 계획](docs/PLAN.md)
- [운영 번들 및 연결 조건](docs/DEPLOYMENT_CONTEXT.md)
- [환경](code/omx_rl/env.py), [학습](code/omx_rl/train.py), [평가](code/omx_rl/evaluate.py)
- [실물 어댑터 계약](code/omx_rl/hardware_contract.py): 인터페이스만 정의, 구현 없음
- references/: 지정 HF 커밋의 코드/설정, 실행하지 않음

## 독립 환경 실행

기존 LeRobot/YOLO 환경을 업그레이드하지 말고 별도 Python 환경에서 실행한다. 아래 명령의 cwd는 이 v002 폴더다.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=code .venv/bin/python -m pytest -q tests
PYTHONPATH=code .venv/bin/python -m omx_rl.train --config configs/toy_sac.json --out runs/toy_seed0 --seed 0
PYTHONPATH=code .venv/bin/python -m omx_rl.evaluate --run runs/toy_seed0 --out runs/eval_seed0 --episodes 30 --seed-start 10000
```

`--steps 400`은 업데이트·저장 확인용 짧은 smoke run이다. 학습 성공률을 보장하는 설정이 아니다. 출력 폴더가 이미 있으면 덮어쓰지 않고 중단한다. CPU로 실행하며 실제 로봇 연결 옵션은 없다.

학습 산출물: model.zip, replay.pkl, monitor.csv, run.json(유효 설정/의존성/seed), 주기별 checkpoint. 평가 산출물: episodes.csv, summary.json(성공수/분모/Wilson 구간/모델 해시). 평가 seed와 spread를 명시하고 평가 중 학습하지 않는다. checkpoint/replay는 신뢰하는 로컬 파일만 읽는다.

성공 분포는 toy의 근사 규칙에 대한 결과다. 실제 카메라/IK/접촉/신발 변형이 없어 실물 성능 및 sim-to-real을 주장할 수 없다. 모델은 실물에 전송하지 않는다.

## 지터 로그 진단

`python -m omx_rl.jitter episode.csv --out jitter.json`으로 한 episode를 분석한다(PYTHONPATH는 위와 동일). CSV 열은 `t_s,joint,act_target,sent_target,actual_position,chunk_id`이며 관절별 시간이 증가해야 한다. raw ACT가 정규화 공간이면 act_target은 먼저 로봇 단위로 역정규화해서 기록한다. 출력은 chunk 경계의 목표 변화, 명령 변화, 추종 오차와 시간 간격이다. 자동 원인 판정기가 아니며 실제 로그 수집기는 아직 연결하지 않았다.
