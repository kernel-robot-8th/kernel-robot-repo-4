import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
      {menu.commands.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>명령 메뉴: 게이트웨이 연결 전에는 비활성</AlertTitle>
          <AlertDescription>
            이 메뉴는 아래 명령을 보내는 화면이 될 예정입니다. 지금 웹 앱은 읽기 전용이라 어떤 명령도 보내지 않습니다.
            <span className="mt-1 block text-xs">{menu.commands.join(" · ")}</span>
          </AlertDescription>
        </Alert>
      )}
    </header>
  );
}
