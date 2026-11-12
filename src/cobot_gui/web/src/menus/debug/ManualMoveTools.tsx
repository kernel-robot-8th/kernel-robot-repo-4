import { useState } from "react";
import { Button } from "@/components/ui/button";
import { stopView } from "@/lib/fmsLiveContext";
import { useSimCommand } from "./useSimCommand";
const BUTTON = "h-7 text-[10px] rounded-none bg-[#1c1d22] border-border text-[#dddddd]";
const INPUT = "h-7 px-1.5 text-[10px] bg-[#1c1d22] border border-border text-white";
const OPERATIONS = ["zone", "goto", "leave", "home"];
const TITLE = "text-[11px] font-bold text-cyan-400";
function MovePanel({
  robots,
  blocked,
  send,
}: {
  robots: string[];
  blocked: (robot: string) => boolean;
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
          disabled={blocked(robot) || (needsPoints && names.length === 0)}
          onClick={() =>
            void send("control", { type: "create", robot_id: robot, operation, points: names })
          }
        >
          명령 요청
        </Button>
        {blocked(robot) && (
          <span className="text-[10px] text-red-400">{robot} 정지 보류 중: 복구 뒤 명령할 수 있습니다</span>
        )}
      </div>
    </section>
  );
}

const MOCK_CLASSES = ["box_on_floor", "box_perched_on_rim", "box_run_over", "lid_detached"];

export default function ManualMoveTools() {
  const { live, allowed, send, message } = useSimCommand();
  const [mock, setMock] = useState({ vision_class: MOCK_CLASSES[0], map_x: "0.6", map_y: "0.5" });
  if (!live || !allowed) return null;
  const stop = stopView(live);
  return <section className="border border-border p-3">
    <h2>격리 시뮬 관제 경유 수동 도구</h2>
    <MovePanel robots={live.robots.map(r => r.robot_id)} blocked={stop.blocks} send={send}/>
          <div className="flex flex-wrap items-center gap-1.5">
            {live.robots
              .filter((robot) => robot.zone.startsWith("ZONE_") && !robot.order_id)
              .map((robot) => (
                <Button
                  key={robot.robot_id}
                  variant="outline"
                  size="sm"
                  className={BUTTON}
                  disabled={stop.blocks(robot.robot_id)}
                  onClick={() =>
                    void send("control", {
                      type: "create",
                      robot_id: robot.robot_id,
                      operation: "leave",
                      points: [],
                    })
                  }
                >
                  {robot.robot_id} 구역 이탈
                </Button>
              ))}
            {live.allow_mock && (
              <>
                <select
                  aria-label="모의 클래스"
                  className={INPUT}
                  value={mock.vision_class}
                  onChange={(event) => setMock({ ...mock, vision_class: event.target.value })}
                >
                  {MOCK_CLASSES.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
                <input
                  aria-label="모의 X"
                  className={`${INPUT} w-12`}
                  value={mock.map_x}
                  onChange={(event) => setMock({ ...mock, map_x: event.target.value })}
                />
                <input
                  aria-label="모의 Y"
                  className={`${INPUT} w-12`}
                  value={mock.map_y}
                  onChange={(event) => setMock({ ...mock, map_y: event.target.value })}
                />
                <Button
                  variant="outline"
                  size="sm"
                  className={BUTTON}
                  onClick={() =>
                    void send("anomalies", {
                      vision_class: mock.vision_class,
                      map_x: Number(mock.map_x),
                      map_y: Number(mock.map_y),
                    })
                  }
                >
                  이상 모의 주입
                </Button>
              </>
            )}
          </div>
    {message && <p role="status">{message}</p>}
  </section>;
}
