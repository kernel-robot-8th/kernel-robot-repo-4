// 메뉴 6.5 디버그 패널. 화면 값은 전부 monitor_node 가 받은 실제 값이다.
// 이동 명령은 로봇 토픽이 아니라 관제 요청으로 나간다 (fms_dev_rules R7).
import { useState } from "react";

import { Button } from "@/components/ui/button";

export interface ZoneRow {
  zone: string;
  manager_known: boolean;
  manager: string | null;
  robot: string | null;
  match: boolean | null;
}

export interface TopicLink {
  publishers: number;
  subscribers: number;
  reliability?: string[];
}

export interface LinkRow {
  robot_id: string;
  status: Record<string, unknown>;
  ages: Record<string, number>;
  graph: Record<string, TopicLink>;
  problems: string[];
}

export interface LogRow {
  at: number;
  type: string;
  robot_id: string | null;
  operation: string | null;
  points: string[] | null;
  status: number | null;
  rtt_ms: number | null;
  detail: string;
}

export interface TaskRow {
  task_id: string;
  robot_id: string;
  command: string;
  state: string;
  detail: string;
}

export interface DebugState {
  ros: { domain_id?: string; rmw?: string };
  zones: ZoneRow[];
  links: LinkRow[];
  log: LogRow[];
  tasks: TaskRow[];
  routes: Record<string, string[]>;
}

const OPERATIONS = ["zone", "goto", "leave", "home"];
const TOPICS = ["patrol_status", "amcl_pose", "odom"];
const BUTTON = "h-7 text-[10px] rounded-none bg-[#1c1d22] border-border text-[#dddddd]";
const INPUT = "h-7 px-1.5 text-[10px] bg-[#1c1d22] border border-border text-white";
const TITLE = "text-[11px] font-bold text-cyan-400";
const CELL = "pr-3 py-0.5 align-top";

function zoneResult(row: ZoneRow) {
  if (row.match === null) return "관리자 값 없음";
  return row.match ? "일치" : "불일치";
}

