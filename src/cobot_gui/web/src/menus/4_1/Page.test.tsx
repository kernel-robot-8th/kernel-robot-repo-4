import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("4.1 실시간 카메라 모니터링", () => {
  it("멈춘 화면, 오래된 프레임, 시뮬레이션을 구분해 보인다", () => {
    render(<Page menu={findMenu("4.1")!} />);
    expect(within(screen.getByLabelText("cam_desk")).getByText("화면 정지 (같은 프레임 반복)")).toBeInTheDocument();
    expect(within(screen.getByLabelText("cam_gate")).getByText("3100 ms")).toBeInTheDocument();
    expect(within(screen.getByLabelText("cam_gate")).getByText("수신 시각 기준 (캡처 시각 검증 안 됨)")).toBeInTheDocument();
    expect(within(screen.getByLabelText("cam_overhead")).getByText("움직임 있음")).toBeInTheDocument();
    expect(within(screen.getByLabelText("cam_overhead")).queryByText(/수신 시각 기준/)).not.toBeInTheDocument();
  });

  it("프레임이 없으면 0 ms 가 아니라 프레임 없음이다", () => {
    render(<Page menu={findMenu("4.1")!} />);
    const card = screen.getByLabelText("cam_pinky_1_front");
    expect(within(card).getByText("프레임 없음")).toBeInTheDocument();
    expect(within(card).getByText("시뮬레이션 (제어에 쓰지 않음)")).toBeInTheDocument();
    expect(within(card).queryByText(/0 ms/)).not.toBeInTheDocument();
  });

  it("미디어 서버 경로 표에 송출자와 화면 상태가 있다", () => {
    render(<Page menu={findMenu("4.1")!} />);
    const gate = screen.getByText("cam_gate", { selector: "td" }).closest("tr")!;
    expect(within(gate).getByText("끊김")).toBeInTheDocument();
    expect(within(gate).getByText("UNKNOWN")).toBeInTheDocument();
    const desk = screen.getByText("cam_desk", { selector: "td" }).closest("tr")!;
    expect(within(desk).getByText("FROZEN")).toBeInTheDocument();
  });
});
