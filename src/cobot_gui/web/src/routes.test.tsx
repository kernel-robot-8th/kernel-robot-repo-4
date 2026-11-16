import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { MENUS } from "@/generated/menus";
import { ACTIVE_MENUS, folderOf, menuGroups } from "@/lib/registry";
import { AppRoutes } from "@/routes";
import { hasMenuPage } from "@/shell/pages";

afterEach(cleanup);

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe("레지스트리에서 생성된 메뉴 데이터", () => {
  it("활성 메뉴 34개가 고유하고 6개 그룹으로 묶인다", () => {
    expect(ACTIVE_MENUS).toHaveLength(34);
    expect(new Set(ACTIVE_MENUS.map((menu) => menu.id)).size).toBe(34);
    expect(new Set(MENUS.map((menu) => folderOf(menu.id))).size).toBe(MENUS.length);
    expect(menuGroups()).toHaveLength(6);
  });

  it("3.7 은 팀원 앱으로 등록돼 있고 구현도는 외부 구현이다", () => {
    const menu = ACTIVE_MENUS.find((item) => item.id === "3.7");
    expect(menu?.impl).toBe("external");
    expect(menu?.implRef).toContain("e78dd9a");
    expect(menu?.commands).toEqual([]);
  });
});

describe("5대 운영자 디버그 관측 경로", () => {
  it("루트(/) 및 /debug/overview 접속 시 1. 실시간 실행·배정 현황이 열린다", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: /1\. 실시간 실행·배정 현황/ })).toBeInTheDocument();
    cleanup();
    renderAt("/debug/overview");
    expect(await screen.findByRole("heading", { level: 1, name: /1\. 실시간 실행·배정 현황/ })).toBeInTheDocument();
  });

  it("/debug/trace 접속 시 2. 주문 19단계 실행 추적 및 생명주기 로깅이 열린다", async () => {
    renderAt("/debug/trace");
    expect(
      await screen.findByRole("heading", { level: 1, name: /2\. 주문 19단계 실행 추적 및 생명주기 로깅/ }),
    ).toBeInTheDocument();
  });

  it("/debug/comm 접속 시 3. 통신·DDS 브리지·노드 진단이 열린다", async () => {
    renderAt("/debug/comm");
    expect(
      await screen.findByRole("heading", { level: 1, name: /3\. 통신·DDS 브리지·노드 진단/ }),
    ).toBeInTheDocument();
  });

  it("/debug/vision 접속 시 4. 비전 적재 판정·이상 감지 로그가 열린다", async () => {
    renderAt("/debug/vision");
    expect(
      await screen.findByRole("heading", { level: 1, name: /4\. 비전 적재 판정·이상 감지 로그/ }),
    ).toBeInTheDocument();
  });

  it("/debug/sim-tools 접속 시 5. 시뮬레이션·수동 보조 도구가 열린다", async () => {
    renderAt("/debug/sim-tools");
    expect(await screen.findByText(/SR-22 3D 물리 시뮬레이션 온라인 실험장/)).toBeInTheDocument();
  });
});

describe("모든 메뉴 경로", () => {
  it.each(ACTIVE_MENUS.map((menu) => [menu.id, menu.name]))("메뉴 %s 가 열린다 (%s)", async (id, name) => {
    renderAt(`/menus/${id}`);
    expect(await screen.findByRole("heading", { level: 1, name: `${id} ${name}` })).toBeInTheDocument();
    if (!hasMenuPage(id)) {
      expect(screen.getByText("이 메뉴의 화면은 아직 없습니다")).toBeInTheDocument();
    }
  });

  it("레지스트리에 없는 메뉴 ID 는 열리지 않는다", () => {
    renderAt("/menus/9.9");
    expect(screen.getByRole("heading", { level: 1, name: "찾을 수 없는 메뉴입니다" })).toBeInTheDocument();
    cleanup();
    renderAt("/menus/아무거나");
    expect(screen.getByRole("heading", { level: 1, name: "찾을 수 없는 메뉴입니다" })).toBeInTheDocument();
  });

  it("명령이 있는 틀 페이지는 비활성 안내를 보인다", () => {
    const withCommands = ACTIVE_MENUS.filter((menu) => menu.commands.length > 0 && !hasMenuPage(menu.id));
    expect(withCommands.length).toBeGreaterThan(0);
    for (const menu of withCommands) {
      renderAt(`/menus/${menu.id}`);
      expect(screen.getByText("명령 메뉴: 게이트웨이 연결 전에는 비활성")).toBeInTheDocument();
      cleanup();
    }
  });

  it("명령이 없는 메뉴에는 비활성 안내가 없다", () => {
    renderAt("/menus/1.1");
    expect(screen.queryByText("명령 메뉴: 게이트웨이 연결 전에는 비활성")).not.toBeInTheDocument();
  });
});

