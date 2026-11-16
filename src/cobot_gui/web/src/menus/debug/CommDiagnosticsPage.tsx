import ZoneTable from "./ZoneTable";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useFmsLive, type Endpoints } from "@/lib/fmsLiveContext";

const TOPICS = ["patrol_status", "amcl_pose", "odom"];

export default function CommDiagnosticsPage() {
  const { live, offline } = useFmsLive();

  const ros = live?.ros ?? {};
  const ready = live?.ready_graph;
  const diag = live?.diagnostics;
  const links = live?.links ?? [];
  const routes = live?.routes ?? {};
  const log = live?.log ?? [];
  const tasks = live?.tasks ?? [];
  const isDiagStale = offline || !diag || !live || !Number.isFinite(diag.at) || !(live.time - diag.at >= 0 && live.time - diag.at <= 5);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            <span className="font-mono text-cyan-400">3.</span> 통신·DDS 브리지·노드 진단
          </h1>
          <p className="text-xs text-zinc-400">
            P2 ready() 엔드포인트 그래프, P5 브리지 양쪽 표본 비교, P10 순찰 경고, P12 위치 추정 진단
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="border-cyan-700 text-cyan-300 font-mono">
            도메인 {ros.domain_id ?? "?"} / {ros.rmw ?? "?"}
          </Badge>
          <span>모니터 좌표 파일 {ros.monitor_site ?? "미확인"}</span>
          {ros.site_sha256 && (
            <Badge variant="outline" className="border-zinc-700 text-zinc-400 font-mono text-[10px]">
              SHA {ros.site_sha256.slice(0, 8)}
            </Badge>
          )}
        </div>
      </div>

      {/* P2: 명령 토픽 연결 노드 (ready() 엔드포인트 수 검사) */}
      <Card className="rounded-none border-border bg-[#121316]">
        <CardHeader className="p-3 border-b border-border">
          <CardTitle className="text-xs font-bold text-white tracking-wide flex items-center justify-between">
            <span>P2 명령 토픽 연결 노드 (ready_graph 엔드포인트 진단)</span>
            <span className="text-[11px] text-zinc-400 font-normal">
              관제 ready()가 요구하는 토픽별 수량을 대조합니다.
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-3">
          {!ready ? (
            <div className="text-xs text-zinc-500 font-mono">엔드포인트 그래프 수신 대기 중...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead className="bg-[#181a20] text-zinc-400 text-left border-b border-border">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">토픽 이름</th>
                    <th className="px-3 py-1.5 font-medium">발행 노드 (Publishers)</th>
                    <th className="px-3 py-1.5 font-medium">구독 노드 (Subscribers)</th>
                    <th className="px-3 py-1.5 font-medium">단일 소유권 진단</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {[
                    ["task_request", ready.request],
                    ["tasks", ready.tasks],
                    ...Object.entries(ready.robots || {}).map(([r, g]) => [
                      `${r}/patrol_cmd`,
                      g.patrol_cmd,
                    ]),
                  ].map(([topic, entry]) => {
                    const ep = entry as Endpoints;
                    const pubs = ep?.publisher_nodes || [];
                    const subs = ep?.subscriber_nodes || [];
                    const checks = [];
                    if (topic !== "tasks") checks.push(["구독", ep?.subscribers] as const);
                    if (topic !== "task_request") checks.push(["발행", ep?.publishers] as const);
                    const met = checks.every(([, count]) => count === 1);
                    return (
                      <tr key={topic as string} className="hover:bg-zinc-800/20">
                        <td className="px-3 py-1.5 font-bold text-cyan-300">{topic as string}</td>
                        <td className="px-3 py-1.5 text-zinc-300">
                          {pubs.length ? pubs.join(", ") : <span className="text-zinc-600">없음</span>}
                        </td>
                        <td className="px-3 py-1.5 text-zinc-300">
                          {subs.length ? subs.join(", ") : <span className="text-zinc-600">없음</span>}
                        </td>
                        <td className="px-3 py-1.5">
                          <Badge variant="outline" className={met ? "text-emerald-400" : "text-amber-300"}>
                            {met ? "조건 충족" : "조건 미충족"} · {checks.map(([name, count]) =>
                              `${name} ${count ?? "미확인"}/1`).join(" · ")}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* P5 브리지 전달 비교 & P10 순찰 경고 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* P5: 10초 표본 원천 / 관제 비교 */}
        <Card className="rounded-none border-border bg-[#121316]">
          <CardHeader className="p-3 border-b border-border">
            <CardTitle className="text-xs font-bold text-white tracking-wide">
              P5 브리지 전달 비교 (최근 10초 표본)
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            <p className="text-xs text-zinc-400">수집 도메인 {diag?.source_domains?.join(", ") ?? "미확인"} → {diag?.destination_domain ?? "미확인"} · 마지막 수집 {diag?.at ? new Date(diag.at * 1000).toLocaleTimeString() : "미수신"}</p>
            {isDiagStale ? (
              <div className="text-xs text-zinc-500 font-mono">진단기 수신 대기 (최근 5초 내 수신 없음)</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] font-mono">
                  <thead className="bg-[#181a20] text-zinc-400 text-left border-b border-border">
                    <tr>
                      <th className="px-2 py-1 font-medium">로봇/토픽</th>
                      <th className="px-2 py-1 font-medium">원천 표본 수</th>
                      <th className="px-2 py-1 font-medium">관제 전달</th>
                      <th className="px-2 py-1 font-medium">상태</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {diag.links.map((row) => (
                      <tr key={`${row.robot}/${row.topic}`} className="hover:bg-zinc-800/20">
                        <td className="px-2 py-1 font-bold text-white">{row.robot}/{row.topic}</td>
                        <td className="px-2 py-1 text-zinc-300">{row.source}</td>
                        <td className="px-2 py-1 text-zinc-300">{row.destination}</td>
                        <td className="px-2 py-1">
                          <span
                            className={
                              row.state === "양쪽 수신"
                                ? "text-emerald-400 font-bold"
                                : row.state === "관측 중"
                                  ? "text-amber-400 font-bold"
                                  : "text-red-400 font-bold"
                            }
                          >
                            {row.state}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {/* P10: 최근 60초 순찰 경고 */}
        <Card className="rounded-none border-border bg-[#121316]">
          <CardHeader className="p-3 border-b border-border">
            <CardTitle className="text-xs font-bold text-white tracking-wide">
              P10 최근 60초 순찰 경고 (Patrol Node Warnings)
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            {isDiagStale ? <p>순찰 경고 미확인 · 진단기 미수신 또는 만료</p> : !diag.warnings?.length ? (
              <div className="text-xs text-zinc-500 font-mono">수집된 최근 60초 순찰 경고 0건</div>
            ) : (
              <div className="space-y-1.5 max-h-60 overflow-y-auto">
                {diag.warnings.map((w, idx) => (
                  <div
                    key={idx}
                    className="border border-amber-900/40 bg-amber-950/20 p-2 text-xs font-mono text-zinc-300"
                  >
                    <div className="flex items-center justify-between text-amber-300 font-bold">
                      <span>{w.robot} · {w.node}</span>
                      <span className="text-[10px] text-zinc-500">{w.age_sec.toFixed(1)}초 전</span>
                    </div>
                    <p className="text-[11px] text-zinc-400 break-all">{w.message}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* P12 위치 추정 & 호기별 토픽 링크 상태 */}
      <Card className="rounded-none border-border bg-[#121316]">
        <CardHeader className="p-3 border-b border-border">
          <CardTitle className="text-xs font-bold text-white tracking-wide">
            P12 위치 추정 및 호기별 토픽 링크 상태
          </CardTitle>
        </CardHeader>
        <CardContent className="p-3 space-y-3">
          {links.length === 0 ? (
            <div className="text-xs text-zinc-500 font-mono">호기 링크 정보 없음</div>
          ) : (
            links.map((link) => (
              <div key={link.robot_id} className="border border-border p-2.5 space-y-1.5 bg-[#16171b]">
                <div className="flex flex-wrap items-center justify-between text-xs font-mono">
                  <span className="font-bold text-cyan-300 text-sm">{link.robot_id}</span>
                  <div className="flex items-center gap-2 text-zinc-400 text-[11px]">
                    <span>상태: <b className="text-white">{String(link.status.state ?? "미수신")}</b></span>
                    <span>웨이포인트: <b className="text-white">{String(link.status.waypoint ?? "-")}/{String(link.status.total ?? "-")}</b></span>
                    <span>busy: <b className="text-white">{String(link.status.busy ?? "-")}</b></span>
                    <span>래치: <b className="text-white">{String(link.status.central_latched ?? "-")}</b></span>
                  </div>
                </div>

                <div className="text-[11px] font-mono text-zinc-400 flex flex-wrap gap-x-4 gap-y-1">
                  {TOPICS.map((topic) => (
                    <span key={topic}>
                      {topic}: 발행자 {link.graph[topic]?.publishers ?? "?"}개,{" "}
                      {link.ages[topic] === undefined ? (
                        <span className="text-zinc-600">미수신</span>
                      ) : topic === "amcl_pose" && link.status.busy === false && (live?.robots.find(r => r.robot_id === link.robot_id)?.op_state === "IDLE") ? (
                        <span className="text-zinc-400">{link.ages[topic].toFixed(1)}초 전 (대기 상태 보고)</span>
                      ) : (
                        <span className="text-zinc-300">{link.ages[topic].toFixed(1)}초 전</span>
                      )}
                    </span>
                  ))}
                  <span>
                    scan: 발행자 {link.graph.scan?.publishers ?? "?"}개{" "}
                    {(link.graph.scan?.reliability ?? []).join(",")}
                  </span>
                </div>

                {link.problems && link.problems.length > 0 && (
                  <div className="text-xs text-amber-400 bg-amber-950/20 p-1 border border-amber-900/40">
                    이동 거절 사유: {link.problems.join(", ")}
                  </div>
                )}
              </div>
            ))
          )}
          <div className="text-[10px] text-zinc-500 font-mono">
            참고: amcl_pose는 Nav2 AMCL 특성상 로봇이 정지해 있으면 새로 발행되지 않습니다. 상태 미수신이나 주행 중 위치 만료는 별도로 확인해야 합니다.
          </div>
        </CardContent>
      </Card>

      {/* 요청/응답 로그 & 관제 작업 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 요청과 응답 로그 */}
        <Card className="rounded-none border-border bg-[#121316]">
          <CardHeader className="p-3 border-b border-border">
            <CardTitle className="text-xs font-bold text-white tracking-wide">
              요청과 응답 로그 ({log.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            {log.length === 0 ? (
              <div className="text-xs text-zinc-500 font-mono">기록 없음</div>
            ) : (
              <div className="space-y-1 max-h-64 overflow-y-auto font-mono text-[11px]">
                {log.map((row, idx) => (
                  <div key={idx} className="border-b border-zinc-800/40 pb-1 text-zinc-300 flex items-center justify-between gap-2">
                    <span className="truncate">
                      <span className="text-zinc-500">{new Date(row.at * 1000).toLocaleTimeString()}</span>{" "}
                      <span className="text-cyan-300 font-bold">{row.type}</span> {row.operation ?? ""}{" "}
                      {(row.points ?? []).join(",")}{" "}
                      <span className="text-white">{row.robot_id ?? ""}</span>
                    </span>
                    <span className="shrink-0 flex items-center gap-1.5">
                      <span className={row.status !== null && row.status >= 300 ? "text-red-400 font-bold" : "text-emerald-400 font-bold"}>
                        {row.status ?? "응답 없음"}
                      </span>
                      {row.rtt_ms !== null && <span className="text-cyan-400 font-bold">{row.rtt_ms}ms</span>}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 관제 작업 목록 */}
        <Card className="rounded-none border-border bg-[#121316]">
          <CardHeader className="p-3 border-b border-border">
            <CardTitle className="text-xs font-bold text-white tracking-wide">
              관제 작업 목록 ({tasks.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            {tasks.length === 0 ? (
              <div className="text-xs text-zinc-500 font-mono">현재 실행 중인 관제 작업 없음</div>
            ) : (
              <div className="space-y-1.5 max-h-64 overflow-y-auto font-mono text-[11px]">
                {tasks.map((task) => (
                  <div key={task.task_id} className="border border-border p-2 bg-[#16171b] flex items-center justify-between">
                    <div>
                      <span className="text-white font-bold">{task.robot_id}</span>{" "}
                      <span className="text-cyan-300">{task.command}</span>{" "}
                      <span className="text-zinc-400">({task.detail})</span>
                    </div>
                    <Badge variant="outline" className="border-cyan-700 text-cyan-300">
                      {task.state}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <section><h2>구역 토큰 대조</h2><ZoneTable zones={live?.zones ?? []} /></section>
      {/* 경유 기록 */}
      <Card className="rounded-none border-border bg-[#121316]">
        <CardHeader className="p-3 border-b border-border">
          <CardTitle className="text-xs font-bold text-white tracking-wide">
            AMCL 추정 위치에서 대조한 경유 지점
          </CardTitle>
        </CardHeader>
        <CardContent className="p-3 font-mono text-xs">
          {Object.keys(routes).length === 0 ? (
            <div className="text-zinc-500">기록된 경유 경로 없음</div>
          ) : (
            Object.entries(routes).map(([robot, points]) => (
              <div key={robot} className="text-zinc-300 py-1">
                <span className="text-white font-bold">{robot}</span>: {points.join(" → ")}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
