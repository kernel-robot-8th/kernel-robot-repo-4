import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { AppRoutes } from "@/routes";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const snapshot = {
  time: 1234, mode: "OBSERVE_ONLY", fleet_age_sec: null, armed: null, robots: [], holds: {},
  zones: [], links: [], log: [], tasks: [], routes: {}, work: [], diagnostics: null, anomalies: [],
  adapter: { enabled: false }, commands_enabled: false,
  missions: ["orderA", "orderB"].map(mission_id => ({ mission_id, current_step_code: "LOAD" })),
  ready_graph: { request: { publishers: 0, subscribers: 1 }, tasks: { publishers: 0, subscribers: 1 },
    robots: { pinky1: { patrol_cmd: { publishers: 2, subscribers: 1 } } } },
};
function renderPage(path: string) {
  render(<MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter>);
}
function liveOnly() {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(snapshot)));
}

it("모니터 HTTP 연결과 관제 미수신을 구분한다", async () => {
  liveOnly(); renderPage("/");
  await screen.findByText("orderA");
  expect(screen.getByText("관제 수신 끊김")).toBeInTheDocument();
  expect(screen.getByText("가동 상태 미확인")).toBeInTheDocument();
});
it("P2는 토픽별 개수를 비교하고 P10은 진단기가 없으면 미확인이다", async () => {
  liveOnly(); renderPage("/debug/comm");
  const row = (await screen.findByText("tasks", { selector: "td" })).closest("tr")!;
  expect(within(row).getByText(/조건 미충족 · 발행 0\/1/)).toBeInTheDocument();
  expect(screen.getByText(/조건 미충족 · 구독 1\/1 · 발행 2\/1/)).toBeInTheDocument();
  expect(screen.getByText(/순찰 경고 미확인/)).toBeInTheDocument();
});
it("다른 요청 결과 원문을 보존하고 주문 전환 직후 이전 원문을 숨긴다", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("live_state")) return Response.json(snapshot);
    if (url.includes("orderB")) return new Promise<Response>(() => {});
    return Response.json({ order_id: "orderA", trace: [], unmatched_results: [{ request_id: "foreign-A" }] });
  }));
  renderPage("/debug/trace");
  fireEvent.click(await screen.findByRole("button", {name:/orderA/}));
  expect(await screen.findByText(/foreign-A/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:/orderB/}));
  expect(screen.queryByText(/foreign-A/)).not.toBeInTheDocument();
});
it("녹화에서 빈 차와 적재 예측을 비교하며 상태 변경 요청을 보내지 않는다", async () => {
  liveOnly(); renderPage("/debug/vision");
  const input = screen.getByLabelText("녹화 추론 JSONL");
  const file = {text: async () => JSON.stringify({stream_epoch:"clip",frame_seq:2,zones:{ZA:"LOADED"}})};
  fireEvent.change(input, {target:{files:[file]}});
  await screen.findByText("모델 판정 LOADED");
  fireEvent.change(screen.getByLabelText("영상 정답"),{target:{value:"EMPTY"}});
  expect(screen.getByText("대조 결과 불일치")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name:/실패 처리|제어권 반환/})).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.every(([,init]) => !init?.method || init.method==="GET")).toBe(true);
});

it("SQLite 원문은 선택 주문만 조회하고 관제 RTT를 장치 결과와 구분한다", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("live_state")) return Response.json(snapshot);
    if (url.includes("orderA/history")) return Response.json({order_id:"orderA",next_cursor:null,events:[
      {id:1,kind:"control_reply",request_id:"ctl",at:10,payload:{rtt_ms:24.5}},
      {id:2,kind:"result",request_id:"device",at:11,payload:{stage:"PICK"}},
    ]});
    return Response.json({order_id:"orderA",trace:[],unmatched_results:[]});
  }));
  renderPage("/debug/trace");
  fireEvent.click(await screen.findByRole("button",{name:/orderA/}));
  fireEvent.click(screen.getByText("SQLite 주문 원문 이력"));
  expect(await screen.findByText("24.5 ms")).toBeInTheDocument();
  expect(screen.getByText("미측정")).toBeInTheDocument();
});
