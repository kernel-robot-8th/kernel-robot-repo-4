import type { ReactNode } from "react";
import { Fragment } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MemoryRouter } from "react-router-dom";
import { FmsLiveProvider } from "@/lib/fmsLiveContext";
import LiveOverviewPage from "../debug/LiveOverviewPage";
import CommDiagnosticsPage from "../debug/CommDiagnosticsPage";
import OrderTracePage from "../debug/OrderTracePage";
import VisionControls from "../debug/VisionControls";
import ManualMoveTools from "../debug/ManualMoveTools";

function show(...panels: ReactNode[]) {
  render(<MemoryRouter initialEntries={["/debug/trace"]}><FmsLiveProvider>{panels.map((panel, i) => <Fragment key={i}>{panel}</Fragment>)}</FmsLiveProvider></MemoryRouter>);
}

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
      route: "lab_delivery",
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
      route: "lab_delivery",
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
  commands_enabled: true,
  holds: {},
  ros: { domain_id: "77", rmw: "rmw_fastrtps_cpp", monitor_site: "sim_gate67.yaml", site_sha256: "123456789abcdef0" },
  zones: [
    { zone: "A", manager_known: true, manager: "pinky2", robot: null, match: false },
    { zone: "C", manager_known: false, manager: null, robot: "pinky1", match: null },
  ],
  links: [
    {
      robot_id: "pinky1",
      status: { state: "MOVING", detail: "ZC", waypoint: 1, total: 3, busy: true, central_latched: false },
      ages: { patrol_status: 0.4 },
      graph: {
        patrol_status: { publishers: 1, subscribers: 2 },
        scan: { publishers: 1, subscribers: 0, reliability: ["BEST_EFFORT"] },
      },
      problems: ["patrol_cmd 발행자 2개 (1개여야 함)"],
    },
  ],
  log: [
    {
      at: 1793790000,
      type: "create",
      robot_id: "pinky1",
      operation: "goto",
      points: ["P1"],
      status: 423,
      rtt_ms: 12.5,
      detail: "작업 명령 꺼짐",
    },
  ],
  tasks: [{ task_id: "t1", robot_id: "pinky1", command: "zone:ZC", state: "RUNNING", detail: "" }],
  routes: { pinky1: ["P5", "P6", "ZC"] },
};

