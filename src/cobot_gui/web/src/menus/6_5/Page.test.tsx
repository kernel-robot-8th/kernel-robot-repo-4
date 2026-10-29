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

  it("실시간 텔레메트리 매트릭스와 로컬 3D 뷰어 제어 버튼을 제공한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/LIVE SIM 50Hz/)).toBeInTheDocument();
    expect(screen.getByText(/다중 장치 텔레메트리 & 통신 반응 매트릭스/)).toBeInTheDocument();
    expect(screen.getByText(/로컬 3D 뷰어 창 띄우기/)).toBeInTheDocument();
    expect(screen.getByText(/실시간 명령 반응 이력/)).toBeInTheDocument();
  });

  it("터미널 CLI 실행 명령어 카드와 3D 네이티브 안내를 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/터미널 CLI 실행 명령어/)).toBeInTheDocument();
    expect(screen.getAllByText(/bringup_sim.launch.py/).length).toBeGreaterThan(0);
  });
});
