# 운영 실행기 정적 조사 (2026-11-20)

출처: 사용자가 원격 /home/team11/jihye/kernel-robot-repo-4-omx-dashboard/omx_fleet를 복사한 .local/operating_source/omx_fleet. 프로그램을 실행하지 않음. 현재 실행 프로세스의 ARM_ID/CLI/설치된 LeRobot 버전은 아직 미확인. 아래는 전달된 코드와 omx3 설정의 결과.

## 제어 경로
omx_fleet_worker.chain_args → omx_chain.parse_args → make_robot(OmxFollowerConfig) → load_stage(ACT/pre/post) → run_stage(predict_action → make_robot_action → robot.send_action). 런타임 추가 CLI가 기본값을 덮어쓸 수 있음.

- 기본 fps30, n_action_steps50 (chunk_size와 min), temporal ensemble 계수 미지정. use_degrees를 전달하지 않으므로 설치된 드라이버 기본값을 사용. 로컬 후보의 기본값 false와 원격 설치본의 일치 확인 필요.
- **정정:** 드라이버 클래스 기본 max_relative_target=None과 달리 운영 실행기는 **10**을 전달. ramp는 min(2, normal_max)를 2초간 적용. 다단계는 둘째 단계부터, 단일 단계는 처음부터 적용. 각도/초 제한으로 해석하면 안 됨.
- run_stage는 send_action 반환값을 버림. 현재 recorder는 카메라/판단 시점 기록이며 raw action/실제 clipping 후 명령/현재 관절의 비교 로그는 아님. RL 전에 해당 로그 수집 경로를 구현해야 함.
- 초기 자세 이동은 현재 관절과 init pose 사이 cosine interpolation, 최소2초, 기본속도10 normalized units/s. 이 함수 내부에서 stop 이벤트나 충돌 검사를 확인하지 않음. 자동 RL reset에 그대로 쓰지 않기.

## 작업 연결
omx3 arrange_shoe: 정리90초 → 성공 판단 있을 때 실패면 종료 → 1초 유지 → 싣기 init pose로 이동 → 싣기35초 → rest pose 복귀.
각 단계마다 policy/pre/post reset. 중간 단계로 ACT를 임의 재개하는 구조가 아님.
별도 load 명령의 제한시간은 **90초**: arrange_shoe 안의 싣기35초와 구분.

## 성공 의미의 한계
worker 548–550: 하나 이상의 judge가 있고 모든 단계를 끝까지 실행했고 judge가 있는 단계만 성공했으며 hold가 없으면 전체 success=True. 따라서 정리 judge 성공 + 싣기 timeout 조합도 전체 success=True 가능. 이는 적재 성공 검증이 아니다. RL 보상은 단계별 물체 상태로 별도 정의 필요.
success_judge.py 기본 hold_s=5, still_speed=0(정지 조건 꺼짐). 사용자가 보고한3초+정지+끝자세 조건은 success.json 덮어쓰기를 확인해야 함. 현재 json은 복사본에 없음. 기본값을 운영 설정이라고 단정하지 않음.

## 아직 필요한 파일
- 두 운영 번들의 init_pose.json, success.json, 모델 config 및 전처리/후처리 설정
- 원격 설치된 OmxFollower/모터 변환 구현과 실제 calibration
- 정확한 로봇 모델 URDF/메시/관성, 실제 축 영점·방향·그리퍼 치수
- 실행에 쓰는 ARM_ID, 추가 CLI 및 Python 경로 (기본값과 실제값 비교)

collect_inputs.py는 알려진 위치에서 선택된 JSON/Python만 수집하고 누락 패턴도 기록. 가중치/영상/인증정보는 수집 대상으로 지정하지 않음. 장치 연결 또는 드라이버 import 없음. 코드 확보 후에도 실제 좌표·제어주기 계측은 별도 작업.