function MovePanel({
  robots,
  blocked,
  send,
}: {
  robots: string[];
  blocked: boolean;
  send: (path: string, body: unknown) => Promise<void>;
}) {
  const [robot, setRobot] = useState(robots[0] ?? "");
  const [operation, setOperation] = useState(OPERATIONS[0]);
  const [points, setPoints] = useState("ZA");
  const needsPoints = operation === "zone" || operation === "goto";
  const names = needsPoints ? points.split(",").map((item) => item.trim()).filter(Boolean) : [];

  return (
    <section className="space-y-1">
      <h3 className={TITLE}>이동 명령 (관제 요청)</h3>
      <div className="flex flex-wrap items-center gap-1.5">
        <select aria-label="명령 로봇" className={INPUT} value={robot} onChange={(event) => setRobot(event.target.value)}>
          {robots.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <select
          aria-label="명령 종류"
          className={INPUT}
          value={operation}
          onChange={(event) => setOperation(event.target.value)}
        >
          {OPERATIONS.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <input
          aria-label="지점"
          className={`${INPUT} w-28`}
          disabled={!needsPoints}
          value={needsPoints ? points : ""}
          onChange={(event) => setPoints(event.target.value)}
        />
        <Button
          variant="outline"
          size="sm"
          className={BUTTON}
          disabled={blocked || (needsPoints && names.length === 0)}
          onClick={() =>
            void send("control", { type: "create", robot_id: robot, operation, points: names })
          }
        >
          명령 요청
        </Button>
      </div>
    </section>
  );
}

function ZonePanel({ zones }: { zones: ZoneRow[] }) {
  return (
    <section className="space-y-1">
      <h3 className={TITLE}>구역 점유</h3>
      {zones.length === 0 && (
        <div className="text-[10px] text-[#888888]">점유 정보 없음. 시작 뒤 몇 초는 비어 있을 수 있습니다.</div>
      )}
      <table className="text-[10px] font-mono text-[#cccccc]">
        <tbody>
          {zones.map((row) => (
            <tr key={row.zone}>
              <td className={CELL}>구역 {row.zone}</td>
              <td className={CELL}>관리자 {row.manager_known ? row.manager ?? "비어 있음" : "미수신"}</td>
              <td className={CELL}>로봇 {row.robot ?? "없음"}</td>
              <td className={`${CELL} ${row.match === false ? "text-red-400 font-bold" : ""}`}>
                {zoneResult(row)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function LinkPanel({ links, ros }: { links: LinkRow[]; ros: DebugState["ros"] }) {
  return (
    <section className="space-y-1">
      <h3 className={TITLE}>
        연결 진단
        <span className="ml-2 font-mono font-normal text-[#888888]">
          도메인 {ros.domain_id ?? "?"} / {ros.rmw ?? "?"}
        </span>
      </h3>
      {links.map((link) => (
        <div key={link.robot_id} className="font-mono text-[10px] text-[#cccccc] space-y-0.5">
          <div>
            <b className="text-white">{link.robot_id}</b> 상태 {String(link.status.state ?? "미수신")} / detail{" "}
            {String(link.status.detail ?? "")} / 진행 {String(link.status.waypoint ?? "-")}/
            {String(link.status.total ?? "-")} / busy {String(link.status.busy ?? "-")} / 정지 래치{" "}
            {String(link.status.central_latched ?? "-")}
          </div>
          <div className="text-[#888888]">
            {TOPICS.map((topic) => (
              <span key={topic} className="mr-3">
                {topic} 발행자 {link.graph[topic]?.publishers ?? "?"}개,{" "}
                {link.ages[topic] === undefined ? "미수신" : `${link.ages[topic].toFixed(1)}초 전`}
              </span>
            ))}
            <span>
              scan 발행자 {link.graph.scan?.publishers ?? "?"}개{" "}
              {(link.graph.scan?.reliability ?? []).join(",")}
            </span>
          </div>
          {link.problems.map((problem) => (
            <div key={problem} className="text-amber-400">
              이동 거절 사유: {problem}
            </div>
          ))}
        </div>
      ))}
      <div className="text-[9px] text-[#888888]">
        amcl_pose는 로봇이 서 있으면 새로 오지 않습니다. 시간이 커도 고장은 아닙니다.
      </div>
    </section>
  );
}

function RoutePanel({ routes }: { routes: DebugState["routes"] }) {
  const robots = Object.keys(routes);
  return (
    <section className="space-y-1">
      <h3 className={TITLE}>경유 기록</h3>
      <div className="text-[9px] text-[#888888]">
        amcl_pose 기준입니다. 로봇이 믿는 위치라서 실제 경로와 다를 수 있고, 지나간 지점이 빠질 수 있습니다.
      </div>
      {robots.length === 0 && <div className="text-[10px] text-[#888888]">기록 없음</div>}
      {robots.map((robot) => (
        <div key={robot} className="font-mono text-[10px] text-[#cccccc] break-all">
          {robot}: {routes[robot].join(" > ")}
        </div>
      ))}
    </section>
  );
}

function LogPanel({ log, tasks }: { log: LogRow[]; tasks: TaskRow[] }) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <div className="space-y-1 min-w-0">
        <h3 className={TITLE}>요청과 응답</h3>
        {log.length === 0 && <div className="text-[10px] text-[#888888]">기록 없음</div>}
        {log.map((row, index) => (
          <div key={index} className="font-mono text-[10px] text-[#cccccc] break-all">
            {new Date(row.at * 1000).toLocaleTimeString()} {row.type} {row.operation ?? ""}{" "}
            {(row.points ?? []).join(",")} {row.robot_id ?? ""}{" "}
            <span className={row.status !== null && row.status >= 300 ? "text-red-400" : "text-emerald-400"}>
              {row.status ?? "응답 없음"}
            </span>{" "}
            {row.rtt_ms === null ? "" : `${row.rtt_ms} ms`} {row.detail}
          </div>
        ))}
      </div>
      <div className="space-y-1 min-w-0">
        <h3 className={TITLE}>관제 작업</h3>
        {tasks.length === 0 && <div className="text-[10px] text-[#888888]">작업 없음</div>}
        {tasks.map((task) => (
          <div key={task.task_id} className="font-mono text-[10px] text-[#cccccc] break-all">
            {task.robot_id} {task.command} {task.state} {task.detail}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function DebugPanels({
  debug,
  robots,
  blocked,
  send,
}: {
  debug: DebugState;
  robots: string[];
  blocked: boolean;
  send: (path: string, body: unknown) => Promise<void>;
}) {
  return (
    <div className="space-y-3 border-t border-border pt-3">
      <MovePanel robots={robots} blocked={blocked} send={send} />
      <ZonePanel zones={debug.zones} />
      <LinkPanel links={debug.links} ros={debug.ros} />
      <RoutePanel routes={debug.routes} />
      <LogPanel log={debug.log} tasks={debug.tasks} />
    </div>
  );
}