describe("사이드바", () => {
  it("5대 디버그 메뉴 링크와 기획 카탈로그 34개 아카이브 링크가 모두 있다", () => {
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "메뉴 트리" });
    // 디버그 링크 7개(5대 + 자원 모니터링 + 맵 실시간 화면) + 기획 개요 링크 1개 + 34개 메뉴 링크 = 42개
    expect(within(nav).getAllByRole("link")).toHaveLength(ACTIVE_MENUS.length + 1 + 7);
    expect(within(nav).getByRole("link", { name: /1\.\s*실시간 실행·배정 현황/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /2\.\s*주문 19단계 실행 추적·로깅/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /3\.\s*통신·DDS 브리지·노드 진단/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /4\.\s*비전 적재 판정·이상 감지 로그/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /5\.\s*시뮬레이션·수동 보조 도구/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /6\.\s*자원 모니터링/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /7\.\s*맵 실시간 화면/ })).toBeInTheDocument();
    expect(within(nav).getAllByRole("heading", { level: 2 })).toHaveLength(6);
  });
});

describe("3.7 팀원 앱 화면", () => {
  it("메뉴 폴더의 화면이 틀 페이지를 대신한다", async () => {
    renderAt("/menus/3.7");
    expect(await screen.findByText("읽기 전용 안내 화면입니다")).toBeInTheDocument();
    expect(screen.queryByText("이 메뉴의 화면은 아직 없습니다")).not.toBeInTheDocument();
    expect(screen.getAllByText("모의 데이터")).toHaveLength(2);
  });

  it("팔을 움직이는 버튼이 없다", async () => {
    renderAt("/menus/3.7");
    await screen.findByText("읽기 전용 안내 화면입니다");
    expect(within(screen.getByRole("main")).queryAllByRole("button")).toHaveLength(0);
  });
});

describe("기획 카탈로그 개요 (/overview)", () => {
  it("관제 두 영역과 지정된 개인 담당을 표시한다", () => {
    renderAt("/overview");
    const split = screen.getByLabelText("관제 담당");
    expect(within(split).getByRole("heading", { name: "로봇 수행 관제" })).toBeInTheDocument();
    expect(within(split).getByRole("heading", { name: "이상 감지 관제" })).toBeInTheDocument();
    expect(within(split).getByText("19개 메뉴")).toBeInTheDocument();
    expect(within(split).getByText("15개 메뉴")).toBeInTheDocument();
    expect(within(split).getByText("로봇 수행 관제 (김지혜)")).toBeInTheDocument();
    expect(within(split).getByText("이상 감지 관제 (강건한)")).toBeInTheDocument();
  });

  it("운용 관제와 비전 기능 개발 담당을 같은 역할로 표시하지 않는다", async () => {
    renderAt("/menus/4.3");
    await screen.findByRole("heading", { level: 1, name: "4.3 비전 인식·이벤트 결과" });
    const main = screen.getByRole("main");
    expect(within(main).getByText(/관제 구현: 이상 감지 관제/)).toBeInTheDocument();
    expect(within(main).getByText(/기능·데이터 계약: 비전/)).toBeInTheDocument();
  });

  it("메뉴 34개 행과 구현도를 보인다", () => {
    renderAt("/overview");
    expect(screen.getByRole("heading", { level: 1, name: "FMS 관제 대시보드 메뉴 트리" })).toBeInTheDocument();
    const summary = screen.getByLabelText("요약");
    expect(within(summary).getByText("메뉴").nextElementSibling).toHaveTextContent("34");
    expect(screen.getAllByText("외부 구현 (통합 전)").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("정의 없음").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByRole("row")).toHaveLength(34 + 6);
  });
});
