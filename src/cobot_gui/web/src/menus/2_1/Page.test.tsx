import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("2.1 통합 주행 지도", () => {
  it("지점 8개(작업점·정차점)와 로봇 3대를 그린다", () => {
    const { container } = render(<Page menu={findMenu("2.1")!} />);
    expect(screen.getByRole("img", { name: /map_shoe_store_1021_gate67/ })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-kind="work"]')).toHaveLength(8);
    expect(container.querySelectorAll('[data-kind="approach"]')).toHaveLength(8);
    expect(container.querySelectorAll("[data-robot]")).toHaveLength(3);
    // 작업점과 정차점이 다른 지점(게이트, 벤치)만 점선으로 이어진다.
    expect(container.querySelectorAll("line")).toHaveLength(2);
  });

  it("지점 표에 게이트 정차점 좌표가 있다", () => {
    render(<Page menu={findMenu("2.1")!} />);
    const row = screen.getByText("WP_GATE_TRANSIT", { selector: "td" }).closest("tr")!;
    expect(within(row).getByText("1.250, 0.335")).toBeInTheDocument();
    expect(within(row).getByText("1.250, 0.225")).toBeInTheDocument();
  });

  it("로봇 위치는 맵 좌표를 뒤집어 그린다 (위쪽이 +y)", () => {
    const { container } = render(<Page menu={findMenu("2.1")!} />);
    const transform = container.querySelector('[data-robot="pinky_1"]')!.getAttribute("transform")!;
    const [x, y] = transform.replace("translate(", "").replace(")", "").split(" ").map(Number);
    expect(x).toBeCloseTo(1.62 + 0.02, 2); // x - origin_x
    expect(y).toBeCloseTo(2.54 - (0.335 + 0.02), 2); // 높이 - (y - origin_y)
  });
});
