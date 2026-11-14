// 자동 생성 파일이다. 직접 고치지 말 것.
// 원본: src/cobot_interfaces 의 msg, srv, action 정의.
// 재생성: PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_types
// 확인: PYTHONPATH=src/cobot_gui python3 -m cobot_gui.gen_web_types --check

/** float 필드. NaN(미측정)은 JSON 에서 null 이 된다. 0 으로 바꿔 보이지 않는다. */
export type Float = number | null;

/** 표준 메시지 Time */
export interface Time {
  sec: number;
  nanosec: number;
}

/** 표준 메시지 Header */
export interface Header {
  stamp: Time;
  frame_id: string;
}

/** 표준 메시지 Point */
export interface Point {
  x: Float;
  y: Float;
  z: Float;
}

/** 표준 메시지 Quaternion */
export interface Quaternion {
  x: Float;
  y: Float;
  z: Float;
  w: Float;
}

/** 표준 메시지 Pose */
export interface Pose {
  position: Point;
  orientation: Quaternion;
}

/** AlarmEvent.msg */
export interface AlarmEvent {
  header: Header;
  /** 알림 ID (UUIDv4) */
  alarm_id: string;
  /** 위 SEVERITY_* 중 하나 */
  severity: string;
  /** 위 CODE_* 중 하나 */
  code: string;
  /** 대상: pinky_1, omx_2, cam_gate, CORRIDOR_MAIN ... */
  target_id: string;
  /** 생긴 시각 */
  raised_at: Time;
  /** 풀린 시각. active 가 true 면 의미 없음 */
  cleared_at: Time;
  /** 아직 풀리지 않았는가 */
  active: boolean;
  /** 풀려면 Reconcile 이 필요한가 (SR-14) */
  requires_reconcile: boolean;
  /** 사람이 읽는 설명. 비밀값·주소·사람 이름을 넣지 않는다 */
  detail: string;
}
export const AlarmEventConst = {
  SEVERITY_INFO: "INFO",
  SEVERITY_AMBER: "AMBER",
  SEVERITY_RED: "RED",
  CODE_LINK_LOSS: "LINK_LOSS",
  CODE_CAMERA_STALE: "CAMERA_STALE",
  CODE_CAMERA_FROZEN: "CAMERA_FROZEN",
  CODE_UNKNOWN_BLOCKED: "UNKNOWN_BLOCKED",
  CODE_RETRY_EXCEEDED: "RETRY_EXCEEDED",
  CODE_QR_MISMATCH: "QR_MISMATCH",
  CODE_HUMAN_IN_ZONE: "HUMAN_IN_ZONE",
  CODE_CLOCK_OFFSET: "CLOCK_OFFSET",
  CODE_SINGLE_WRITER_VIOLATION: "SINGLE_WRITER_VIOLATION",
  CODE_NO_COMMAND_PUBLISHER: "NO_COMMAND_PUBLISHER",
  CODE_ACK_WITHOUT_PHYSICAL: "ACK_WITHOUT_PHYSICAL",
  CODE_MAP_HASH_MISMATCH: "MAP_HASH_MISMATCH",
  CODE_LEDGER_UNAVAILABLE: "LEDGER_UNAVAILABLE",
  CODE_POWER_LOST: "POWER_LOST",
  CODE_ARM_INTERLOCK: "ARM_INTERLOCK",
  CODE_INVENTORY_SHORTAGE: "INVENTORY_SHORTAGE",
} as const;

/** ArmCommand.msg */
export interface ArmCommand {
  /** 세션 펜싱 (SR-20)·서명 (D13, 설계 초안). header.robot_id = arm_id */
  header: CommandHeader;
  /** [-] 위 CMD_* 중 하나 */
  command: number;
}
export const ArmCommandConst = {
  /** 팔 정지 유지 */
  CMD_HOLD: 0,
  /** HOLD 해제 (모션 시작은 아님) */
  CMD_RELEASE_HOLD: 1,
  /** 래치 -> DISARMED. 구동 없음 */
  CMD_RESET: 2,
  /** DISARMED -> 가동. 새 epoch 에서만 */
  CMD_START: 3,
  /** 소프트 정지 래치 (전원 차단 아님). RESET 으로만 해제 */
  CMD_SOFT_LATCH: 4,
} as const;

/** ArmMode.msg */
export interface ArmMode {
  /** stamp = 판정 시각 */
  header: Header;
  /** omx_1~3 */
  arm_id: string;
  /** 위 MODE_* 중 하나. 빈 문자열은 MODE_UNKNOWN 으로 다룬다 */
  mode: string;
  /** 판정 근거 (잠금 파일 경로와 sha256). 장치 경로·홈 경로는 넣지 않는다 */
  source: string;
}
export const ArmModeConst = {
  MODE_ROS_MANAGED: "ROS_MANAGED",
  MODE_LEROBOT_EXCLUSIVE: "LEROBOT_EXCLUSIVE",
  MODE_OFFLINE: "OFFLINE",
  MODE_UNKNOWN: "UNKNOWN",
} as const;

/** ArmStatus.msg */
export interface ArmStatus {
  /** stamp = 측정 시각 (Station PC 시계) */
  header: Header;
  /** omx_1~3 */
  arm_id: string;
  /** 팔 노드 기동마다 새 값 */
  robot_boot_id: string;
  /** 위 JOINT_UNIT_* 중 하나. 보정 파일이 없으면 3D 자세를 계산하지 않는다 */
  joint_unit: string;
  /** joint_positions 와 같은 순서 */
  joint_names: string[];
  /** [joint_unit] 관절 위치 */
  joint_positions: Float[];
  /** [joint_unit] 그리퍼 위치 */
  gripper_position: Float;
  /** [mA] 관절별 전류. 미지원 축은 NaN */
  present_current_ma: Float[];
  /** 토크 켜짐 */
  torque_enabled: boolean;
  /** 퇴피 완료 Z >= 280 mm (SR-10) */
  retract_safe: boolean;
  /** retract_safe 를 실제로 쟀는가. false 는 PASS 가 아니다 (초안) */
  retract_safe_measured: boolean;
  /** 사람 진입 HOLD 중 (SR-12) */
  hold_active: boolean;
  /** HOLD 사유. 없으면 "" */
  hold_reason: string;
  /** 팔 전원(12 V) 증거. 측정 수단은 D6 */
  power_present: boolean;
  /** [-] 팔 노드가 받아들인 epoch. 0 = 아직 없음 */
  epoch_accepted: number;
  /** [-] 마지막으로 수락한 ArmCommand seq (초안) */
  last_seq_accepted: number;
  /** 위 WORK_STEP_* 중 하나. MANUAL_START 때 로컬 작업 단계 (D7) */
  work_step: string;
}
export const ArmStatusConst = {
  JOINT_UNIT_RAD: "RAD",
  JOINT_UNIT_NORMALIZED_0_4095: "NORMALIZED_0_4095",
  WORK_STEP_IDLE: "IDLE",
  WORK_STEP_APPROACHING: "APPROACHING",
  WORK_STEP_VISION_ALIGNING: "VISION_ALIGNING",
  WORK_STEP_GRASPING: "GRASPING",
  WORK_STEP_PLACING: "PLACING",
  WORK_STEP_RETRACTING: "RETRACTING",
  WORK_STEP_VERIFYING: "VERIFYING",
  /** 초안. 'VERIFYING 이후' 를 나타내려고 더했다 */
  WORK_STEP_DONE: "DONE",
} as const;

