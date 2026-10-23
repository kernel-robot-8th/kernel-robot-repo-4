import { Menu as MenuIcon } from "lucide-react";
import { NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { menuGroups } from "@/lib/registry";
import { cn } from "@/lib/utils";
import { hasMenuPage } from "@/shell/pages";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center justify-between gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
    isActive
      ? "bg-accent font-medium text-accent-foreground"
      : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
  );

function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="메뉴 트리" className="space-y-5 p-3">
      <div>
        <p className="px-3 pb-1 text-xs font-semibold text-muted-foreground">FMS 관제 대시보드</p>
        <NavLink to="/" end className={linkClass} onClick={onNavigate}>
          개요 (구현도)
        </NavLink>
      </div>
      {menuGroups().map((group) => (
        <div key={group.title}>
          <h2 className="px-3 pb-1 text-xs font-semibold text-muted-foreground">{group.title}</h2>
          <ul className="space-y-0.5">
            {group.menus.map((menu) => (
              <li key={menu.id}>
                <NavLink to={`/menus/${menu.id}`} className={linkClass} onClick={onNavigate}>
                  <span className="truncate">
                    <span className="font-mono text-xs">{menu.id}</span> {menu.name}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 text-[10px]",
                      hasMenuPage(menu.id) || menu.impl !== "none" ? "text-primary" : "text-muted-foreground",
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
