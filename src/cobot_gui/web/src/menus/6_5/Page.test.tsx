import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("6.5 시뮬레이션·기능 검증 (SR-22 3D 가상환경 온라인 실험장)", () => {
  it("엔진 생존 감지기 배너 및 도커 통신 상태를 표시한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(
      screen.getByText(/SR-22 3D 물리 시뮬레이션 온라인 실험장/),
    ).toBeInTheDocument();
    expect(screen.getByText(/50.0 Hz ACTIVE/)).toBeInTheDocument();
    expect(screen.getByText(/DOCKER: CONNECTED/)).toBeInTheDocument();
  });

  it("브라우저 내장 3D 뷰포트와 시점 조절 프리셋 버튼을 제공한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(
      screen.getByText(/브라우저 내장 3D 가상환경 뷰포트/),
    ).toBeInTheDocument();
    expect(screen.getByText(/📐 입체뷰/)).toBeInTheDocument();
    expect(screen.getByText(/🔝 탑뷰/)).toBeInTheDocument();
    expect(screen.getByText(/👀 정면뷰/)).toBeInTheDocument();
  });

  it("세분화된 포인트별 태스크 동작 신호 인젝션 버튼들을 모두 제공한다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    expect(screen.getByText(/① 상차대 1 도킹 이동/)).toBeInTheDocument();
    expect(screen.getByText(/② OMX 1 피킹 & 상차/)).toBeInTheDocument();
    expect(screen.getByText(/③ 67cm 협소 게이트 통과 주행 신호/)).toBeInTheDocument();
    expect(screen.getByText(/④ 하차대 도킹 이동/)).toBeInTheDocument();
    expect(screen.getByText(/⑤ OMX 3 하차 & 벤치 배치/)).toBeInTheDocument();
    expect(screen.getByText(/⑥ 충전소 1 복귀 주행/)).toBeInTheDocument();
    expect(screen.getByText(/⚡ 전체 시퀀스 연속 실행/)).toBeInTheDocument();
    expect(screen.getByText(/🚨 긴급 정지 \(E-STOP\)/)).toBeInTheDocument();
  });

  it("태스크 신호 클릭 시 도커 통신 콘솔에 디스패치 로그가 기록된다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    const dockBtn = screen.getByText(/① 상차대 1 도킹 이동/);
    fireEvent.click(dockBtn);

    expect(screen.getAllByText(/T1_상차대1_도킹/).length).toBeGreaterThan(0);
    expect(screen.getByText(/도커 백엔드 신호 송수신 콘솔/)).toBeInTheDocument();
  });

  it("긴급 정지(E-STOP) 토글 시 엔진 상태가 즉시 변경된다", () => {
    render(<Page menu={findMenu("6.5")!} />);
    const eStopBtn = screen.getByText(/🚨 긴급 정지 \(E-STOP\)/);
    fireEvent.click(eStopBtn);

    expect(screen.getByText(/E-STOPPED/)).toBeInTheDocument();
    expect(screen.getByText(/▶ E-STOP 해제/)).toBeInTheDocument();
  });
});
