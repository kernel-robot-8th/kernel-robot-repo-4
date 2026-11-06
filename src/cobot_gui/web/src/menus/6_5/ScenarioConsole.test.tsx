import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ScenarioConsole from "./ScenarioConsole";

const LIVE = {
  mode: "OBSERVE_ONLY",
  armed: false,
  fleet_age_sec: 0.5,
  robots: [
    {
      robot_id: "pinky1",
      op_state: "HOLD_ANOMALY",
      cargo_state: "LOADED",
      zone: "LANE",
      step_seq: 4,
      order_id: "o1",
      stage: "MOVE_DROPOFF",
      pose_x: 0.1,
      pose_y: -1,
    },
    {
      robot_id: "pinky2",
      op_state: "IDLE",
      cargo_state: "EMPTY",
      zone: "ZONE_A",
      step_seq: 0,
      order_id: null,
      stage: null,
      pose_x: null,
      pose_y: null,
    },
  ],
  missions: [
    {
      mission_id: "o1",
      route: "wh_a_to_store",
      robot_id: "pinky1",
      current_step_seq: 4,
      current_step_code: "TRANSIT_TO_STORE",
      current_stage: "MOVE_DROPOFF",
      mission_state: "PAUSED",
      hold_reason: "CCTV TRANSIT_DROP e1",
      recovery: "resume",
    },
    {
      mission_id: "o2",
      route: "wh_a_to_store",
      robot_id: "pinky3",
      current_step_seq: 3,
      current_step_code: "ARM_LOADING",
      current_stage: "LOAD",
      mission_state: "PAUSED",
      hold_reason: "",
      recovery: "fail",
    },
  ],
  anomalies: [
    {
      event_id: "e1",
      vision_class: "box_on_floor",
      judgment: "TRANSIT_DROP",
      linked_robot_id: "pinky1",
      recommended_action: "PAUSE",
      control_action: "PAUSE_ACCEPTED",
      alarm_text: "[주행 중 낙하] pinky1 이동 중 상자가 바닥에 떨어졌습니다.",
      ack_state: "UNREAD",
      repeat_count: 2,
    },
  ],
  work: [
    {
      request_id: "r1",
      order_id: "o3",
      robot_id: "pinky3",
      stage: "VERIFY_LOAD",
      target: "vision",
      action: "verify_load",
      sku: "SHOE42",
    },
  ],
  adapter: { enabled: true, blocked: "" },
  allow_mock: true,
};

function serve(live: unknown = LIVE) {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.body) calls.push({ url, body: JSON.parse(init.body as string) });
      return { ok: true, status: 200, json: async () => (init ? { ok: true } : live) };
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("6.5 시나리오 콘솔", () => {
  it("monitor_node가 없으면 연결 안 됨을 표시한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<ScenarioConsole />);
    expect(await screen.findByText(/monitor_node 연결 안 됨/)).toBeInTheDocument();
  });

  it("로봇 카드에 적재 배지, HOLD, 7단계 진행을 표시한다", async () => {
    serve();
    render(<ScenarioConsole />);
    expect(await screen.findByText("LOADED")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
    expect(screen.getByLabelText("pinky1 7단계 진행").children).toHaveLength(7);
    expect(screen.getByText(/자세 없음/)).toBeInTheDocument();
  });

  it("가동 허용과 시나리오 시작은 관제 요청으로 나간다", async () => {
    const calls = serve();
    render(<ScenarioConsole />);
    fireEvent.click(await screen.findByText("가동 허용 켜기"));
    fireEvent.click(screen.getByText("시나리오 B 출고"));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[0]).toEqual({
      url: "/api/fms/control",
      body: { type: "arm", armed: true, source: "menu_6_5" },
    });
    expect(calls[1].body).toEqual({
      type: "order",
      order: { sku: "SHOE42", route: "wh_b_to_store" },
    });
  });

  it("수동 승인은 운영자 이름이 있어야 보낸다", async () => {
    const calls = serve();
    render(<ScenarioConsole />);
    const approve = await screen.findByText("승인");
    expect(approve).toBeDisabled();
    fireEvent.change(screen.getByLabelText("운영자"), { target: { value: "kgh" } });
    fireEvent.click(approve);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      url: "/api/fms/work/r1",
      body: { decision: "approve", operator: "kgh" },
    });
  });

  it("복구는 현장 확인 4항목과 내용이 있어야 보내고 값을 대신 채우지 않는다", async () => {
    const calls = serve({ ...LIVE, armed: true });
    render(<ScenarioConsole />);
    const resume = await screen.findByText("재개");
    fireEvent.change(screen.getByLabelText("운영자"), { target: { value: "kgh" } });
    expect(resume).toBeDisabled();
    for (const label of ["로봇 정지", "팔 퇴피", "화물 확인", "통로·구역 확인"]) {
      fireEvent.click(screen.getByLabelText(label));
    }
    expect(resume).toBeDisabled();
    fireEvent.change(screen.getByLabelText("확인 내용"), { target: { value: "상자 제거" } });
    fireEvent.click(resume);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({
      type: "resolve",
      order_id: "o1",
      decision: "resume",
      operator: "kgh",
      note: "상자 제거",
      evidence: {
        base_stopped: true,
        arms_safe: true,
        cargo_reconciled: true,
        resources_clear: true,
      },
    });
  });

  it("가동 허용이 꺼져 있으면 재개를 막고, 상·하차 단계에는 재개 버튼이 없다", async () => {
    serve();
    render(<ScenarioConsole />);
    expect(await screen.findByText("재개")).toBeDisabled();
    expect(screen.getAllByText("재개")).toHaveLength(1);
    expect(screen.getAllByText("실패 처리")).toHaveLength(2);
  });

  it("주문 없이 구역에 남은 로봇은 구역 이탈 요청을 낸다", async () => {
    const calls = serve();
    render(<ScenarioConsole />);
    fireEvent.click(await screen.findByText("pinky2 구역 이탈"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({
      type: "create",
      robot_id: "pinky2",
      operation: "leave",
      points: [],
    });
  });

  it("이상 판정과 조치 결과를 표시하고 모의 주입을 보낸다", async () => {
    const calls = serve();
    render(<ScenarioConsole />);
    expect(await screen.findByText("TRANSIT_DROP")).toBeInTheDocument();
    expect(screen.getByText("PAUSE_ACCEPTED x2")).toBeInTheDocument();
    fireEvent.click(screen.getByText("이상 모의 주입"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      url: "/api/fms/anomalies",
      body: { vision_class: "box_on_floor", map_x: 0.6, map_y: 0.5 },
    });
  });

  it("관제 스냅샷이 끊기면 끊김을 표시한다", async () => {
    serve({ ...LIVE, fleet_age_sec: 30 });
    render(<ScenarioConsole />);
    expect(await screen.findByText("관제 수신 끊김")).toBeInTheDocument();
  });

  it("거절 사유를 숨기지 않는다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) =>
        init
          ? { ok: false, status: 423, json: async () => ({ detail: "작업 명령 꺼짐" }) }
          : { ok: true, status: 200, json: async () => LIVE },
      ),
    );
    render(<ScenarioConsole />);
    fireEvent.click(await screen.findByText("시나리오 A 출고"));
    expect(await screen.findByText("거절 423: 작업 명령 꺼짐")).toBeInTheDocument();
  });
});
