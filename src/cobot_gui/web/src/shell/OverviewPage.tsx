import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { DECISIONS } from "@/generated/menus";
import { CONTRACT_LABELS, contractOf } from "@/lib/contracts";
import { ACTIVE_MENUS, CONTROL_AREA_LABELS, IMPL_LABELS, STATUS_LABELS, controlOwnerText, menuGroups, screenText } from "@/lib/registry";
import { hasMenuPage } from "@/shell/pages";

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-none border border-border bg-card p-4 shadow-none">
      <p className="text-xs font-sans text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-2xl font-bold tabular-nums text-foreground">{value}</p>
    </div>
  );
}

/** 메뉴 트리 전체와 구현도를 한 장에 보인다. 구현도의 정본은 레지스트리의 impl 칸과 menus/ 폴더다. */
export default function OverviewPage() {
  const withPage = ACTIVE_MENUS.filter((menu) => hasMenuPage(menu.id)).length;
  const external = ACTIVE_MENUS.filter((menu) => menu.impl !== "none").length;
  const open = DECISIONS.filter((d) => d.status === "open").length;
  const proposed = DECISIONS.filter((d) => d.status === "proposed").length;
  const decided = DECISIONS.filter((d) => d.status === "decided").length;
  return (
    <div className="max-w-5xl space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">FMS 관제 대시보드 메뉴 트리</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          메뉴 목록은 레지스트리(menu_tree.yaml)에서 생성합니다. 화면이 없는 메뉴는 틀 페이지가 대신 열립니다.
          지금 이 앱은 읽기 전용이고 로봇에 아무것도 보내지 않습니다. 구현도는 서버 연결까지 포함한 실제 구현 기준이고,
          웹 화면은 모의 데이터로 만든 화면까지 셉니다.
        </p>
      </header>

      <section aria-label="요약" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="메뉴" value={ACTIVE_MENUS.length} />
        <Stat label="웹 화면이 있는 메뉴 (모의 데이터)" value={withPage} />
        <Stat label="레지스트리 구현도가 있는 메뉴" value={external} />
        <Stat label="결정 확정 / 전체" value={decided} />
      </section>
      <p className="-mt-4 text-xs text-muted-foreground">
        결정 {DECISIONS.length}건 중 확정 {decided}, 추천안 있음 {proposed}, 미결 {open}.
      </p>

      <section aria-label="관제 담당 분리안" className="grid gap-3 md:grid-cols-2">
        {(["operational", "anomaly"] as const).map((area) => (
          <div key={area} className="border border-border bg-card p-4">
            <h2 className="font-semibold">{CONTROL_AREA_LABELS[area]}</h2>
            <p className="text-sm text-muted-foreground">{ACTIVE_MENUS.filter((menu) => menu.controlArea === area).length}개 메뉴</p>
            <p className="text-xs text-muted-foreground">{controlOwnerText(area === "operational" ? "operation_control" : "anomaly_monitoring")}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              {area === "operational" ? "로봇 기능 수행의 요청·진행·결과를 관제합니다. 로봇 기능 개발 담당과는 별도입니다." : "항공뷰 문제 상황과 장치·통신·프로세스 이상을 관찰합니다. 판별 결과만으로 로봇을 자동 제어하지 않습니다."}
            </p>
          </div>
        ))}
      </section>
      {menuGroups().map((group) => (
        <section key={group.title} className="space-y-2">
          <h2 className="text-lg font-semibold">{group.title}</h2>
          <div className="overflow-x-auto rounded-none border">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="bg-muted text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">ID</th>
                  <th className="px-3 py-2 font-medium">이름</th>
                  <th className="px-3 py-2 font-medium">관제 영역</th>
                  <th className="px-3 py-2 font-medium">관제 구현 담당</th>
                  <th className="px-3 py-2 font-medium">화면</th>
                  <th className="px-3 py-2 font-medium">단계</th>
                  <th className="px-3 py-2 font-medium">상태</th>
                  <th className="px-3 py-2 font-medium">구현도</th>
                  <th className="px-3 py-2 font-medium">데이터 계약</th>
                  <th className="px-3 py-2 font-medium">웹 화면</th>
                </tr>
              </thead>
              <tbody>
                {group.menus.map((menu) => (
                  <tr key={menu.id} className="border-t">
                    <td className="px-3 py-2 font-mono text-xs">{menu.id}</td>
                    <td className="px-3 py-2">
                      <Link to={`/menus/${menu.id}`} className="text-primary underline-offset-2 hover:underline">
                        {menu.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2">{CONTROL_AREA_LABELS[menu.controlArea]}</td>
                    <td className="px-3 py-2 text-muted-foreground">{controlOwnerText(menu.controlOwner)}</td>
                    <td className="px-3 py-2 text-muted-foreground">{screenText(menu.screen)}</td>
                    <td className="px-3 py-2">{menu.phase}</td>
                    <td className="px-3 py-2">{STATUS_LABELS[menu.status]}</td>
                    <td className="px-3 py-2">
                      <Badge variant={menu.impl === "none" ? "outline" : "default"}>{IMPL_LABELS[menu.impl]}</Badge>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{CONTRACT_LABELS[contractOf(menu).level]}</td>
                    <td className="px-3 py-2">
                      <Badge variant={hasMenuPage(menu.id) ? "default" : "outline"}>
                        {hasMenuPage(menu.id) ? "화면 있음" : "틀만"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