function serve(live: unknown = LIVE) {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.body) calls.push({ url, body: JSON.parse(init.body as string) });
      return { ok: true, status: 200, json: async () => (init?.body ? { ok: true } : live) };
    }),
  );
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("역할별 시뮬 관제 도구", () => {
  it("monitor_node가 없으면 연결 안 됨을 표시한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    show(<LiveOverviewPage/>);
    expect(await screen.findByText("관제 수신 끊김")).toBeInTheDocument();
  });

  it("로봇 카드에 적재 배지, HOLD, 7단계 진행을 표시한다", async () => {
    serve();
    show(<LiveOverviewPage/>);
    expect(await screen.findByText("LOADED")).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
    expect(screen.getByLabelText("pinky1 7단계 진행").children).toHaveLength(7);
    expect(screen.getByText(/좌표: 미수신/)).toBeInTheDocument();
  });

  it("가동 허용과 시나리오 시작은 관제 요청으로 나간다", async () => {
    const calls = serve();
    show(<LiveOverviewPage/>);
    fireEvent.click(await screen.findByText("가동 허용 켜기"));
    fireEvent.click(screen.getByText("시나리오 B 출고 (ZB)"));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[0]).toEqual({
      url: "/api/fms/control",
      body: { type: "arm", armed: true, source: "menu_6_5" },
    });
    expect(calls[1].body).toEqual({
      type: "order",
      order: { sku: "SHOE42", route: "lab_delivery_zb", quantity: 1 },
    });
  });

  it("수동 승인은 운영자 이름이 있어야 보낸다", async () => {
    const calls = serve();
    show(<VisionControls/>);
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
    show(<VisionControls/>);
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
    show(<VisionControls/>);
    expect(await screen.findByText("재개")).toBeDisabled();
    expect(screen.getAllByText("재개")).toHaveLength(1);
    expect(screen.getAllByText("실패 처리")).toHaveLength(2);
  });

  it("주문 없이 구역에 남은 로봇은 구역 이탈 요청을 낸다", async () => {
    const calls = serve();
    show(<ManualMoveTools/>);
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
    show(<VisionControls/>, <ManualMoveTools/>);
    expect(await screen.findByText("TRANSIT_DROP")).toBeInTheDocument();
    expect(screen.getByText("PAUSE_ACCEPTED x2")).toBeInTheDocument();
    fireEvent.click(screen.getByText("이상 모의 주입"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      url: "/api/fms/anomalies",
      body: { vision_class: "box_on_floor", map_x: 0.6, map_y: 0.5 },
    });
  });

  it("읽기 전용이면 모든 명령 버튼을 막고 이유를 표시한다", async () => {
    serve({ ...LIVE, commands_enabled: false });
    show(<LiveOverviewPage/>, <ManualMoveTools/>);
    expect(await screen.findByText("읽기 전용")).toBeInTheDocument();
    for (const label of ["전체 비상 정지 요청", "가동 허용 켜기", "시나리오 A 출고 (ZA)", "명령 요청", "이상 모의 주입"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("전체 비상 정지는 로봇을 지정하지 않은 관제 요청으로 나간다", async () => {
    const calls = serve();
    show(<LiveOverviewPage/>);
    fireEvent.click(await screen.findByText("전체 비상 정지 요청"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({ url: "/api/fms/control", body: { type: "estop" } });
  });

  it("정지 상태이면 이동과 출고를 막고 제어권 반환을 내놓는다", async () => {
    const calls = serve({ ...LIVE, holds: { pinky2: "ESTOP" } });
    show(<LiveOverviewPage/>, <VisionControls/>, <ManualMoveTools/>);
    expect(await screen.findByText(/정지.*pinky2/)).toBeInTheDocument();
    expect(screen.getByText("명령 요청")).toBeDisabled();
    expect(screen.getByText("시나리오 A 출고 (ZA)")).toBeDisabled();
    expect(screen.getByText("pinky2 구역 이탈")).toBeDisabled();
    const release = screen.getByText("제어권 반환");
    expect(release).toBeDisabled();
    fireEvent.change(screen.getByLabelText("운영자"), { target: { value: "kgh" } });
    for (const label of ["로봇 정지", "팔 퇴피", "화물 확인", "통로·구역 확인"]) {
      fireEvent.click(screen.getByLabelText(label));
    }
    fireEvent.change(screen.getByLabelText("확인 내용"), { target: { value: "정지 확인" } });
    fireEvent.click(release);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({ type: "release_control", robot_id: "pinky2", operator: "kgh" });
  });

  it("이동 명령은 로봇 토픽이 아니라 관제 요청으로 나간다", async () => {
    const calls = serve();
    show(<ManualMoveTools/>);
    fireEvent.change(await screen.findByLabelText("명령 종류"), { target: { value: "goto" } });
    fireEvent.change(screen.getByLabelText("지점"), { target: { value: "P1, P2" } });
    fireEvent.click(screen.getByText("명령 요청"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      url: "/api/fms/control",
      body: { type: "create", robot_id: "pinky1", operation: "goto", points: ["P1", "P2"] },
    });
  });

  it("leave는 지점 없이 보낸다", async () => {
    const calls = serve();
    show(<ManualMoveTools/>);
    fireEvent.change(await screen.findByLabelText("명령 종류"), { target: { value: "leave" } });
    expect(screen.getByLabelText("지점")).toBeDisabled();
    fireEvent.click(screen.getByText("명령 요청"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({ operation: "leave", points: [] });
  });

  it("구역 관리자와 로봇이 다르면 불일치로 표시한다", async () => {
    serve();
    show(<CommDiagnosticsPage/>);
    expect(await screen.findByText(/불일치 \(경고\)/)).toBeInTheDocument();
    expect(screen.getAllByText("pinky2")[0]).toBeInTheDocument();
    expect(screen.getByText("관리자 값 없음")).toBeInTheDocument();
  });

  it("연결 진단은 실제 값과 이동 거절 사유를 표시한다", async () => {
    serve();
    show(<CommDiagnosticsPage/>);
    expect(await screen.findByText("도메인 77 / rmw_fastrtps_cpp")).toBeInTheDocument();
    expect(screen.getByText(/sim_gate67.yaml/)).toBeInTheDocument();
    expect(screen.getByText(/12345678/)).toBeInTheDocument();
    expect(screen.getByText(/이동 거절 사유: patrol_cmd 발행자 2개/)).toBeInTheDocument();
    expect(screen.getByText(/patrol_status: 발행자 1개/)).toBeInTheDocument();
    expect(screen.getByText(/amcl_pose: 발행자 \?개/)).toBeInTheDocument();
    expect(screen.getByText(/BEST_EFFORT/)).toBeInTheDocument();
  });

  it("경유 기록과 요청 응답을 표시한다", async () => {
    serve();
    show(<CommDiagnosticsPage/>);
    expect(await screen.findByText(/P5 → P6 → ZC/)).toBeInTheDocument();
    expect(screen.getByText("423")).toBeInTheDocument();
    expect(screen.getByText("12.5ms")).toBeInTheDocument();
    expect(screen.getByText("zone:ZC")).toBeInTheDocument();
  });

  it("관제 스냅샷이 끊기면 끊김을 표시한다", async () => {
    serve({ ...LIVE, fleet_age_sec: 30 });
    show(<LiveOverviewPage/>);
    expect(await screen.findByText("관제 수신 끊김")).toBeInTheDocument();
  });

  it("거절 사유를 숨기지 않는다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) =>
        init?.body
          ? { ok: false, status: 423, json: async () => ({ detail: "작업 명령 꺼짐" }) }
          : { ok: true, status: 200, json: async () => LIVE },
      ),
    );
    show(<LiveOverviewPage/>);
    fireEvent.click(await screen.findByText("시나리오 A 출고 (ZA)"));
    expect(await screen.findByText("거절 423: 작업 명령 꺼짐")).toBeInTheDocument();
  });

  it("주문 목록에서 주문을 선택하면 19단계 추적 패널과 5대 체크포인트 및 증거 서랍이 열린다", async () => {
    const traceData = [
      {
        stage_code: "MOVE_PICKUP",
        stage_name: "1 상차지로 이동",
        target: "pinky",
        action: "zone",
        is_correction: false,
        attempt_no: 1,
        command_id: "cmd_01",
        request_id: null,
        status: "COMPLETED",
        checkpoints: {
          requested: true,
          received: "CONFIRMED",
          result: "MEASURED",
          accepted: "ACCEPTED",
          next_stage: true,
        },
        evidence_summary: "도착 완료 (task_finished)",
        evidence_detail: null,
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
        request_id: "req_vl",
        status: "COMPLETED",
        checkpoints: {
          requested: true,
          received: "CONFIRMED",
          result: "MEASURED",
          accepted: "ACCEPTED",
          next_stage: true,
        },
        evidence_summary: "적재 확인 완료 (camera_and_operator, 표본 3개)",
        evidence_detail: {
          decision: "camera_and_operator",
          operator: "op_kgh",
          arm_confirmed_at: 1793790010,
          evidence: [
            { capture_time: 1793790008, frame_age_ms: 120, box_present: true },
            { capture_time: 1793790009, frame_age_ms: 110, box_present: true },
            { capture_time: 1793790010, frame_age_ms: 105, box_present: true },
          ],
        },
        hold_reason: null,
      },
    ];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.body) return { ok: true, status: 200, json: async () => ({ ok: true }) };
        if (url.includes("/trace")) return { ok: true, status: 200, json: async () => ({ order_id: "o1", trace: traceData }) };
        return { ok: true, status: 200, json: async () => LIVE };
      }),
    );

    show(<OrderTracePage/>);
    fireEvent.click(await screen.findByRole("button", {name:/o1/}));
    expect(await screen.findByText("주문 o1 19단계 동작 및 보정 시도 추적")).toBeInTheDocument();
    expect(screen.getByText("1 상차지로 이동")).toBeInTheDocument();
    expect(screen.getByText("7 적재 검증")).toBeInTheDocument();
    expect(screen.getByText("도착 완료 (task_finished)")).toBeInTheDocument();
    expect(screen.getByText(/적재 확인 완료/)).toBeInTheDocument();

    // 7번 증거 열람 서랍 검증
    expect(screen.getByText(/수신된 카메라 적재 표본 \(3\/3개\)/)).toBeInTheDocument();
    expect(screen.getByText(/운영자: op_kgh/)).toBeInTheDocument();
  });
});
