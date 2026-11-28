# 제어 경로 조사 — 2026-11-20

범위: 로컬 소스 정적 분석. 로봇 연결·명령 전송·캘리브레이션 실행 없음. 소스 해시는 sources.json. 운영 PC의 실제 설치 버전과 동일하다는 증거는 아직 없음.

## 확인한 후보 경로

HF 참조 모델 policy_postprocessor.json: action shape6, MEAN_STD 역정규화. 통계 텐서 자체는 이번 조사에서 읽지 않았음.
로컬 lerobot_record.py: predict_action(pre/postprocessor) → make_robot_action(dataset.features) → robot_action_processor → robot.send_action.
OmxFollower.send_action: .pos 키를 모터 이름으로 변환 → max_relative_target 설정 시 현재 위치와 차이 제한 → bus.sync_write(Goal_Position).
MotorBus._unnormalize: 캘리브레이션 범위와 drive_mode를 사용해 정규화된 값에서 정수 tick으로 변환. 모델 통계 역정규화와 모터 tick 변환은 서로 다른 단계.

## 로컬 드라이버에서 확인한 사항

- 팔 5관절 + 그리퍼1: shoulder_pan(11), shoulder_lift(12), elbow_flex(13), wrist_flex(14), wrist_roll(15), gripper(16).
- 앞 3모터 xl430-w250, 나머지 xl330-m288로 선언됨. 실물 부품 일치 여부는 미확인.
- use_degrees=False 기본: 팔 RANGE_M100_100, 그리퍼 RANGE_0_100. 각도·라디안으로 직접 해석 금지. 학습 데이터 벡터의 실제 순서는 dataset.features와 운영 실행기를 함께 확인해야 함.
- 팔 extended position mode, 그리퍼 current-based position mode. 명령은 목표 위치이며 속도/토크 명령이 아님.
- max_relative_target 기본 None: 이 경로의 상대 이동 제한은 기본 비활성. 값 클리핑은 충돌 회피나 물리 관절 제한 검증을 대신하지 않음.
- 참조 inference.sh는 dataset.fps=30, n_action_steps=50, 모델 기본 chunk_size100. 이는 운영 fleet의 측정 주기가 아님. 30Hz를 실제로 유지한다면 50-step chunk는 약1.67초이나 실제 사용 설정·속도는 확인 필요.
- get_observation은 관절 Present_Position 및 카메라를 읽음. 기본 클래스는 물체 좌표나 파지 성공 관측을 제공하지 않음.

## 로봇 모델 단서

omx_recoder/core/kinematics.py는 open_manipulator_description/urdf/omx_f/omx_f.urdf를 출처로 주석에 명시. 5축 z/y/y/y/x와 링크 offset을 정의. 이 파일은 정기구학(FK) 구현이며 IK나 접촉 시뮬레이터가 아님. 보정 range/drive_mode, tick2048 중심, signs/offset 가정을 사용하므로 실물 좌표와 검증 필요.
검색한 Project2 및 /home/noma/il_ws 범위에서 실제 URDF/xacro와 omx_fleet 운영 소스를 찾지 못함. 기구학 숫자만으로 충돌체·질량·관성·그리퍼 기하를 만들어 물리 검증됐다고 할 수 없음.

## 다음 구현 기준

1. 운영 PC의 omx_fleet, init_pose.json, success.json, 설치된 omx_follower 및 사용 calibration을 확보하고 로컬 후보와 비교.
2. 실제 OMX-F 모델/리비전 확인 후 대응 URDF 및 메시, 관절 영점/방향/제한 확인.
3. 시뮬레이션 초기 action은 실물과 매핑 가능한 관절 위치 목표 방식부터 검증. Cartesian delta 방식을 유지하려면 검증된 IK 및 5자유도에서 가능한 자세 제약이 필요. 6D pose 임의 제어를 가정하지 않음.
4. 단일 물체 접촉/집기/들기, 충돌·관절제한·명령 변화 제한 검증 후 위치 랜덤화. 실제 신발/그리퍼 형상과 마찰이 없으면 surrogate 실험이라고 명시.
5. toy v004 추가 튜닝은 우선순위에서 제외. 실제 제어 구현/물리 시뮬레이터는 아직 미구현.
