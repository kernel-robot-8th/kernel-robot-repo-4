# GPU 노트북 자동 설정 — v003

지원: Linux 또는 Windows WSL2의 Bash, Python 3.11~3.13(3.12 권장), NVIDIA GPU 사용 시 정상 동작하는 드라이버. Python venv 이름은 `rl`이다. 드라이버/OS 패키지는 이 스크립트가 설치하지 않는다.

`requirements.txt`는 Python 패키지 목록이라 가상환경 생성과 Bash 등록은 할 수 없다. 아래 스크립트가 requirements 설치와 나머지 설정을 함께 수행한다. pip 설치에 숨겨진 shell hook을 넣지 않았다.

## GPU 노트북에서 한 번 실행

저장소 안 `rl_generalization` 디렉터리에서:

```bash
nvidia-smi
bash setup.sh --device cuda
source shell/aliases.bash
rl
cdrl
```

자동으로 수행하는 작업:
1. 현재 checkout 아래 `.venvs/rl` 생성(프롬프트 rl).
2. PyTorch 2.11.0 CUDA 12.8 wheel과 requirements 설치.
3. 실제 CUDA tensor 연산 확인. CUDA 요청이 실패하면 CPU로 조용히 바꾸지 않고 오류 종료.
4. `pip check` 및 테스트 실행.
5. `.local/setup.json`, `.local/requirements.resolved.txt` 기록.
6. `~/.bashrc`의 프로젝트 전용 블록 등록(기존 파일 백업, 재실행 중복 방지).

설치 스크립트는 자식 프로세스이므로 현재 터미널까지 활성화하지는 못한다. `source shell/aliases.bash`와 `rl`은 위와 같이 한 번 실행한다. 이후 새 Bash 터미널에서는 `rl`만 입력하면 된다.

CPU PC는 `bash setup.sh --device cpu`, 자동 감지는 `bash setup.sh --device auto`. auto는 nvidia-smi로 설치 wheel을 선택하고 torch 실행으로 검증한다. 구형 GPU/드라이버는 기본 cu128 wheel과 호환되지 않을 수 있다. 실패 시 PyTorch 공식 표에서 지원 조합을 확인하며, 필요한 경우 `--torch-index-url https://download.pytorch.org/whl/지원플랫폼`을 사용한다. 변경한 버전/환경은 다시 검증한다.

https://pytorch.org/get-started/previous-versions/

`venv` 생성 오류가 나면 Ubuntu에서 `sudo apt install python3-venv`가 필요할 수 있다. 다른 Python을 쓰려면 `RL_PYTHON=python3.12 bash setup.sh --device cuda`.

## 단축 명령

| 명령 | 동작 |
|---|---|
| rl | rl 환경 활성화 |
| cdrl | CURRENT가 가리키는 코드 버전으로 이동 |
| crootrl | 프로젝트 루트로 이동 |
| rltest | 현재 버전 테스트 |
| rltrain ... | 학습 실행 |
| rleval ... | 평가 실행 |
| deactivate | 환경 종료 |

경로가 바뀌어도 shell 파일은 위치를 다시 계산한다. checkout 자체를 다른 곳으로 옮겼다면 venv는 재사용하지 말고 새 경로에서 다시 만들고 setup을 실행한다. 새 노트북으로 `.venvs`를 복사하지 않는다. Bash 단축 명령은 경로 처리 때문에 alias 대신 동일 이름의 함수로 구현했다.

## 학습/평가

```bash
rltrain --config configs/toy_sac.json --out runs/toy_seed0 --seed 0 --device cuda
rleval --run runs/toy_seed0 --out runs/eval_seed0 --episodes 30 --device cuda
```

첫 확인용은 `--steps 400`. 코드 기본 device는 auto이다. 작은 toy MLP는 CPU가 더 빠를 수도 있다. GPU 사용은 실물 성능 향상을 의미하지 않는다. 현재 backend는 toy만 지원한다.

함수를 쓰지 않아도 프로젝트 루트에서 `bash run.sh train ...`, `bash run.sh test`로 실행할 수 있다.

VS Code는 Python: Select Interpreter에서 현재 checkout의 `.venvs/rl/bin/python`을 선택한다.

## 설치 재검증과 셸 설정 제외

- `bash setup.sh --device cuda --skip-install`: 이미 설치된 환경 검사만 수행, shell 등록은 수행.
- `--no-shell`: bashrc 등록 생략.
- `--bashrc PATH`: 테스트용/다른 Bash 설정 파일 지정.

모든 테스트/환경 검증이 성공한 다음에만 shell 등록을 한다. 등록 블록명은 `omx-rl environment`이다. 환경 제거 시 해당 블록을 삭제하면 된다. 이번 개발 PC 검증에서는 `--no-shell`로 사용자 bashrc를 변경하지 않았다.