/** Assignment.msg */
export interface Assignment {
  header: Header;
  /** 주문 ID */
  order_id: string;
  /** 배정으로 생긴 작업 ID */
  task_id: string;
  /** 배정된 로봇. 아직 없으면 "" */
  robot_id: string;
  /** 배정 시각 */
  assigned_at: Time;
  /** 배정에서 뺀 로봇 */
  excluded_robot_ids: string[];
  /** 뺀 이유. excluded_robot_ids 와 같은 순서, 위 EXCLUSION_* 값 */
  exclusion_reasons: string[];
}
export const AssignmentConst = {
  EXCLUSION_NONE: "NONE",
  /** 배터리 20 % 이하 (SR-03) */
  EXCLUSION_BATTERY_LE_20: "BATTERY_LE_20",
  /** 통신 장애 */
  EXCLUSION_LINK_STALE: "LINK_STALE",
  /** 오류 상태 */
  EXCLUSION_ERROR: "ERROR",
} as const;

/** AuditEvent.msg */
export interface AuditEvent {
  /** [-] 원장 행 번호 (64-bit 단조 증가) */
  seq: number;
  /** UUIDv4 */
  event_id: string;
  /** 이벤트 유형 (예: COMMAND_ISSUED) */
  event_type: string;
  /** [-] 원장 스키마 버전 */
  schema_version: number;
  /** 기록 시각 (중앙 FMS PC 시계) */
  ts_fms: Time;
  /** false 면 ts_source 는 의미 없음 */
  has_ts_source: boolean;
  /** 원천 측정 시각 */
  ts_source: Time;
  /** 기록을 낸 장비 ID */
  source_host: string;
  /** 기록을 낸 노드 */
  source_node: string;
  /** 대상. 없으면 "" */
  target_id: string;
  /** [-] 관련 epoch. 0 = 없음 */
  epoch: number;
  /** [-] 관련 명령 seq. 0 = 없음 */
  cmd_seq: number;
  /** 없으면 "" */
  order_id: string;
  /** 없으면 "" */
  task_id: string;
  /** 없으면 "" */
  command_id: string;
  /** 없으면 "" */
  tx_id: string;
  /** customer | staff | operator | system */
  actor_role: string;
  /** 계정 ID (사람 이름 아님) */
  actor_id: string;
  /** 이벤트 본문 JSON */
  payload_json: string;
  /** true 면 실물이 아니다 */
  simulated: boolean;
  /** 앞 행의 row_hash */
  prev_hash: string;
  /** sha256(prev_hash 와 정규화한 행) */
  row_hash: string;
}

/** CameraHealth.msg */
export interface CameraHealth {
  /** stamp = 보고 시각 */
  header: Header;
  /** 카메라 ID (예: cam_gate) */
  camera_id: string;
  /** 위 ROLE_* 중 하나 */
  role: string;
  /** 위 SOURCE_KIND_* 중 하나. SIM 은 제어 경로에 섞지 않는다 (SR-07) */
  source_kind: string;
  /** 마지막 프레임의 캡처(또는 수신) 시각 */
  last_capture_stamp: Time;
  /** [ms] 마지막 프레임 나이. NaN = 프레임 없음 */
  frame_age_ms: Float;
  /** 위 AGE_BASIS_* 중 하나 */
  age_basis: string;
  /** [Hz] 실측 프레임률 */
  fps_measured: Float;
  /** 같은 프레임 해시가 N 회 반복됨 */
  frozen: boolean;
  /** [px] 프레임 너비 */
  width: number;
  /** [px] 프레임 높이 */
  height: number;
}
export const CameraHealthConst = {
  ROLE_OVERHEAD: "OVERHEAD",
  ROLE_GATE: "GATE",
  ROLE_DESK: "DESK",
  ROLE_TTOP: "TTOP",
  ROLE_TWRIST: "TWRIST",
  ROLE_PINKY_FRONT: "PINKY_FRONT",
  SOURCE_KIND_REAL: "REAL",
  SOURCE_KIND_SIM: "SIM",
  /** 카메라 쪽 캡처 시각을 검증했다 */
  AGE_BASIS_CAPTURE: "CAPTURE",
  /** 수신 시각 기준 (검증 안 됨) */
  AGE_BASIS_RECEIVE: "RECEIVE",
} as const;

/** CommandAck.msg */
export interface CommandAck {
  /** 원인 명령의 header.command_id */
  command_id: string;
  /** 판정한 대상: pinky_1~3 | omx_1~3 */
  robot_id: string;
  /** [-] 원인 명령의 header.epoch */
  epoch: number;
  /** [-] 원인 명령의 header.seq */
  seq: number;
  /** [-] 위 ACCEPTED / REJECTED_* 중 하나 */
  result: number;
  /** 정지 계열은 판정이 거부여도 정지했으면 true (D4, 초안) */
  stop_executed: boolean;
  /** 사람이 읽는 사유. 비밀값·주소를 넣지 않는다 */
  reason: string;
  /** [ms] 로봇 로컬 단조 시계로 잰 수신~ACK 체류 시간 */
  rx_to_ack_ms: number;
  /** 로봇 시계의 수신 시각 (진단용) */
  robot_rx_stamp: Time;
}
export const CommandAckConst = {
  ACCEPTED: 0,
  /** epoch 가 받아들인 값보다 낮음 */
  REJECTED_EPOCH: 1,
  /** seq 가 마지막 수락 seq 이하 */
  REJECTED_SEQ: 2,
  /** issued_at + ttl_ms 지남 */
  REJECTED_TTL: 3,
  /** 이동 계열인데 로드한 맵과 해시가 다름 */
  REJECTED_MAP_HASH: 4,
  /** 지금 상태에서 허용하지 않음 (예: DISARMED 에서 RESUME) */
  REJECTED_STATE: 5,
  /** 대상이 자신이 아님 */
  REJECTED_ROBOT_ID: 6,
  /** 시계 오프셋을 모르거나 허용치 초과 (구동 명령만) */
  REJECTED_CLOCK_UNSYNCED: 7,
  /** 서명 불일치 */
  REJECTED_SIGNATURE: 8,
} as const;

