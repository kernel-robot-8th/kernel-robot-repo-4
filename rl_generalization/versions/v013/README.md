# v013: 실제 시연 데이터와 시뮬레이터 대응 분석

## 확인한 데이터
- Yuzriha00/shoebox_D @ d641442875f08264680b19fe7d961c0f1343c40c: 50 episodes / 73559 frames.
- hfhfhf111/move_in_success @ 71f08f2ca8ec29386ead547542578ccbc09b17e7: 37 episodes / 21284 frames.
- 고정 커밋의 data/meta만 .local/demonstrations에 다운로드. 기존 classification/shoebox_D의 parquet는 LFS 포인터여서 원본으로 사용하지 않음.
- 실제 데이터의 episode_success는 모두1. 수집자 성공 라벨이며 별도의 영상 재검증은 하지 않음. ACT 추론 로그가 아니라 리더→팔 시연 기록.
- action은 실제 전송 목표값, observation.state는 follower 관절 상태. 관절 -100..100, 그리퍼0..100 정규화 값으로 도(degree)가 아님. 30Hz, 에피소드 내 timestamp 단조 증가 확인.
- aux.current, aux.gripper_current, aux.velocity, aux.ee_pose 등 실제 기록 존재. 그리퍼 전류 raw 범위 정리[-268,75], 운반[-496,151]. collector는 XL330 그리퍼1mA/unit로 명시. 압력/접촉력/물성값으로 직접 환산 불가; 부호도 열림/닫힘 방향 보정 없이 해석하지 않음.
- 그리퍼 상태 범위: 정리47.057..59.853, 운반47.155..68.889 정규화 단위. 시뮬레이터의0..1.745rad에 단순 비례시키지 말 것.

## 중요한 불일치
기존 v012의 TCP [0.075,-0.00165,0]m는 임시값. 관측 팔 상태를 기존 tick 영점2048, 모든 축+방향 후보 변환으로 시뮬레이터 FK와 비교하면, 기록된 aux.ee_pose는 link5의 [0.09193,-0.0016,0]m 지점과 일치한다. 약1.693cm의 TCP 차이가 있었다. 기록 FK도 계산값이므로 이 일치는 계산 체계 일관성만 입증하며 실제 손끝 위치 측정이 아니다.

30프레임 간격 표본 비교에서 정리2477개 중 wrist_flex468개, 운반728개 중 wrist_flex39개/elbow_flex1개가 공식 시뮬레이터 관절 범위를 벗어남. 원인 확인 전 제한을 임의 확대하거나 데이터를 잘라내지 않는다. 기존 접근 성공은 실물 작업 재현 증거가 아니다.

## 코드와 결과
- code/audit_demonstrations.py: 전체 프레임 분석, 해시, 에피소드0 CSV/SVG. --out NEW_DIRECTORY.
- code/check_fk_mapping.py: 30프레임 간격 FK 일관성과 범위 검사. evidence/fk_candidate.json.
- code/replay_arm.py: 관측 관절 상태를 이용한 팔 5축 기구학 재생. 물리/접촉 계산 없음, 그리퍼0 고정, 물체 정지. 범위 밖 자세도 그대로 보여주는 진단용이며 실행 가능한 제어 명령이 아님.

```bash
.venvs/omx_sim/bin/python versions/v013/code/replay_arm.py --dataset shoebox_D --episode 0
# 운반 시연 팔 자세
.venvs/omx_sim/bin/python versions/v013/code/replay_arm.py --dataset move_in_success --episode 0
```

## 다음 검증 순서
1. 동일 에피소드 카메라 영상과 팔 자세 재생 비교 (현재 영상 다운로드/대조 미실행).
2. 수집 시점 calibration과 recorder FK/그리퍼 모터 영점 및 링크 기구 대응 확인.
3. 성공 시연이 공식 모델 제한 밖에 나가는 원인 확인; 실물 영점·가동범위 증거로만 수정.
4. 그리퍼 상태/명령/전류 그래프와 영상의 개방폭·접촉을 시간 정렬, 실제 접촉 대응 보정.
5. 보정된 성공 궤적의 동적 재생 → 작은 위치 변화 일반화 학습. 이번 버전은 RL 학습이나 실물 제어를 하지 않음.
