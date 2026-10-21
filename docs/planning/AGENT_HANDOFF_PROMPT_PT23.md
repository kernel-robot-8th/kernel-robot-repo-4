# [인수인계] PT-23 LiveKit Teleop & LeRobot 모방학습 시스템 구현 에이전트 브리핑 프롬프트

> 본 문서는 **PT-23 구현 작업을 직접 수행할 후속 AI 코딩 에이전트(Codex, Claude, Cursor 등)**에게 프로젝트 맥락과 작업 지시를 완벽하게 전달하기 위한 **복사-붙여넣기 전용 프롬프트**입니다.

---

```markdown
당신은 팀의 로봇/FMS 핵심 소프트웨어 구현 엔지니어입니다.
아래의 배경 맥락과 기술 명세, 작업 지침을 정독하고 지정된 저장소와 브랜치에서 코드를 직접 작성, 테스트, 커밋해 주십시오.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 미션 목표 및 긴급성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 대상 과제: Jira 이슈 [PT-23] OMX 모방학습·Teleop 개발 화면 (우선순위: P0 긴급)
- 마감 기한: 2026년 10월 24일 (Sprint 2 MVP 배포)
- 핵심 목표: 
  매니퓰레이터 파트(김성아 님)의 ACT 모방학습 모델 학습을 위해 태스크별 100~200 에피소드 데이터 수집이 즉시 필요합니다.
  이를 지원하기 위해 WebRTC 기반 초저지연(<100ms) 원격 텔레옵(LiveKit), 로봇팔 파라미터 전체 제어, 그리고 HuggingFace LeRobot 규격 호환 1-Click 에피소드 레코더가 통합된 [메뉴 3.7 스튜디오] 시스템을 완성해야 합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. 작업 대상 저장소 및 참고 문서 (Single Source of Truth)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 코드 저장소: https://github.com/rkd1rjs2/robot_mini_project_pinky
- 작업 브랜치: codex/hybrid-stand-67cm (활성 검수 PR #3)
- 상세 구현 계획서 (반드시 먼저 정독할 것):
  docs/planning/PT23_OMX_LIVEKIT_TELEOP_LEROBOT_IMPLEMENTATION_PLAN.md
- 연계 문서:
  1) FMS 대시보드 메뉴 3.7 명세: https://pinkyteam4.atlassian.net/wiki/spaces/PinkyTeam4/pages/6783015
  2) 매니퓰레이터 작업 세부 계획서(김성아): https://pinkyteam4.atlassian.net/wiki/spaces/PinkyTeam4/pages/3899403
  3) LiveKit 공식 레퍼런스: https://docs.livekit.io/robotics/teleop/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. 구현할 컴포넌트 및 파일 배치 구조
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
다음 파일들을 새로 구현하거나 기존 시스템에 연동해야 합니다:

robot_mini_project_pinky/
├── relay_station/
│   ├── configs/
│   │   ├── livekit.yaml                     # LiveKit SFU 서버 설정 (포트 7880/7882)
│   │   └── omx_teleop_config.json           # 모터 ID(1~6), 관절 한계각, 카메라 디바이스 설정
│   ├── docker-compose.livekit.yml           # LiveKit Server 로컬 컨테이너 실행 파일
│   ├── omx/
│   │   ├── __init__.py
│   │   ├── dynamixel_hardware_interface.py  # DYNAMIXEL Protocol 2.0 드라이버 (Mock 모드 필수 포함)
│   │   ├── omx_teleop_daemon.py             # LiveKit RTC 데몬 + 50ms Watchdog 안전 정지
│   │   └── lerobot_dataset_writer.py        # 30Hz 상태/행동 시계열 Parquet & MP4 저장 모듈
│   └── tests/
│       ├── test_dynamixel_interface.py      # 모터 6개 제어 및 Mock 단위 테스트
│       ├── test_omx_teleop_e2e.py           # DataTrack 루프 지연시간 및 Fail-safe E2E 테스트
│       └── test_lerobot_dataset_export.py   # LeRobot 데이터셋 규격 호환성 검증 테스트
└── gateway_web/components/omx_teleop/       # (또는 Next.js 대시보드 프론트엔드)
    ├── DualCameraViewport.tsx (or .js)      # Top Cam(720p) + Wrist Cam(480p) WebRTC 뷰어
    ├── ActuatorParamPanel.tsx (or .js)      # 관절 슬라이더, PID 게인, 속도 프로파일, 토크 On/Off
    ├── GamepadTeleopEngine.ts (or .js)      # HTML5 Gamepad API 연동 조작 엔진
    └── LeRobotRecorderPanel.tsx (or .js)    # 1-Click 에피소드 레코더 및 인라인 리플레이 모달

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. 핵심 기술 명세 및 필수 준수 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1) DYNAMIXEL 액추에이터 제어 (OpenManipulator-F):
   - ID 1~5 (관절) + ID 6 (그리퍼), Protocol 2.0, 1Mbps.
   - SyncRead: Present Position, Velocity, Current, Temp 동시 수신 (30Hz).
   - SyncWrite: Goal Position, Profile Vel/Accel, PID Gain, Current Limit.
   - Mock Mode: 실물 하드웨어 없이도 CI 및 로컬 환경에서 테스트 가능하도록 가상 모터 시뮬레이션 지원 필수.

2) LiveKit 통신 및 안전 프로토콜 (SR-19 & SR-20 준수):
   - 비디오: camera_top(1280x720@30fps), camera_wrist(640x480@30fps) WebRTC VideoTrack 퍼블리시.
   - DataTrack (robot.control): buffer_size=1, Lossy 비신뢰성 채널로 30~50Hz 조작 패킷 전송. 지연 패킷(>50ms) 즉시 폐기.
   - Safety Watchdog: 50ms 감시 루프에서 100ms 이상 조작 패킷 미수신 시 자동으로 Safe Position Hold 진입.
   - RPC 단일 제어권(SR-19): acquire_control_lease를 통해 1명의 조작자에게만 독점 권한 부여, 미인증 조작 지령 차단.

3) HuggingFace LeRobot 데이터셋 규격 (30Hz 동기화):
   - 저장 경로: ~/.cache/huggingface/lerobot/pinky_omx_tasks/
   - 파일 구성:
     * data/chunk-000/episode_XXXXXX.parquet (observation.state: 12 dims, action: 6 dims, timestamp, next.done)
     * videos/observation.images.top/chunk-000/episode_XXXXXX.mp4
     * videos/observation.images.wrist/chunk-000/episode_XXXXXX.mp4
     * meta/info.json 및 meta/episodes.jsonl
   - 단축키: [Space/Gamepad R1] 녹화 시작 -> [Enter/Gamepad L1] 저장 -> [Backspace/Gamepad B] 즉시 폐기 및 Ready 복귀.
   - 인라인 리플레이: 방금 녹화된 시연 영상을 즉시 재생하여 김성아 님의 M-03 검수 기준 충족.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. 단계별 작업 절차 및 완료 기준 (Checklist)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ ] Step 1: 환경 구성 (livekit, livekit-rtc, dynamixel-sdk, pyarrow, opencv-python, pytest 의존성)
[ ] Step 2: dynamixel_hardware_interface.py 구현 및 test_dynamixel_interface.py 단위 테스트 통과 (Mock 모드 지원)
[ ] Step 3: omx_teleop_daemon.py 구현 (LiveKit 방 참여, 듀얼 카메라 트랙 송출, 50ms Watchdog 안전 정지 검증)
[ ] Step 4: lerobot_dataset_writer.py 구현 및 test_lerobot_dataset_export.py 통과 (Parquet/MP4 동기화 무결성)
[ ] Step 5: 웹 프론트엔드 컴포넌트(DualCamera, ActuatorParam, GamepadTeleop, LeRobotRecorder) 구현
[ ] Step 6: test_omx_teleop_e2e.py 통합 테스트 통과 (가상 5 에피소드 수집 드라이런 성공)

모든 작업이 완료되면 'feat(omx): implement LiveKit teleop and LeRobot dataset recorder for PT-23' 커밋 메시지로 커밋 후 Push해 주십시오.
```