/** CommandHeader.msg */
export interface CommandHeader {
  /** UUIDv4. 명령마다 새 값 */
  command_id: string;
  /** 트랜잭션 ID. 원장 역추적용 (SR-21) */
  tx_id: string;
  /** 주문 ID. 없으면 "" */
  order_id: string;
  /** 작업 ID (SR-21) */
  task_id: string;
  /** 명령을 받는 대상: pinky_1~3 | omx_1~3 */
  robot_id: string;
  /** [-] 대상별 세션 번호. fms_core 가 영속한다. 1 부터 쓴다 (초안) */
  epoch: number;
  /** [-] 대상별·epoch 안에서 단조 증가. 명령 전용 번호 공간 */
  seq: number;
  /** 발행 시각. 중앙 FMS PC 시계 (chrony 기준) */
  issued_at: Time;
  /** [ms] 유효 기한. 5000 고정 (SR-20). 0 이면 바로 만료 */
  ttl_ms: number;
  /** sha256 16진 문자열 64자. 계산법은 맵 계약(D3)을 따른다 */
  map_hash: string;
  /** 발행자 이름. "control_center" */
  issued_by: string;
  /** 서명 키 식별자 (대상별 키, D13) */
  key_id: string;
  /** HMAC-SHA256(대상별 키, 헤더 + 본문 정규화). S3(P2) 필수 (D13) */
  sig: string;
}

/** CompletionEvidence.msg */
export interface CompletionEvidence {
  /** stamp = 측정 시각 (원천 시계) */
  header: Header;
  /** UUIDv4. LaneLeaseState·HandoverTask 결과가 이 값으로 가리킨다 */
  evidence_id: string;
  /** 원인 명령 ID. 없으면 "" */
  command_id: string;
  /** 작업 ID (SR-21) */
  task_id: string;
  /** 증거를 낸 쪽: pinky_2, omx_1, cam_gate ... */
  source_id: string;
  /** [-] 위 상수 중 하나 */
  kind: number;
  /** [kind 별] 단위는 docs/fms_interfaces.md 의 증거 표 */
  value: Float;
  /** [kind 별] value 와 같은 단위 */
  threshold: Float;
  /** value 가 threshold 조건을 만족하는가 */
  satisfied: boolean;
  /** 센서로 실제로 쟀는가. false 는 PASS 가 아니다 */
  measured: boolean;
}
export const CompletionEvidenceConst = {
  /** 엔코더 속도 0 지속 (value [m/s]) */
  ENCODER_VEL_ZERO: 0,
  /** 바퀴 잠금 체결 (SR-08) */
  BASE_HOLD_ENGAGED: 1,
  /** 팔 퇴피 Z >= 280 mm (SR-10, value [mm]) */
  ARM_RETRACT_SAFE: 2,
  /** 적재 센서 (SR-10) */
  LOAD_SENSOR_PRESENT: 3,
  /** 그리퍼 파지 확인 (SR-21) */
  GRIPPER_HOLD_OK: 4,
  /** 게이트 카메라 후미 퇴장 (SR-05). age_basis=CAPTURE 일 때만 measured=true */
  TAIL_EXIT_CONFIRMED: 5,
  /** 천장 카메라 구역 안에 있음 (보조 증거) */
  ZONE_PRESENT: 6,
} as const;

/** DeviceDiag.msg */
export interface DeviceDiag {
  /** 장비 ID (예: pinky_1, station_1) */
  device_id: string;
  /** 장비 주소 문자열. 레포의 예시·설정에는 실주소를 쓰지 않는다 */
  ip: string;
  /** [ms] 링크 왕복 시간 (단일 시계). NaN = 미측정 */
  link_rtt_ms: Float;
  /** [ms] 마지막으로 본 뒤 경과 시간 */
  last_seen_age_ms: number;
  /** [-] 장비가 스스로 보고한 ROS_DOMAIN_ID. 없으면 DOMAIN_ID_NOT_REPORTED */
  ros_domain_id_reported: number;
}
export const DeviceDiagConst = {
  /** 자기 보고 없음 = 다른 도메인이거나 미기동 */
  DOMAIN_ID_NOT_REPORTED: -1,
} as const;

/** DiagSnapshot.msg */
export interface DiagSnapshot {
  header: Header;
  /** 장비별 링크 상태 */
  devices: DeviceDiag[];
  /** 토픽별 발행자 수·유량 */
  topics: TopicDiag[];
  /** 노드·서비스 왕복 */
  nodes: NodeDiag[];
  /** [-] fleet_monitor 자신의 ROS_DOMAIN_ID. DeviceDiag.ros_domain_id_reported 와 같은 타입 (-1 = 모름) */
  ros_domain_id_configured: number;
  /** [ms] 중앙 PC 의 chrony 오프셋. NaN = 모름 */
  chrony_offset_ms: Float;
}

/** DropEvent.msg */
export interface DropEvent {
  timestamp: Time;
  /** "overhead_cam" or "pinky_cam" */
  detected_by: string;
  /** [-] 고유 사고 식별자 */
  incident_id: number;
  /** [m] 글로벌 맵 기준 x, y 좌표 */
  location: Point;
  /** "disc_puffed_rice", "sphere", "vinyl_box" */
  item_type: string;
  /** [0~1] 비전 인식 신뢰도 (0.0 ~ 1.0) */
  confidence: Float;
  /** 사고가 발생한 차선 구역 ID (예: "LANE_SOUTH_1") */
  lane_segment_id: string;
}

/** FleetCommand.msg */
export interface FleetCommand {
  /** 세션 펜싱 (SR-20)·서명 (D13, 설계 초안) */
  header: CommandHeader;
  /** [-] 위 CMD_* 중 하나 */
  command: number;
  /** [m] map 프레임. CMD_GOTO, CMD_SET_INITIAL_POSE */
  x: Float;
  /** [m] map 프레임 */
  y: Float;
  /** [rad] map 프레임 */
  yaw: Float;
  /** [m/s] CMD_SET_SPEED */
  max_linear_vel: Float;
  /** [rad/s] CMD_SET_SPEED */
  max_angular_vel: Float;
  /** 맵 YAML 의 웨이포인트 이름 (표시·감사용) */
  waypoint_id: string;
  /** 통로 진입 허가 ID (SR-05). 없으면 "" */
  lane_lease_id: string;
  /** 통로 허가 만료 시각 */
  lease_valid_until: Time;
  /** 확장자 없는 맵 이름. CMD_SET_MAP */
  map_name: string;
}
export const FleetCommandConst = {
  /** 이동. fms_core 가 waypoint_id 에서 바꾼 좌표만. 공통 출발 게이트 통과 뒤에만 발행 */
  CMD_GOTO: 0,
  /** goal 취소 + PAUSED. last_goal 을 발행 epoch 와 함께 보존 (= PAUSE) */
  CMD_STOP: 1,
  /** PAUSED 해제 전용. 현재 epoch 의 last_goal 이 있을 때만 재전송 */
  CMD_RESUME: 2,
  /** goal 취소 + last_goal 폐기 */
  CMD_CANCEL: 3,
  /** x, y, yaw 로 initialpose 발행 (AMCL 재초기화) */
  CMD_SET_INITIAL_POSE: 4,
  /** 속도 제한 변경. MVP 미사용 */
  CMD_SET_SPEED: 5,
  /** map_name 으로 맵 교체. MVP 미사용 */
  CMD_SET_MAP: 6,
  /** 번호만 남김. v1 뜻(수신 시각 갱신)은 폐기. v2 가드는 무시하고 워치독을 갱신하지 않는다 */
  CMD_HEARTBEAT: 7,
  /** 래치 -> DISARMED. 구동 없음. last_goal 폐기 */
  CMD_RESET: 8,
  /** DISARMED -> 가동. 새 epoch 에서만. last_goal 없이 시작 */
  CMD_START: 9,
  /** 로봇 쪽 소프트 정지 래치(전원 차단 아님). RESET 으로만 해제. last_goal 폐기 */
  CMD_SOFT_LATCH: 10,
} as const;

