import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { formatPrice } from "./format";
import { ApiError, createMockApi, isMockMode, viewOf, type OrderState } from "./api";

let clock = 0;

beforeEach(() => {
  clock = 0;
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  clock += ms;
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
  });
  await flush();
}

function renderApp(search = "?loc=P22") {
  const api = createMockApi(1000, () => clock);
  render(<App api={api} search={search} />);
  return api;
}

describe("고객 주문 화면", () => {
  it("자리 QR 없이 들어오면 QR 을 찍으라고 한다", async () => {
    renderApp("");
    await flush();
    expect(screen.getByText("자리의 QR 코드를 찍어 주세요")).toBeInTheDocument();
  });

  it("관제와 연결되기 전이면 기다렸다가 다시 물어 신발 목록을 연다", async () => {
    const api = createMockApi(1000, () => clock);
    const real = api.catalog;
    let calls = 0;
    api.catalog = (loc) => {
      calls += 1;
      return calls === 1 ? Promise.reject(new ApiError(503, "CONTROL_CENTER_UNAVAILABLE")) : real(loc);
    };
    render(<App api={api} search="?loc=P22" />);
    await flush();
    expect(screen.getByText("매장 시스템에 연결하는 중이에요")).toBeInTheDocument();
    expect(screen.queryByText("자리의 QR 코드를 찍어 주세요")).not.toBeInTheDocument();
    await advance(3000);
    expect(calls).toBe(2);
    expect(screen.getByLabelText("주문 자리")).toHaveTextContent("P22 자리");
  });

  it("신발 목록과 자리, 품절을 보인다", async () => {
    renderApp();
    await flush();
    expect(screen.getByLabelText("주문 자리")).toHaveTextContent("P22 자리");
    expect(screen.getByRole("button", { name: "에어 러너 260" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "컴포트 샌들 240" })).toBeDisabled();
    expect(screen.getByText("품절")).toBeInTheDocument();
  });

  it("주문 → 준비 중 → 도착 → 결제 QR → 구매 완료", async () => {
    renderApp();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "에어 러너 260" }));
    fireEvent.click(screen.getByRole("button", { name: /Cobot에게 가져다/ }));
    await flush();
    expect(screen.getByText("Cobot이 물건을 준비 중이에요")).toBeInTheDocument();
    await advance(5000);
    expect(screen.getByText("신발이 도착했어요!")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /구매하기/ }));
    expect(screen.getByAltText("결제 QR 코드 (예시)")).toBeInTheDocument();
    expect(screen.getByText("89,000원")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /QR 결제를 완료했어요/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "결제하기" }));
    await flush();
    expect(screen.getByText("구매가 완료됐어요")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /다른 신발 보기/ }));
    expect(screen.getByText("어떤 신발을 신어 볼까요?")).toBeInTheDocument();
  });

  it("도착 뒤 구매하지 않으면 정리 안내를 보인다", async () => {
    renderApp();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "클래식 스니커즈 270" }));
    fireEvent.click(screen.getByRole("button", { name: /Cobot에게 가져다/ }));
    await flush();
    await advance(5000);
    fireEvent.click(screen.getByRole("button", { name: /구매하지 않을게요/ }));
    await flush();
    expect(screen.getByText("구매를 취소했어요")).toBeInTheDocument();
    expect(screen.getByText(/Cobot이 신발을 정리해서 창고로 돌아가요/)).toBeInTheDocument();
  });

  async function orderWith(state: Partial<OrderState>) {
    const api = createMockApi(1000, () => clock);
    let current: Partial<OrderState> = state;
    const real = api.status;
    api.status = async (id, session) => ({ ...(await real(id, session)), ...current });
    render(<App api={api} search="?loc=P22" />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "에어 러너 260" }));
    fireEvent.click(screen.getByRole("button", { name: /Cobot에게 가져다/ }));
    await flush();
    await advance(1000);
    return (next: Partial<OrderState>) => {
      current = next;
    };
  }

  it("멈추면 안내하고, 재개되면 원래 화면으로 돌아온다", async () => {
    const set = await orderWith({ view: "preparing", stage: "UNLOADING", paused: true });
    expect(screen.getByText("잠시 멈췄어요")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /구매하기/ })).not.toBeInTheDocument();
    set({ view: "arrived", stage: "UNLOADING", paused: false });
    await advance(1000);
    expect(screen.getByRole("button", { name: /구매하기/ })).toBeInTheDocument();
  });

  it("주문 받기가 꺼져 있으면 접수 단계에서만 안내한다", async () => {
    const set = await orderWith({ view: "preparing", stage: "RECEIVED", accepting: false });
    expect(screen.getByText(/지금은 로봇이 쉬고 있어요/)).toBeInTheDocument();
    set({ view: "preparing", stage: "LOADING", accepting: false });
    await advance(1000);
    expect(screen.queryByText(/지금은 로봇이 쉬고 있어요/)).not.toBeInTheDocument();
  });

  it.each([
    ["store_cancelled", "매장에서 주문을 취소했어요"],
    ["timed_out", "시간이 지나 Cobot이 돌아갔어요"],
  ] as const)("끝난 이유를 구분한다: %s", async (view, title) => {
    await orderWith({ view, stage: "CANCELLED" });
    expect(screen.getByText(title)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /다른 신발 보기/ }));
    expect(screen.getByText("어떤 신발을 신어 볼까요?")).toBeInTheDocument();
  });

  it("새로고침해도 진행 중인 주문을 이어 본다", async () => {
    renderApp();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "에어 러너 260" }));
    fireEvent.click(screen.getByRole("button", { name: /Cobot에게 가져다/ }));
    await flush();
    expect(JSON.parse(localStorage.getItem("cobot-customer-order")!).orderId).toBe("ORD-00001");
  });
});

describe("도우미", () => {
  it("가격을 원 단위로 쓴다", () => {
    expect(formatPrice(129000)).toBe("129,000원");
  });

  it("단계를 화면 상태로 바꾼다", () => {
    expect(viewOf("IN_TRANSIT")).toBe("preparing");
    expect(viewOf("UNLOADING")).toBe("arrived");
    expect(viewOf("CANCELLED")).toBe("cancelled");
  });

  it("주소에 mock=1 이 있으면 모의 모드다", () => {
    expect(isMockMode("?loc=P22&mock=1")).toBe(true);
  });
});
