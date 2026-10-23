// 메뉴 1.4 알림·이벤트 센터. AlarmEvent 를 심각도와 진행 여부로 걸러 보인다. 읽기 전용이다.
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useMessages } from "@/lib/dataSource";
import { timeText } from "@/lib/format";
import { severityTone } from "@/lib/tones";
import MenuHeader from "@/shell/MenuHeader";
import Pill from "@/shell/Pill";
import ResourceSection from "@/shell/ResourceSection";
import type { MenuPageProps } from "@/shell/types";

type Filter = "active" | "cleared" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "active", label: "진행 중" },
  { key: "cleared", label: "해제됨" },
  { key: "all", label: "전체" },
];

const SEVERITY_ORDER: Record<string, number> = { RED: 0, AMBER: 1, INFO: 2 };

export default function Page({ menu }: MenuPageProps) {
  const alarms = useMessages("AlarmEvent");
  const [filter, setFilter] = useState<Filter>("active");

  return (
    <div className="max-w-5xl space-y-6">
      <MenuHeader menu={menu} kind="page" />

      <ResourceSection title="알림" resource={alarms}>
        {(items) => {
          const shown = items
            .filter((item) => filter === "all" || (filter === "active") === item.active)
            .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9));
          const count = (severity: string) => items.filter((item) => item.active && item.severity === severity).length;
          return (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3 bg-muted/40 p-3 rounded-md border border-border/60">
                <p className="text-xs font-mono text-neutral-300">
                  진행 중 알림 상태: 위험 <b className="text-rose-400 font-bold">{count("RED")}</b>건 · 주의{" "}
                  <b className="text-amber-400 font-bold">{count("AMBER")}</b>건 · 정보 <b className="text-blue-400 font-bold">{count("INFO")}</b>건
                </p>
                <div className="flex gap-1.5" role="group" aria-label="알림 거르기">
                  {FILTERS.map((item) => (
                    <Button
                      key={item.key}
                      size="sm"
                      variant={filter === item.key ? "default" : "outline"}
                      className="text-xs h-7 px-2.5 font-medium"
                      aria-pressed={filter === item.key}
                      onClick={() => setFilter(item.key)}
                    >
                      {item.label}
                    </Button>
                  ))}
                </div>
              </div>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full min-w-[720px] text-sm">
                  <thead className="bg-muted text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">심각도</th>
                      <th className="px-3 py-2 font-medium">코드</th>
                      <th className="px-3 py-2 font-medium">대상</th>
                      <th className="px-3 py-2 font-medium">발생</th>
                      <th className="px-3 py-2 font-medium">상태</th>
                      <th className="px-3 py-2 font-medium">설명</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                          해당하는 알림이 없습니다.
                        </td>
                      </tr>
                    )}
                    {shown.map((item) => (
                      <tr key={item.alarm_id} className="border-t align-top">
                        <td className="px-3 py-2">
                          <Pill tone={severityTone(item.severity)}>{item.severity}</Pill>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{item.code}</td>
                        <td className="px-3 py-2 font-mono text-xs">{item.target_id}</td>
                        <td className="px-3 py-2 tabular-nums">{timeText(item.raised_at)}</td>
                        <td className="space-y-1 px-3 py-2">
                          <div>{item.active ? "진행 중" : `해제 ${timeText(item.cleared_at)}`}</div>
                          {item.requires_reconcile && item.active && <Pill tone="warn">Reconcile 필요</Pill>}
                        </td>
                        <td className="px-3 py-2">{item.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                알림 확인·Reconcile 같은 조작은 게이트웨이(S2)와 안전 검토 뒤에 붙입니다. 지금은 보기만 합니다.
              </p>
            </>
          );
        }}
      </ResourceSection>
    </div>
  );
}