/** FleetSafetyState.msg */
export interface FleetSafetyState {
  header: Header;
  /** 위 SYSTEM_MODE_* 중 하나 */
  system_mode: string;
  /** 위 RUN_STATE_* 중 하나 (소프트웨어 축) */
  run_state: string;
  /** 위 HW_ESTOP_* 중 하나 (HW 축, run_state 와 별도) */
  hw_estop: string;
  /** 판독 장치 ID 또는 "not_installed" */
  hw_estop_source: string;
  /** HW 축 값의 판독 시각 */
  hw_estop_stamp: Time;
  /** motor_power_present=false 또는 전원 복귀 edge 를 보고한 대상 */
  power_lost_targets: string[];
  /** 소프트 정지 래치가 걸린 대상 */
  latched_targets: string[];
  /** epochs 와 같은 순서의 대상 ID */
  epoch_targets: string[];
  /** [-] 대상별 현재 epoch. epoch_targets 와 같은 순서 */
  epochs: number[];
  /** 콘솔 보유 계정 ID (사람 이름 아님). 없으면 "" */
  console_holder_id: string;
  /** customer | staff | operator */
  console_holder_role: string;
  /** 콘솔 만료 시각 */
  console_expires_at: Time;
  /** 승인 대기 참조: report_hash 또는 challenge_id */
  pending_approval_ref: string;
  /** 지금 상태에서 허용되는 동작. 게이트웨이가 세션 역할로 한 번 더 거른다 */
  allowed_actions: string[];
}
export const FleetSafetyStateConst = {
  SYSTEM_MODE_AUTO: "AUTO",
  SYSTEM_MODE_MANUAL: "MANUAL",
  RUN_STATE_DISARMED: "DISARMED",
  RUN_STATE_RECONCILING: "RECONCILING",
  RUN_STATE_APPROVED: "APPROVED",
  RUN_STATE_RUNNING: "RUNNING",
  RUN_STATE_PAUSED: "PAUSED",
  RUN_STATE_SOFT_LATCH: "SOFT_LATCH",
  HW_ESTOP_ENGAGED: "ENGAGED",
  HW_ESTOP_RELEASED: "RELEASED",
  HW_ESTOP_UNKNOWN: "UNKNOWN",
  HW_ESTOP_SOURCE_NOT_INSTALLED: "not_installed",
} as const;

/** FmsHeartbeat.msg */
export interface FmsHeartbeat {
  /** 대상: pinky_1~3 | omx_1~3 */
  robot_id: string;
  /** [-] 대상별 세션 번호 */
  epoch: number;
  /** [-] 하트비트 전용 단조 번호 (명령 seq 와 다른 공간) */
  hb_seq: number;
  /** 발행 시각. 중앙 FMS PC 시계 */
  issued_at: Time;
  /** [ms] 하트비트 유효 기한. 기본 200 제안 (D11) */
  ttl_ms: number;
  /** sha256 16진 문자열 64자 (D3) */
  map_hash: string;
  /** [-] 위 MODE_* 중 하나. 낮추기 전용 */
  fleet_mode: number;
  /** 통로 허가 ID. 없으면 "" */
  lane_lease_id: string;
  /** 통로 허가 만료 시각 (TTL 5000 ms, SR-05). 하트비트로 갱신하는 것은 설계 초안 */
  lease_valid_until: Time;
  /** [-] 진단용. 이 대상에 마지막으로 낸 명령 seq (명령 유실 감지) */
  last_cmd_seq_issued: number;
  /** 서명 키 식별자 (D13) */
  key_id: string;
  /** HMAC-SHA256. 서명이 맞지 않으면 워치독을 갱신하지 않는다 (D13) */
  sig: string;
}
export const FmsHeartbeatConst = {
  /** 제한 없음 */
  MODE_RUN: 0,
  /** 일시정지 */
  MODE_PAUSE: 1,
  /** 소프트 정지 래치 (전원 차단 아님) */
  MODE_SOFT_LATCH: 2,
  /** 안전 대기. HW 전원 상실(HwEstopState ENGAGED 또는 motor_power_present=false)도 이 값 */
  MODE_DISARMED: 3,
} as const;

/** HwEstopState.msg */
export interface HwEstopState {
  /** stamp = 판독 시각 */
  header: Header;
  /** 위 STATE_* 중 하나. 빈 문자열은 UNKNOWN */
  state: string;
  /** 판독 장치 ID 또는 "not_installed" (D6) */
  source_device: string;
}
export const HwEstopStateConst = {
  /** 릴레이가 모터 전원을 끊었다 */
  STATE_ENGAGED: "ENGAGED",
  /** 릴레이 풀림 */
  STATE_RELEASED: "RELEASED",
  /** 판독 불가 */
  STATE_UNKNOWN: "UNKNOWN",
  SOURCE_NOT_INSTALLED: "not_installed",
} as const;

/** InventoryItem.msg */
export interface InventoryItem {
  /** 신발 종류 */
  sku: string;
  /** 보관 위치 */
  location_id: string;
  /** [개] 보유 수량 */
  qty_on_hand: number;
  /** [개] 가점유 수량 */
  qty_reserved: number;
  /** 락을 가진 주문. 없으면 "" */
  lock_holder_order_id: string;
}

/** InventoryState.msg */
export interface InventoryState {
  header: Header;
  /** 재고 항목 */
  items: InventoryItem[];
  /** 재고 원천. 위 SOURCE_* 중 하나 (D19 에서 더한다) */
  source: string;
}
export const InventoryStateConst = {
  SOURCE_MANUAL_YAML: "MANUAL_YAML",
} as const;

