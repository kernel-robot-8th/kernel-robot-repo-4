import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/routes";
import ResourceMonitorPage from "./ResourceMonitorPage";
import { clock, describeError, fmt, HISTORY_URL, LATEST_URL } from "./useResources";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setHidden(false);
});

/** 탭 숨김 상태를 흉내 낸다 (jsdom 의 document.hidden 은 기본 false). */
function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
}

const NOW = 1_794_000_000;

function relay(extra: Record<string, unknown> = {}) {
  return {
    id: "relay", name: "중계", address: "local",
    collected_at: NOW - 4, last_attempt_at: NOW - 4, ok: true, error: null, duration_ms: 310,
    cpu: { cores: 12, used_pct: 42, load1: 1.25 },
    memory: { total_mb: 16000, used_mb: 8000, available_mb: 8000 },
    disk: [{ mount: "/", total_gb: 468, used_gb: 120.5, avail_gb: 323.6, used_pct: 27.1 }],
    gpus: [], gpu_note: "NVIDIA GPU 없음",
    containers: [
      { name: "mosquitto-broker", image: "eclipse-mosquitto:latest", status: "Up 2 days",
        cpu_pct: 0.3, mem_used_mb: 12, mem_limit_mb: 15700, mem_pct: 0.1 },
      { name: "fms-web-server", image: "node:22.14.0-bookworm", status: "Up 2 days",
        cpu_pct: null, mem_used_mb: null, mem_limit_mb: null, mem_pct: null },
    ],
    containers_note: null,
    ...extra,
  };
}

function omen8(extra: Record<string, unknown> = {}) {
  return {
    id: "omen8", name: "8-OMEN", address: "192.168.0.5",
    collected_at: NOW - 6, last_attempt_at: NOW - 6, ok: true, error: null, duration_ms: 820,
    cpu: { cores: 16, used_pct: 95, load1: 15.2 },
    memory: { total_mb: 32000, used_mb: 25600, available_mb: 6400 },
    disk: [{ mount: "/", total_gb: 900, used_gb: 450, avail_gb: 404, used_pct: 52.7 }],
    gpus: [{ name: "NVIDIA GeForce RTX 4060", util_pct: 61, mem_used_mb: 4096, mem_total_mb: 8192, temp_c: 66 }],
    gpu_note: null,
    containers: [{ name: "sim", image: "sim:dev", status: "Up 3 hours", cpu_pct: 88.4, mem_used_mb: 2048, mem_limit_mb: 32000, mem_pct: 6.4 }],
    containers_note: null,
    ...extra,
  };
}

function team11(extra: Record<string, unknown> = {}) {
  return {
    id: "team11", name: "team11", address: "192.168.0.4",
    collected_at: NOW - 8, last_attempt_at: NOW - 8, ok: true, error: null, duration_ms: 640,
    cpu: { cores: 24, used_pct: 12.5, load1: 0.8 },
    memory: { total_mb: 64000, used_mb: 9600, available_mb: 54400 },
    disk: [{ mount: "/", total_gb: 1800, used_gb: 300, avail_gb: 1400, used_pct: 17.6 }],
    gpus: [{ name: "NVIDIA GeForce RTX 5080 Laptop GPU", util_pct: 7, mem_used_mb: 1638, mem_total_mb: 16303, temp_c: 51 }],
    gpu_note: null,
    containers: [], containers_note: "docker 조회 권한 없음",
    ...extra,
  };
}

function latest(hosts: unknown[] = [relay(), omen8(), team11()], extra: Record<string, unknown> = {}) {
  return { schema: 1, generated_at: NOW, interval_sec: 10, stale_after_sec: 30, hosts, ...extra };
}

function history() {
  const series = (base: number, gpu: number | null) =>
    Array.from({ length: 12 }, (_, i) => ({
      t: NOW - 110 + i * 10, cpu: base + i, mem: 50, gpu, gpu_mem: gpu, gpu_temp: gpu === null ? null : 60,
    }));
  return { schema: 1, generated_at: NOW, hosts: { relay: series(30, null), omen8: series(80, 61), team11: series(10, 7) } };
}

