import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("6.5 시뮬레이션·기능 검증 (SR-22 통신 및 건전성 진단 센터)", () => {
  it("상단 헤더 및 50Hz 엔진 가동 배지를 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(
      screen.getByText(/SR-22 시뮬레이션 패키지 통신 및 기능 검증 센터/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Jazzy 50Hz 엔진 가동/)).toBeInTheDocument();
    expect(screen.getByText(/PyTorch 의존성 0%/)).toBeInTheDocument();
  });

  it("3개 핵심 엔진 상태 카드(50Hz 기구학, DDS 도메인, 안전 제약)를 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/50Hz 기구학 시뮬레이션 엔진/)).toBeInTheDocument();
    expect(screen.getByText(/DDS 도메인 및 브로커 상태/)).toBeInTheDocument();
    expect(screen.getByText(/안전 제약 및 단일 기록자/)).toBeInTheDocument();
    expect(screen.getByText(/1.2 rad\/s 클램프 PASS/)).toBeInTheDocument();
  });

  it("핑키 3대와 로봇팔 3대의 통신 건전성 매트릭스 표를 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(
      screen.getByText(/핑키 3대 \+ 로봇팔 3대 통신 건전성 매트릭스/),
    ).toBeInTheDocument();
    expect(screen.getByText("Pinky 1호기")).toBeInTheDocument();
    expect(screen.getByText("Pinky 2호기")).toBeInTheDocument();
    expect(screen.getByText("Pinky 3호기")).toBeInTheDocument();
    expect(screen.getByText("OMX 1호기 (상차 1)")).toBeInTheDocument();
    expect(screen.getByText("OMX 2호기 (상차 2)")).toBeInTheDocument();
    expect(screen.getByText("OMX 3호기 (하차 3)")).toBeInTheDocument();
    expect(screen.getByText("6 / 6 ONLINE")).toBeInTheDocument();
  });

  it("장치별 통신 핑 시험 및 RTT 로그 출력을 정상 지원한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/장치별 통신 핑\(Ping\) 반응 시험/)).toBeInTheDocument();
    expect(screen.getByText(/실시간 통신 핑 수신 로그/)).toBeInTheDocument();

    const pingBtn = screen.getByText(/⚡ 통신 생존 핑 \(Heartbeat\)/);
    expect(pingBtn).toBeInTheDocument();
    fireEvent.click(pingBtn);

    // 로그에 토픽 핑 응답 기록 추가 확인
    expect(screen.getAllByText(/\/pinky1\/ping/).length).toBeGreaterThan(0);
  });

  it("로컬 3D 물리 시뮬레이터 실행 안내 카드와 CLI 명령어를 제공한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/로컬 3D 물리 시뮬레이터 실행 안내/)).toBeInTheDocument();
    expect(screen.getAllByText(/bringup_sim.launch.py/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/ros2 run rviz2 rviz2/).length).toBeGreaterThan(0);
  });
});