/** LaneLeaseState.msg */
export interface LaneLeaseState {
  header: Header;
  /** 통로 ID. MVP 는 "CORRIDOR_MAIN" 하나 (초안) */
  lane_id: string;
  /** 위 STATE_* 중 하나 */
  state: string;
  /** 허가를 가진 로봇. 없으면 "" */
  holder_robot_id: string;
  /** 허가 ID. FleetCommand.lane_lease_id 와 같은 값 */
  lease_id: string;
  /** [-] 허가를 받은 로봇의 epoch */
  epoch: number;
  /** 허가 시각 */
  granted_at: Time;
  /** 만료 시각 (TTL 5000 ms, SR-05) */
  valid_until: Time;
  /** 대기 중인 로봇 (먼저 온 순서) */
  waiting_robot_ids: string[];
  /** 진입 전 출구 공간 확인 결과 (데드락 방지) */
  exit_space_ok: boolean;
  /** 해제 근거 CompletionEvidence.evidence_id. 없으면 "" */
  tail_exit_evidence_id: string;
}
export const LaneLeaseStateConst = {
  STATE_FREE: "FREE",
  STATE_HELD: "HELD",
  STATE_RELEASE_PENDING_TAIL_EXIT: "RELEASE_PENDING_TAIL_EXIT",
  STATE_UNKNOWN_BLOCKED: "UNKNOWN_BLOCKED",
} as const;

/** MapInfo.msg */
export interface MapInfo {
  header: Header;
  /** 확장자 없는 맵 이름 (예: map_shoe_store_1021_gate67) */
  map_name: string;
  /** sha256 16진 문자열 64자 (D3) */
  map_hash: string;
  /** [m/px] 칸 크기 */
  resolution: Float;
  /** [m] 맵 원점 x (맵 YAML origin) */
  origin_x: Float;
  /** [m] 맵 원점 y */
  origin_y: Float;
  /** [rad] 맵 원점 회전 */
  origin_yaw: Float;
  /** [px] 맵 너비 */
  width: number;
  /** [px] 맵 높이 */
  height: number;
  /** 이름 붙은 지점 */
  waypoints: Waypoint[];
}

/** MediaHealth.msg */
export interface MediaHealth {
  /** stamp = 보고 시각 */
  header: Header;
  /** 미디어 서버 경로 이름 (예: cam_desk) */
  path: string;
  /** 송출자가 붙어 있는가 */
  publisher_online: boolean;
  /** [B/s] 받은 바이트율 */
  bytes_rx_rate: Float;
  /** 위 FROZEN_STATE_* 중 하나. 빈 문자열은 UNKNOWN */
  frozen_state: string;
}
export const MediaHealthConst = {
  FROZEN_STATE_LIVE: "LIVE",
  FROZEN_STATE_FROZEN: "FROZEN",
  /** 프레임 해시를 볼 수 없음 */
  FROZEN_STATE_UNKNOWN: "UNKNOWN",
} as const;

/** NodeDiag.msg */
export interface NodeDiag {
  /** 노드 이름 (예: /control_center/fms_core) */
  name: string;
  /** 그래프에 보이는가 */
  alive: boolean;
  /** [ms] 진단 서비스 왕복 시간. NaN = 미측정 */
  srv_rtt_ms: Float;
}

/** OrderStatus.msg */
export interface OrderStatus {
  header: Header;
  /** 주문 ID */
  order_id: string;
  /** 신발 종류 */
  sku: string;
  /** [개] 주문 수량 */
  qty: number;
  /** 배송할 매장 테이블 위치 */
  table_id: string;
  /** 위 STAGE_* 중 하나 (지금 단계) */
  stage: string;
  /** 지나온 단계. stage_entered_at 과 같은 순서 */
  stage_history: string[];
  /** 각 단계에 들어간 시각 */
  stage_entered_at: Time[];
  /** 실패 원인. 없으면 "" */
  failure_reason: string;
  /** [회] 재시도 횟수 (SR-14 는 3회) */
  retry_count: number;
}
export const OrderStatusConst = {
  STAGE_RECEIVED: "RECEIVED",
  STAGE_ASSIGNED: "ASSIGNED",
  STAGE_LOADING: "LOADING",
  STAGE_IN_TRANSIT: "IN_TRANSIT",
  STAGE_UNLOADING: "UNLOADING",
  STAGE_HANDOVER_CONFIRMED: "HANDOVER_CONFIRMED",
  STAGE_RETURNING: "RETURNING",
  STAGE_COMPLETED: "COMPLETED",
  STAGE_FAILED: "FAILED",
  STAGE_CANCELLED: "CANCELLED",
} as const;

/** ReconcileItem.msg */
export interface ReconcileItem {
  /** 대조 대상 (예: pinky_1) */
  target_id: string;
  /** 원장이 기대하는 값 */
  expected: string;
  /** 현장에서 관측한 값 */
  observed: string;
  /** expected 와 observed 가 같은가 */
  matched: boolean;
  /** 근거 CompletionEvidence.evidence_id */
  evidence_ids: string[];
}

/** RobotStatus.msg */
export interface RobotStatus {
  /** stamp = 측정 시각 (로봇 시계). frame_id = "map" */
  header: Header;
  /** pinky_1~3 */
  robot_id: string;
  /** 부팅(가드 기동)마다 새 값. 바뀌면 fms_core 가 대상을 UNKNOWN 으로 둔다 */
  robot_boot_id: string;
  /** 위 STATE_* 중 하나 */
  state: string;
  /** [m],[rad] map 프레임 */
  current_pose: Pose;
  /** AMCL 위치 추정이 유효한가 */
  localized: boolean;
  /** [m/s] 엔코더 기준 */
  linear_vel: Float;
  /** [rad/s] 엔코더 기준 */
  angular_vel: Float;
  /** [-] Nav2 goal 상태. action_msgs/GoalStatus 의 STATUS_* 값을 쓴다 (초안) */
  nav_status: number;
  /** [%] 0~100. NaN = 미계측 (0 으로 채우지 않는다) */
  battery_percentage: Float;
  /** v1 호환 필드. 새 코드는 state·motor_power_present 를 본다 */
  is_emergency_stopped: boolean;
  /** 모터 전원 증거. false 또는 복귀 edge 면 가드가 DISARMED 래치. 측정 수단은 D6 */
  motor_power_present: boolean;
  /** 바퀴 잠금 체결 여부 (SR-08). 상태가 아니며 여러 상태에서 true 일 수 있다 */
  base_hold_engaged: boolean;
  /** 위 HOLD_REASON_* 또는 "". STATE_HOLD·LINK_LOST 때 채운다 */
  hold_reason: string;
  /** 진행 중 작업 ID. 없으면 "" */
  current_task_id: string;
  /** [-] 가드가 받아들인 epoch. 0 = 아직 없음 */
  epoch_accepted: number;
  /** [-] 마지막으로 수락한 명령 seq */
  last_seq_accepted: number;
  /** [-] 마지막 유효 하트비트의 hb_seq 반향 (링크 RTT 상한 계산용) */
  last_heartbeat_seq: number;
  /** [ms] 마지막 유효 하트비트 뒤 경과 시간 */
  last_heartbeat_rx_age_ms: number;
  /** 로드한 맵의 sha256 16진 문자열 (D3) */
  map_hash_loaded: string;
  /** [m] 1차 정차 오차 (SR-08). NaN = 미측정 */
  dock_err_xy: Float;
  /** [rad] 1차 정차 각도 오차. NaN = 미측정 */
  dock_err_yaw: Float;
  /** [mm] ArUco 최종 정합 오차. NaN = 미측정 */
  dock_err_aruco_mm: Float;
  /** false 면 clock_offset_ms 는 의미 없음 (= 시계 모름) */
  clock_offset_known: boolean;
  /** [ms] chrony 가 보고한 시계 오프셋 */
  clock_offset_ms: number;
  /** [개] 도메인 12 의 navigate_to_pose 클라이언트 수. 1(가드) 이 정상 */
  nav2_action_clients: number;
}
export const RobotStatusConst = {
  STATE_IDLE: "IDLE",
  STATE_NAVIGATING: "NAVIGATING",
  STATE_LOADING: "LOADING",
  STATE_UNLOADING: "UNLOADING",
  /** 원격 일시정지. 현재 epoch 의 last_goal 보존. 해제는 서명된 RESUME */
  STATE_PAUSED: "PAUSED",
  /** 로컬 안전 사유 정지. 사유는 hold_reason */
  STATE_HOLD: "HOLD",
  /** 안전 대기. last_goal 없음. 해제는 새 epoch 의 서명된 START */
  STATE_DISARMED: "DISARMED",
  /** 소프트 정지 래치. RESET -> DISARMED */
  STATE_SOFT_LATCH: "SOFT_LATCH",
  /** 워치독 만료 래치. 하트비트 재개는 해제가 아니다 */
  STATE_LINK_LOST: "LINK_LOST",
  /** v1 값. SR-17 회수용으로 남긴다 (MVP 미사용) */
  STATE_RECOVERING: "RECOVERING",
  STATE_ERROR: "ERROR",
  /** 하트비트 200 ms 넘게 끊김 (SR-14). '유효' 조건은 설계 초안 */
  HOLD_REASON_WATCHDOG: "WATCHDOG",
  /** 가드가 아닌 Nav2 goal 발견 (SR-19) */
  HOLD_REASON_EXTERNAL_NAV_GOAL: "EXTERNAL_NAV_GOAL",
  /** 근접 정지 (SR-11). 초안, 주행 담당이 더한다 */
  HOLD_REASON_PROXIMITY: "PROXIMITY",
} as const;

