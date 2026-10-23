import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("3.7 로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오", () => {
  it("3대 통합 탭(원격 앱, 검수 스튜디오, 팔 상태)을 모두 표시한다", () => {
    render(<Page menu={findMenu("3.7")!} />);
    expect(screen.getByRole("tab", { name: /팀원 녹화 앱/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /에피소드 검수 스튜디오/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /팔 상태/ })).toBeInTheDocument();
  });

  it("기본으로 noVNC 원격 뷰 iframe이 렌더링된다", () => {
    render(<Page menu={findMenu("3.7")!} />);
    const iframe = screen.getByTitle("Station PC noVNC Stream");
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute("src", expect.stringContaining(":6080/vnc.html"));
  });

  it("검수 스튜디오 탭 선택 시 8088 뷰어가 표시된다", () => {
    render(<Page menu={findMenu("3.7")!} />);
    fireEvent.click(screen.getByRole("tab", { name: /에피소드 검수 스튜디오/ }));
    const iframe = screen.getByTitle("LeRobot Inspector Studio");
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute("src", expect.stringContaining(":8088"));
  });

  it("팔 상태 탭 선택 시 ArmMode 및 주의사항이 표시된다", () => {
    render(<Page menu={findMenu("3.7")!} />);
    fireEvent.click(screen.getByRole("tab", { name: /팔 상태/ }));
    expect(screen.getByText("팔 제어 모드")).toBeInTheDocument();
    expect(screen.getByText("녹화 앱 개발 정보 (Station PC 데스크톱)")).toBeInTheDocument();
    expect(screen.getByText("FMS 에 붙이기 전에 풀어야 할 것")).toBeInTheDocument();
  });
});