function stubFetch(latestBody: unknown = latest(), historyBody: unknown = history()) {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    return Response.json(String(url).startsWith("/api/resources/history") ? historyBody : latestBody);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function card(name: string) {
  return screen.findByRole("group", { name: `${name} 자원` });
}

describe("자원 모니터링 화면", () => {
  it("세 장비의 CPU·메모리·디스크·GPU·컨테이너와 마지막 수집 시각을 보인다", async () => {
    stubFetch();
    render(<ResourceMonitorPage />);
    expect(screen.getByRole("heading", { level: 1, name: /6\. 자원 모니터링/ })).toBeInTheDocument();

    const relayCard = await card("중계");
    expect(relayCard).toHaveAttribute("data-stale", "false");
    expect(within(relayCard).getByText("수집 중")).toBeInTheDocument();
    expect(within(relayCard).getByText(`마지막 수집 ${clock(NOW - 4)} (4초 전)`)).toBeInTheDocument();
    expect(within(relayCard).getByText("42.0 %")).toHaveClass("text-emerald-400");
    expect(within(relayCard).getByText("부하(1분) 1.25 / 12코어")).toBeInTheDocument();
    expect(within(relayCard).getByText("50.0 %")).toBeInTheDocument();
    expect(within(relayCard).getByText("7.8 / 15.6 GB · 가용 7.8 GB")).toBeInTheDocument();
    expect(within(relayCard).getByText("로컬")).toBeInTheDocument();
    expect(within(relayCard).queryByText("local")).not.toBeInTheDocument();
    expect(within(relayCard).getByText("27.1 %")).toBeInTheDocument();
    expect(within(relayCard).getByText("120.5 / 468.0 GB · 남음 323.6 GB")).toBeInTheDocument();
    expect(within(relayCard).getByText("NVIDIA GPU 없음")).toBeInTheDocument();
    const brokerRow = within(relayCard).getByText("mosquitto-broker").closest("tr")!;
    expect(within(brokerRow).getByText("eclipse-mosquitto:latest")).toBeInTheDocument();
    expect(within(brokerRow).getByText("Up 2 days")).toBeInTheDocument();
    expect(within(brokerRow).getByText("0.3 %")).toBeInTheDocument();
    expect(within(brokerRow).getByText("12 / 15700 MB")).toBeInTheDocument();

    const omenCard = await card("8-OMEN");
    expect(within(omenCard).getByText("95.0 %")).toHaveClass("text-red-400");
    expect(within(omenCard).getByText("80.0 %")).toHaveClass("text-amber-400");
    expect(within(omenCard).getByText("NVIDIA GeForce RTX 4060")).toBeInTheDocument();
    expect(within(omenCard).getByText("61.0 %")).toBeInTheDocument();
    expect(within(omenCard).getByText("(4096 / 8192 MB)")).toBeInTheDocument();
    expect(within(omenCard).getByText("66.0 °C")).toBeInTheDocument();
    expect(within(omenCard).getByText(`마지막 수집 ${clock(NOW - 6)} (6초 전)`)).toBeInTheDocument();

    const teamCard = await card("team11");
    expect(within(teamCard).getByText("NVIDIA GeForce RTX 5080 Laptop GPU")).toBeInTheDocument();
    expect(within(teamCard).getByText(`마지막 수집 ${clock(NOW - 8)} (8초 전)`)).toBeInTheDocument();
    expect(screen.queryByText("수집 끊김")).not.toBeInTheDocument();
    expect(screen.queryByText("수집기 응답 없음")).not.toBeInTheDocument();
  });

  it("team11 은 빈 표 대신 docker 조회 권한 없음 안내를 보인다", async () => {
    stubFetch();
    render(<ResourceMonitorPage />);
    const teamCard = await card("team11");
    expect(within(teamCard).getByText("docker 조회 권한 없음")).toBeInTheDocument();
    expect(within(teamCard).queryByRole("table")).not.toBeInTheDocument();
    expect(within(await card("중계")).getByRole("table")).toBeInTheDocument();
  });

  it("null 값은 0 이나 NaN 이 아니라 - 로 보인다", async () => {
    stubFetch(latest([
      relay({ cpu: { cores: 12, used_pct: null, load1: 0.4 }, memory: null, disk: [] }),
      omen8({ gpus: [{ name: "GPU-X", util_pct: null, mem_used_mb: null, mem_total_mb: null, temp_c: null }] }),
      team11({ cpu: null }),
    ]));
    render(<ResourceMonitorPage />);
    const relayCard = await card("중계");
    const cpuRow = within(relayCard).getByText("CPU", { selector: "span" }).parentElement!;
    expect(within(cpuRow).getByText("-")).toBeInTheDocument();
    const memoryRow = within(relayCard).getByText("메모리", { selector: "span" }).parentElement!;
    expect(within(memoryRow).getByText("-")).toBeInTheDocument();
    expect(within(memoryRow).getByText("- / - · 가용 -")).toBeInTheDocument();
    const webRow = within(relayCard).getByText("fms-web-server").closest("tr")!;
    expect(within(webRow).getByText("- / -")).toBeInTheDocument();
    expect(within(webRow).getByText("(-)")).toBeInTheDocument();

    const gpuBox = within(await card("8-OMEN")).getByText("GPU-X").parentElement!;
    expect(within(gpuBox).getAllByText("-")).toHaveLength(3);
    expect(within(gpuBox).getByText("(- / -)")).toBeInTheDocument();
    expect(within(await card("team11")).getByText("부하(1분) - / -코어")).toBeInTheDocument();

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/NaN|undefined|null/);
    expect(text).not.toMatch(/(^|[^\d.])0\.0 %/);
  });

  it("stale_after_sec 를 넘긴 장비는 수집 끊김과 사유를 보이고 옛 값을 회색으로 낸다", async () => {
    stubFetch(latest([
      relay(),
      omen8({ collected_at: NOW - 95, last_attempt_at: NOW - 5, ok: false, error: "ssh 시간 초과" }),
      team11({ collected_at: null, last_attempt_at: NOW - 5, ok: false, error: "연결 거부", cpu: null, memory: null, disk: [], gpus: [] }),
    ]));
    render(<ResourceMonitorPage />);
    const omenCard = await card("8-OMEN");
    expect(omenCard).toHaveAttribute("data-stale", "true");
    expect(within(omenCard).getByText("수집 끊김")).toBeInTheDocument();
    expect(within(omenCard).getByText(/사유: ssh 시간 초과/)).toBeInTheDocument();
    expect(within(omenCard).getByText(/현재 값이 아닙니다/)).toBeInTheDocument();
    expect(within(omenCard).getByText(`마지막 수집 ${clock(NOW - 95)} (95초 전)`)).toBeInTheDocument();
    const oldCpu = within(omenCard).getByText("95.0 %");
    expect(oldCpu).toHaveClass("text-zinc-500");
    expect(oldCpu).not.toHaveClass("text-red-400");
    expect(within(omenCard).queryByText("높음")).not.toBeInTheDocument();
    expect(within(omenCard).queryByText("수집 중")).not.toBeInTheDocument();

    const teamCard = await card("team11");
    expect(teamCard).toHaveAttribute("data-stale", "true");
    expect(within(teamCard).getByText("수집 끊김")).toBeInTheDocument();
    expect(within(teamCard).getByText("마지막 수집 없음")).toBeInTheDocument();
    expect(within(teamCard).getByText(/사유: 연결 거부/)).toBeInTheDocument();

    const relayCard = await card("중계");
    expect(relayCard).toHaveAttribute("data-stale", "false");
    expect(within(relayCard).getByText("수집 중")).toBeInTheDocument();
  });

  it("응답에 빠진 장비도 수집 끊김 카드로 남긴다", async () => {
    stubFetch(latest([relay(), omen8()]));
    render(<ResourceMonitorPage />);
    const teamCard = await card("team11");
    expect(within(teamCard).getByText("수집 끊김")).toBeInTheDocument();
    expect(within(teamCard).getByText(/수집기 응답에 이 장비가 없습니다/)).toBeInTheDocument();
  });

  it("최근 수집이 실패했으면 기한 안이어도 옛 값을 회색으로 내고 사유와 마지막 시도 시각을 보인다", async () => {
    stubFetch(latest([
      relay(),
      omen8({ collected_at: NOW - 29, last_attempt_at: NOW - 3, ok: false, error: "ssh 시간 초과" }),
      team11(),
    ]));
    render(<ResourceMonitorPage />);
    const omenCard = await card("8-OMEN");
    expect(omenCard).toHaveAttribute("data-stale", "true");
    expect(within(omenCard).getByText("최근 수집 실패")).toBeInTheDocument();
    expect(within(omenCard).getByText(/사유: ssh 시간 초과/)).toBeInTheDocument();
    expect(within(omenCard).getByText(new RegExp(`마지막 시도 ${clock(NOW - 3)}`))).toBeInTheDocument();
    expect(within(omenCard).getByText(/현재 값이 아닙니다/)).toBeInTheDocument();
    expect(within(omenCard).queryByText("수집 끊김")).not.toBeInTheDocument();
    const oldCpu = within(omenCard).getByText("95.0 %");
    expect(oldCpu).toHaveClass("text-zinc-500");
    expect(oldCpu).not.toHaveClass("text-red-400");
    expect(within(omenCard).queryByText("높음")).not.toBeInTheDocument();
    expect(within(omenCard).queryByText("주의")).not.toBeInTheDocument();
    // 다른 장비는 그대로 살아 있는 값이다.
    expect(await card("중계")).toHaveAttribute("data-stale", "false");
  });

  it("기한 경계: 정확히 30초는 수집 중, 30초를 넘기면 수집 끊김이고 초 표시가 기준과 어긋나지 않는다", async () => {
    stubFetch(latest([relay({ collected_at: NOW - 30 }), omen8({ collected_at: NOW - 30.001 }), team11()]));
    render(<ResourceMonitorPage />);
    const relayCard = await card("중계");
    expect(within(relayCard).getByText("수집 중")).toBeInTheDocument();
    expect(within(relayCard).getByText(`마지막 수집 ${clock(NOW - 30)} (30초 전)`)).toBeInTheDocument();
    const omenCard = await card("8-OMEN");
    expect(within(omenCard).getByText("수집 끊김")).toBeInTheDocument();
    expect(within(omenCard).getByText(`마지막 수집 ${clock(NOW - 30.001)} (31초 전)`)).toBeInTheDocument();
  });

  it("collected_at 이 generated_at 보다 앞서면 시계 이상으로 보고 살아 있는 값으로 내지 않는다", async () => {
    stubFetch(latest([relay({ collected_at: NOW + 500 }), omen8(), team11()]));
    render(<ResourceMonitorPage />);
    const relayCard = await card("중계");
    expect(relayCard).toHaveAttribute("data-stale", "true");
    expect(within(relayCard).getByText("수집 끊김")).toBeInTheDocument();
    expect(within(relayCard).getByText(/수집 시각이 응답 시각보다 500초 앞섬 \(시계 이상\)/)).toBeInTheDocument();
    expect(within(relayCard).getByText(`마지막 수집 ${clock(NOW + 500)} (시각 이상)`)).toBeInTheDocument();
    expect(within(relayCard).getByText("42.0 %")).toHaveClass("text-zinc-500");
    expect(await card("8-OMEN")).toHaveAttribute("data-stale", "false");
  });

  it("hosts 가 비어 있으면 세 장비 모두 수집 끊김 카드로 남긴다", async () => {
    stubFetch(latest([]));
    render(<ResourceMonitorPage />);
    for (const name of ["중계", "8-OMEN", "team11"]) {
      const hostCard = await card(name);
      expect(within(hostCard).getByText("수집 끊김")).toBeInTheDocument();
      expect(within(hostCard).getByText(/수집기 응답에 이 장비가 없습니다/)).toBeInTheDocument();
    }
    expect(screen.queryByText("수집 중")).not.toBeInTheDocument();
  });

  it("모르는 id 의 장비는 세 장비 뒤에 카드로 덧붙인다", async () => {
    stubFetch(latest([relay(), omen8(), team11(), relay({ id: "extra1", name: "추가 장비", address: "192.168.0.9" })]));
    render(<ResourceMonitorPage />);
    const extra = await card("추가 장비");
    expect(within(extra).getByText("192.168.0.9")).toBeInTheDocument();
    expect(screen.getAllByRole("group")).toHaveLength(4);
  });

  it("잘못된 장비 항목과 겹친 id 는 버리고 알리며, 나머지는 그대로 보인다", async () => {
    stubFetch(latest([null, 7, { id: 5 }, "x", relay(), relay({ cpu: { cores: 1, used_pct: 1, load1: 1 } })]));
    render(<ResourceMonitorPage />);
    const relayCard = await card("중계");
    expect(within(relayCard).getByText("수집 중")).toBeInTheDocument();
    expect(within(relayCard).getByText("42.0 %")).toBeInTheDocument();
    expect(screen.getByText(/수집기 응답 형식 오류: 장비 항목 5개를 읽지 못했습니다/)).toBeInTheDocument();
    expect(within(await card("8-OMEN")).getByText("수집 끊김")).toBeInTheDocument();
    expect(screen.getAllByRole("group")).toHaveLength(3);
  });

  it("장비 항목 안의 값이 계약과 달라도 화면이 깨지지 않고 - 로 보인다", async () => {
    stubFetch(latest([
      relay({
        name: { a: 1 }, address: 12, duration_ms: "x", error: { code: 1 },
        cpu: "x", memory: [1], disk: [null, { mount: 3, used_pct: "9" }], gpus: "none",
        gpu_note: 3, containers: [null, { name: 5, image: null, status: {}, cpu_pct: "1" }], containers_note: 1,
      }),
      omen8({ disk: null, gpus: [null, 3], containers: {} }),
      team11(),
    ]));
    render(<ResourceMonitorPage />);
    const relayCard = await card("relay");
    expect(within(relayCard).getByText("부하(1분) - / -코어")).toBeInTheDocument();
    expect(within(relayCard).getByText("GPU 정보 없음")).toBeInTheDocument();
    expect(within(relayCard).getByText("컨테이너 (1)")).toBeInTheDocument();
    const omenCard = await card("8-OMEN");
    expect(within(omenCard).getByText("GPU 정보 없음")).toBeInTheDocument();
    expect(within(omenCard).getByText("실행 중인 컨테이너 없음")).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/NaN|undefined|null|\[object/);
  });

  it("schema 가 1 이 아니면 형식 버전이 다르다고 알린다", async () => {
    stubFetch(latest(undefined, { schema: 99 }));
    render(<ResourceMonitorPage />);
    await card("중계");
    expect(screen.getByText(/수집기 형식 버전 다름 \(schema 99, 화면은 1 기준\)/)).toBeInTheDocument();
  });

  it("정상 응답에는 형식 경고가 없다", async () => {
    stubFetch();
    render(<ResourceMonitorPage />);
    await card("중계");
    expect(screen.queryByText(/수집기 형식 버전 다름/)).not.toBeInTheDocument();
    expect(screen.queryByText(/수집기 응답 형식 오류/)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("수집기가 처음부터 응답하지 않으면 수집기 응답 없음과 마지막 정상 응답 없음을 보인다", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("bad gateway", { status: 502 })));
    render(<ResourceMonitorPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("수집기 응답 없음")).toBeInTheDocument();
    expect(within(alert).getByText("마지막 정상 응답: 없음")).toBeInTheDocument();
    expect(within(alert).getByText("(HTTP 502)")).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(screen.queryByText("수집 중")).not.toBeInTheDocument();
  });

  it("응답 형식이 계약과 다르면 수집기 응답 없음으로 처리한다", async () => {
    stubFetch({ schema: 1, hosts: "x" });
    render(<ResourceMonitorPage />);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("수집기 응답 없음")).toBeInTheDocument();
    expect(within(alert).getByText("(수집기 응답 형식 오류)")).toBeInTheDocument();
  });

  it("받던 응답이 끊기면 마지막 정상 응답 시각을 보이고 모든 값을 회색으로 낸다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW * 1000));
    let healthy = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).startsWith("/api/resources/history")) return Response.json(history());
      if (!healthy) throw new TypeError("fetch failed");
      return Response.json(latest());
    }));
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByRole("group", { name: "중계 자원" })).toHaveAttribute("data-stale", "false");
    const goodAt = clock(Date.now() / 1000);

    healthy = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("수집기 응답 없음")).toBeInTheDocument();
    expect(within(alert).getByText(`마지막 정상 응답: ${goodAt}`)).toBeInTheDocument();
    expect(within(alert).getByText("(연결 실패: fetch failed)")).toBeInTheDocument();
    const relayCard = screen.getByRole("group", { name: "중계 자원" });
    expect(relayCard).toHaveAttribute("data-stale", "true");
    expect(within(relayCard).getByText("갱신 중단")).toBeInTheDocument();
    expect(within(relayCard).getByText("42.0 %")).toHaveClass("text-zinc-500");
    expect(within(relayCard).getByText(`마지막 수집 ${clock(NOW - 4)} (9초 전)`)).toBeInTheDocument();
    expect(screen.queryByText("수집 중")).not.toBeInTheDocument();
    expect(screen.queryByText("수집기 응답 중")).not.toBeInTheDocument();

    // 끊긴 채 30초를 넘기면 장비 카드도 수집 끊김으로 바뀐다. 장비 탓이 아니므로 사유는 수집기 응답 없음이다.
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    const downCard = screen.getByRole("group", { name: "중계 자원" });
    expect(within(downCard).getByText("수집 끊김")).toBeInTheDocument();
    expect(within(downCard).getByText(/사유: 수집기 응답 없음/)).toBeInTheDocument();
    expect(within(downCard).queryByText(/보고된 사유 없음/)).not.toBeInTheDocument();
  });

  it("끊겼던 수집기가 다시 응답하면 경고를 지우고 살아 있는 값으로 되돌린다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW * 1000));
    let healthy = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).startsWith("/api/resources/history")) return Response.json(history());
      if (!healthy) return new Response("", { status: 500 });
      const at = Date.now() / 1000;
      return Response.json(latest([relay({ collected_at: at - 4 }), omen8({ collected_at: at - 6 }), team11({ collected_at: at - 8 })],
        { generated_at: at }));
    }));
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    healthy = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(40000); });
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "중계 자원" })).getByText("수집 끊김")).toBeInTheDocument();

    healthy = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const relayCard = screen.getByRole("group", { name: "중계 자원" });
    expect(relayCard).toHaveAttribute("data-stale", "false");
    expect(within(relayCard).getByText("수집 중")).toBeInTheDocument();
    expect(within(relayCard).getByText("42.0 %")).toHaveClass("text-emerald-400");
    expect(within(relayCard).getByText(/\(4초 전\)/)).toBeInTheDocument();
    expect(screen.getByText("수집기 응답 중")).toBeInTheDocument();
  });

  it("같은 응답 시각이 반복되면 브라우저 경과 시간으로 끊김을 판정한다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW * 1000));
    stubFetch();   // generated_at 이 NOW 로 고정된 같은 본문만 돌려준다
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(within(screen.getByRole("group", { name: "중계 자원" })).getByText(/\(4초 전\)/)).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    const aging = screen.getByRole("group", { name: "중계 자원" });
    expect(within(aging).getByText(/\(14초 전\)/)).toBeInTheDocument();
    expect(within(aging).getByText("수집 중")).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(25000); });
    expect(within(screen.getByRole("alert")).getByText("수집기 응답이 갱신되지 않음")).toBeInTheDocument();
    expect(screen.queryByText("수집기 응답 중")).not.toBeInTheDocument();
    expect(screen.queryByText("수집 중")).not.toBeInTheDocument();
    for (const name of ["중계", "8-OMEN", "team11"]) {
      const hostCard = screen.getByRole("group", { name: `${name} 자원` });
      expect(hostCard).toHaveAttribute("data-stale", "true");
      expect(within(hostCard).getByText("수집 끊김")).toBeInTheDocument();
      expect(within(hostCard).getByText(/사유: 수집기 응답이 갱신되지 않음/)).toBeInTheDocument();
    }
    expect(within(screen.getByRole("group", { name: "8-OMEN 자원" })).getByText("95.0 %")).toHaveClass("text-zinc-500");
  });
});

