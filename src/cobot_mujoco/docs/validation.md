# OMX MuJoCo 검증·학습 실험

사용자 요청: 저장된 실제 카메라 장면을 재현하고, 여러 학습 방법의 과적합·데이터 부족을 비교하며, 최대 12시간 실행 후 HTML 보고서를 Git에 저장한다.

## 현재 범위와 검증 상태

- 기준 저장소: `kernel-robot-8th/kernel-robot-repo-4`. 최신 `submaster`에서 `feature/manipulation-mujoco-validation`을 만들었다. main·submaster에는 병합하지 않는다.
- 패키지: `src/cobot_mujoco` (`ament_python`). ROS 노드를 만들지 않으며 다른 기능 패키지·msg/srv/action을 바꾸지 않는다. MuJoCo 데이터만 제어하며 로봇 포트·카메라 장치·ROS 통신을 열지 않는다.
- 화면 공유 도구에 연결된 화면이 없어서, **데이터셋의 저장된 top/wrist 영상**을 직접 확인했다. 초기 세션은 흰 작업대의 쌓인 상자, 왼쪽 흰 원형 로봇이다. 나중 세션에는 한 개 상자와 바뀐 초기 자세가 관찰된다.
- 실제 장면 치수·카메라 보정값이 제공되지 않았다. `config/scene.json`의 추정값과 `validation_gate`를 확인한다. 제조사 기하 일치만으로 현장 검증 환경이 완성되었다고 판단하지 않는다.
- 원본 제조사 위치 제어기와 수동 마찰은 근사치다. 시연 재생의 위치 오차·물체 접촉·힘 제한을 기록한다. 초기 재생에서 집기 실패가 관찰되어 **물리 성공 판정은 잠정 진단값**이다.
- 추정 치수를 성공률에 맞추어 선택하지 않는다. 장면·접촉 보정 시도는 학습 녹화에만 사용하며 별도 근거를 남긴다. 테스트 지표로 장면이나 정책을 조정하지 않는다.

## 데이터·모델 출처

