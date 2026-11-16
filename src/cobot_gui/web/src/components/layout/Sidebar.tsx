import { Menu as MenuIcon } from "lucide-react";
import { NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { menuGroups } from "@/lib/registry";
import { cn } from "@/lib/utils";
import { hasMenuPage } from "@/shell/pages";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs transition-colors rounded-none",
    isActive
      ? "bg-[#1565c0] font-bold text-white shadow-sm"
      : "text-[#888888] hover:bg-[#2a2a2a] hover:text-white",
  );

const DEBUG_MENUS = [
  {
    id: "1",
    path: "/debug/overview",
    name: "실시간 실행·배정 현황",
    desc: "시나리오 7단계 E2E · P7/P8 배정 · 구역 점유",
    isDefault: true,
  },
  {
    id: "2",
    path: "/debug/trace",
    name: "주문 19단계 실행 추적·로깅",
    desc: "19단계 동작 · 5대 체크포인트 · 도킹 보정",
  },
  {
    id: "3",
    path: "/debug/comm",
    name: "통신·DDS 브리지·노드 진단",
    desc: "P2 ready 그래프 · P5 브리지 · P10/P12",
  },
  {
    id: "4",
    path: "/debug/vision",
    name: "비전 적재 판정·이상 감지 로그",
    desc: "VERIFY_LOAD 결합 · 수동 상차 · CCTV 이상",
  },
  {
    id: "5",
    path: "/debug/sim-tools",
    name: "시뮬레이션·수동 보조 도구",
    desc: "SR-22 3D 모의 실험장 · 수동 개입 콘솔",
  },
  {
    id: "6",
    path: "/debug/resources",
    name: "자원 모니터링",
    desc: "중계 · 8-OMEN · team11 CPU · 메모리 · GPU · 컨테이너",
  },
  {
    id: "7",
    path: "/debug/camera",
    name: "맵 실시간 화면",
    desc: "마커 안쪽 영상 · 박스 인식 · 로봇 주행 상태",
  },
];

function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="메뉴 트리" className="space-y-4 p-3 font-sans">
      {/* 5대 운영자 디버깅·관측 주 메뉴 */}
      <div className="border-b border-border/80 pb-3">
        <p className="px-2.5 pb-2 text-[11px] font-bold tracking-wider text-[#cccccc] uppercase">
          FMS 관제 대시보드
        </p>
        <div className="space-y-1">
          {DEBUG_MENUS.map((menu) => (
            <NavLink
              key={menu.id}
              to={menu.path}
              end={menu.isDefault}
              className={({ isActive }) =>
                cn(
                  "flex flex-col gap-0.5 px-2.5 py-2 text-xs transition-colors rounded-none",
                  isActive
                    ? "bg-[#1565c0] font-bold text-white shadow-sm"
                    : "text-[#aaaaaa] hover:bg-[#252830] hover:text-white",
                )
              }
              onClick={onNavigate}
            >
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-cyan-400 font-bold">{menu.id}.</span>
                <span className="truncate">{menu.name}</span>
              </div>
              <span className="text-[10px] text-zinc-400 font-normal pl-4 truncate">{menu.desc}</span>
            </NavLink>
          ))}
        </div>
      </div>

      {/* 기획 카탈로그 아카이브 (기본 접힘) */}
      <details className="space-y-3 pt-1 group">
        <summary className="cursor-pointer px-2.5 py-1.5 text-[11px] font-bold text-zinc-400 hover:text-white uppercase tracking-wider flex items-center justify-between border border-border/60 bg-[#16171b]">
          <span>[기획 카탈로그 아카이브 (34)]</span>
          <span className="text-[10px] text-zinc-500 group-open:rotate-180 transition-transform font-mono">▼</span>
        </summary>

        <div className="space-y-3 pt-2">
          <NavLink to="/overview" className={linkClass} onClick={onNavigate}>
            <span>개요 (구현도 및 메뉴 매트릭스)</span>
          </NavLink>

          {menuGroups().map((group) => (
            <div key={group.title}>
              <h2 className="px-2.5 pb-1 text-[11px] font-bold tracking-wider text-[#888888] uppercase">
                {group.title}
              </h2>
              <ul className="space-y-0.5">
                {group.menus.map((menu) => (
                  <li key={menu.id}>
                    <NavLink to={`/menus/${menu.id}`} className={linkClass} onClick={onNavigate}>
                      <span className="truncate">
                        <span className="font-mono text-[11px] text-[#888888] mr-1">{menu.id}</span>
                        <span className="text-[#dddddd]">{menu.name}</span>
                      </span>
                      <span
                        className={cn(
                          "shrink-0 text-[10px]",
                          hasMenuPage(menu.id) || menu.impl !== "none" ? "text-[#2e7d32]" : "text-[#555555]",
                        )}
                        aria-label={hasMenuPage(menu.id) || menu.impl !== "none" ? "구현 있음" : "틀만 있음"}
                      >
                        {hasMenuPage(menu.id) || menu.impl !== "none" ? "●" : "○"}
                      </span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </details>
    </nav>
  );
}

export default function Sidebar() {
  return (
    <>
      <aside className="fixed inset-y-0 left-0 hidden w-72 overflow-y-auto border-r bg-card lg:block">
        <NavContent />
      </aside>
      <div className="fixed inset-x-0 top-0 z-40 flex items-center gap-2 border-b bg-card px-4 py-2 lg:hidden">
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="메뉴 열기">
              <MenuIcon className="h-5 w-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 overflow-y-auto p-0">
            <SheetHeader className="px-4 pt-4">
              <SheetTitle>메뉴 트리</SheetTitle>
              <SheetDescription>메뉴를 고르면 닫힙니다.</SheetDescription>
            </SheetHeader>
            <NavContent />
          </SheetContent>
        </Sheet>
        <span className="text-sm font-semibold">FMS 관제 대시보드</span>
      </div>
    </>
  );
}
