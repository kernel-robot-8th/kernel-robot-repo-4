import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Menu } from "@/shell/types";

interface Eli5Meta {
  analogy: string;
  concept: string;
  flow: {
    input: string;
    process: string;
    output: string;
  };
  uiComponents: string[];
  safetyCheck: string;
}

const ELI5_REGISTRY: Record<string, Eli5Meta> = {
  "1.1": {
    analogy: "🚦 달리는 미니카들의 실시간 신호등 & 위치 전광판",
    concept: "모든 핑키 로봇과 로봇팔의 배터리, 현재 좌표, 작업 상태를 5Hz 속도로 한눈에 모아 보여주는 종합 현황판이에요.",
    flow: {
      input: "RobotStatus v2 (좌표/배터리/모드), ArmStatus (팔 각도/상태)",
      process: "1초 이상 소식 없으면 회색(STALE) 처리, 모드별 색상 분류",
      output: "로봇별 상태 카드 (3열 그리드), 위치(X,Y,Yaw), 배터리 게이지",
    },
    uiComponents: ["로봇 상태 카드 그리드", "STALE 타임아웃 뱃지", "배터리 & 모드 톤 알약(Pill)"],
    safetyCheck: "1초 이상 데이터 수신 없으면 무조건 '통신 지연(STALE)' 경고 표시",
  },
  "1.2": {
    analogy: "📋 신발 상자 배달 주문서와 진행 단계 체크리스트",
    concept: "손님이 주문한 신발 상자를 찾아서 싣고 배달하는 6단계 여정이 어디까지 진행되었는지 보여주는 주문 현황판이에요.",
    flow: {
      input: "OrderStatus (주문 진행 단계), InventoryState (창고 재고 수량)",
      process: "주문 접수 ➔ 상차 ➔ 이동 ➔ 하차 ➔ 완료 6단계 진행률 계산",
      output: "주문 진행 바(Progress Bar), 현재 배달 중인 로봇 매핑 표",
    },
    uiComponents: ["6단계 스텝 진행 바", "주문-로봇 매핑 카드", "재고 수량 카운터"],
    safetyCheck: "상차 실패나 QR 불일치 시 붉은색 예외 알림 팝업",
  },
  "1.3": {
    analogy: "👮 로봇 교통정리관의 일감 배정 게시판",
    concept: "어떤 로봇이 신발을 가지러 가고, 어떤 로봇이 충전소에서 쉬고 있는지 배정 상태를 교통정리해 주는 화면이에요.",
    flow: {
      input: "Assignment (배정 내역), UnloadQueue (하차 대기열)",
      process: "대기 로봇 중 배터리 넉넉하고 가장 가까운 로봇 우선순위 정렬",
      output: "대기 로봇 목록, 주행 중인 로봇 목록, 하차장 대기열 순번",
    },
    uiComponents: ["로봇 할당 테이블", "대기열 큐(Queue) 시각화", "우선순위 뱃지"],
    safetyCheck: "배터리 20% 미만 로봇은 신규 미션 배정 자동 차단",
  },
  "1.4": {
    analogy: "🚨 로봇이 아프거나 길 막혔을 때 울리는 119 비상벨 창",
    concept: "로봇이 장애물을 만나 멈췄거나 긴급 정지 버튼이 눌렸을 때 관제사에게 즉시 알리고 소리를 울리는 경보 센터예요.",
    flow: {
      input: "AlarmEvent (위험 등급: WARN, ERROR, CRITICAL)",
      process: "치명적(CRITICAL) 알림 최상단 고정, 확인된 알림 음소거",
      output: "시간순 알림 타임라인, 소리 토글 버튼, 경보 인지(ACK) 버튼",
    },
    uiComponents: ["등급별 색상 배너(레드/오렌지/옐로우)", "경보 확인(ACK) 버튼", "이벤트 히스토리 로그"],
    safetyCheck: "CRITICAL 등급 발생 시 관리자가 '확인'을 누를 때까지 깜빡임 유지",
  },
  "1.5": {
    analogy: "📖 오늘 하루 로봇들이 달린 영수증 일기장",
    concept: "오늘 총 몇 개의 상자를 배달했고, 에러는 몇 번 났는지 과거 기록을 찾아보고 엑셀(CSV)로 내려받는 도서관이에요.",
    flow: {
      input: "QueryAudit (과거 이력 DB 쿼리), 주문 완료 내역",
      process: "날짜 및 로봇 ID 필터링, 성공률/평균 배달 시간 통계 집계",
      output: "날짜별 이력 데이터 테이블, CSV 다운로드 버튼",
    },
    uiComponents: ["기간/로봇 필터 바", "이력 데이터 테이블", "CSV 내보내기 버튼"],
    safetyCheck: "대량 쿼리 시 페이징(20건씩) 처리로 브라우저 멈춤 방지",
  },
  "2.1": {
    analogy: "🗺️ 바닥 지도 위에서 로봇들이 움직이는 2D 실시간 내비게이션",
    concept: "실제 매장 바닥 지도(PNG) 위에 로봇 4대의 위치와 목적지 경로 선을 게임 맵처럼 실시간으로 그려주는 화면이에요.",
    flow: {
      input: "MapInfo (67cm 정본 맵), RobotStatus.pose, LaneLeaseState",
      process: "실제 미터 좌표(X,Y)를 캔버스 픽셀로 변환, 차선 점유 색칠",
      output: "Canvas/SVG 인터랙티브 맵, 로봇 아이콘, 주행 궤적 선",
    },
    uiComponents: ["지도 캔버스 뷰포트", "로봇 실시간 마커", "충돌 회피 안전 구역(차선) 표시"],
    safetyCheck: "맵 지문(sha256)이 불일치하면 '지도 버전 오류' 경고 레이어 표시",
  },
  "2.2": {
    analogy: "🔍 특정 로봇 하나만 집중해서 따라가는 돋보기 카메라",
    concept: "1번 로봇이나 2번 로봇 하나를 찍어서 속도계, 모터 온도, 현재 바라보는 방향(각도)을 자세히 보여주는 정밀 계기판이에요.",
    flow: {
      input: "RobotStatus v2 (선속도 v, 각속도 w, 바퀴 회전수)",
      process: "속도(m/s) 게이지 변환, 주행 방향 화살표(Compass) 렌더링",
      output: "원형 속도계 게이지, 나침반 헤딩 뷰, 바퀴 모터 전압 그래프",
    },
    uiComponents: ["속도/회전 각도 다이얼 게이지", "로봇 단독 상세 패널", "모터 진단 수치"],
    safetyCheck: "제한 속도(0.5 m/s) 초과 시 속도계 붉은색 경고 표시",
  },
  "2.3": {
    analogy: "📍 바닥에 테이프로 '정차장', '충전소' 이름표 붙이기",
    concept: "매장 안의 8개 중요 지점(U1, U2 작업대, 충전소 등)의 좌표와 이름을 관리하고 새 정차점을 추가하는 지도 편집기예요.",
    flow: {
      input: "MapInfo.waypoints (경유지 이름과 X,Y,목표 각도)",
      process: "경유지 목록 파싱 및 지도 상의 좌표 핀(Pin) 매핑",
      output: "경유지 목록 표, 위치 편집 다이얼로그, 구역별 진입 규칙",
    },
    uiComponents: ["웨이포인트 목록 테이블", "좌표 편집 인풋 폼", "구역(Zone) 속성 태그"],
    safetyCheck: "벽이나 통로 밖 금지 구역에 좌표 설정 시 유효성 에러 발생",
  },
  "2.4": {
    analogy: "🎮 무전기로 로봇에게 '너 저기로 출발해!' 명령하기",
    concept: "관제사가 마우스 클릭으로 '핑키야, B작업대로 가!' 하고 목표 지점을 찍어 보내고 로봇의 응답을 확인하는 명령창이에요.",
    flow: {
      input: "관제사 목표 클릭 ➔ Navigation Goal 메시지 발행",
      process: "수동 모드 확인(MANUAL 토글) ➔ 명령 전송 ➔ ACK 확인 수신",
      output: "목적지 전송 버튼, 경로 취소(ABORT) 버튼, 로봇 접수 상태",
    },
    uiComponents: ["목적지 선택 드롭다운", "명령 전송/취소 버튼", "명령 접수(ACK) 상태창"],
    safetyCheck: "비상 정지 상태거나 자동(AUTO) 모드 중에는 수동 출발 버튼 비활성화",
  },
  "2.5": {
    analogy: "📼 로봇이 왜 코너에서 헤맸는지 돌려보는 블랙박스",
    concept: "로봇이 주행하다가 미끄러졌거나 경로를 이탈했던 순간의 경로 기록과 센서 로그를 되감기해서 분석하는 분석실이에요.",
    flow: {
      input: "QueryAudit (주행 궤적 로그), AlarmEvent (센서 이상 시점)",
      process: "시간대별 실제 경로 vs 계획 경로 오차 거리(cm) 계산",
      output: "오차 거리 시계열 차트, 이상 발생 지점 지도 오버레이",
    },
    uiComponents: ["타임라인 슬라이더", "오차 거리 그래프", "이상 구간 맵 하이라이트"],
    safetyCheck: "위치 추정 오차가 10cm 이상 지속된 구간은 붉은색 궤적으로 강조",
  },
  "3.1": {
    analogy: "🦾 로봇팔 관절 6개가 건강한지 재보는 스마트 체온계",
    concept: "로봇팔의 6개 모터가 과열되지 않았는지, 각도가 정상 범위인지, 토크(힘)가 켜져 있는지 감시하는 로봇팔 종합 계기판이에요.",
    flow: {
      input: "ArmStatus (6개 관절 각도, 모터 온도), ArmMode (HOLD/PAUSE/RUN)",
      process: "모터 전류 및 온도 정상 범위(60도 미만) 검사, 모드 파싱",
      output: "6관절 바(Bar) 차트, 그리퍼 열림/닫힘 상태 아이콘, 모드 뱃지",
    },
    uiComponents: ["6관절 실시간 각도/온도 바", "그리퍼 개폐 상태 표시기", "팔 모드 뱃지"],
    safetyCheck: "모터 온도 65도 초과 시 즉시 토크 차단 경보 점등",
  },
  "3.2": {
    analogy: "📦 신발 상자 집어 올리기 1단계, 2단계 지휘봉",
    concept: "핑키가 도착했을 때 로봇팔이 '상자 집기 ➔ 들어올리기 ➔ 핑키 등에 얹기' 작업을 순서대로 진행하도록 지휘하는 관제창이에요.",
    flow: {
      input: "ArmStatus.work_step (단계 상태), HandoverTask v2",
      process: "핑키 정차 확인(핑키 STOP) ➔ 집기 허가 ➔ 완료 신호 핸드셰이크",
      output: "작업 단계 스텝 인디케이터, 단계 강제 진행/정지 버튼",
    },
    uiComponents: ["상·하차 스텝 플로우", "단계별 타임아웃 타이머", "수동 트리거 버튼"],
    safetyCheck: "핑키가 완전히 멈추기 전(HOLD 확정 전)에는 로봇팔 작동 트리거 금지",
  },
  "3.3": {
    analogy: "📚 로봇팔이 보고 배울 모범 답안 비디오 모음집",
    concept: "사람이 손으로 로봇팔을 움직여 모아둔 신발 상자 집기 시연 데이터가 몇 편(에피소드) 모였는지 보여주는 도서관 목록이에요.",
    flow: {
      input: "DatasetSummary (에피소드 수, 프레임 수, 데이터 용량)",
      process: "성공 에피소드 비율 계산, 총 학습 가능 시간 집계",
      output: "에피소드 통계 카드, 데이터셋 버전 태그, 다운로드 링크",
    },
    uiComponents: ["에피소드 카운터 카드", "데이터셋 품질 요약 바", "작업 태그 필터"],
    safetyCheck: "최소 50회 이상 모범 데이터가 모여야 학습 파이프라인 연계 가능",
  },
  "3.4": {
    analogy: "✅ 흔들린 비디오는 버리고 잘 된 것만 도장 찍는 검수대",
    concept: "녹화된 데이터 중 손이 미끄러졌거나 엉뚱한 곳을 집은 불량 에피소드를 골라내어 '불합격' 처리하는 데이터 검수 화면이에요.",
    flow: {
      input: "에피소드별 프레임 데이터 및 카메라 재생 영상",
      process: "에피소드 재생 ➔ 검수자 합격(PASS) / 불합격(DROP) 태깅",
      output: "에피소드 비디오 플레이어, PASS/FAIL 토글 버튼, 태그 목록",
    },
    uiComponents: ["간이 비디오/궤적 뷰어", "검수 도장(PASS/DROP) 버튼", "검수 완료율 게이지"],
    safetyCheck: "검수되지 않은 원천 데이터는 모델 학습에 직접 유입 차단",
  },
  "3.5": {
    analogy: "🎓 사람이 손잡고 '이렇게 움직이는 거야' 가르쳐주는 교실",
    concept: "로봇팔을 시뮬레이터 가상 공간에서 먼저 움직여보고, 목표 궤적을 3D로 미리 그려서 안전한지 시험해 보는 연습장이에요.",
    flow: {
      input: "궤적 티칭 포인트 (시작점, 경유점, 집기 목표점)",
      process: "역기구학(IK) 풀이 및 관절 가동 범위 충돌 시뮬레이션",
      output: "3D 가상 로봇팔 렌더러, 티칭 포인트 좌표 목록, 시뮬레이션 재생",
    },
    uiComponents: ["가상 로봇팔 시뮬레이터 캔버스", "포즈 프리셋 버튼", "궤적 유효성 검사표"],
    safetyCheck: "관절 한계각도(Joint Limit)를 벗어나는 포즈는 입력 즉시 차단",
  },
  "3.6": {
    analogy: "📊 로봇팔이 오늘 몇 번 성공하고 실패했는지 시험 성적표",
    concept: "로봇팔이 오늘 하루 신발 상자를 몇 번 집었고, 몇 번 놓쳤는지 성공률과 작업 시간을 그래프로 보여주는 성적표예요.",
    flow: {
      input: "QueryAudit (상·하차 시도 횟수, 성공/실패 여부, 소요 시간)",
      process: "성공률(%) = 성공 / 전체 시도, 평균 작업 시간(초) 산출",
      output: "성공률 도넛 차트, 시간대별 작업량 막대그래프",
    },
    uiComponents: ["성공률 도넛 차트", "평균 작업 소요시간 카드", "실패 원인 파이 차트"],
    safetyCheck: "연속 3회 집기 실패 시 '그리퍼 점검 필요' 경보 알림 자동 발생",
  },
  "3.7": {
    analogy: "🕹️ Station PC의 실제 조종실 화면 (모터 켜기 & 데이터 녹화)",
    concept: "팀원이 만든 파이썬 데스크톱 앱(omx_recoder)의 조종실로, 토크를 켜고 끄며 LeRobot 스튜디오와 연동하는 전문 화면이에요.",
    flow: {
      input: "Station PC 로컬 USB 시리얼 포트 (/dev/ttyACM0), 카메라 3채널",
      process: "단일 시리얼 소유권(SR-19) 보장, PySide6 원격 스트림 연계",
      output: "산업용 직각 조종판, 토크 BringUp/Servo OFF 버튼, VNC 안내",
    },
    uiComponents: ["직각 솔리드 조종 패널", "시리얼 포트 단독 소유권 가드", "안전 VNC/뷰어 가이드"],
    safetyCheck: "웹에서 직접 모터 명령을 쏘지 않고 반드시 Station PC 데스크톱 권한을 통해 안전 제어",
  },
  "4.1": {
    analogy: "📺 매장 천장 CCTV와 로봇 눈으로 보는 실시간 생중계 TV",
    concept: "천장에 달린 카메라 4대와 로봇에 달린 전방 카메라 화면을 지연 없이 매끄럽게 모아보는 다채널 CCTV 모니터예요.",
    flow: {
      input: "MediaMTX WHEP WebRTC 비디오 스트림 (H.264/Opus)",
      process: "WebRTC P2P 스트림 연결, 카메라 지연(FPS, Latency) 측정",
      output: "카메라 4분할 화면 그리드, 실시간 FPS/지연시간 뱃지",
    },
    uiComponents: ["4분할/단독 비디오 뷰포트", "카메라 상태 뱃지", "전체화면 확대 버튼"],
    safetyCheck: "카메라 연결 끊김 시 검은 화면 대신 '연결 시도 중(재연결)' 오버레이 표시",
  },
  "4.2": {
    analogy: "🔘 1번 카메라, 2번 카메라 채널을 돌리는 리모컨",
    concept: "보고 싶은 카메라 각도를 1번, 2번 버튼 눌러 선택하고, 카메라 해상도나 밝기 설정을 원격으로 조절하는 리모컨이에요.",
    flow: {
      input: "/api/v1/cameras (등록된 카메라 목록 및 RTSP 주소)",
      process: "선택된 카메라 ID로 메인 뷰포트 전환, 스트림 품질 파라미터 전달",
      output: "카메라 선택 썸네일 바, 해상도 선택 드롭다운, 채널 버튼",
    },
    uiComponents: ["카메라 채널 선택 탭", "스트림 품질(720p/1080p) 토글", "카메라 상세 정보표"],
    safetyCheck: "인증되지 않은 외부 스트림 주소는 보안을 위해 연결 거부",
  },
  "4.3": {
    analogy: "항공뷰로 문제 상황 후보를 알려주는 관찰 창",
    concept: "충돌·접근 위험, 박스 낙하, 장시간 정체를 후보로 판별합니다. 로봇 위치 추적이나 도킹 완료 증명은 이번 항공뷰 목표가 아닙니다.",
    flow: {
      input: "항공뷰 판별 결과, 원본/합성 출처, 모델 버전, 캡처 시각 (계약 초안)",
      process: "문제 후보와 미확인·입력 없음 상태를 구분하고 담당자가 확인",
      output: "문제 후보·증거 영상·확인 상태. 자동 수거·주행 명령은 없음",
    },
    uiComponents: ["문제 후보 목록", "판별 근거 영상", "미확인·입력 없음 표시"],
    safetyCheck: "학습은 시뮬레이션 이상 데이터와 정상 영상의 합성을 활용할 계획입니다. 실제 영상 보류 평가 전에는 운영 성능을 확인한 것으로 표시하지 않습니다.",
  },
  "4.4": {
    analogy: "📸 중요한 장면을 찰칵 찍어서 스티커 붙여 저장하기",
    concept: "학습용 데이터로 쓰기 위해 카메라 화면을 찰칵 캡처하고, '이건 신발 상자'라고 네모 박스를 쳐서 AI 훈련소로 보내는 작업대예요.",
    flow: {
      input: "현재 비디오 프레임 버퍼 (JPG/PNG 이미지)",
      process: "마우스 드래그로 바운딩 박스 생성 ➔ 클래스 레이블 매핑 ➔ 저장",
      output: "라벨링 캔버스 툴, 바운딩 박스 목록, JSON 어노테이션 파일",
    },
    uiComponents: ["이미지 캡처 버튼", "박스 그리기 캔버스", "라벨 선택 팔레트"],
    safetyCheck: "고화질 이미지는 로컬 임시 버퍼에 저장 후 백그라운드로 전송",
  },
  "4.5": {
    analogy: "🗂️ 지난주에 떨어진 신발 상자 사진 앨범 뒤적거리기",
    concept: "과거에 낙하물이 떨어졌던 날짜와 시간대별로 캡처된 사진들을 앨범처럼 검색하고 넘겨보는 사진 보관함이에요.",
    flow: {
      input: "날짜 및 위치 필터 ➔ 이미지 서버 조회",
      process: "타임스탬프 역순 정렬, 썸네일 그리드 렌더링",
      output: "사진 갤러리 그리드, 확대 모달 뷰어, 촬영 당시 로봇 정보",
    },
    uiComponents: ["사진 갤러리 그리드", "확대 라이트박스 모달", "날짜 검색 필터"],
    safetyCheck: "디스크 용량 절약을 위해 30일 지난 임시 캡처 사진 자동 만료",
  },
  "5.1": {
    analogy: "🔑 '로봇 조종 리모컨은 이제 내가 쥘게!' 마스터 열쇠 교환",
    concept: "로봇을 자동(AUTO)으로 컴퓨터가 움직이게 둘지, 아니면 사람이 수동(MANUAL) 조종권을 쥐고 운전할지 열쇠를 넘겨받는 화면이에요.",
    flow: {
      input: "FleetSafetyState (현재 제어권 소유자: NONE, OPERATOR_A, TABLET)",
      process: "제어권 획득 요청(ACQUIRE) ➔ 단일 소유권 잠금(LOCK) ➔ 반납(RELEASE)",
      output: "현재 제어권 소유자 배너, 제어권 뺏기/반납 버튼, AUTO/MANUAL 스위치",
    },
    uiComponents: ["제어권 점유 상태 인디케이터", "조종권 획득/반납 액션 버튼", "운전 모드 토글 스위치"],
    safetyCheck: "동시에 두 사람이 조종권을 쥘 수 없도록 '단일 소유권 원칙' 철저 강제",
  },
  "5.2": {
    analogy: "🕹️ 화면 속 가상 조이스틱으로 미니카 직접 조종하기",
    concept: "제어권을 얻은 관제사가 키보드 방향키(WASD)나 마우스 조이스틱을 밀어서 로봇을 직접 앞뒤 좌우로 운전하는 리모컨 창이에요.",
    flow: {
      input: "키보드 WASD / 화면 조이스틱 터치 입력",
      process: "전진 속도(Linear X), 회전 속도(Angular Z) Twist 메시지 발행",
      output: "원형 가상 조이스틱, 현재 조종 속도 수치, 비상 멈춤 스페이스바",
    },
    uiComponents: ["원형 터치 조이스틱 UI", "속도 출력 게이지", "즉시 정지 버튼"],
    safetyCheck: "조작 손을 떼거나 0.5초 동안 입력이 없으면 로봇 속도 0으로 자동 정지(Deadman Switch)",
  },
  "5.3": {
    analogy: "⏸️ 노란 신호등: '로봇들 잠깐만 멈춰! 다 지나가면 다시 출발!'",
    concept: "매장에 사람이 걸어오거나 잠시 정리가 필요할 때 모든 로봇을 그 자리에 얌전히 멈춰 세우고(PAUSE), 안전해지면 다시 풀고 달리는 화면이에요.",
    flow: {
      input: "PAUSE / RESUME 명령 버튼 클릭",
      process: "전체 로봇에 속도 0 감속 지시 (일시정지 상태 유지) ➔ 재개 명령",
      output: "노란색 PAUSE 배너, 일시정지 버튼, 작업 재개(RESUME) 버튼",
    },
    uiComponents: ["대형 PAUSE/RESUME 토글 버튼", "정지된 로봇 대수 카운터", "일시정지 사유 입력칸"],
    safetyCheck: "RESUME(재개) 버튼은 반드시 '안전 확인 체크박스'를 체크해야 활성화",
  },
  "5.4": {
    analogy: "🛑 빨간 비상정지 스위치 쾅! 누르고, 조심조심 다시 깨우기",
    concept: "큰 사고를 막기 위해 전체 전원과 모터를 즉시 끊어버리는 대형 비상 버튼과, 상황 종료 후 2단계 확인을 거쳐 복구하는 복구 센터예요.",
    flow: {
      input: "HARD ESTOP (즉시 정지) / RESET ➔ APPROVE (2단계 복구)",
      process: "모터 전원 즉각 컷 ➔ 안전 요원 상태 점검 ➔ 관리자 2인 승인 후 기동",
      output: "초대형 붉은 ESTOP 버튼, 2단계 복구 다이얼로그, 복구 리포트",
    },
    uiComponents: ["초대형 붉은 ESTOP 버튼", "2단계 복구 승인 모달", "복구 체크리스트"],
    safetyCheck: "ESTOP 복구는 단독 클릭 불가! 반드시 2단계 승인(D5 룰)을 거쳐야만 해제 가능",
  },
  "5.5": {
    analogy: "🛡️ 로봇의 범퍼와 레이저 눈이 살아있는지 지키는 보초병",
    concept: "로봇의 하드웨어 비상정지 버튼, 범퍼 충돌 센서, 바퀴 모터 전원선이 정상적으로 전기를 공급받고 있는지 감시하는 안전 보초병이에요.",
    flow: {
      input: "HwEstopState (물리 버튼 눌림 여부), motor_power_present",
      process: "센서 핑 신호 주기 검증, 하나라도 단선 시 즉각 경보 발생",
      output: "하드웨어 센서 신호등 표, 모터 전원 공급 상태 LED 아이콘",
    },
    uiComponents: ["하드웨어 센서 LED 테이블", "단선/정상 상태 뱃지", "전원 전압 모니터"],
    safetyCheck: "물리 E-STOP 버튼이 한 번이라도 눌리면 물리 스위치를 손으로 당겨 뽑기 전까지 복구 불가",
  },
  "5.6": {
    analogy: "📬 '명령 보냈는데 로봇이 진짜 접수했나요?' 등기우편 확인증",
    concept: "관제사가 내린 이동이나 정지 명령을 로봇이 몇 밀리초(ms) 만에 알아듣고 '접수했습니다!' 하고 도장을 찍어 보냈는지 확인하는 기록판이에요.",
    flow: {
      input: "CommandAck (명령 ID, 수신 여부, 처리 결과 코드)",
      process: "명령 발송 시각 vs 접수 시각 델타(지연 시간) 계산, 미접수 명령 탐지",
      output: "명령-응답(ACK) 타임라인 테이블, 실패한 명령 재전송 버튼",
    },
    uiComponents: ["명령 접수 타임라인 표", "지연 시간(Latency ms) 뱃지", "재시도 액션 버튼"],
    safetyCheck: "명령 발송 후 500ms 안에 ACK 응답이 오지 않으면 '명령 유실' 경보 발생",
  },
  "6.1": {
    analogy: "🩺 로봇 부품들이 아프지 않은지 진찰하는 종합건강검진표",
    concept: "로봇에 달린 라이다, 카메라, 미니 PC CPU, 모터 컨트롤러가 정상적으로 켜져 있고 열이 나지 않는지 확인하는 의사 선생님 차트예요.",
    flow: {
      input: "DiagSnapshot.devices (장비 목록: LiDAR, Camera, Motor, IMU)",
      process: "장치별 정상(OK), 주의(WARN), 고장(ERROR) 3단계 상태 진단",
      output: "디바이스 건강검진 카드 그리드, CPU 사용량/온도 프로그레스 바",
    },
    uiComponents: ["장치 상태 그리드 카드", "CPU/RAM 사용량 게이지", "온도 상태 바"],
    safetyCheck: "라이다 센서 통신 끊김 감지 시 즉시 로봇 주행 소프트웨어 잠금",
  },
  "6.2": {
    analogy: "📡 로봇들과 관제탑 사이 무선 전화기가 잘 터지는지 보는 안테나",
    concept: "ROS 2 통신망에서 주고받는 데이터가 초당 몇 번(Hz) 오고 가는지, 데이터 선이 끊기지는 않았는지 실시간으로 주파수를 맞추는 화면이에요.",
    flow: {
      input: "DiagSnapshot.topics (토픽명, 수신 주기 hz, single_writer 상태)",
      process: "기대 주기(예: 10Hz) 대비 실제 주기 비교 ➔ 누락률 계산",
      output: "토픽별 실시간 Hz 테이블, 단일 발행자(Single Writer) 안전 뱃지",
    },
    uiComponents: ["토픽 통신 속도(Hz) 표", "단일 발행자 검증 뱃지", "통신 지연 상태 인디케이터"],
    safetyCheck: "하나의 명령 토픽에 두 컴퓨터가 동시에 말을 하면(충돌) 붉은색 경보 표시",
  },
  "6.3": {
    analogy: "🐜 컴퓨터 안에서 일하는 작은 일꾼 요정들이 살아있는지 보기",
    concept: "로봇 안에서 내비게이션, 비전, 제어를 각각 맡아 돌아가는 소프트웨어 프로그램(ROS 노드)들이 꺼지지 않고 뛰고 있는지 보는 화면이에요.",
    flow: {
      input: "DiagSnapshot.nodes (노드 이름, 실행 상태: ALIVE / DEAD)",
      process: "생명 신호(Heartbeat) 수신 확인, 죽은 노드 탐지",
      output: "실행 중인 노드 트리 뷰, 죽은 노드 알림 배너, 재시작 안내",
    },
    uiComponents: ["노드 목록 트리/테이블", "ALIVE/DEAD 상태 뱃지", "마지막 생존 시간 표시"],
    safetyCheck: "내비게이션 필수 노드(nav2) 사망 시 전체 주행 즉각 비상 정지",
  },
  "6.4": {
    analogy: "📝 로봇 시스템이 내뱉는 컴퓨터 로그 일기장 모음",
    concept: "로봇 안의 프로그램들이 남기는 세세한 컴퓨터 안내문(/rosout)을 실시간으로 흘려보내며 오류 단어를 찾아내는 콘솔 화면이에요.",
    flow: {
      input: "/rosout (시간, 노드명, 로그 레벨: INFO/WARN/ERROR, 메시지)",
      process: "로그 레벨 필터링, 검색 키워드(예: 'fail', 'timeout') 하이라이트",
      output: "다크 모드 콘솔 터미널 창, 실시간 자동 스크롤, 검색 인풋",
    },
    uiComponents: ["다크 단색 콘솔 로그 뷰어", "로그 레벨(WARN/ERROR) 필터 바", "자동 스크롤 고정 토글"],
    safetyCheck: "대용량 로그 유입 시 브라우저 렉 방지를 위해 최근 500줄만 링 버퍼 유지",
  },
  "6.5": {
    analogy: "🏎️ 가상 매장 시뮬레이터와 실물 로봇의 달리기 시합 비교표",
    concept: "컴퓨터 속 가상 시뮬레이터(MuJoCo / Isaac Sim)에서 달린 기록과 실제 로봇이 매장에서 달린 기록의 오차(Gap)를 비교하는 연구실이에요.",
    flow: {
      input: "simulation_report.json (시뮬레이션 완주 통계, Real-to-Sim 갭)",
      process: "MuJoCo 완주율 계산 + Isaac Sim 실물 6회 주행 대비 오차(±3cm) 정합성 분석",
      output: "트랙 A(MuJoCo) 완주 통계 탭, 트랙 B(Isaac Sim) 리얼투심 비교 탭",
    },
    uiComponents: ["이원화 탭(MuJoCo / Isaac Sim)", "리얼투심 오차 비교 차트", "시뮬레이션 보고서 뷰"],
    safetyCheck: "정본 맵 67cm 지문과 시뮬레이션 환경 지문이 일치하는지 해시 대조",
  },
  "6.6": {
    analogy: "⚙️ FMS 전체 시스템의 두꺼운 설정값 설명서 책",
    concept: "매장 크기, 로봇 최대 속도, 테일스케일 IP 주소 등 전체 시스템의 비밀번호와 설정 파일(YAML)을 읽어보고 확인하는 관리자 책상이에요.",
    flow: {
      input: "/api/v1/config (시스템 설정 YAML, Git 커밋 해시, 설정 sha256)",
      process: "설정 파일 유효성 검사, 변경 이력 및 현재 버전 표기",
      output: "YAML 설정 코드 뷰어, 설정 무결성 체크 해시 뱃지",
    },
    uiComponents: ["설정 파일 코드 뷰어", "버전/해시 무결성 카드", "설정값 읽기 전용 패널"],
    safetyCheck: "운영 중에는 설정 파일 수정 불가(읽기 전용 ro), 배포 파이프라인을 통해서만 변경 허용",
  },
};

