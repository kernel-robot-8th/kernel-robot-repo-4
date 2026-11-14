import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { formatPrice } from "./format";
import { createMockApi, isMockMode, viewOf } from "./api";

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

function renderApp(search = "?loc=BENCH_1") {
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

  it("신발 목록과 자리, 품절을 보인다", async () => {
    renderApp();
    await flush();
    expect(screen.getByLabelText("주문 자리")).toHaveTextContent("고객 벤치 1");
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
    expect(isMockMode("?loc=BENCH_1&mock=1")).toBe(true);
  });
});
