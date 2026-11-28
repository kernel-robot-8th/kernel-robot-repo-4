# v003 — 이동 가능한 RL 개발 환경

정책/환경은 v002와 동일한 toy 전용이다. 실제 카메라/IK/로봇 제어는 구현되지 않았다.

## 변경 사항

- train/evaluate의 --device auto/cpu/cuda 지원. CUDA 지정 실패 시 중단.
- 프로젝트 루트 setup.sh + requirements.txt로 rl 가상환경/패키지/셸 명령 자동 설정.
- 프로젝트 루트 run.sh와 CURRENT로 PYTHONPATH를 자동 구성.
- 이전 9개 테스트와 설치/경로/장치 테스트 추가.

[설치](../../ENVIRONMENT.md), [GitHub](../../GITHUB.md), [인수인계](../../HANDOFF.md), [검증](docs/VALIDATION.md).

```bash
# 프로젝트 루트에서
bash run.sh test
bash run.sh train --config configs/toy_sac.json --out runs/smoke --steps 400 --device auto
bash run.sh evaluate --run runs/smoke --out runs/eval --episodes 3 --device auto
```

출력 경로는 이 v003 디렉터리를 기준으로 해석한다. 기존 출력은 덮어쓰지 않는다. GPU에서 작은 MLP가 CPU보다 빠르다는 보장은 없다.

역사 버전과 실행 코드는 versions에 저장하고 공용 설치/셸/인수인계 파일은 Git으로 관리한다. manifest의 external_files는 이번 시점의 공용 파일 해시를 기록한다.
