import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("6.2 ROS 2·FMS 통신 상태", () => {
  it("유일 기록자 위반을 요약과 토픽 줄에서 보인다", () => {
    render(<Page menu={findMenu("6.2")!} />);
    expect(screen.getByText("유일 기록자 위반 1건")).toBeInTheDocument();
    const row = screen.getByText("/control_center/pinky_3/command").closest("tr")!;
    expect(within(row).getByText("VIOLATION")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    const none = screen.getByText("/vision/cam_gate/health").closest("tr")!;
    expect(within(none).getByText("NO_PUBLISHER")).toBeInTheDocument();
  });

  it("보이지 않는 노드와 미측정 왕복 시간을 구분해 보인다", () => {
    render(<Page menu={findMenu("6.2")!} />);
    const row = screen.getByText("/vision/monitor").closest("tr")!;
    expect(within(row).getByText("안 보임")).toBeInTheDocument();
    expect(within(row).getByText("미측정")).toBeInTheDocument();
    const alive = screen.getByText("/control_center/fms_core").closest("tr")!;
    expect(within(alive).getByText("3.1 ms")).toBeInTheDocument();
  });

  it("진단 노드의 도메인과 chrony 오프셋을 보인다", () => {
    render(<Page menu={findMenu("6.2")!} />);
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("1.8 ms")).toBeInTheDocument();
  });
});
