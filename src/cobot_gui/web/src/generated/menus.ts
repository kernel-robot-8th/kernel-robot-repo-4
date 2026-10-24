// 자동 생성 파일이다. 직접 고치지 말 것.
// 원본: src/cobot_gui/config/menu_tree.yaml
// 재생성: PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_menus
// 확인: PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_menus --check

import type { Decision, Menu, Phase, Role, Screen, SrItem } from "../shell/types";

export const SCREENS: Screen[] = [
  {
    "id": "screen_1",
    "label": "①",
    "name": "통합 관제",
    "phaseNote": "P1 읽기 → P2 명령"
  },
  {
    "id": "screen_2",
    "label": "②",
    "name": "핑키 주행 관제",
    "phaseNote": "P1 → P2"
  },
  {
    "id": "screen_3",
    "label": "③",
    "name": "로봇팔 작업 관제",
    "phaseNote": "P4"
  },
  {
    "id": "screen_4",
    "label": "④",
    "name": "비전·안전 모니터링",
    "phaseNote": "P1 → P3"
  },
  {
    "id": "screen_5",
    "label": "⑤",
    "name": "제어권·안전 관리",
    "phaseNote": "P2"
  },
  {
    "id": "screen_6",
    "label": "⑥",
    "name": "시스템 통신 진단",
    "phaseNote": "P1"
  },
  {
    "id": "screen_7",
    "label": "⑦",
    "name": "주문·작업 이력",
    "phaseNote": "P1 → P3"
  },
  {
    "id": "screen_8",
    "label": "⑧",
    "name": "시스템 설정",
    "phaseNote": "P1"
  },
  {
    "id": "aux_a",
    "label": "보조 A",
    "name": "주문 호출",
    "phaseNote": "P3"
  }
];

export const PHASES: Phase[] = [
  {
    "id": "P1",
    "title": "읽기 전용 관제",
    "roadmapStage": "S2"
  },
  {
    "id": "P2",
    "title": "정지·펜싱·복구",
    "roadmapStage": "S3"
  },
  {
    "id": "P3",
    "title": "주문·통로·비전",
    "roadmapStage": "S4"
  },
  {
    "id": "P4",
    "title": "팔 연동",
    "roadmapStage": "S5"
  },
  {
    "id": "P5",
    "title": "이후",
    "roadmapStage": "S6"
  }
];

export const ROLES: Role[] = [
  {
    "key": "vision",
    "name": "비전",
    "members": [
      "강건한",
      "손선아"
    ]
  },
  {
    "key": "navigation",
    "name": "주행",
    "members": [
      "김지호",
      "김성아"
    ]
  },
  {
    "key": "manipulation",
    "name": "매니퓰레이터",
    "members": [
      "강민석",
      "김성아",
      "손선아",
      "허지혁"
    ]
  },
  {
    "key": "control_center",
    "name": "관제",
    "members": [
      "강건한"
    ]
  },
  {
    "key": "gui",
    "name": "GUI",
    "members": [
      "강건한",
      "김지혜"
    ]
  },
  {
    "key": "common",
    "name": "공통",
    "members": []
  },
  {
    "key": "operation_control",
    "name": "로봇 수행 관제",
    "members": []
  },
  {
    "key": "anomaly_monitoring",
    "name": "이상 감지 관제",
    "members": []
  }
];

export const SR_CATALOG: SrItem[] = [
  {
    "id": "SR-01",
    "name": "주문 관리 기능",
    "priority": "R"
  },
  {
    "id": "SR-02",
    "name": "재고 및 대상 박스 확인 기능",
    "priority": "RO(DB)"
  },
  {
    "id": "SR-03",
    "name": "로봇 작업 배정 기능",
    "priority": "R"
  },
  {
    "id": "SR-04",
    "name": "자율주행 및 운송 기능",
    "priority": "R"
  },
  {
    "id": "SR-05",
    "name": "다중 로봇 통행 관리 기능",
    "priority": "R"
  },
  {
    "id": "SR-06",
    "name": "로봇 상태 모니터링 기능",
    "priority": "R"
  },
  {
    "id": "SR-07",
    "name": "비전 인식 기능",
    "priority": "R"
  },
  {
    "id": "SR-08",
    "name": "정차 위치 확인 기능",
    "priority": "R"
  },
  {
    "id": "SR-09",
    "name": "로봇팔 상차·하차 기능",
    "priority": "R"
  },
  {
    "id": "SR-10",
    "name": "적재 및 작업 완료 확인 기능",
    "priority": "R"
  },
  {
    "id": "SR-11",
    "name": "주행 안전 제어 기능",
    "priority": "R"
  },
  {
    "id": "SR-12",
    "name": "로봇팔 안전 제어 기능",
    "priority": "O"
  },
  {
    "id": "SR-13",
    "name": "사용자 작업 제어 기능",
    "priority": "R"
  },
  {
    "id": "SR-14",
    "name": "오류 및 통신 장애대응 기능",
    "priority": "R"
  },
  {
    "id": "SR-15",
    "name": "오류 알림 기능",
    "priority": ""
  },
  {
    "id": "SR-16",
    "name": "하차 대기열 관리 기능",
    "priority": "R"
  },
  {
    "id": "SR-17",
    "name": "취소 및 반품 회수 관리 기능",
    "priority": "O"
  },
  {
    "id": "SR-18",
    "name": "작업 흐름 및 주문 완료 관리 기능",
    "priority": "R"
  },
  {
    "id": "SR-19",
    "name": "네트워크 분리 및 단일 제어권 관리 기능",
    "priority": "O"
  },
  {
    "id": "SR-20",
    "name": "명령 유효성 확인 및 옛날 권한 차단 기능",
    "priority": "O"
  },
  {
    "id": "SR-21",
    "name": "실제 동작 센서 확인 및 이력 기록 기능",
    "priority": "O"
  },
  {
    "id": "SR-22",
    "name": "가상환경 시뮬레이션 및 사전 검증 기능 (신규 롤)",
    "priority": "R"
  }
];