| 항목 | 위치 / 고정 리비전 |
|---|---|
| 데이터 | [Sungah/omx_1024_test_jihyeok_success](https://huggingface.co/datasets/Sungah/omx_1024_test_jihyeok_success), `3502381b21fe15eae125dc36570779737ca85a71`, Apache-2.0 |
| 본인 작업 사본 | [toryjihyeok/omx_1024_test_jihyeok_success](https://huggingface.co/datasets/toryjihyeok/omx_1024_test_jihyeok_success), 비공개, 원본 출처 보존 |
| 로봇 | [ROBOTIS-GIT/open_manipulator](https://github.com/ROBOTIS-GIT/open_manipulator/tree/ee9a720bcc45acda9c0df8fe689b1182844307db/open_manipulator_description/mujoco/omx), `ee9a720bcc45acda9c0df8fe689b1182844307db`, Apache-2.0 |
| 학습 | 실제 LeRobot 0.6.1 ACT + 상태 MLP BC + 두 카메라 CNN BC. 기존 현장 모델은 모든 학습 녹화 노출 여부가 불명확하여 비교 학습에 재사용하지 않는다. ACT 이미지 인코더의 ImageNet 사전학습만 사용한다. |

원본은 15개 녹화, 14,292프레임, 30fps, 640×480 두 영상이다. 캐시에 128×96으로 디코딩하므로 기존 640×480 모델과 구조·입력 조건이 다른 신규 실험이다. 다운샘플링의 한계도 비교 시 고려한다. 데이터·메시·가중치는 Git 밖에 저장하며 SHA256과 리비전으로 재현한다.

## 설치

새 환경에서는 CUDA 버전에 맞는 PyTorch를 설치하고 다음을 실행한다. ffmpeg는 설치되어 있어야 한다.

```bash
python3 -m venv --system-site-packages ~/venv/omx_mujoco
source ~/venv/omx_mujoco/bin/activate
python -m pip install -r src/cobot_mujoco/requirements.txt
python -m pip install --no-deps -e src/cobot_mujoco
export MUJOCO_GL=egl
```

이번 PC는 기존 `~/venv/lerobot061`의 검증된 CUDA PyTorch·LeRobot을 읽기 전용 공유하는 `.pth` 파일을 전용 venv에 두었다. MuJoCo·SciPy·pytest·ruff는 새 venv에만 설치했다. 재현할 때는 위 전체 설치 방법을 사용할 수 있다. 실제 해석기 경로와 패키지 버전은 보고서 폴더의 `environment.json`에 남긴다. GPU는 RTX 5080 Laptop 16GB이다.

```bash
hf download Sungah/omx_1024_test_jihyeok_success \
  --repo-type dataset --revision 3502381b21fe15eae125dc36570779737ca85a71 \
  --local-dir ~/omx_sim_data/omx_1024_test_jihyeok_success
cobot-mujoco fetch-robot --assets ~/omx_sim_assets/robotis
cobot-mujoco prepare --source ~/omx_sim_data/omx_1024_test_jihyeok_success \
  --cache ~/omx_sim_data/cache_v1
cobot-mujoco render --assets ~/omx_sim_assets/robotis --output /tmp/omx_scene
```

GUI가 있는 로컬 터미널에서 실제 물리 장면을 열려면:

```bash
MUJOCO_GL=glfw cobot-mujoco view --assets ~/omx_sim_assets/robotis
```

설치된 console script가 PATH에 없으면 `PYTHONPATH=src/cobot_mujoco python -m cobot_mujoco.cli ...`로 같은 명령을 실행할 수 있다. scene·sweep는 소스의 `config/`에 있다. 이 도구에는 실제 로봇 구동 기능이 없다.

## 분리·학습·선택

1. 학습: 녹화 0–7. 검증: 8–9. 잠금 테스트: 나중 수집한 10–14. 프레임 무작위 분리는 사용하지 않는다. 원본 녹화 전체 해시 중복 검사와 미래 action chunk의 에피소드 경계 패딩 검사를 수행한다.
2. 2·4·8개 데이터 비교는 시드별 학습 녹화 순서를 무작위로 정한 **같은 중첩 부분집합**으로 수행한다. 상태·행동 평균/표준편차는 해당 부분집합만으로 계산한다. 이미지에는 고정 ImageNet 통계를 사용한다.
3. 상태 BC, 시각 CNN BC, ACT를 비교한다. ACT는 action chunk 16/32/64, dropout, weight decay, 학습률, 밝기·대비·이동 증강, 상태 노이즈를 바꾼다. 시드는 17·42·97. 고정 계획은 `config/sweep.json`에 있으며 총 36개 실험이다.
4. 각 실험은 최대 1,500초, 최대 30,000스텝이다. 250스텝마다 학습·검증 녹화별 MAE를 기록하고, 검증 개선이 10번 멈추면 조기 종료한다. 최소 1,000스텝을 수행한다. 학습 시작 1스텝에서도 파이프라인 확인용 검증을 기록한다.
5. 서로 다른 chunk 길이를 공정하게 비교하기 위해 공통으로 앞 10개 미래 스텝의 녹화별 MAE를 사용한다. 최저 검증 체크포인트를 보존하고 모델 계열별로 검증 성능이 가장 좋은 실험을 고른 뒤 테스트에 접근한다. `test_access.json`에 선택 목록을 먼저 고정한다. 테스트 결과로 추가 튜닝하지 않는다. 현재 관절 자세를 그대로 유지하는 무학습 대조군과도 비교해 정지 정책의 낮은 오차를 성공으로 오인하지 않게 한다.
6. 전체 벽시계 상한은 최대 12시간이며 마지막 평가·보고서 작성에 30분을 남긴다. 36개가 먼저 끝나면 불필요한 반복 없이 종료한다. 남은 시간에 따라 뒤쪽 시드가 실행되지 않을 수 있으며 보고서에 완료 개수를 표시한다.

보존 기록에는 seed·학습 녹화 목록·정규화 통계·배치 크기·학습 시간·GPU 최대 메모리·최저 검증 단계·종료 이유가 포함된다. 검증 데이터가 2개뿐이므로 많은 조합을 고르는 과정 자체도 검증 세트에 과적합될 수 있다. 테스트 5개와 3개 시드가 이 한계를 없애지는 않는다.

## 시뮬레이션 판정

- 제조사 메시·질량·관성·모터 힘 제한·양쪽 손가락 mimic 관계를 사용한다. 물체는 자유 관절과 실제 접촉으로 움직이며 가짜 부착·텔레포트를 하지 않는다.
- 관절 5개는 -100…100, gripper는 0…100 정규화다. gripper 0…100을 임의의 0…최대 관절각으로 선형 대응하지 않는다. 녹화 캘리브레이션의 raw tick 범위와 중심값 2048/4096으로 역변환한다.
- 2ms 물리 스텝을 16/17회씩 번갈아 진행해 30Hz 제어 시간을 맞춘다.
- 원위치보다 25mm 이상 들린 상자가 원형 수신대에 완전히 들어가고, 열린 그리퍼에서 낮은 속도로 15프레임 안정적으로 놓여야 성공이다. 실제 접촉이 수신대 또는 그 위의 상자로 이어지는 지지 관계도 확인한다. 쌓아 놓기도 허용하며 이후 떨어진 상자는 성공으로 유지하지 않는다. 하나 이상/전체 상자 성공을 따로 기록한다.
- 사전 지정 조건: nominal, object_shift(±15mm), low_friction, heavy_box(2배), camera_shift, single_box. chunk 제어와 temporal ensemble을 비교한다.
- 물리 환경이 미검증인 동안 위 지표는 후보 정책의 잠정 진단값이다. 실제 로봇 성공률로 표현하지 않는다. 시연 재생 실패를 모델의 실패로 오인하면 안 된다.

## 실행·중단·재개·보고서

```bash
scripts/mujoco/run_12h.sh
tail -f ~/omx_sim_runs/validation_20261025/supervisor.log
cat ~/omx_sim_runs/validation_20261025/status.json
```

`run_12h.sh`는 새 세션에서 감독 프로세스를 실행한다. 터미널을 닫아도 계속되지만 전원 종료·절전 중에는 학습할 수 없다. 로그와 `pid`, flock 잠금으로 중복 실행을 막는다. 중단 요청:

```bash
PYTHONPATH=src/cobot_mujoco ~/venv/omx_mujoco/bin/python -m cobot_mujoco.cli stop \
  --run ~/omx_sim_runs/validation_20261025
```

감독 프로세스는 현재 학습을 중단하고 완료된 결과·실패 기록으로 보고서를 마무리한다. 같은 실행 경로를 다시 실행하면 완료된 실험은 건너뛰고 `last.pt`부터 재개한다. 12시간 마감 시각과 실험 계획은 최초 시작 시 고정되며 재실행으로 연장되지 않는다. 종료 후 테스트를 이미 열었다면 튜닝을 재개하지 않는다. 별도 새 실험은 새로운 독립 테스트 설계가 필요하다.

보고서: [`docs/mujoco_validation/report.html`](../../../docs/mujoco_validation/report.html). 하나의 HTML에 수치·곡선·이미지·JSON을 포함하므로 파일을 내려받아 브라우저에서 열면 된다. GitHub 파일 화면은 HTML을 실행하지 않는다. 실행 중에는 60초마다 갱신되며 종료 후 `status.json`, `trials.json`, `diagnostics.json`, `selected.json`, `final_evaluation.json`이 함께 저장된다. 완료/시간 초과/오류 모두 보고서를 생성한다. `--push-report` 사용 시 전용 브랜치의 보고서만 커밋·푸시한다. 실패하면 `publication_error`와 재시도 명령을 확인한다.

## 검증 명령

```bash
source /opt/ros/jazzy/setup.bash
~/venv/omx_mujoco/bin/python -m colcon build --symlink-install --packages-select cobot_mujoco
OMX_ROBOT_ASSETS=~/omx_sim_assets/robotis MUJOCO_GL=egl \
  ~/venv/omx_mujoco/bin/python -m colcon test --packages-select cobot_mujoco --python-testing pytest --event-handlers console_direct+
colcon test-result --verbose
PYTHONPATH=src/cobot_mujoco OMX_ROBOT_ASSETS=~/omx_sim_assets/robotis MUJOCO_GL=egl \
  ~/venv/omx_mujoco/bin/python -m pytest src/cobot_mujoco/test -q
~/venv/omx_mujoco/bin/python -m ruff check src/cobot_mujoco
~/venv/omx_mujoco/bin/python -c 'from ament_flake8.main import main; raise SystemExit(main(["--config", "src/cobot_mujoco/.flake8", "src/cobot_mujoco"]))'
~/venv/omx_mujoco/bin/python -c 'from ament_pep257.main import main; raise SystemExit(main(["src/cobot_mujoco"]))'
```

## 현장 검증기로 승인하기 위해 남은 작업

상자 치수·질량, 작업대/수신대 높이·거리, 팔 고정대와 카메라 외부 파라미터를 실측한다. 카메라 내부 파라미터·마찰·모터 응답을 별도 데이터로 식별한다. 보정에 쓰지 않은 시연으로 재생 성공을 검증한다. 충분한 독립 배치에서 실제 성공·실패 결과와 시뮬레이션 판정의 상관을 확인한 뒤에만 `validation_gate`를 갱신한다. 성공 영상만으로 실패 탐지기 성능을 발표하지 않는다.