/** TopicDiag.msg */
export interface TopicDiag {
  /** 토픽 이름 (예: /control_center/pinky_1/command) */
  name: string;
  /** [개] 발행자 수 */
  publishers: number;
  /** [Hz] 실측 유량 */
  measured_hz: Float;
  /** 위 SINGLE_WRITER_* 중 하나 */
  single_writer_state: string;
}
export const TopicDiagConst = {
  SINGLE_WRITER_NO_PUBLISHER: "NO_PUBLISHER",
  SINGLE_WRITER_OK: "OK",
  SINGLE_WRITER_VIOLATION: "VIOLATION",
} as const;

/** UnloadQueue.msg */
export interface UnloadQueue {
  header: Header;
  /** 하차 지점 (예: WP_UNLOAD) */
  waypoint_id: string;
  /** 도착 순서 (FIFO). 맨 앞이 지금 하차하는 로봇 */
  robot_ids: string[];
}

/** VisionEvent.msg */
export interface VisionEvent {
  /** UUIDv4 (초안: 증거로 가리키려고 더했다) */
  event_id: string;
  /** 위 KIND_* 중 하나 */
  kind: string;
  /** 카메라 ID */
  camera_id: string;
  /** 캡처 시각 (수신 시각 아님) */
  capture_stamp: Time;
  /** 위 AGE_BASIS_* 중 하나. 빈 문자열은 RECEIVE 로 다룬다 (초안) */
  age_basis: string;
  /** 구역 ID. 없으면 "" */
  zone_id: string;
  /** 관련 로봇. 없으면 "" */
  robot_id: string;
  /** [0~1] 인식 신뢰도 */
  confidence: Float;
}
export const VisionEventConst = {
  KIND_PERSON_IN_ZONE: "PERSON_IN_ZONE",
  KIND_QR_MATCH: "QR_MATCH",
  KIND_QR_MISMATCH: "QR_MISMATCH",
  KIND_TAIL_EXIT: "TAIL_EXIT",
  KIND_DROP: "DROP",
  AGE_BASIS_CAPTURE: "CAPTURE",
  AGE_BASIS_RECEIVE: "RECEIVE",
} as const;

/** Waypoint.msg */
export interface Waypoint {
  /** 이름 (예: WP_LOAD_1) */
  waypoint_id: string;
  /** [m] 작업점 x, map 프레임 */
  work_x: Float;
  /** [m] 작업점 y */
  work_y: Float;
  /** [rad] 작업점 방향 */
  work_yaw: Float;
  /** [m] Nav2 정차점 x, map 프레임 */
  approach_x: Float;
  /** [m] Nav2 정차점 y */
  approach_y: Float;
  /** [rad] Nav2 정차점 방향 */
  approach_yaw: Float;
  /** 이 지점에 연계된 팔 (출발 게이트용). 없으면 "" (초안) */
  arm_id: string;
}

/** ConsoleLease.srv Request */
export interface ConsoleLeaseRequest {
  /** 위 OP_* 중 하나 */
  op: string;
  /** 브라우저 세션 ID 의 해시 (원문은 싣지 않는다) */
  session_id_hash: string;
  /** 계정 ID */
  operator_id: string;
  /** customer | staff | operator (자기 신고) */
  role: string;
  /** 게이트웨이 nonce (초안: 서명 재전송 방지용으로 더했다) */
  gw_nonce: string;
  /** HMAC-SHA256(게이트웨이 키). 없으면 BAD_SIGNATURE */
  gw_sig: string;
}
export const ConsoleLeaseRequestConst = {
  OP_ACQUIRE: "ACQUIRE",
  OP_RENEW: "RENEW",
  OP_RELEASE: "RELEASE",
} as const;

/** ConsoleLease.srv Response */
export interface ConsoleLeaseResponse {
  /** 받았는가 */
  granted: boolean;
  /** 받았을 때만 채운다 */
  console_token: string;
  /** 지금 보유자 계정 ID */
  holder_id: string;
  /** 지금 보유자 역할 */
  holder_role: string;
  /** 만료 시각 */
  expires_at: Time;
  /** 거부 사유. 위 REASON_* 중 하나. 받았으면 "" */
  reason: string;
}
export const ConsoleLeaseResponseConst = {
  REASON_CONSOLE_HELD: "CONSOLE_HELD",
  REASON_BAD_SIGNATURE: "BAD_SIGNATURE",
  REASON_ROLE_FORBIDDEN: "ROLE_FORBIDDEN",
} as const;

