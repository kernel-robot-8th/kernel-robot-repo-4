import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("6.5 시뮬레이션·기능 검증", () => {
  it("2D 아레나 탑뷰와 주요 치수 및 게이트 설정을 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/신발 매장 2D 아레나 탑뷰/)).toBeInTheDocument();
    expect(screen.getAllByText(/2.5m × 2.4m/).length).toBeGreaterThan(0);
    expect(screen.getByText(/67cm \(정본\)/)).toBeInTheDocument();
    expect(screen.getByText(/50cm \(v9\)/)).toBeInTheDocument();
  });

  it("핑키 3대의 텔레메트리와 수동 조종 패널을 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText("PINKY1")).toBeInTheDocument();
    expect(screen.getByText("PINKY2")).toBeInTheDocument();
    expect(screen.getByText("PINKY3")).toBeInTheDocument();
    expect(screen.getByText("정지")).toBeInTheDocument();
    expect(screen.getByText("▲ 전진")).toBeInTheDocument();
  });

  it("로봇팔(OMX) 3대 탭과 모션 제어 인터페이스를 지원한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText("🦾 OMX 로봇팔 제어")).toBeInTheDocument();
    expect(screen.getByText("🤖 핑키 이동 로봇 제어")).toBeInTheDocument();
  });

  it("50Hz 실시간 시뮬레이션 텔레메트리와 자동 순회 데모 모드를 제공한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/LIVE SIM 50Hz/)).toBeInTheDocument();
    expect(screen.getByText(/SIM TIME:/)).toBeInTheDocument();
    expect(screen.getByText(/360° ACTIVE/)).toBeInTheDocument();
    expect(screen.getByText(/자동 순회 데모/)).toBeInTheDocument();
    expect(screen.getByText(/Dual-View: 2D Web \+ 3D Native/)).toBeInTheDocument();
  });

  it("터미널 CLI 실행 명령어 카드와 3D 네이티브 안내를 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/터미널 CLI 실행 명령어/)).toBeInTheDocument();
    expect(screen.getAllByText(/bringup_sim.launch.py/).length).toBeGreaterThan(0);
  });
});
