# 수집 번들 검증 — 2026-11-20

omx_control_inputs.tar.gz의 manifest에 기록된 20개 파일의 SHA256 및 크기 검증 완료. 보관 위치 .local/operating_source. 장치 연결/모터 명령 없음.

## 확인
- 원격 il_ws/src/lerobot의 omx_follower.py, config, __init__, motors_bus.py는 조사한 로컬 소스와 바이트 단위 동일. 실제 프로세스가 이 소스를 import하는지는 별도 확인 필요.
- use_degrees=False 기본, 팔 -100..100 / gripper0..100. 두 init_pose.json의 units도 일치.
- 수집한 보정 두 파일은 동일: 모든 모터 range0..4095, homing_offset0, drive_mode0. 이는 기본 전 범위 설정이며 충돌 없는 관절 가동범위나 실물 영점 측정 증거가 아니다.
- 기본 경로대로라면 팔 tick=int((clip(u,-100,100)+100)/200*4095), gripper tick=int(clip(g,0,100)/100*4095). 시뮬레이터 라디안 변환에는 URDF 영점·축 방향·구동 기구 매핑이 추가로 필요.
- 정리 init pose [-12.97,-17.31,-0.85,43.59,-0.85,59.68], 싣기 [2.22,-34.99,14.68,40.37,1.0,58.93]. 순서 shoulder_pan,shoulder_lift,elbow_flex,wrist_flex,wrist_roll,gripper. 명령 실행용이 아닌 기록용 수치.
- 정리 success.json: top, conf0.5, hz10, arm_class inside_box / arm_s1.0, target closed_box / hold_s3.0 / min_ratio0.8, forbid inside_box0.1 shoe0.1, gap_s1.0, still_speed8.0 / still_s0.7, rest_tol18.0, rest_pose[1.2,-28.7,7.3,39.0,-0.6,47.2]. 단순히 closed_box 3초라는 요약보다 조건이 많음.
- 싣기 success.json은 수집 목록에 없음. 알려진 실행기의 시간 종료 방식과 일치하나 실제 적재 성공을 판단하지 않음.

## 누락 3패턴 해석
- dashboard 상위 act_ensemble.py 없음.
- venv/il/site-packages 내 드라이버/모터 소스 패턴 없음. 그러나 il_ws/src 소스는 확보됨. editable 설치나 다른 Python 환경 가능성; 패키지 미설치라고 결론 내리지 않음.

## 다음 작업
ROBOTIS 공식 OMX-F 형상/동역학 모델을 확보하고 5축·그리퍼 구조 및 FK 링크 오프셋을 대조. OpenMANIPULATOR-X는 명칭이 비슷해도 OMX-F와 구분. 이 번들만으로 관성·충돌체·신발 접촉 물성을 추정하지 않는다. 실행 중 Python/ARM_ID/CLI, 실물 영점·그리퍼 개방폭은 아직 미확인. 현재 파일만으로 물리 모델 준비는 진행 가능하나 실물 좌표 검증은 완료되지 않음.
