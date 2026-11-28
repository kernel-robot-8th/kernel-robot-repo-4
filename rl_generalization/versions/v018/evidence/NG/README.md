# NG simulation recordings

이 폴더는 시뮬레이터의 시행착오를 영상으로 남기는 곳이다. 영상의 `NG / SIMULATION ONLY` 표시는 실제 로봇 성공 영상이 아니라는 뜻이다.

현재 기록 대상은 다음 두 가지다.

- 초기 접촉 모델에서 신발이 흔들리거나 튀는 현상
- 기록 명령을 그대로 재생할 때 손가락 프록시가 신발을 관통하면서 들어 올려지는 가짜 성공 현상

먼저 GPU PC에서 프로젝트 위치를 확인한다. 아래 `cd`가 실패하면 이후 명령을 실행하지 말고, 실제 경로를 사용해야 한다.

```bash
find ~ -path '*/rl_generalization/versions/v018/code/record_ng.py' -print
```

12초 NG 영상은 GPU PC에서 다음처럼 실행한다.

```bash
set -e
cd ~/rl_ws/rl_generalization
mkdir -p versions/v018/evidence/NG
MUJOCO_GL=egl .venvs/omx_sim/bin/python versions/v018/code/record_ng.py \
  --scene .local/finger_proxy_v018/scene.xml \
  --seconds 12 \
  --shift-z -0.018 \
  --out versions/v018/evidence/NG/proxy_penetration_$(date +%Y%m%d_%H%M%S)
```

노트북을 끄기 전에는 원격 GPU에서 `tmux` 세션으로 실행한다.

```bash
sudo apt update && sudo apt install -y tmux   # 한 번만
tmux new -s ng_record
# 위 명령 실행
# Ctrl-b, d 로 분리
```

완료 확인:

```bash
find versions/v018/evidence/NG -name ng_replay.mp4 -printf '%TY-%Tm-%Td %TH:%TM %p %k KB\n'
cat versions/v018/evidence/NG/proxy_penetration_*/summary.json
```

`max_finger_shoe_penetration_m`가 `0.001`보다 크면 grasp 성공으로 사용하지 않는다. 영상과 `summary.json`을 함께 발표 증거로 보관한다.
