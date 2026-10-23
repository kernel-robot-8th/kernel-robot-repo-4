import { Badge } from "@/components/ui/badge";
import { IMPL_LABELS, STATUS_LABELS, phaseTitle, screenText } from "@/lib/registry";
import type { Menu } from "@/shell/types";

/** 틀 페이지와 메뉴 화면이 같이 쓰는 머리글. 정보는 전부 레지스트리에서 온다. */
export default function MenuHeader({ menu, kind }: { menu: Menu; kind: "placeholder" | "page" }) {
  return (
    <header className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {menu.depth1} › {screenText(menu.screen)}
        {menu.alsoShownIn.length > 0 && (
          <span> (함께 보임: {menu.alsoShownIn.map(screenText).join(", ")})</span>
        )}
      </p>
      <h1 className="text-2xl font-bold leading-tight">{`${menu.id} ${menu.name}`}</h1>
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline">{phaseTitle(menu.phase)}</Badge>
        <Badge variant="secondary">{STATUS_LABELS[menu.status]}</Badge>
        <Badge variant={menu.impl === "none" ? "outline" : "default"}>
          구현도: {IMPL_LABELS[menu.impl]}
        </Badge>
        <Badge variant={kind === "page" ? "default" : "outline"}>
          {kind === "page" ? "화면 있음" : "틀 페이지"}
        </Badge>
      </div>
    </header>
  );
}
