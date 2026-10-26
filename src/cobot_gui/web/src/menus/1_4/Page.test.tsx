import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

function bodyRows() {
  return within(screen.getAllByRole("rowgroup")[1]).getAllByRole("row");
}

describe("1.4 알림·이벤트 센터", () => {
  it("처음에는 진행 중 알림만, 위험이 먼저 보인다", () => {
    render(<Page menu={findMenu("1.4")!} />);
    const rows = bodyRows();
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("RED")).toBeInTheDocument();
    expect(within(rows[1]).getByText("RED")).toBeInTheDocument();
    expect(within(rows[3]).getByText("INFO")).toBeInTheDocument();
    expect(screen.queryByText("CLOCK_OFFSET")).not.toBeInTheDocument();
  });

  it("거르기 버튼으로 해제된 알림과 전체를 본다", () => {
    render(<Page menu={findMenu("1.4")!} />);
    fireEvent.click(screen.getByRole("button", { name: "해제됨" }));
    expect(bodyRows()).toHaveLength(1);
    expect(screen.getByText("CLOCK_OFFSET")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "해제됨" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "전체" }));
    expect(bodyRows()).toHaveLength(5);
  });

  it("Reconcile 이 필요한 진행 중 알림에 표시가 있다", () => {
    render(<Page menu={findMenu("1.4")!} />);
    expect(screen.getAllByText("Reconcile 필요")).toHaveLength(2);
  });

  it("알림을 바꾸는 버튼이 없고 명령 비활성 안내가 있다", () => {
    render(<Page menu={findMenu("1.4")!} />);
    const names = screen.getAllByRole("button").map((button) => button.textContent);
    expect(names).toEqual(["진행 중", "해제됨", "전체"]);
    expect(screen.getByText("명령 메뉴: 게이트웨이 연결 전에는 비활성")).toBeInTheDocument();
  });
});
