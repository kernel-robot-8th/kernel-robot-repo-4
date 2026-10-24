// 메뉴 2.1 통합 주행 지도. MapInfo 의 지점과 RobotStatus 의 자세를 맵 좌표 그대로 그린다. 읽기 전용이다.
// 벽·가구(점유 격자)는 게이트웨이가 PNG 로 내면 겹쳐 그린다 (S2). 지금은 지점과 로봇만 그린다.
import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { MapInfo, RobotStatus } from "@/generated/messages";
import { useMessages } from "@/lib/dataSource";
import { num, yawDeg } from "@/lib/format";
import { robotTone } from "@/lib/tones";
import MenuHeader from "@/shell/MenuHeader";
import Pill from "@/shell/Pill";
import ResourceSection from "@/shell/ResourceSection";
import type { MenuPageProps } from "@/shell/types";

const ROBOT_COLORS: Record<string, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  bad: "var(--destructive)",
  muted: "var(--muted-foreground)",
};

function MapView({ map, robots }: { map: MapInfo; robots: RobotStatus[] }) {
  const x0 = map.origin_x ?? 0;
  const y0 = map.origin_y ?? 0;
  const w = map.width * (map.resolution ?? 0.01);
  const h = map.height * (map.resolution ?? 0.01);
  // 맵 y 는 위로 늘고 화면 y 는 아래로 늘어서 뒤집는다.
  const px = (x: number | null) => (x ?? 0) - x0;
  const py = (y: number | null) => h - ((y ?? 0) - y0);
  const label = 0.07;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label={`${map.map_name} 지점과 로봇 위치`}
      className="max-h-[70vh] w-full rounded-none border bg-card"
    >
      <rect x={0} y={0} width={w} height={h} fill="none" stroke="var(--border)" strokeWidth={0.01} />
      {map.waypoints.map((wp) => {
        const moved = wp.work_x !== wp.approach_x || wp.work_y !== wp.approach_y;
        return (
          <g key={wp.waypoint_id}>
            {moved && (
              <line
                x1={px(wp.work_x)}
                y1={py(wp.work_y)}
                x2={px(wp.approach_x)}
                y2={py(wp.approach_y)}
                stroke="var(--muted-foreground)"
                strokeWidth={0.008}
                strokeDasharray="0.03 0.02"
              />
            )}
            <rect
              data-kind="work"
              x={px(wp.work_x) - 0.03}
              y={py(wp.work_y) - 0.03}
              width={0.06}
              height={0.06}
              fill="none"
              stroke="var(--primary)"
              strokeWidth={0.01}
            />
            <circle data-kind="approach" cx={px(wp.approach_x)} cy={py(wp.approach_y)} r={0.025} fill="var(--primary)" />
            <text x={px(wp.work_x) + 0.05} y={py(wp.work_y) - 0.05} fontSize={label} fill="var(--foreground)">
              {wp.waypoint_id}
            </text>
          </g>
        );
      })}
      {robots.map((robot) => {
        const pos = robot.current_pose.position;
        const yaw = yawDeg(robot.current_pose.orientation);
        const color = ROBOT_COLORS[robotTone(robot.state)];
        return (
          <g key={robot.robot_id} data-robot={robot.robot_id} transform={`translate(${px(pos.x)} ${py(pos.y)})`}>
            <g transform={`rotate(${yaw === null ? 0 : -yaw})`}>
              <polygon points="0.09,0 -0.06,0.055 -0.06,-0.055" fill={color} opacity={yaw === null ? 0.4 : 0.9} />
            </g>
            <text x={0.08} y={0.1} fontSize={label} fontWeight={700} fill={color}>
              {robot.robot_id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Legend({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}

export default function Page({ menu }: MenuPageProps) {
  const maps = useMessages("MapInfo");
  const robots = useMessages("RobotStatus");
  return (
    <div className="max-w-5xl space-y-6">
      <MenuHeader menu={menu} kind="page" />

      <ResourceSection title="지도" resource={maps}>
        {(maplist) => {
          const map = maplist[0];
          if (!map) return <p className="text-sm text-muted-foreground">맵 정보가 없습니다.</p>;
          const robotList = robots.data ?? [];
          return (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-mono">{map.map_name}</span>
                <Pill tone="muted">지문 {map.map_hash.slice(0, 8)}…</Pill>
                <span className="text-muted-foreground">
                  {map.width}×{map.height} 칸 · {num(map.resolution, 2, " m/칸")}
                </span>
              </div>
              <MapView map={map} robots={robotList} />
              <Legend>
                □ 작업점 · ● Nav2 정차점(작업점과 다르면 점선으로 이음) · ▶ 로봇 (색은 상태). 좌표는 맵 프레임(m)이고 위쪽이 +y 입니다.
              </Legend>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">지점</CardTitle>
                </CardHeader>
                <CardContent className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead className="text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="py-1 font-medium">이름</th>
                        <th className="py-1 font-medium">작업점 (x, y)</th>
                        <th className="py-1 font-medium">정차점 (x, y)</th>
                        <th className="py-1 font-medium">팔</th>
                      </tr>
                    </thead>
                    <tbody>
                      {map.waypoints.map((wp) => (
                        <tr key={wp.waypoint_id} className="border-t">
                          <td className="py-1.5 font-mono text-xs">{wp.waypoint_id}</td>
                          <td className="py-1.5 tabular-nums">
                            {num(wp.work_x, 3)}, {num(wp.work_y, 3)}
                          </td>
                          <td className="py-1.5 tabular-nums">
                            {num(wp.approach_x, 3)}, {num(wp.approach_y, 3)}
                          </td>
                          <td className="py-1.5">{wp.arm_id || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </>
          );
        }}
      </ResourceSection>
    </div>
  );
}