export const DECISIONS: Decision[] = [
  {
    "id": "D1",
    "title": "인터페이스 패키지 — fleet_msgs(미병합 브랜치 feature/setup-fleet-msgs-structure)를 cobot_interfaces 로 옮겨 확장할지, 접두사를 `cobot_` 로 할지",
    "status": "proposed",
    "blocks": "S1(P0) 이후 전부",
    "proposal": "fleet_msgs 를 cobot_interfaces 로 옮겨 확장한다. 접두사는 cobot_ 로 한다. team11 pinky_fleet_msgs(Apache-2.0) 원저작 표기를 복원한다.",
    "record": "docs/fms_decisions.md#d1",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D2",
    "title": "ROS_DOMAIN_ID — README 100 vs 팀 설계 10/12, 두 도메인의 교차점, 개발용 도메인 값",
    "status": "proposed",
    "blocks": "모든 노드 발견",
    "proposal": "팀 설계 제안: 10 = 실물 구동, 12 = Nav2. SR-19는 번호를 지정하지 않는다. 두 도메인의 교차점은 핑키 온보드 가드 하나(두 rclpy Context, S1 스파이크로 확인). README 의 100 은 개발·시뮬 전용.",
    "record": "docs/fms_decisions.md#d2",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D3",
    "title": "맵 정본, map_hash 입력 정의, 접근 자세, 맵 파일 위치",
    "status": "proposed",
    "blocks": "미션, 펜싱, ② 지도",
    "proposal": "정본 = map_shoe_store_1021_gate67 (Floor Map 1021 도면 + 아래 벽에 붙은 67 cm 게이트), 위치 = src/cobot_bringup/config/maps/, map_hash = sha256(sha256(pgm) ‖ sha256(LF 정규화 yaml)) 이고 입력은 install 된 파일, 작업점(work_pose)과 Nav2 정차점(approach_pose)을 나눈다. approach_pose 값·theta·맵 린트 반경 6 cm 는 초안. 팔 고정대는 맵에 없다.",
    "record": "docs/fms_decisions.md#d3",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D4",
    "title": "정지 계열 펜싱 예외, 통신 순단 복구의 무게",
    "status": "proposed",
    "blocks": "P2 가드 구현",
    "proposal": "정지 계열은 펜싱 판정이 거부여도 수행하고 워치독은 갱신하지 않는다. 통신 순단 복구는 SR-20 대로 epoch+1·DISARMED.",
    "record": "docs/fms_decisions.md#d4",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D5",
    "title": "복구 2단계 승인 설계의 독립 요소",
    "status": "proposed",
    "blocks": "⑤ 복구",
    "proposal": "Reconcile 항목별 확인 입력(attest) + APPROVE 뒤 최소 체류(초안 5 s). 2인 승인·비밀번호 재입력은 설정으로 고른다.",
    "record": "docs/fms_decisions.md#d5",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D6",
    "title": "HW E-STOP 판독 장치·배선·구역, 모터 전원 증거, 미설치 때 RUNNING 허용, 물리 완료 센서원",
    "status": "open",
    "blocks": "P2 HW 축, SR-10·13·21",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D7",
    "title": "PRD_3 OMX 상·하차를 수업 로컬 게이트(사람 수동 시작, 원격 트리거 없음) 대상으로 볼지",
    "status": "open",
    "blocks": "P4, 3.5, SR-09 시연 흐름",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D8",
    "title": "웹 화면 소스·빌드 결과 위치(CLAUDE.md §3 에 없음), Node/npm·fastapi·uvicorn 의존성 허락",
    "status": "proposed",
    "blocks": "P1 빌드 (화면 셸 위치)",
    "proposal": "2안: cobot_gui(ament_python) 의 web/ 폴더에 화면 소스(React·Vite)를 두고 빌드 결과 web/dist 를 setup.py data_files 로 설치한다. CLAUDE.md §3 에 web/ 규칙을 더한다. Node/npm 사용과 패키지 목록(docs/fms_web_dependencies.md), fastapi·uvicorn 허락은 팀 허락이 필요하다(D8 후속).",
    "record": "docs/fms_decisions.md#d8",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D9",
    "title": "역할 권한표 — 직원 정지 허용, 주문 취소 범위, 고객 화면 범위, 콘솔 만료 때 처리",
    "status": "open",
    "blocks": "P1 로그인, P2",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D10",
    "title": "카메라 구성·항공뷰 문제 상황 판별(충돌/접근 위험·낙하·정체 후보), 학습 합성·실영상 평가 출처, 제어 증거와 분리",
    "status": "open",
    "blocks": "④ 항공뷰 이상 후보, P1 영상, P3 별도 퇴장 증거원, P4 LeRobot 모드",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D11",
    "title": "하트비트 주기·ttl, 시계 허용 오프셋, 승인 만료·최소 체류·WS 끊김 시간 값",
    "status": "open",
    "blocks": "P2",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D12",
    "title": "3.3·3.4 데이터 전달 수단, PT-23 공식 녹화 도구 (방향: 팀원 앱을 3.7 로 채택, 관제 담당 지시 2026-10-22, 공지 전)",
    "status": "open",
    "blocks": "P4",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D13",
    "title": "서명 키의 생성·배포·교체 방법",
    "status": "open",
    "blocks": "P2",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D14",
    "title": "주문 상태 열거, 메뉴 트리에 주문 호출·재고·회수 화면 추가",
    "status": "open",
    "blocks": "P3",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D15",
    "title": "원장·로그 보존 기간과 백업, 영상 사람 촬영·보존·삭제 정책",
    "status": "open",
    "blocks": "P5, 4.4·4.5",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D16",
    "title": "Git 규칙 단일화, main 보호, CODEOWNERS",
    "status": "open",
    "blocks": "모든 PR",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D17",
    "title": "6.5 'SR-22' 의 정체, 메뉴 문서 정정(33 → 34, 3.7 은 팀원 앱으로 채택), SR 정본 = SR_v2",
    "status": "open",
    "blocks": "문서 정합",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D18",
    "title": "현장 실측 — Station PC 사양(OS·ROS·Python·LeRobot), OMEN-A 주소와 역할, AP 구성, RMW, 핑키 RTC·도메인",
    "status": "open",
    "blocks": "P1~P4",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D19",
    "title": "SR-02 재고 원장 — 소유자, 재고 원천과 입력 수단, 가점유·락 규칙",
    "status": "open",
    "blocks": "P3 SR-02",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D20",
    "title": "개인 레포 자산 반입 범위와 방법, 로봇 탑재 소스의 팀 레포 이관 여부",
    "status": "open",
    "blocks": "자산 재사용, P2 가드",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  },
  {
    "id": "D21",
    "title": "Sprint 2·3 의 실제 날짜와 P1 의 Sprint 2/3 경계",
    "status": "open",
    "blocks": "전체 일정",
    "proposal": "",
    "record": "",
    "decidedBy": "",
    "decidedOn": ""
  }
];

