import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CONTRACT_LABELS, contractOf } from "@/lib/contracts";
import {
  DECISION_LABELS,
  decisionOf,
  folderOf,
  roleText,
  srName,
} from "@/lib/registry";
import MenuHeader from "@/shell/MenuHeader";
import type { Menu } from "@/shell/types";

function List({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/** 화면이 아직 없는 메뉴에 보이는 틀. 레지스트리에 적힌 사실만 보여 준다. */
export default function MenuPlaceholder({ menu }: { menu: Menu }) {
  const folder = `src/cobot_gui/web/src/menus/${folderOf(menu.id)}/Page.tsx`;
  return (
    <div className="max-w-4xl space-y-6">
      <MenuHeader menu={menu} kind="placeholder" />

      <Alert>
        <AlertTitle>이 메뉴의 화면은 아직 없습니다</AlertTitle>
        <AlertDescription>
          담당자가 <code className="font-mono text-xs">{folder}</code> 를 만들면 이 틀을 대신합니다.
          복사용 틀은 <code className="font-mono text-xs">menus/_template/Page.tsx</code> 입니다.
        </AlertDescription>
      </Alert>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">담당 (초안)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              <span className="text-muted-foreground">화면 </span>
              {roleText(menu.screenOwner)}
            </p>
            <p>
              <span className="text-muted-foreground">데이터 </span>
              {roleText(menu.dataOwner)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">SR (SR_v2 v13)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <List
              items={menu.sr.map((id) => `${id} ${srName(id)}`)}
              empty="이 메뉴를 요구하는 SR 이 없습니다."
            />
            {menu.srOriginal && (
              <p className="text-xs text-muted-foreground">
                ✱ 메뉴 트리 원문 매핑: {menu.srOriginal.length ? menu.srOriginal.join(", ") : "없음"}
              </p>
            )}
            {menu.srUnconfirmed.length > 0 && (
              <p className="text-xs text-destructive">확인 필요: {menu.srUnconfirmed.join(", ")}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">데이터 원천</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <List items={menu.dataSources} empty="정해지지 않았습니다." />
            <p className="text-xs text-muted-foreground">
              인터페이스 정의: {CONTRACT_LABELS[contractOf(menu).level]}
              {contractOf(menu).found.length > 0 && ` (있음: ${contractOf(menu).found.join(", ")})`}
              {contractOf(menu).missing.length > 0 && ` (없음: ${contractOf(menu).missing.join(", ")})`}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">명령</CardTitle>
          </CardHeader>
          <CardContent>
            <List items={menu.commands} empty="없음 (읽기 전용 메뉴)" />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">기다리는 결정</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {menu.decisions.length === 0 && (
            <p className="text-muted-foreground">이 메뉴만 기다리는 결정은 없습니다.</p>
          )}
          {menu.decisions.map((id) => {
            const decision = decisionOf(id);
            return (
              <div key={id} className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{id}</Badge>
                <Badge variant="secondary">{decision ? DECISION_LABELS[decision.status] : "?"}</Badge>
                <span>{decision?.title}</span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {menu.implRef && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">구현이 있는 곳</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">{menu.implRef}</CardContent>
        </Card>
      )}

      {menu.notes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">메모</CardTitle>
          </CardHeader>
          <CardContent>
            <List items={menu.notes} empty="" />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
