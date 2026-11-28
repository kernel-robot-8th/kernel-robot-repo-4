# v003 검증 — 2026-11-18

- 실제 프로젝트 .venvs/rl에 setup.sh --device cpu --no-shell 설치 완료.
- PyTorch 2.11.0+cpu, pip check 성공, pytest 13 passed.
- 기존 환경 테스트9개 + bashrc 백업/중복 방지, 공백 경로 이동, CUDA 요청 시 CPU 자동 대체 금지, 손상된 bashrc 블록 보호 검증.
- --skip-install --device cpu --bashrc /tmp/omx_rl_v003_test_bashrc로 실제 설치 후 검증 및 임시 셸 등록 완료. 사용자의 ~/.bashrc는 수정하지 않음.
- run.sh로 400-step CPU SAC 학습/저장 후 evaluate --device auto로 재로딩/독립 평가3회 완료(성공0/3). 소프트웨어 검증이며 실물 성능 검증 아님.
- GPU 하드웨어 설치·연산은 이 PC에서 실측하지 않음. setup --device cuda는 노트북에서 실제 CUDA tensor 연산을 수행하고 실패 시 중단하도록 구현.
- Python 의존성 목록은 evidence/cpu_requirements.resolved.txt. CUDA 설치 환경은 노트북의 .local/requirements.resolved.txt로 별도 기록.
- 브랜치명 reinforcement-learning은 git check-ref-format으로 검증. 원격 branch 생성/push는 미실행.
