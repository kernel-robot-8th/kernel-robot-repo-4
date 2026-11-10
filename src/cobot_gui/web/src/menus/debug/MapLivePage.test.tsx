import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/routes";
import { MAP_STATE_URL, MAP_STREAM_URL, parseMapState, robotAgeSec } from "./useMapView";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NOW = 1_794_000_000;

function camera(extra: Record<string, unknown> = {}) {
  return {
    id: "ceiling", name: "천장 폰", state: "running", connected: true, stale: false, frame_age_sec: 0.2,
    input: { fps_received: 11.7 }, fps_processed: 5.0, detect_ms_recent: 122.4,
    map: { state: "OK", markers_seen: 4, visible: true, box: [57, 224, 927, 1040], rejected: 0, dropped_outside: 7 },
    current: [{ event_type: "box_on_floor", confidence: 0.91, in_roi: false, bbox: [1, 2, 3, 4] }],
    ...extra,
  };
}

function robot(id: string, extra: Record<string, unknown> = {}) {
  return {
    robot_id: id, op_state: "MOVING", cargo_state: "LOADED", battery_percent: 81, zone: "ZB", step_seq: 7,
    order_id: "ORD-1", stage: "VERIFY_LOAD", pose_x: 1, pose_y: 2, driving: true, speed_mps: 0.21,
    waypoint: "ZC", updated_at: NOW - 1, ...extra,
  };
}

function live(robots: unknown[]) {
  return {
    time: NOW, mode: "OBSERVE_ONLY", armed: false, fleet_age_sec: 1, robots, holds: {}, missions: [], anomalies: [],
    work: [], adapter: { enabled: false, blocked: "" }, allow_mock: false, commands_enabled: false,
    ros: {}, zones: [], links: [], log: [], tasks: [], routes: {},
  };
}

/** 주소별로 응답을 정한다. 뷰어 응답이 null 이면 502 로 답한다. */
function stubFetch(viewer: unknown, robots: unknown[]) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method ?? "GET" });
      if (url === MAP_STATE_URL) {
        return viewer === null
          ? new Response("", { status: 502 })
          : new Response(JSON.stringify(viewer), { status: 200 });
      }
      if (url.startsWith("/api/fms/live_state")) return new Response(JSON.stringify(live(robots)), { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/debug/camera"]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("7. 맵 실시간 화면", () => {
  it("맵 영역 영상과 마커·추론 수치를 보인다", async () => {
    const calls = stubFetch({ model: "kneg_v3 abcd1234", cameras: [camera()] }, [robot("pinky1")]);
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: /7\. 맵 실시간 화면/ })).toBeInTheDocument();
    expect(await screen.findByText("마커 4개 인식")).toBeInTheDocument();
    const image = screen.getByRole("img", { name: "마커 안쪽 맵 영역 실시간 영상" });
    expect(image.getAttribute("src")).toContain(MAP_STREAM_URL);
    expect(screen.getByText("4/4 OK")).toBeInTheDocument();
    expect(screen.getByText("11.7 fps")).toBeInTheDocument();
    expect(screen.getByText("box_on_floor 0.91")).toBeInTheDocument();
    expect(screen.getByText(/맵 밖이라 뺀 누계 7건/)).toBeInTheDocument();
    // 이 화면은 읽기만 한다.
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("로봇 주행 상태를 카드로 보이고, 오래된 값은 수신 끊김으로 보인다", async () => {
    stubFetch({ model: "m", cameras: [camera()] }, [
      robot("pinky1"),
      robot("pinky2", { driving: false, speed_mps: 0, op_state: "IDLE", stage: null, order_id: null }),
      robot("pinky3", { updated_at: NOW - 60 }),
    ]);
    renderPage();
    const first = (await screen.findByText("pinky1")).closest("div[class*='border']") as HTMLElement;
    expect(within(first).getByText("주행 중", { selector: "div" })).toBeInTheDocument();
    expect(within(first).getByText("0.21 m/s")).toBeInTheDocument();
    expect(within(first).getByText("7. VERIFY_LOAD")).toBeInTheDocument();
    const second = screen.getByText("pinky2").closest("div[class*='border']") as HTMLElement;
    expect(within(second).getByText("정지")).toBeInTheDocument();
    expect(within(second).getByText("임무 없음")).toBeInTheDocument();
    const third = screen.getByText("pinky3").closest("div[class*='border']") as HTMLElement;
    expect(within(third).getByText("수신 끊김")).toBeInTheDocument();
    expect(within(third).getByText("60.0초 전")).toBeInTheDocument();
  });

  it("마커를 놓치면 가림 상태를 알린다", async () => {
    stubFetch({ model: "m", cameras: [camera({ map: { state: "LOST", markers_seen: 1, visible: false } })] }, []);
    renderPage();
    expect(await screen.findByText("마커 인식 실패 (영상 가림)")).toBeInTheDocument();
    expect(screen.getByText("1/4 LOST")).toBeInTheDocument();
    expect(screen.getByText("로봇 상태 수신 대기 중...")).toBeInTheDocument();
  });

  it("뷰어가 꺼져 있으면 영상 대신 안내를 보인다", async () => {
    stubFetch(null, [robot("pinky1")]);
    renderPage();
    expect(await screen.findByText("영상 뷰어에 연결하지 못했습니다")).toBeInTheDocument();
    expect(screen.getByText("뷰어 연결 끊김")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
    expect(await screen.findByText("pinky1")).toBeInTheDocument();
  });

  it("폰 영상이 끊기면 영상을 내리고 알린다", async () => {
    stubFetch({ model: "m", cameras: [camera({ connected: false, stale: true })] }, []);
    renderPage();
    expect(await screen.findByText("폰 영상이 들어오지 않습니다")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("값 정리", () => {
  it("형식이 다른 뷰어 응답은 오류로, 빠진 값은 null 로 본다", () => {
    expect(() => parseMapState({ cameras: "x" })).toThrow();
    expect(parseMapState({ cameras: [] }).camera).toBeNull();
    const parsed = parseMapState({ cameras: [{ id: "ceiling", state: "running", current: [{ event_type: 3 }] }] }).camera;
    expect(parsed?.markerState).toBe("UNKNOWN");
    expect(parsed?.visible).toBe(false);
    expect(parsed?.stale).toBe(true);
    expect(parsed?.fpsProcessed).toBeNull();
    expect(parsed?.detections).toEqual([]);
  });

  it("로봇 값의 나이는 모니터 시계끼리 뺀다", () => {
    expect(robotAgeSec({ updated_at: NOW - 1 }, NOW)).toBe(1);
    expect(robotAgeSec({ updated_at: null }, NOW)).toBeNull();
    expect(robotAgeSec({ updated_at: NOW - 1 }, undefined)).toBeNull();
  });
});
