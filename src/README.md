# 📦 Pinky_Team4 ROS 2 패키지 구조 및 협업 가이드

본 저장소(`kernel-robot-repo-4`)는 다중 로봇(Pinky Pro 3대 + OMX 3대) 기반 스마트 물류 및 자율 장애물 회수 시스템의 공식 통합 워크스페이스입니다.

---

## 🏛️ 디렉토리 및 패키지 구조 (모노레포 정석)

```
src/
├── fleet_msgs/               # ⭐ [공용 인터페이스] 최우선 정의 (메시지, 액션, 서비스)
│   ├── msg/
│   │   ├── DropEvent.msg     # 낙하 감지 좌표 및 물품 정보
│   │   └── RobotStatus.msg   # 핑키/로봇팔 실시간 상태 및 배터리
│   └── action/
│       ├── RecoveryTask.action   # 복구 봇 급파 및 수거 액션
│       └── HandoverTask.action   # 상·하차 도킹 정지 공차 보정 액션
│
├── pinky_navigation/         # [주행 트랙 - 김진호] Nav2, SLAM, 순차 출발, 충돌 방지
├── vision_detector/          # [비전 트랙 - 손선아] YOLOv11 객체/비닐 세그멘테이션, 마커 인식
├── omx_manipulation/         # [매니퓰레이션 트랙 - 강민석, 허지혁] LeRobot ACT 추론 및 상·하차 제어
├── overhead_vision/          # [관제 트랙 - 강건한] 천장 카메라 스트림, 차선 낙하 좌표 추출
└── fms_orchestrator/         # [통합 트랙 - 강건한, 김지혜] 관제 FSM 상태머신, 브릿지, 작업자 UI
```

---

## 🛠️ 협업 및 개발 수칙

1. **인터페이스 최우선**:
   * 모든 통신 규격은 `fleet_msgs` 패키지를 참조하며, 규격 수정이 필요할 경우 팀 협의 후 `fleet_msgs`를 먼저 갱신합니다.
2. **독립 패키지 빌드**:
   * 본인 담당 패키지만 빌드하여 테스트할 수 있습니다:
     ```bash
     colcon build --packages-select fleet_msgs <내_패키지_이름>
     ```
3. **브랜치 전략**:
   * `main` 브랜치에 직접 푸시하지 않고, 기능별 브랜치(`feat/<기능명>`)를 생성하여 작업 후 PR(Pull Request)로 머지합니다.
4. **Git 대용량 파일 금지**:
   * 모델 가중치(`.pt`, `.onnx`)나 로스백(`.mcap`) 파일은 깃에 올리지 않고 외부 링크(Hugging Face, Drive)를 통해 관리합니다.