/** OperatorCommand.srv Request */
export interface OperatorCommandRequest {
  /** UUID. 멱등 키 */
  client_request_id: string;
  /** 위 OP_* 중 하나 */
  op: string;
  /** "ALL" | robot_id | arm_id */
  scope: string;
  /** SEND_MISSION 전용. 원시 좌표는 받지 않는다 */
  waypoint_id: string;
  /** SET_MODE 전용: AUTO | MANUAL */
  mode: string;
  /** ACK_ALARM 전용 */
  alarm_id: string;
  /** 계정 ID (사람 이름 아님) */
  operator_id: string;
  /** customer | staff | operator (자기 신고) */
  role: string;
  /** 콘솔 토큰 (ConsoleLease 로 받는다) */
  console_token: string;
  /** APPROVE 때 report_hash, START 때 challenge_id */
  approval_ref: string;
  /** APPROVE 전용: Reconcile 항목별 관제사 확인 입력 ("target_id=관측값", D5) */
  attest: string[];
  /** 사람이 읽는 사유 */
  reason: string;
  /** 게이트웨이 nonce (재전송 방지) */
  gw_nonce: string;
  /** HMAC-SHA256(게이트웨이 키, 레포 밖). S3(P2) 필수 */
  gw_sig: string;
}
export const OperatorCommandRequestConst = {
  OP_PAUSE: "PAUSE",
  OP_RESUME: "RESUME",
  OP_SOFT_LATCH: "SOFT_LATCH",
  OP_RESET: "RESET",
  OP_RECONCILE: "RECONCILE",
  OP_APPROVE: "APPROVE",
  OP_START: "START",
  OP_SET_MODE: "SET_MODE",
  OP_SEND_MISSION: "SEND_MISSION",
  OP_CANCEL_MISSION: "CANCEL_MISSION",
  OP_CANCEL_ORDER: "CANCEL_ORDER",
  OP_ACK_ALARM: "ACK_ALARM",
  SCOPE_ALL: "ALL",
} as const;

/** OperatorCommand.srv Response */
export interface OperatorCommandResponse {
  /** 위 RESULT_* 중 하나 */
  result: string;
  /** 위 REJECT_* 중 하나. 거부가 아니면 "" */
  reject_code: string;
  /** 이 요청으로 낸 명령 ID */
  command_ids: string[];
  /** epochs 와 같은 순서의 대상 ID */
  epoch_targets: string[];
  /** [-] 대상별 epoch. epoch_targets 와 같은 순서 */
  epochs: number[];
  /** fms_core 가 내보낸 시각 (로봇 ACK 가 아니다) */
  dispatched_at: Time;
  /** RECONCILE 응답은 report_hash, APPROVE 응답은 challenge_id */
  approval_ref_out: string;
}
export const OperatorCommandResponseConst = {
  RESULT_DISPATCHED: "DISPATCHED",
  RESULT_DUPLICATE: "DUPLICATE",
  RESULT_REJECTED: "REJECTED",
  REJECT_NO_CONSOLE: "NO_CONSOLE",
  REJECT_ROLE_FORBIDDEN: "ROLE_FORBIDDEN",
  REJECT_STATE_CONFLICT: "STATE_CONFLICT",
  REJECT_LEASE_CONFLICT: "LEASE_CONFLICT",
  REJECT_UNKNOWN_WAYPOINT: "UNKNOWN_WAYPOINT",
  REJECT_APPROVAL_REQUIRED: "APPROVAL_REQUIRED",
  REJECT_APPROVAL_DWELL: "APPROVAL_DWELL",
  REJECT_ATTEST_MISMATCH: "ATTEST_MISMATCH",
  REJECT_CLOCK_UNSYNCED: "CLOCK_UNSYNCED",
  REJECT_LEDGER_UNAVAILABLE: "LEDGER_UNAVAILABLE",
  REJECT_BAD_SIGNATURE: "BAD_SIGNATURE",
  REJECT_ARM_INTERLOCK: "ARM_INTERLOCK",
  REJECT_INVENTORY_UNAVAILABLE: "INVENTORY_UNAVAILABLE",
} as const;

/** QueryAudit.srv Request */
export interface QueryAuditRequest {
  order_id: string;
  task_id: string;
  command_id: string;
  tx_id: string;
  target_id: string;
  event_type: string;
  /** 이 시각 이후 (0 = 경계 없음) */
  from_time: Time;
  /** 이 시각 이전 (0 = 경계 없음) */
  to_time: Time;
  /** 앞 응답의 next_cursor. 처음이면 "" */
  cursor: string;
  /** [건] 최대 500 */
  limit: number;
}

/** QueryAudit.srv Response */
export interface QueryAuditResponse {
  /** 찾은 행 */
  events: AuditEvent[];
  /** 다음 쪽 커서. 끝이면 "" */
  next_cursor: string;
  /** 해시 체인 검증 결과. false 면 원장이 바뀌었다 */
  chain_ok: boolean;
}

/** ReconcileReport.srv Request */
export interface ReconcileReportRequest {
  /** "ALL" | robot_id | arm_id */
  scope: string;
}

/** ReconcileReport.srv Response */
export interface ReconcileReportResponse {
  /** 대조 항목 */
  items: ReconcileItem[];
  /** 보고서 sha256 16진 문자열. APPROVE 때 approval_ref 로 쓴다 */
  report_hash: string;
}

/** SubmitOrder.srv Request */
export interface SubmitOrderRequest {
  /** 멱등 키. 같은 키면 같은 주문 */
  idempotency_key: string;
  /** 신발 종류 */
  sku: string;
  /** [개] 주문 수량 */
  qty: number;
  /** 배송할 매장 테이블 위치 */
  table_id: string;
  /** customer | staff | operator (자기 신고) */
  requester_role: string;
  /** 계정 ID (초안: 원장 actor_id 용으로 더했다) */
  requester_id: string;
  /** 게이트웨이 nonce (초안) */
  gw_nonce: string;
  /** HMAC-SHA256(게이트웨이 키). 없으면 BAD_SIGNATURE */
  gw_sig: string;
}

/** SubmitOrder.srv Response */
export interface SubmitOrderResponse {
  /** 주문 ID. 거부면 "" */
  order_id: string;
  /** 이미 받은 키였는가 */
  duplicate: boolean;
  /** 위 RESULT_* 중 하나 */
  result: string;
  /** 거부·예외 사유. INVENTORY_UNAVAILABLE 은 접수하되 배정 보류 (초안) */
  reject_code: string;
}
export const SubmitOrderResponseConst = {
  RESULT_ACCEPTED: "ACCEPTED",
  RESULT_REJECTED: "REJECTED",
  REJECT_BAD_SIGNATURE: "BAD_SIGNATURE",
  REJECT_ROLE_FORBIDDEN: "ROLE_FORBIDDEN",
  REJECT_INVENTORY_UNAVAILABLE: "INVENTORY_UNAVAILABLE",
  REJECT_LEDGER_UNAVAILABLE: "LEDGER_UNAVAILABLE",
} as const;