export default function Eli5FeatureGuide({ menu }: { menu: Menu }) {
  const meta = ELI5_REGISTRY[menu.id] || {
    analogy: `💡 ${menu.name} 기능 관제 화면`,
    concept: `${menu.name} 화면은 ${menu.dataSources.join(", ") || "관련 데이터"}를 모니터링하고 제어하는 FMS 메뉴예요.`,
    flow: {
      input: menu.dataSources.length > 0 ? menu.dataSources.join(", ") : "시스템 기본 상태",
      process: "데이터 유효성 검증 및 관제 화면 실시간 렌더링",
      output: `${menu.name} 카드 및 상태 표시 UI`,
    },
    uiComponents: ["데이터 현황 카드", "상태 인디케이터", "조작/명령 패널"],
    safetyCheck: "비정상 데이터 수신 시 통신 지연 경보 및 폴백 표시",
  };

  return (
    <Card className="border-border bg-card">
      <CardHeader className="pb-3 border-b border-border">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <span>💡</span>
            <span>구현 기능 도식화 (ELI5 가이드)</span>
          </CardTitle>
          <Badge variant="outline" className="font-mono text-xs">
            Menu {menu.id} · {menu.phase}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="pt-4 space-y-4 text-sm">
        {/* 1. 비유 설명 (어린이도 이해하는 한 줄 비유) */}
        <div className="bg-muted p-3 border border-border">
          <p className="font-medium text-foreground">{meta.analogy}</p>
          <p className="mt-1 text-xs text-muted-foreground leading-relaxed">{meta.concept}</p>
        </div>

        {/* 2. 데이터 흐름 도식화 (ASCII / Flow Diagram) */}
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            데이터 처리 및 화면 흐름도 (Data Flow)
          </p>
          <div className="grid gap-2 md:grid-cols-3">
            <div className="border border-border p-2.5 bg-background">
              <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
                [1] 📥 입력 데이터
              </span>
              <p className="text-xs font-mono text-foreground break-words">{meta.flow.input}</p>
            </div>
            <div className="border border-border p-2.5 bg-background">
              <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
                [2] ⚙️ 처리 &amp; 검증 로직
              </span>
              <p className="text-xs text-foreground">{meta.flow.process}</p>
            </div>
            <div className="border border-border p-2.5 bg-background">
              <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
                [3] 🖥️ 구현할 화면 UI
              </span>
              <p className="text-xs text-foreground">{meta.flow.output}</p>
            </div>
          </div>
        </div>

        {/* 3. 개발자 구현 체크리스트 */}
        <div className="grid gap-3 pt-1 md:grid-cols-2">
          <div className="space-y-1.5">
            <span className="text-xs font-semibold text-muted-foreground">🎨 구현해야 할 필수 UI 구성요소</span>
            <ul className="list-disc pl-4 text-xs space-y-1 text-foreground">
              {meta.uiComponents.map((item, idx) => (
                <li key={idx}>{item}</li>
              ))}
            </ul>
          </div>
          <div className="space-y-1.5">
            <span className="text-xs font-semibold text-muted-foreground">⚠️ 필수 안전 &amp; 예외 처리 규칙</span>
            <div className="border border-border p-2 bg-muted text-xs text-foreground">
              {meta.safetyCheck}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
