# CompletionEvidence.msg - 물리 완료 증거 1건 (SR-21)
# ACK(받았다)와 다르다. 움직였다·멈췄다·빠져나왔다를 센서로 보인 것이다.
# 토픽: /navigation/<robot_id>/completion_evidence, /manipulation/<arm_id>/completion_evidence,
#       /vision/completion_evidence (이벤트 QoS, 이름은 초안)
# measured=false 는 PASS 가 아니다. 센서가 없거나 캡처 시각을 검증할 수 없으면 false 로 낸다.

uint8 ENCODER_VEL_ZERO=0           # 엔코더 속도 0 지속 (value [m/s])
uint8 BASE_HOLD_ENGAGED=1          # 바퀴 잠금 체결 (SR-08)
uint8 ARM_RETRACT_SAFE=2           # 팔 퇴피 Z >= 280 mm (SR-10, value [mm])
uint8 LOAD_SENSOR_PRESENT=3        # 적재 센서 (SR-10)
uint8 GRIPPER_HOLD_OK=4            # 그리퍼 파지 확인 (SR-21)
uint8 TAIL_EXIT_CONFIRMED=5        # 게이트 카메라 후미 퇴장 (SR-05). age_basis=CAPTURE 일 때만 measured=true
uint8 ZONE_PRESENT=6               # 천장 카메라 구역 안에 있음 (보조 증거)

std_msgs/Header header             # stamp = 측정 시각 (원천 시계)
string evidence_id                 # UUIDv4. LaneLeaseState·HandoverTask 결과가 이 값으로 가리킨다
string command_id                  # 원인 명령 ID. 없으면 ""
string task_id                     # 작업 ID (SR-21)
string source_id                   # 증거를 낸 쪽: pinky_2, omx_1, cam_gate ...
uint8 kind                         # [-] 위 상수 중 하나
float64 value                      # [kind 별] 단위는 docs/fms_interfaces.md 의 증거 표
float64 threshold                  # [kind 별] value 와 같은 단위
bool satisfied                     # value 가 threshold 조건을 만족하는가
bool measured                      # 센서로 실제로 쟀는가. false 는 PASS 가 아니다