/** HandoverTask.action Goal */
export interface HandoverTaskGoal {
  /** 세션 펜싱·서명. header.robot_id = 이 Goal 을 받는 팔 (omx_1~3) */
  header: CommandHeader;
  /** 대상 핑키 (pinky_1~3) */
  robot_id: string;
  /** 작업 지점: WP_LOAD_1 | WP_LOAD_2 | WP_UNLOAD (맵 정본 확정 후, D3) */
  waypoint_id: string;
  /** 위 ACTION_TYPE_* 중 하나 */
  action_type: string;
  /** 신발 종류 */
  sku: string;
}
export const HandoverTaskGoalConst = {
  ACTION_TYPE_LOAD: "LOAD",
  ACTION_TYPE_UNLOAD: "UNLOAD",
} as const;

/** HandoverTask.action Result */
export interface HandoverTaskResult {
  /** 작업 성공 (요약. 물리 판정은 evidence_ids 로 한다) */
  success: boolean;
  /** [mm] 비전 정렬 보정량 x */
  alignment_offset_x_mm: Float;
  /** [mm] 비전 정렬 보정량 y */
  alignment_offset_y_mm: Float;
  /** [deg] 비전 정렬 보정 각도 */
  alignment_offset_yaw_deg: Float;
  /** 퇴피 완료 Z >= 280 mm (SR-10). 요약값 */
  retract_safe: boolean;
  /** 적재 확인 (SR-10). 요약값 */
  load_confirmed: boolean;
  /** 근거 CompletionEvidence.evidence_id (measured 는 증거 쪽에 있다) */
  evidence_ids: string[];
  /** 위 ERROR_CODE_* 중 하나. 오류 없으면 "" */
  error_code: string;
  /** 사람이 읽는 설명 */
  error_message: string;
}
export const HandoverTaskResultConst = {
  ERROR_CODE_QR_MISMATCH: "QR_MISMATCH",
  ERROR_CODE_GRASP_FAIL: "GRASP_FAIL",
  ERROR_CODE_HUMAN_HOLD: "HUMAN_HOLD",
  ERROR_CODE_BUS_FAULT: "BUS_FAULT",
} as const;

/** HandoverTask.action Feedback */
export interface HandoverTaskFeedback {
  /** 위 STEP_* 중 하나 */
  step: string;
  /** [%] 0~100 */
  progress_percent: Float;
}
export const HandoverTaskFeedbackConst = {
  STEP_APPROACHING: "APPROACHING",
  STEP_VISION_ALIGNING: "VISION_ALIGNING",
  STEP_GRASPING: "GRASPING",
  STEP_PLACING: "PLACING",
  STEP_RETRACTING: "RETRACTING",
  STEP_VERIFYING: "VERIFYING",
} as const;

/** RecoveryTask.action Goal */
export interface RecoveryTaskGoal {
  /** [-] DropEvent.incident_id */
  incident_id: number;
  /** [m] 맵 기준 회수 위치 */
  target_location: Point;
  target_item_type: string;
  /** "HOME_RECOVERY_POCKET" */
  destination_station: string;
}

/** RecoveryTask.action Result */
export interface RecoveryTaskResult {
  success: boolean;
  /** [s] 회수에 걸린 시간 */
  recovery_duration_sec: Float;
  /** "RE_INJECTED" or "DISCARDED" */
  final_disposition: string;
  error_message: string;
}

/** RecoveryTask.action Feedback */
export interface RecoveryTaskFeedback {
  /** "DISPATCHING", "SWEEPING_LANE", "POCKET_DELIVERED", "ARM_SORTING" */
  current_phase: string;
  /** [%] 0~100 */
  progress_percent: Float;
  /** [m] 회수 위치까지 남은 거리 */
  current_distance_to_target: Float;
}

/** 메시지 이름 → 타입. useMessages(이름) 이 이 표로 타입을 정한다. */
export interface MessageMap {
  AlarmEvent: AlarmEvent;
  ArmCommand: ArmCommand;
  ArmMode: ArmMode;
  ArmStatus: ArmStatus;
  Assignment: Assignment;
  AuditEvent: AuditEvent;
  CameraHealth: CameraHealth;
  CommandAck: CommandAck;
  CommandHeader: CommandHeader;
  CompletionEvidence: CompletionEvidence;
  DeviceDiag: DeviceDiag;
  DiagSnapshot: DiagSnapshot;
  DropEvent: DropEvent;
  FleetCommand: FleetCommand;
  FleetSafetyState: FleetSafetyState;
  FmsHeartbeat: FmsHeartbeat;
  HwEstopState: HwEstopState;
  InventoryItem: InventoryItem;
  InventoryState: InventoryState;
  LaneLeaseState: LaneLeaseState;
  MapInfo: MapInfo;
  MediaHealth: MediaHealth;
  NodeDiag: NodeDiag;
  OrderStatus: OrderStatus;
  ReconcileItem: ReconcileItem;
  RobotStatus: RobotStatus;
  TopicDiag: TopicDiag;
  UnloadQueue: UnloadQueue;
  VisionEvent: VisionEvent;
  Waypoint: Waypoint;
}

export type MessageName = keyof MessageMap;

export const MESSAGE_NAMES: MessageName[] = [
  "AlarmEvent",
  "ArmCommand",
  "ArmMode",
  "ArmStatus",
  "Assignment",
  "AuditEvent",
  "CameraHealth",
  "CommandAck",
  "CommandHeader",
  "CompletionEvidence",
  "DeviceDiag",
  "DiagSnapshot",
  "DropEvent",
  "FleetCommand",
  "FleetSafetyState",
  "FmsHeartbeat",
  "HwEstopState",
  "InventoryItem",
  "InventoryState",
  "LaneLeaseState",
  "MapInfo",
  "MediaHealth",
  "NodeDiag",
  "OrderStatus",
  "ReconcileItem",
  "RobotStatus",
  "TopicDiag",
  "UnloadQueue",
  "VisionEvent",
  "Waypoint"
];

/** 메시지·서비스·액션 이름 전부. 메뉴의 데이터 원천이 계약에 있는지 볼 때 쓴다. */
export const CONTRACT_NAMES: string[] = [
  "AlarmEvent",
  "ArmCommand",
  "ArmMode",
  "ArmStatus",
  "Assignment",
  "AuditEvent",
  "CameraHealth",
  "CommandAck",
  "CommandHeader",
  "CompletionEvidence",
  "DeviceDiag",
  "DiagSnapshot",
  "DropEvent",
  "FleetCommand",
  "FleetSafetyState",
  "FmsHeartbeat",
  "HwEstopState",
  "InventoryItem",
  "InventoryState",
  "LaneLeaseState",
  "MapInfo",
  "MediaHealth",
  "NodeDiag",
  "OrderStatus",
  "ReconcileItem",
  "RobotStatus",
  "TopicDiag",
  "UnloadQueue",
  "VisionEvent",
  "Waypoint",
  "ConsoleLease",
  "OperatorCommand",
  "QueryAudit",
  "ReconcileReport",
  "SubmitOrder",
  "HandoverTask",
  "RecoveryTask"
];