export const MENUS: Menu[] = [
  {
    "id": "1.1",
    "name": "전체 로봇 현황",
    "depth1": "01. 통합 관제",
    "screen": "screen_1",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-06",
      "SR-10",
      "SR-12"
    ],
    "srOriginal": [
      "SR-06",
      "SR-09"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "RobotStatus v2",
      "ArmStatus",
      "ArmMode"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "navigation",
    "decisions": [],
    "notes": [
      "갱신: 5 Hz 합류. 원천 시각 기준 1 s 를 넘으면 STALE(회색).",
      "P1 은 기존 RobotStatus(v1) 필드로 먼저 돈다. 이때 데이터 나이 기준은 v1 timestamp 다.",
      "초안: SR-09 로봇팔 상차·하차 기능을 빼고 SR-10 적재 및 작업 완료 확인 기능, SR-12 로봇팔 안전 제어 기능을 더했다. 팔 카드는 팔 동작이 아니라 퇴피·적재 확인과 안전 정지 상태를 보인다. SR-06 로봇 상태 모니터링 기능은 핑키 상태를 다룬다.",
      "초안: 데이터 담당은 핑키 카드 기준이다. 팔 카드(ArmStatus·ArmMode)는 manipulation 이 낸다."
    ],
    "branch": ""
  },
  {
    "id": "1.2",
    "name": "작업·미션 현황",
    "depth1": "01. 통합 관제",
    "screen": "screen_1",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-01",
      "SR-02",
      "SR-18"
    ],
    "srOriginal": [
      "SR-01",
      "SR-18"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "OrderStatus",
      "팔 작업 단계 요약",
      "InventoryState"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [
      "D14",
      "D19"
    ],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "P1 은 틀만 만든다. 실데이터는 P3.",
      "SR-18 6단계와 QR 결과·재고 가점유 상태(SR-02)를 보인다.",
      "초안: SR-02 재고 및 대상 박스 확인 기능을 더했다. 원문에는 SR-02 를 보이는 메뉴가 없었다."
    ],
    "branch": ""
  },
  {
    "id": "1.3",
    "name": "로봇 할당 현황",
    "depth1": "01. 통합 관제",
    "screen": "screen_1",
    "alsoShownIn": [],
    "phase": "P3",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-03",
      "SR-16"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "Assignment",
      "UnloadQueue"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "수동 재배정 버튼은 두지 않는다.",
      "배정 제외 사유(SR-03)와 하차 FIFO(SR-16)를 보인다."
    ],
    "branch": ""
  },
  {
    "id": "1.4",
    "name": "알림·이벤트 센터",
    "depth1": "01. 통합 관제",
    "screen": "screen_1",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-02",
      "SR-11",
      "SR-14",
      "SR-15"
    ],
    "srOriginal": [
      "SR-11",
      "SR-14",
      "SR-15"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "AlarmEvent"
    ],
    "commands": [
      "알림 확인 (표시만 바꾸고 원장에 기록)"
    ],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "알림 확인은 잠금 해제가 아니다.",
      "초안: SR-02 재고 및 대상 박스 확인 기능을 더했다. QR 이 주문 상품과 다를 때의 알림을 이 메뉴에 띄운다."
    ],
    "branch": ""
  },
  {
    "id": "1.5",
    "name": "운영 이력",
    "depth1": "01. 통합 관제",
    "screen": "screen_7",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-18",
      "SR-21"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "QueryAudit",
      "주문 이력"
    ],
    "commands": [
      "CSV 내보내기"
    ],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [],
    "notes": [
      "갱신: 조회할 때.",
      "P1 은 감사 원장 조회, 주문 이력은 P3.",
      "처리량 정의는 시뮬레이션 쪽 정의와 같게 맞춘다."
    ],
    "branch": ""
  },
  {
    "id": "2.1",
    "name": "통합 주행 지도",
    "depth1": "02. Pinky 주행",
    "screen": "screen_2",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-04",
      "SR-05",
      "SR-06"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "MapInfo",
      "지도 PNG",
      "RobotStatus pose",
      "LaneLeaseState"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "navigation",
    "decisions": [
      "D3"
    ],
    "notes": [
      "갱신: 위치 5 Hz, lease 는 변화가 생기면 바로.",
      "원문의 '67 cm 게이트' 는 맵 정본(D3 추천안)의 게이트다. 중앙 벽 아래 Y 0~0.67 m. 장애물 랙 2 가 벽에 붙어 있어 창고 쪽 실제 통행은 0.45 m 이고 게이트 정차점은 [1.25, 0.225] 다.",
      "map_hash 가 맞지 않으면 RED.",
      "초안: 데이터 담당은 위치·맵 기준이다. lease는 control_center가 낸다. 항공뷰는 위치·도킹 정본으로 사용하지 않는다."
    ],
    "branch": ""
  },
  {
    "id": "2.2",
    "name": "로봇별 주행 상태",
    "depth1": "02. Pinky 주행",
    "screen": "screen_2",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-06",
      "SR-08"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "RobotStatus v2"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "navigation",
    "decisions": [],
    "notes": [
      "② 지도의 인스펙터 패널이다.",
      "갱신: 5 Hz.",
      "P1 은 v1 필드로 먼저 돈다. v2 필드(도킹 오차·BASE_HOLD, SR-08)는 P2."
    ],
    "branch": ""
  },
  {
    "id": "2.3",
    "name": "목표점·경로 관리",
    "depth1": "02. Pinky 주행",
    "screen": "screen_2",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-04"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "MapInfo.waypoints"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "navigation",
    "decisions": [
      "D3"
    ],
    "notes": [
      "② 지도 위 레이어다. 읽기 전용이다.",
      "웨이포인트는 패키지 config YAML 을 PR 로 고쳐서 바꾼다. 화면에서 고치지 않는다.",
      "갱신: 기동할 때.",
      "접근 자세가 없는 웨이포인트에는 경고를 띄운다."
    ],
    "branch": ""
  },
  {
    "id": "2.4",
    "name": "주행 미션 관리",
    "depth1": "02. Pinky 주행",
    "screen": "screen_2",
    "alsoShownIn": [],
    "phase": "P2",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-04"
    ],
    "srOriginal": [
      "SR-04",
      "SR-17"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "OrderStatus",
      "CommandAck",
      "CompletionEvidence"
    ],
    "commands": [
      "웨이포인트 미션 보내기 (관제사 + 콘솔 + MANUAL)",
      "미션 취소"
    ],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [
      "D3",
      "D13"
    ],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "원시 좌표는 보내지 않는다. 배정·lease 를 거친다.",
      "ACK·물리 증거(CommandAck·CompletionEvidence)는 navigation 이 낸다.",
      "초안: SR-17 빈 박스 및 반품 회수 관리 기능을 뺐다. 우선순위 R 이고, 회수는 이후 단계(S6)에서 다룬다. 회수 화면을 정할 때(D14) 다시 넣는다.",
      "초안: 데이터 담당은 미션을 내는 control_center 로 두었다."
    ],
    "branch": ""
  },
  {
    "id": "2.5",
    "name": "주행 이력·이상 상태",
    "depth1": "02. Pinky 주행",
    "screen": "screen_7",
    "alsoShownIn": [],
    "phase": "P3",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-11",
      "SR-14",
      "SR-18"
    ],
    "srOriginal": [
      "SR-14",
      "SR-18"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "QueryAudit (주행 이벤트)",
      "AlarmEvent"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [
      "D15"
    ],
    "notes": [
      "갱신: 조회할 때.",
      "궤적 원시 저장은 보존 결정(D15) 뒤에 한다.",
      "초안: SR-11 주행 안전 제어 기능을 더했다. 이 메뉴가 보이는 장애물 감속·정지 이벤트가 SR-11 의 결과다."
    ],
    "branch": ""
  },
  {
    "id": "3.1",
    "name": "로봇팔 상태 모니터링",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [],
    "phase": "P4",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-09",
      "SR-10",
      "SR-12"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "ArmStatus",
      "ArmMode"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "manipulation",
    "decisions": [
      "D18"
    ],
    "notes": [
      "갱신: 5 Hz.",
      "ArmMode 가 LEROBOT_EXCLUSIVE 이면 ArmStatus 가 오지 않는다. 관절 값은 STALE(회색)로 두고 배너를 띄운다.",
      "Station PC 가 Jazzy 가 아니면 이 메뉴는 뒤로 밀린다 (D18, docs/fms_roadmap.md S5 의 D18 분기)."
    ],
    "branch": ""
  },
  {
    "id": "3.2",
    "name": "작업 시퀀스 관리",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [],
    "phase": "P4",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-09",
      "SR-10"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "ArmStatus.work_step (MANUAL_START)",
      "HandoverTask v2 feedback/result (FMS_TRIGGER)"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "manipulation",
    "decisions": [
      "D7",
      "D18"
    ],
    "notes": [
      "조회만 한다. 갱신: 변화가 생기면 바로.",
      "6단계(RETRACTING 포함)를 보인다. LeRobot 모드에서는 단계 정보가 없다(STALE).",
      "D7 결정 전 기본값은 MANUAL_START 다."
    ],
    "branch": ""
  },
  {
    "id": "3.3",
    "name": "모방학습 데이터 수집",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [],
    "phase": "P4",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [],
    "srOriginal": [
      "SR-09",
      "SR-19",
      "UR-04"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "DatasetSummary (세션 상태)"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "manipulation",
    "decisions": [
      "D12"
    ],
    "notes": [
      "③ 화면의 탭(축소판)이다.",
      "녹화는 Station PC 에서 사람이 한다. 대시보드는 녹화 명령을 만들거나 나르지 않고 안내만 한다.",
      "갱신: 변화가 생길 때.",
      "초안: 원문 매핑을 모두 뺐다. 데이터 수집을 요구하는 SR 이 없다. SR-09 로봇팔 상차·하차 기능은 팔 동작을, SR-19 네트워크 분리 및 단일 제어권 관리 기능은 네트워크와 단일 기록자를 다룬다. UR ID 는 sr 에 넣지 않는다. 선택 기능이다."
    ],
    "branch": ""
  },
  {
    "id": "3.4",
    "name": "데이터셋 관리",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [],
    "phase": "P4",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [],
    "srOriginal": [
      "SR-21"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "DatasetSummary (검수 결과·태그·지문)"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "manipulation",
    "decisions": [
      "D12"
    ],
    "notes": [
      "③ 화면의 탭(축소판)이다.",
      "지문이 맞지 않으면 표시를 거부한다. 다시 보기는 Station PC 도구에서 한다.",
      "초안: SR-21 실제 동작 센서 확인 및 이력 기록 기능을 뺐다. SR-21 의 대상은 명령과 물리 동작의 실행 이력이고, 데이터셋이 아니다."
    ],
    "branch": ""
  },
  {
    "id": "3.5",
    "name": "작업 실행·재생",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [],
    "phase": "P4",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-09"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "도착 확정",
      "팔 준비 상태"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "manipulation",
    "decisions": [
      "D7",
      "D18"
    ],
    "notes": [
      "명령은 없다. '작업 준비' 표시와 수동 시작 안내만 한다. 도착 1회에 1회 표시한다.",
      "초안: SR-09 로봇팔 상차·하차 기능은 두되 웹에서 팔 동작을 시작하지 않는다. SR-09 에 웹 트리거 요구가 없고, 팔 동작은 SR-12·SR-13·SR-19 의 제약을 받는다.",
      "초안: 데이터 담당은 팔 준비 상태 기준이다. 도착 확정은 control_center 가 낸다."
    ],
    "branch": ""
  },
  {
    "id": "3.6",
    "name": "작업 이력",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [
      "screen_7"
    ],
    "phase": "P4",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-18",
      "SR-21"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "QueryAudit"
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [],
    "notes": [
      "③ 은 최근 10건, ⑦ 은 전체를 보인다.",
      "ACK 와 물리 증거를 나눠 보인다.",
      "초안: 주 화면을 ③ 으로 두었다."
    ],
    "branch": ""
  },
  {
    "id": "3.7",
    "name": "로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오",
    "depth1": "03. OMX 작업",
    "screen": "screen_3",
    "alsoShownIn": [],
    "phase": "P4",
    "status": "planned",
    "impl": "external",
    "implRef": "tool/omx-ai_record_dashboard 브랜치 e78dd9a (omx_recoder/, PySide6 데스크톱 앱). main 에 통합 전이다.",
    "sr": [],
    "srOriginal": [
      "SR-09",
      "SR-10",
      "SR-19",
      "SR-20",
      "SR-21",
      "UR-04",
      "UR-26"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "앱 안의 세션 상태, LeRobot 데이터셋 폴더 (success/fail). FMS 토픽이 아니다."
    ],
    "commands": [],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "manipulation",
    "dataOwner": "manipulation",
    "decisions": [
      "D12",
      "D17",
      "D18"
    ],
    "notes": [
      "팀원이 만든 Station PC 데스크톱 앱(omx_recoder)을 3.7 로 채택한다 (관제 담당 지시 2026-10-22). ③ 웹 화면의 일부가 아니다. ③ 에는 3.3·3.4 요약 탭과 앱 안내만 둔다.",
      "이 앱은 FMS 명령 경로를 쓰지 않는다. 앱 안의 조작(BringUp, 녹화, Init/Rest 자세 저장, Servo OFF, HF 업로드)은 앱 프로세스가 팔 포트를 직접 연다.",
      "영상: 앱은 Station PC 에 꽂힌 카메라(wrist·top)를 LeRobot OpenCVCamera 로 직접 받아 녹화한다. 영상을 밖으로 내보내는 코드(LiveKit·RTSP·MediaMTX)는 없다. 통합에 영상 전송은 필요 없다.",
      "초안: 앱이 연 카메라는 보통 다른 프로세스가 같이 받을 수 없다. 웹 4.x 의 MediaMTX 영상과 같은 카메라를 나눠 쓰려면 앱이 받은 프레임을 내보내는 방법을 따로 정해야 한다 (D12).",
      "초안: 화면 담당과 데이터 담당을 매니퓰레이터로 두었다. 운용 관제는 앱 안내·요약 연결을 맡고 Station PC 앱 구현은 기존 매니퓰레이터 담당이 유지한다.",
      "통합 전 조건 (docs/fms_branch_compatibility_review.md): 팔 배타 제어(ArmMode LEROBOT_EXCLUSIVE), Servo OFF 는 긴급 정지가 아니다(정상 종료와 정지를 나눈다), 실행 환경 차이(Ubuntu 22.04 + 별도 LeRobot 환경, D18).",
      "초안: 원문 SR 매핑을 모두 뺐다. SR_v2 v13 에는 원격 텔레옵·모터 파라미터 제어·모방학습 데이터 수집을 요구하는 SR 이 없다. 원문의 SR/UR 은 sr_original 에 보존한다. 선택 기능이다 (D17).",
      "공식 녹화 도구 방향은 이 앱이다. D12 는 공지 전이라 open 이다.",
      "웹에서 팔을 움직이는 원격 텔레옵은 이 앱과 별개이고 이후(P5) 조건부 검토 항목이다."
    ],
    "branch": ""
  },
  {
    "id": "4.1",
    "name": "실시간 카메라 모니터링",
    "depth1": "04. 비전 모니터링",
    "screen": "screen_4",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-07",
      "SR-11"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "MediaMTX WHEP 스트림",
      "CameraHealth (P1 은 MediaHealth, health=UNKNOWN)"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "vision",
    "decisions": [
      "D10"
    ],
    "notes": [
      "갱신: 영상은 실시간, health 는 1 Hz.",
      "P1 은 USB 데스크 웹캠 1대를 먼저 붙인다. 폰 카메라는 송출 수단(D10)이 정해진 뒤. 3대는 P3.",
      "프레임 나이가 200 ms 를 넘거나 같은 프레임이 반복되면(동결) Amber·Red (SR-07).",
      "바닥 15 cm 뷰는 자리만 둔다 (D10).",
      "초안: 데이터 담당은 CameraHealth 기준이다. 시청 스트림(MediaMTX)은 gui, P1 MediaHealth 는 control_center 가 낸다.",
      "2026-10-24 범위: 항공뷰는 문제 상황 판별용 관찰 입력이다. 위치 추적·도킹 완료·통로 퇴장 증거를 이 입력에 요구하지 않는다."
    ],
    "branch": ""
  },
  {
    "id": "4.2",
    "name": "카메라 선택·설정",
    "depth1": "04. 비전 모니터링",
    "screen": "screen_4",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-07"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "/api/v1/cameras"
    ],
    "commands": [
      "뷰 전환 (화면 안에서만)"
    ],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "gui",
    "decisions": [
      "D10"
    ],
    "notes": [
      "해상도·fps 는 바꾸지 않는다. 읽기만 한다. 갱신: 1 Hz.",
      "팔 카메라 640×480@30 계약을 건드리지 않는다.",
      "초안: 데이터 담당은 게이트웨이 API 를 내는 gui 로 두었다."
    ],
    "branch": ""
  },
  {
    "id": "4.3",
    "name": "비전 인식·이벤트 결과",
    "depth1": "04. 비전 모니터링",
    "screen": "screen_4",
    "alsoShownIn": [],
    "phase": "P3",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-07",
      "SR-11"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "VisionEvent (기존 계약; 새 이상 판별 결과의 필드 확정은 별도)",
      "항공뷰 이상 후보 결과·출처·모델 버전·시각 (계약 초안)"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "vision",
    "decisions": [
      "D10"
    ],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "캡처 시각 기준으로 오버레이한다. 대시보드는 판정하지 않는다.",
      "원문의 '바코드' 는 QR 로 고친다 (SR-02·07).",
      "2026-10-24 최소 목표: 충돌·접근 위험, 박스 낙하, 장시간 정체 세 후보의 문제 상황 여부를 판별한다. 클래스 경계·정체 시간·임계치는 미정이다.",
      "정상 영상과 시뮬레이션 이상 데이터의 합성으로 학습을 준비한다. 학습·합성 결과는 실제 운영 판정과 구분하며, 모델 결과만으로 출발·회수·정지를 자동 실행하지 않는다."
    ],
    "branch": ""
  },
  {
    "id": "4.4",
    "name": "이미지 캡처·영상 녹화",
    "depth1": "04. 비전 모니터링",
    "screen": "screen_4",
    "alsoShownIn": [],
    "phase": "P5",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [],
    "commands": [
      "디버그 캡처 (기본 꺼짐)"
    ],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "vision",
    "decisions": [
      "D15"
    ],
    "notes": [
      "④ 화면의 탭이다. 지금은 자리만 둔다.",
      "사람 촬영·보존 정책(D15)이 먼저다.",
      "원문 SR 미명시 (추가 후보).",
      "초안: 데이터 담당 vision.",
      "학습 원본 영상 보존과 출처 기록은 비전·시뮬 담당이 맡고 관제는 필요한 결과만 본다. 웹 라벨링 도구 신규 구현은 최소 범위 밖이다."
    ],
    "branch": ""
  },
  {
    "id": "4.5",
    "name": "영상·이미지 기록 조회",
    "depth1": "04. 비전 모니터링",
    "screen": "screen_7",
    "alsoShownIn": [],
    "phase": "P5",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "vision",
    "decisions": [
      "D15"
    ],
    "notes": [
      "⑦ 화면의 탭이다. 지금은 자리만 둔다. 4.4 와 같은 정책을 따른다.",
      "원문 SR 미명시 (추가 후보).",
      "초안: 데이터 담당 vision."
    ],
    "branch": ""
  },
  {
    "id": "5.1",
    "name": "제어권·운용 모드 관리",
    "depth1": "05. 제어·안전",
    "screen": "screen_5",
    "alsoShownIn": [],
    "phase": "P2",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-13"
    ],
    "srOriginal": [
      "SR-13",
      "SR-19"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "FleetSafetyState (콘솔·모드)"
    ],
    "commands": [
      "콘솔 획득",
      "콘솔 갱신",
      "콘솔 반납",
      "AUTO/MANUAL 전환"
    ],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [
      "D9",
      "D11",
      "D13"
    ],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "콘솔 토큰은 FMS 안의 운영자 잠금이다. SR-19 네트워크 분리 및 단일 제어권 관리 기능의 단일 기록자(장비 단위)가 아니다.",
      "초안: 그래서 원문의 SR-19 를 뺐다."
    ],
    "branch": ""
  },
  {
    "id": "5.2",
    "name": "수동 조작 (Teleop)",
    "depth1": "05. 제어·안전",
    "screen": "screen_2",
    "alsoShownIn": [],
    "phase": "P5",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [],
    "srOriginal": [
      "SR-13"
    ],
    "srUnconfirmed": [],
    "dataSources": [],
    "commands": [
      "핑키 조이스틱 + 데드맨 (관제사 전용, 이후)"
    ],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "navigation",
    "decisions": [],
    "notes": [
      "② 화면의 비활성 자리다.",
      "속도 명령 인터페이스가 아직 없다. 인터페이스 PR 과 데드맨 설계가 먼저다.",
      "초안: 대상은 핑키로 해석했다. 원문 대조표가 이 메뉴를 '비상 도킹 보정용' 조이스틱이라 적었다.",
      "초안: SR-13 사용자 작업 제어 기능을 뺐다. SR-13 은 역할별 권한, 일시정지·재개·비상정지를 다루고 조이스틱 조작은 없다.",
      "초안: 데이터 담당은 속도 명령을 받는 navigation 으로 두었다."
    ],
    "branch": ""
  },
  {
    "id": "5.3",
    "name": "일시정지·재개",
    "depth1": "05. 제어·안전",
    "screen": "screen_1",
    "alsoShownIn": [],
    "phase": "P2",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-13"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "FleetSafetyState"
    ],
    "commands": [
      "PAUSE (토큰 불필요)",
      "RESUME (관제사 + 콘솔)"
    ],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [
      "D4",
      "D9",
      "D11",
      "D13"
    ],
    "notes": [
      "① 헤더에 늘 보이는 버튼이다.",
      "정지 지연 200 ms 는 아직 잰 적 없는 목표다."
    ],
    "branch": ""
  },
  {
    "id": "5.4",
    "name": "정지 요청·복구 관리",
    "depth1": "05. 제어·안전",
    "screen": "screen_5",
    "alsoShownIn": [
      "screen_1"
    ],
    "phase": "P2",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-11",
      "SR-13",
      "SR-14"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "FleetSafetyState",
      "ReconcileReport"
    ],
    "commands": [
      "소프트 정지 래치 (토큰 불필요)",
      "RESET",
      "Reconcile 항목별 확인",
      "승인(APPROVE)",
      "START"
    ],
    "controlArea": "operational",
    "controlOwner": "operation_control",
    "screenOwner": "operation_control",
    "dataOwner": "control_center",
    "decisions": [
      "D4",
      "D5",
      "D6",
      "D9",
      "D11",
      "D13"
    ],
    "notes": [
      "① 헤더에는 정지 버튼, ⑤ 에는 복구 절차를 둔다.",
      "RESET 은 START 가 아니다. RESET → Reconcile → 승인 → 최소 체류 → START 순서다.",
      "초안: 주 화면을 ⑤ 로 두었다."
    ],
    "branch": ""
  },
  {
    "id": "5.5",
    "name": "안전·장애 상태 모니터링",
    "depth1": "05. 제어·안전",
    "screen": "screen_4",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-10",
      "SR-11",
      "SR-12",
      "SR-14"
    ],
    "srOriginal": [
      "SR-11",
      "SR-12",
      "SR-14"
    ],
    "srUnconfirmed": [],
    "dataSources": [
      "HwEstopState",
      "motor_power_present",
      "RobotStatus",
      "ArmStatus",
      "ArmMode",
      "LaneLeaseState",
      "AlarmEvent"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [
      "D6"
    ],
    "notes": [
      "갱신: 변화가 생기면 바로 + 2 Hz.",
      "P1 은 UNKNOWN 표시만 한다. 나머지는 P2.",
      "3회 재시도는 오류 유형별이다. 통신 두절은 즉시 로컬 정지다.",
      "HW E-STOP 배지와 전원 증거는 다른 행으로 보인다.",
      "초안: SR-10 적재 및 작업 완료 확인 기능을 더했다. 팔 퇴피(ARM_RETRACT_SAFE) 확인은 핑키 출발을 막는 인터록이므로 안전 상태로 함께 보인다.",
      "초안: 데이터 담당은 HW E-STOP 판독·알림 기준이다. 전원 증거는 navigation, 팔 상태는 manipulation 이 낸다."
    ],
    "branch": ""
  },
  {
    "id": "5.6",
    "name": "제어 명령·ACK 이력",
    "depth1": "05. 제어·안전",
    "screen": "screen_5",
    "alsoShownIn": [],
    "phase": "P2",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-20",
      "SR-21"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "CommandAck",
      "CompletionEvidence",
      "QueryAudit"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [
      "D6"
    ],
    "notes": [
      "갱신: 변화가 생기면 바로 보낸다.",
      "'ACK 있음 · 물리 미완료' 를 경고로 보인다.",
      "초안: 데이터 담당은 원장 기준이다. ACK·물리 증거는 navigation·manipulation 이 낸다."
    ],
    "branch": ""
  },
  {
    "id": "6.1",
    "name": "로봇·장치 연결 현황",
    "depth1": "06. 시스템·진단",
    "screen": "screen_6",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-06",
      "SR-14",
      "SR-19"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "DiagSnapshot.devices"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [
      "D18"
    ],
    "notes": [
      "갱신: 0.5 Hz.",
      "SR-19 계획 대역과 실제 주소를 나란히 보인다. 실제 주소 값은 레포에 적지 않는다."
    ],
    "branch": ""
  },
  {
    "id": "6.2",
    "name": "ROS 2·FMS 통신 상태",
    "depth1": "06. 시스템·진단",
    "screen": "screen_6",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-19",
      "SR-20"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "DiagSnapshot.topics (발행자 수, 실측 hz, single_writer_state)",
      "장비별 도메인 자기 보고"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [
      "D18"
    ],
    "notes": [
      "갱신: 0.5 Hz.",
      "도메인·네트워크 설정은 바꾸지 않는다. 보기만 한다.",
      "비교 기준이 되는 도메인 값은 D2(전체를 막는 결정이라 decisions 에는 적지 않는다)를 따른다.",
      "다른 도메인은 잴 수 없으므로 '보고 없음' 을 따로 보인다."
    ],
    "branch": ""
  },
  {
    "id": "6.3",
    "name": "노드·서비스 상태",
    "depth1": "06. 시스템·진단",
    "screen": "screen_6",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-14"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "DiagSnapshot.nodes"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [],
    "notes": [
      "갱신: 0.5 Hz.",
      "특정 스택(MoveIt 등)을 가정하지 않는다. 실제 ROS 그래프를 보인다."
    ],
    "branch": ""
  },
  {
    "id": "6.4",
    "name": "시스템 로그·오류 진단",
    "depth1": "06. 시스템·진단",
    "screen": "screen_6",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-14",
      "SR-15",
      "SR-21"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "/rosout (fleet_monitor)"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "control_center",
    "decisions": [],
    "notes": [
      "갱신: 스트림.",
      "재시도 3회를 넘긴 예외를 보인다."
    ],
    "branch": ""
  },
  {
    "id": "6.5",
    "name": "시뮬레이션·기능 검증",
    "depth1": "06. 시스템·진단",
    "screen": "screen_6",
    "alsoShownIn": [],
    "phase": "P5",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [
      "SR-22"
    ],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "시뮬 보고 JSON (USB 반입, 정적 읽기)"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "",
    "decisions": [
      "D17"
    ],
    "notes": [
      "⑥ 화면의 탭이다. [SIM] 배지를 늘 띄운다.",
      "실물 명령 경로는 없다.",
      "SR-22는 SR_v2 v13에서 확인했다. D17의 메뉴 수·명칭 정정은 별도로 남는다.",
      "초안: 데이터 담당은 비워 두었다. 시뮬레이션을 맡는 역할이 README 팀 구성 표에 없다. 팀이 정한다.",
      "이상 감지용 합성 데이터 출처, 정상 실영상 보류 평가, 오탐·미탐·지연 결과를 표시한다. 시뮬·학습 실행 담당과 관제 결과 표시 담당은 별도다."
    ],
    "branch": ""
  },
  {
    "id": "6.6",
    "name": "시스템 설정",
    "depth1": "06. 시스템·진단",
    "screen": "screen_8",
    "alsoShownIn": [],
    "phase": "P1",
    "status": "planned",
    "impl": "none",
    "implRef": "",
    "sr": [],
    "srOriginal": null,
    "srUnconfirmed": [],
    "dataSources": [
      "/api/v1/config (YAML 값, sha256, git rev)"
    ],
    "commands": [],
    "controlArea": "anomaly",
    "controlOwner": "anomaly_monitoring",
    "screenOwner": "anomaly_monitoring",
    "dataOwner": "gui",
    "decisions": [],
    "notes": [
      "읽기 전용이다. 값은 YAML 을 PR 로 고쳐서 바꾼다. 화면은 바꾸는 방법만 안내한다.",
      "SR_v2의 TTL 5000 ms와 설계 제안(워치독 200 ms, 배터리 20 %, 감속 0.8 m, 정지 0.25~0.4 m)을 분리해 표시한다.",
      "원문 SR 매핑 없음 (운영 파라미터).",
      "초안: 데이터 담당은 게이트웨이 API 를 내는 gui 로 두었다."
    ],
    "branch": ""
  }
];