describe("자원 모니터링 조회 방식", () => {
  it("버튼이 없고 두 조회 경로에 GET 만 보낸다", async () => {
    const mock = stubFetch();
    render(<ResourceMonitorPage />);
    await card("team11");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(document.querySelectorAll("form, input, select, textarea, a[href]")).toHaveLength(0);
    expect(mock.mock.calls.length).toBeGreaterThanOrEqual(2);
    for (const [url, init] of mock.mock.calls) {
      expect([LATEST_URL, HISTORY_URL]).toContain(url);
      expect(init?.method ?? "GET").toBe("GET");
      expect(init?.body).toBeUndefined();
    }
    expect(LATEST_URL).toBe("/api/resources/latest");
    expect(HISTORY_URL).toBe("/api/resources/history?minutes=30");
  });

  it("현재 값은 5초, 추이는 30초마다 다시 읽는다", async () => {
    vi.useFakeTimers();
    const mock = stubFetch();
    const count = (url: string) => mock.mock.calls.filter(([called]) => called === url).length;
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(count(LATEST_URL)).toBe(1);
    expect(count(HISTORY_URL)).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(count(LATEST_URL)).toBe(2);
    expect(count(HISTORY_URL)).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(25000); });
    expect(count(LATEST_URL)).toBe(7);
    expect(count(HISTORY_URL)).toBe(2);
  });

  it("응답이 늦어도 요청을 겹쳐 보내지 않고, 화면을 떠나면 취소하고 더 보내지 않는다", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const mock = vi.fn((url: string, init?: RequestInit) => {
      void url;
      if (init?.signal) signals.push(init.signal);
      return new Promise<Response>(() => {});
    });
    vi.stubGlobal("fetch", mock);
    const view = render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(mock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("수집기 첫 응답 대기")).toBeInTheDocument();
    expect(signals).toHaveLength(2);
    expect(signals.every((signal) => !signal.aborted)).toBe(true);

    view.unmount();
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("탭이 숨겨지면 조회를 멈추고 값을 회색으로 내며, 다시 보이면 바로 한 번 읽는다", async () => {
    vi.useFakeTimers();
    const mock = stubFetch();
    const count = () => mock.mock.calls.filter(([called]) => called === LATEST_URL).length;
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(count()).toBe(1);

    setHidden(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(mock.mock.calls.length).toBe(2);   // latest 1 + history 1, 숨겨진 동안 추가 요청 없음
    const pausedCard = screen.getByRole("group", { name: "중계 자원" });
    expect(pausedCard).toHaveAttribute("data-stale", "true");
    expect(within(pausedCard).getByText("조회 일시 중지")).toBeInTheDocument();
    expect(within(pausedCard).getByText("42.0 %")).toHaveClass("text-zinc-500");
    expect(screen.queryByText("수집기 응답 중")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    setHidden(false);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(count()).toBe(2);
    expect(mock.mock.calls.length).toBe(4);
    expect(within(screen.getByRole("group", { name: "중계 자원" })).queryByText("조회 일시 중지")).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(count()).toBe(3);
  });

  it("연속 3회 실패하면 조회 간격을 15초로 늘리고, 다시 성공하면 5초로 돌아온다", async () => {
    vi.useFakeTimers();
    let healthy = false;
    let generatedAt = NOW;
    const mock = vi.fn(async (url: string) => {
      if (String(url).startsWith("/api/resources/history")) return Response.json(history());
      if (!healthy) return new Response("", { status: 500 });
      generatedAt += 5;
      return Response.json(latest(undefined, { generated_at: generatedAt }));
    });
    vi.stubGlobal("fetch", mock);
    const count = () => mock.mock.calls.filter(([called]) => called === LATEST_URL).length;
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(count()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(count()).toBe(3);                    // 0초, 5초, 10초
    await act(async () => { await vi.advanceTimersByTimeAsync(14000); });
    expect(count()).toBe(3);                    // 24초까지 추가 요청 없음
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(count()).toBe(4);                    // 25초
    healthy = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(count()).toBe(5);                    // 40초, 성공
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(count()).toBe(6);                    // 45초, 다시 5초 간격
  });

  it("응답을 받은 뒤 화면을 떠나면 예약된 다음 조회를 지운다", async () => {
    vi.useFakeTimers();
    const mock = stubFetch();
    const view = render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const before = mock.mock.calls.length;
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
    expect(mock.mock.calls.length).toBe(before);
  });
});

describe("추이 선", () => {
  it("장비별 CPU·메모리 추이와 GPU 가 있는 장비의 GPU 추이를 그린다", async () => {
    stubFetch();
    render(<ResourceMonitorPage />);
    expect(await screen.findByRole("img", { name: "중계 CPU 사용률 추이 (최근 30분)" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "중계 메모리 사용률 추이 (최근 30분)" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "중계 GPU 사용률 추이 (최근 30분)" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "8-OMEN GPU 사용률 추이 (최근 30분)" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "team11 GPU 사용률 추이 (최근 30분)" })).toBeInTheDocument();
  });

  it("null 값과 수집 공백에서 선을 끊고, 값이 없으면 추이 없음을 보인다", async () => {
    const point = (t: number, cpu: number | null) => ({ t, cpu, mem: null, gpu: null, gpu_mem: null, gpu_temp: null });
    stubFetch(latest(), {
      schema: 1, generated_at: NOW,
      hosts: {
        relay: [point(NOW - 600, 10), point(NOW - 590, 20), point(NOW - 580, null), point(NOW - 570, 30), point(NOW - 560, 40),
          point(NOW - 200, 50), point(NOW - 190, 60)],
        omen8: [],
      },
    });
    render(<ResourceMonitorPage />);
    const svg = await screen.findByRole("img", { name: "중계 CPU 사용률 추이 (최근 30분)" });
    expect(svg.querySelectorAll("polyline")).toHaveLength(3);
    expect(svg.innerHTML).not.toMatch(/NaN/);
    expect(within(await card("중계")).getAllByText("추이 없음")).toHaveLength(1);
    expect(within(await card("8-OMEN")).getAllByText("추이 없음")).toHaveLength(3);
    expect(within(await card("team11")).getAllByText("추이 없음")).toHaveLength(3);
  });

  it("추이 조회만 실패해도 현재 값은 그대로 보이고 실패를 알린다", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      String(url).startsWith("/api/resources/history") ? new Response("", { status: 500 }) : Response.json(latest())));
    render(<ResourceMonitorPage />);
    expect(within(await card("중계")).getByText("수집 중")).toBeInTheDocument();
    expect(await screen.findByText(/추이 조회 실패 \(HTTP 500\)/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("추이 응답 이상", () => {
  it("장비별 추이가 배열이 아니어도 현재 값은 그대로 보이고 추이만 비운다", async () => {
    stubFetch(latest(), { schema: 1, generated_at: NOW, hosts: { relay: {}, omen8: "x", team11: [null, { t: "a" }, 3] } });
    render(<ResourceMonitorPage />);
    const relayCard = await card("중계");
    expect(within(relayCard).getByText("수집 중")).toBeInTheDocument();
    expect(within(relayCard).getByText("42.0 %")).toHaveClass("text-emerald-400");
    expect(within(relayCard).getAllByText("추이 없음")).toHaveLength(2);
    expect(within(await card("team11")).getAllByText("추이 없음")).toHaveLength(3);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("받던 추이 조회가 실패하면 추이 선만 회색으로 내고 현재 값은 살아 있는 색을 유지한다", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW * 1000));
    let historyOk = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).startsWith("/api/resources/history")) {
        return historyOk ? Response.json(history()) : new Response("", { status: 500 });
      }
      const at = Date.now() / 1000;
      return Response.json(latest([relay({ collected_at: at - 4 }), omen8({ collected_at: at - 6 }), team11({ collected_at: at - 8 })],
        { generated_at: at }));
    }));
    render(<ResourceMonitorPage />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const name = "중계 CPU 사용률 추이 (최근 30분)";
    expect(screen.getByRole("img", { name })).toHaveClass("text-cyan-400");

    historyOk = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(screen.getByRole("img", { name })).toHaveClass("text-zinc-600");
    expect(screen.getByText(/추이 조회 실패 \(HTTP 500\)/)).toBeInTheDocument();
    const relayCard = screen.getByRole("group", { name: "중계 자원" });
    expect(relayCard).toHaveAttribute("data-stale", "false");
    expect(within(relayCard).getByText("42.0 %")).toHaveClass("text-emerald-400");
  });
});

