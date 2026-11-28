# 사용자 제공 운영 정보 — 2026-11-18, OMEN-11/team11

관제 명령 arrange_shoe → 신발 정리 ACT → YOLO 성공 판단 → 싣기 ACT.

| 항목 | 신발 정리 | 싣기 |
|---|---|---|
| HF | Sungah/omx_shoebox_d | Sungah/omx_move_in_success |
| commit | 8497dfe4fe4247f7c4a20b55b212912c4f69479a | d2a2cd1eedfbf29c8f409dc305fae2e75b8b3cf4 |
| 모델 경로 | models/act_shoebox_d_5000step | models/act_move_in_5000step |
| 데이터 | Yuzriha00/shoebox_D, 50 episodes | hfhfhf111/move_in_success, 37 episodes |
| 운영 제한 | 90초, YOLO 조기 종료 | 35초, 시간 기준 |

관절 6 + top/wrist 640×480, LeRobot 0.4.4. move_in은 원문에는 '밀어 넣기'로 적혔으나 사용자 정정과 영상에 따라 **상자 파지·들기·운반·적재 포함**으로 해석한다.

OMEN-11의 파일 위치(현재 PC에 있다고 가정하지 않음):
- ~/il_ws/omx_shoebox_d/models/act_shoebox_d_5000step
- ~/il_ws/omx_move_in_success/models/act_move_in_5000step
- ~/il_ws/bundles/omx_arrange_shoe_zc/v1/: ACT + init_pose.json + success.json + yolo/
- ~/il_ws/bundles/omx_load_zc/v1/: ACT + init_pose.json
- ~/il_ws/bundles/omx_arrange_shoe_zc/v1/yolo/best_shoebox_D_rec_1116_2010.pt
- ~/il_ws/handoff_arm_still/best_shoebox_D_rec_1116_2010.pt

YOLO11 segmentation classes: closed_box=0, inside_box=1, shoe=2.
기존 종료 기준: top closed_box 3초 유지 + 팔 정지 + 끝 자세 근처. 신발이 모두 들어갔는지, 새로운 정책의 끝 자세에도 타당한지 별도 검증해야 한다. 이 판정은 새 신발 파지 보상과 동일하지 않다. 35초 경과는 적재 성공으로 변환하지 않는다.

HF에는 YOLO 가중치, 운영 번들의 init_pose.json/success.json, omx_fleet 실행 코드가 포함되어 있지 않다. 현재 references/에는 앞서 확인한 HF 코드/JSON만 보관하고 모델 가중치는 보관하지 않는다. 기존 omx_run.py의 누락된 depth 모듈 import, inference.sh의 누락된 omx_record.py 참조 때문에 운영 번들이 필요하다.

실물 연결에 필요한 자료: 위 두 운영 번들, omx_fleet 실행/관절 명령 경로, 캘리브레이션 및 카메라 설정, IK/URDF 정보, 실제 실행 로그. 이 자료를 확인하기 전 실물 드라이버를 추측해서 구현하지 않는다. 현재 PC /home/noma/il_ws에는 과거 source가 있지만 OMEN-11 번들과 같다고 확인되지 않았다.
