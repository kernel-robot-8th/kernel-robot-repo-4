# GitHub 공유

저장소: https://github.com/kernel-robot-8th/kernel-robot-repo-4
새 브랜치 제안: `reinforcement-learning` (Git 브랜치에는 공백 불가).
이번 작업에서는 업로드 명령을 준비했으며 push는 하지 않았다. 팀 저장소의 기본 브랜치를 새 clone하여 변경 범위를 RL 폴더 하나로 제한한다.

## 현재 PC에서 최초 업로드

아래 새 clone 폴더가 이미 있으면 다른 이름을 사용한다. 새 브랜치가 이미 있으면 기존 브랜치를 조회해 이어서 작업하며 force-push하지 않는다.

```bash
cd ~/dev_ws
git clone https://github.com/kernel-robot-8th/kernel-robot-repo-4.git kernel-robot-repo-4-rl
cd kernel-robot-repo-4-rl
git switch -c reinforcement-learning
python3 ../Project2/rl_generalization/tools/export_project.py --out "$PWD/rl_generalization"
git add -- rl_generalization
git diff --cached --stat
git commit -m "Add portable RL training scaffold and project handoff"
git push -u origin reinforcement-learning
```

export_project.py는 venv/cache/local 설치 기록/run 출력을 제외하고 코드·버전 자료만 복사한다. 원본 mp4/모델 weights는 프로젝트에 없으며 업로드하지 않는다. references에는 이전 HF 공개 코드/설정이 포함되고 evidence에는 문서용 영상 요약 이미지/검증 로그가 포함된다. 원격 기본 브랜치를 덮어쓰지 않는다. GitHub HTTPS 인증이 필요하면 gh auth login 또는 기존 credential manager/PAT 흐름을 사용하며 토큰을 명령이나 파일에 넣지 않는다.

## GPU 노트북에서

```bash
git clone --branch reinforcement-learning https://github.com/kernel-robot-8th/kernel-robot-repo-4.git
cd kernel-robot-repo-4/rl_generalization
bash setup.sh --device cuda
source shell/aliases.bash
rl
rltrain --config configs/toy_sac.json --out runs/gpu_smoke --steps 400 --device cuda
```

setup 대상은 Ubuntu/WSL2 Bash. 드라이버는 nvidia-smi로 먼저 확인한다. 자세한 내용은 ENVIRONMENT.md.

이후 두 PC 모두 이 Git checkout을 작업 기준으로 쓰고 시작 전 git pull --ff-only, 종료 후 필요한 파일만 commit/push한다. 초기 복사본 Project2/rl_generalization과 Git checkout을 동시에 수정하면 자동 동기화되지 않는다.

## Codex 맥락 공유

Git clone은 코드/문서만 복제한다. 로컬 IDE 대화가 동일 계정 로그인만으로 다른 머신에 반드시 나타난다고 가정하지 않는다. GPU 노트북에서 새 Codex 대화를 열고 다음을 요청한다:

> rl_generalization/HANDOFF.md, README.md, ENVIRONMENT.md를 읽고 이전 작업을 이어가자. 우선 GPU 설정과 테스트를 확인한 뒤 실물 어댑터의 미구현 항목을 점검해줘.

이 방식은 대화 원문 동기화가 아니라 검증 가능한 작업 맥락 인계다. 작업 끝에 HANDOFF.md를 갱신해 Git으로 공유한다. ~/.codex 전체 또는 인증 파일을 저장소에 넣지 않는다.

원문 스레드를 이어가는 별도 선택지는 지원되는 ChatGPT/Codex 앱의 원격 연결·연결된 프로젝트 간 thread handoff다. 실제 앱/OS 지원 여부를 확인해야 하며 VS Code 로컬 대화가 새 PC로 자동 복제되는 기능과 동일하지 않다. 원격 연결은 원래 호스트에서 실행할 수 있으므로 GPU 노트북에서 계산하는지 구분한다.

공식 확인 자료(2026-11-18):
- https://learn.chatgpt.com/docs/remote-connections
- https://learn.chatgpt.com/docs/changelog (2026-06-18 thread handoff)
- https://learn.chatgpt.com/docs/codex-sdk (local thread resume)