describe("표시 함수", () => {
  it("describeError 는 시간 초과와 연결 실패를 한글 문구로 바꾼다", () => {
    expect(describeError(new DOMException("The operation timed out.", "TimeoutError"))).toBe("응답 시간 초과(4초)");
    expect(describeError(new TypeError("Failed to fetch"))).toBe("연결 실패: Failed to fetch");
    expect(describeError(new Error("HTTP 500"))).toBe("HTTP 500");
    expect(describeError("x")).toBe("x");
  });

  it("fmt 는 null·NaN·무한대를 - 로 낸다", () => {
    expect(fmt(null)).toBe("-");
    expect(fmt(undefined, 1, " %")).toBe("-");
    expect(fmt(Number.NaN, 1, " %")).toBe("-");
    expect(fmt(Number.POSITIVE_INFINITY)).toBe("-");
    expect(fmt(0, 1, " %")).toBe("0.0 %");
    expect(fmt(12.345, 2)).toBe("12.35");
  });

  it("clock 은 hh:mm:ss 를 낸다", () => {
    expect(clock(NOW)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    expect(clock(null)).toBe("-");
  });
});

describe("자원 모니터링 경로", () => {
  function renderAt(path: string) {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).startsWith("/api/resources/history")) return Response.json(history());
      if (String(url).startsWith("/api/resources/")) return Response.json(latest());
      return new Response("", { status: 503 });
    }));
    render(<MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter>);
  }

  it("/debug/resources 접속 시 6. 자원 모니터링이 열린다", async () => {
    renderAt("/debug/resources");
    expect(await screen.findByRole("heading", { level: 1, name: /6\. 자원 모니터링/ })).toBeInTheDocument();
    expect(within(await card("team11")).getByText("docker 조회 권한 없음")).toBeInTheDocument();
  });

  it("메뉴 6.5 화면 안에는 자원 모니터링이 없다", async () => {
    renderAt("/menus/6.5");
    await screen.findByRole("heading", { level: 1, name: /6\.5/ });
    const main = screen.getByRole("main");
    expect(within(main).queryByText(/자원 모니터링/)).not.toBeInTheDocument();
    expect(within(main).queryByRole("group", { name: /자원$/ })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).startsWith("/api/resources"))).toBe(false);
  });
});
