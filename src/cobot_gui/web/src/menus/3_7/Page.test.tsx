import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { findMenu } from "@/lib/registry";
import Page from "./Page";

afterEach(cleanup);

describe("3.7 로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오", () => {
  it("팀원 녹화 앱(omx_recoder) 대시보드의 주요 구성 요소를 렌더링한다", () => {
    render(<Page menu={findMenu("3.7")!} />);
    // 세션 및 상태 배너
    expect(screen.getByText("세션")).toBeInTheDocument();
    expect(screen.getByText(/원격조종 대기 중/)).toBeInTheDocument();
    // 듀얼 카메라 뷰
    expect(screen.getByText(/Top Camera/)).toBeInTheDocument();
    expect(screen.getByText(/Wrist Camera/)).toBeInTheDocument();
    // 6축 관절 모터 테이블
    expect(screen.getByText("Shoulder Pan")).toBeInTheDocument();
    expect(screen.getByText("Gripper")).toBeInTheDocument();
    // 조작 컨트롤 및 터미널 로그
    expect(screen.getByText("BringUp (토크 ON)")).toBeInTheDocument();
    expect(screen.getByText("녹화 시작 [Space]")).toBeInTheDocument();
    expect(screen.getByText(/Terminal Log/)).toBeInTheDocument();
  });

  it("팔 제어 모드 탭 선택 시 ArmMode 및 주의사항이 표시된다", () => {
    render(<Page menu={findMenu("3.7")!} />);
    fireEvent.click(screen.getByRole("tab", { name: /팔 제어 모드/ }));
    expect(screen.getByText("팔 제어 모드")).toBeInTheDocument();
    expect(screen.getByText("녹화 앱 개발 정보 (Station PC 데스크톱)")).toBeInTheDocument();
    expect(screen.getByText("FMS 에 붙이기 전에 풀어야 할 것")).toBeInTheDocument();
  });
});
