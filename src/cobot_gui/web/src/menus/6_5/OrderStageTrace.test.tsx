import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OrderStageTrace, { type StageTraceRow } from "./OrderStageTrace";

const SAMPLE_TRACE: StageTraceRow[] = [
  {
    stage_code: "MOVE_PICKUP",
    stage_name: "1 상차지로 이동",
    target: "pinky",
    action: "zone",
    is_correction: false,
    attempt_no: 1,
    command_id: "cmd_move_zb",
    request_id: null,
    status: "FAILED",
    checkpoints: {
      requested: true,
      received: "CONFIRMED",
      result: "NONE",
      accepted: "REJECTED",
      next_stage: false,
    },
    evidence_summary: "구역 B 점유 · UNKNOWN (운영자 stop) · 로봇 정지 (도착 미성공)",
    evidence_detail: null,
    hold_reason: "운영자 비상 정지",
  },
  {
    stage_code: "DOCK_PICKUP",
    stage_name: "3 상차 접안 확인",
    target: "vision",
    action: "dock_check",
    is_correction: false,
    attempt_no: 1,
    command_id: null,
    request_id: "req_dock_1",
    status: "COMPLETED",
    checkpoints: {
      requested: true,
      received: "CONFIRMED",
      result: "MEASURED",
      accepted: "ACCEPTED",
      next_stage: true,
    },
    evidence_summary: "접안 정차 오차 0.008m, 0.8° (공차 이내)",
    evidence_detail: {
      xy_m: 0.008,
      yaw_deg: 0.8,
      stopped: true,
      base_hold: true,
    },
    hold_reason: null,
  },
  {
    stage_code: "CORRECT_PICKUP",
    stage_name: "3a 접안 보정",
    target: "navigation",
    action: "dock_correct",
    is_correction: true,
    attempt_no: 1,
    command_id: null,
    request_id: "req_corr_1",
    status: "COMPLETED",
    checkpoints: {
      requested: true,
      received: "CONFIRMED",
      result: "MEASURED",
      accepted: "ACCEPTED",
      next_stage: true,
    },
    evidence_summary: "보정 1회차 완료 (도킹 재측정으로 이동)",
    evidence_detail: {
      dx_m: 0.015,
      dyaw_deg: 1.2,
    },
    hold_reason: null,
  },
  {
    stage_code: "VERIFY_LOAD",
    stage_name: "7 적재 검증",
    target: "vision",
    action: "verify_load",
    is_correction: false,
    attempt_no: 1,
    command_id: null,
    request_id: "req_vl_7",
    status: "RUNNING",
    checkpoints: {
      requested: true,
      received: "UNCONFIRMED",
      result: "NONE",
      accepted: "WAITING",
      next_stage: false,
    },
    evidence_summary: "적재 표본 1개 대기 (2/3) · 팔 퇴피 확인됨",
    evidence_detail: {
      decision: "camera_and_operator",
      operator: "op_test",
      arm_confirmed_at: 1793790015,
      evidence: [
        { capture_time: 1793790010, frame_age_ms: 120, box_present: true },
        { capture_time: 1793790012, frame_age_ms: 100, box_present: true },
      ],
    },
    hold_reason: null,
  },
];

describe("OrderStageTrace (주문별 19단계 및 보정 시도 추적)", () => {
  it("장치 수신이 확인되지 않은 단계는 '수신 미확인' 배지를 명확히 표시한다", () => {
    render(<OrderStageTrace orderId="ord_100" trace={SAMPLE_TRACE} />);

    expect(screen.getByText("주문 ord_100 19단계 동작 및 보정 시도 추적")).toBeInTheDocument();
    // 7번 적재 검증은 UNCONFIRMED이므로 '수신 미확인'이 렌더링되어야 함
    expect(screen.getByText("수신 미확인")).toBeInTheDocument();
  });

  it("합격 시험 1: UNKNOWN(stop) 사례는 '도착 미성공' 및 거절/보류로 표시된다", () => {
    render(<OrderStageTrace orderId="ord_100" trace={SAMPLE_TRACE} />);

    expect(screen.getByText(/UNKNOWN \(운영자 stop\) · 로봇 정지 \(도착 미성공\)/)).toBeInTheDocument();
    expect(screen.getByText("거절/보류")).toBeInTheDocument();
  });

  it("보정 하위 단계(3a)는 들여쓰기 기호와 함께 보정 횟수를 표시한다", () => {
    render(<OrderStageTrace orderId="ord_100" trace={SAMPLE_TRACE} />);

    expect(screen.getByText("3a 접안 보정")).toBeInTheDocument();
    expect(screen.getByText("보정 1회차 완료 (도킹 재측정으로 이동)")).toBeInTheDocument();
  });

  it("도킹 및 적재 증거 서랍을 열어 실측 오차와 카메라 표본 목록을 확인한다", () => {
    render(<OrderStageTrace orderId="ord_100" trace={SAMPLE_TRACE} />);

    // 7번 VERIFY_LOAD의 증거 서랍이 기본 열려있음
    expect(screen.getByText(/수신된 카메라 적재 표본 \(2\/3개\)/)).toBeInTheDocument();
    expect(screen.getByText("운영자: op_test")).toBeInTheDocument();
    expect(screen.getByText("표본 #1")).toBeInTheDocument();
    expect(screen.getByText("표본 #2")).toBeInTheDocument();

    // 3번 접안 단계의 열람 버튼 클릭
    const buttons = screen.getAllByRole("button", { name: "열람" });
    fireEvent.click(buttons[0]); // 3 상차 접안 확인 열람

    expect(screen.getByText(/위치 오차: 0.008m/)).toBeInTheDocument();
    expect(screen.getByText(/각도 오차: 0.8°/)).toBeInTheDocument();
  });
});

it("이전 DB의 누락 필드를 박스 미검출로 오독하지 않고 지연 0도 표시한다", () => {
  const load = { ...SAMPLE_TRACE[3], evidence_detail: {
    evidence: [{ capture_time: 1, frame_age_ms: 0 }], decision: "camera_and_operator",
  } };
  render(<OrderStageTrace orderId="recorded" trace={[load]} />);
  expect(screen.getByText(/박스 판정 미기록/)).toBeInTheDocument();
  expect(screen.getByText(/0 ms/)).toBeInTheDocument();
});
