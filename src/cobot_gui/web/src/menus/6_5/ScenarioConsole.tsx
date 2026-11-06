// 메뉴 6.5 시나리오 콘솔. 중계 장비 monitor_node(8083)의 기록을 보여 주는 개발용 화면이다.
// 버튼은 로봇에 직접 명령하지 않고 /api/fms/control 로 관제 요청만 보낸다. 운영 화면은 OMEN 웹이다.
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface RobotView {
  robot_id: string;
  op_state: string;
  cargo_state: string;
  zone: string;
  step_seq: number;
  order_id: string | null;
  stage: string | null;
  pose_x: number | null;
  pose_y: number | null;
}

interface Mission {
  mission_id: string;
  route: string;
  robot_id: string | null;
  current_step_seq: number;
  current_step_code: string;
  current_stage: string;
  mission_state: string;
  hold_reason: string;
  recovery: "resume" | "fail" | null;
}

interface Anomaly {
  event_id: string;
  vision_class: string;
  judgment: string;
  linked_robot_id: string | null;
  recommended_action: string;
  control_action: string;
  alarm_text: string;
  ack_state: string;
  repeat_count: number;
}

interface WorkRequest {
  request_id: string;
  order_id: string;
  robot_id: string;
  stage: string;
  target: string;
  action: string;
  sku: string;
}

interface LiveState {
  mode: "OBSERVE_ONLY" | "AUTO_HOLD";
  armed: boolean | null;
  fleet_age_sec: number | null;
  robots: RobotView[];
  missions: Mission[];
  anomalies: Anomaly[];
  work: WorkRequest[];
  adapter: { enabled: boolean; blocked: string };
  allow_mock: boolean;
}

const STEP_LABELS = ["이동", "접안", "상차", "운송", "접안", "하차", "복귀"];
const ROUTES = [
  { id: "wh_a_to_store", label: "시나리오 A 출고" },
  { id: "wh_b_to_store", label: "시나리오 B 출고" },
];
const EVIDENCE = [
  { id: "base_stopped", label: "로봇 정지" },
  { id: "arms_safe", label: "팔 퇴피" },
  { id: "cargo_reconciled", label: "화물 확인" },
  { id: "resources_clear", label: "통로·구역 확인" },
] as const;
const MOCK_CLASSES = ["box_on_floor", "box_perched_on_rim", "box_run_over", "lid_detached"];
const STALE_SEC = 5;
const POLL_MS = 1000;
const OPEN_ACKS = ["UNREAD", "ACKNOWLEDGED"];
const BUTTON = "h-7 text-[10px] rounded-none bg-[#1c1d22] border-border text-[#dddddd]";
const INPUT = "h-7 px-1.5 text-[10px] bg-[#1c1d22] border border-border text-white";

type EvidenceId = (typeof EVIDENCE)[number]["id"];

async function post(path: string, body: unknown): Promise<string> {
  try {
    const response = await fetch(`/api/fms/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await response.json()) as { detail?: string };
    return response.ok ? `완료: ${path}` : `거절 ${response.status}: ${data.detail ?? path}`;
  } catch (error) {
    return `전송 실패: ${String(error)}`;
  }
}

function cargoClass(cargo: string) {
  if (cargo === "EMPTY") return "border-zinc-600 text-zinc-400";
  if (cargo === "LOADED") return "border-emerald-600 text-emerald-400";
  return "border-amber-600 text-amber-400";
}

function RobotCard({ robot }: { robot: RobotView }) {
  return (
    <div className="border border-border p-2 space-y-1.5 bg-[#16171b]">
      <div className="flex items-center justify-between gap-2 text-[11px] font-bold text-white">
        <span>{robot.robot_id}</span>
        <span className="flex gap-1">
          <Badge variant="outline" className={cargoClass(robot.cargo_state)}>
            {robot.cargo_state}
          </Badge>
          {robot.op_state === "HOLD_ANOMALY" && (
            <Badge variant="outline" className="border-red-600 text-red-400">
              HOLD
            </Badge>
          )}
        </span>
      </div>
      <div className="grid grid-cols-7 gap-0.5" aria-label={`${robot.robot_id} 7단계 진행`}>
        {STEP_LABELS.map((label, index) => (
          <span
            key={index}
            className={`text-center text-[9px] py-0.5 ${
              index + 1 === robot.step_seq
                ? "bg-cyan-700 text-white"
                : index + 1 < robot.step_seq
                  ? "bg-[#2a2d35] text-zinc-300"
                  : "bg-[#1c1d22] text-zinc-600"
            }`}
          >
            {label}
          </span>
        ))}
      </div>
      <div className="font-mono text-[9px] text-[#888888]">
        {robot.op_state} / {robot.zone} / {robot.stage ?? "대기"}
        {robot.pose_x !== null && robot.pose_y !== null
          ? ` / (${robot.pose_x.toFixed(2)}, ${robot.pose_y.toFixed(2)})`
          : " / 자세 없음"}
      </div>
    </div>
  );
}

export default function ScenarioConsole() {
  const [live, setLive] = useState<LiveState | null>(null);
  const [offline, setOffline] = useState(false);
  const [message, setMessage] = useState("");
  const [operator, setOperator] = useState("");
  const [note, setNote] = useState("");
  const [sku, setSku] = useState("SHOE42");
  const [stock, setStock] = useState("10");
  const [evidence, setEvidence] = useState<Record<EvidenceId, boolean>>({
    base_stopped: false,
    arms_safe: false,
    cargo_reconciled: false,
    resources_clear: false,
  });
  const [mock, setMock] = useState({ vision_class: MOCK_CLASSES[0], map_x: "0.6", map_y: "0.5" });

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/fms/live_state");
      if (!response.ok) throw new Error(String(response.status));
      const data = (await response.json()) as LiveState;
      setLive(data.robots ? data : null);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const send = async (path: string, body: unknown) => {
    setMessage(await post(path, body));
    await refresh();
  };

  const named = operator.trim().length > 0;
  const confirmed = EVIDENCE.every((item) => evidence[item.id]) && note.trim().length > 0;
  const recover = (mission: Mission, decision: "resume" | "fail") =>
    send("control", {
      type: "resolve",
      order_id: mission.mission_id,
      decision,
      operator,
      note,
      evidence,
    });

  if (!live) {
    return (
      <Card className="rounded-none border border-border bg-[#121316] shadow-none">
        <CardContent className="p-3 text-[11px] text-[#999999]">
          시나리오 콘솔: {offline ? "monitor_node 연결 안 됨 (8083)" : "상태 수신 대기"}
        </CardContent>
      </Card>
    );
  }

  const fleetStale = live.fleet_age_sec === null || live.fleet_age_sec > STALE_SEC;
  const blocked = live.missions.filter((mission) => mission.recovery);
  const customer = live.missions.filter(
    (mission) => mission.current_stage === "CUSTOMER" && mission.mission_state === "RUNNING",
  );
  const anomalies = live.anomalies.filter((row) => OPEN_ACKS.includes(row.ack_state));

  return (
    <Card className="rounded-none border border-border bg-[#121316] shadow-none">
      <CardHeader className="py-2 px-3 border-b border-border bg-[#18191f] flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle className="text-xs font-bold text-white">
          시나리오 콘솔 (개발용, 관제 요청 경유)
        </CardTitle>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            variant="outline"
            className={fleetStale ? "border-red-600 text-red-400" : "border-emerald-600 text-emerald-400"}
          >
            {fleetStale ? "관제 수신 끊김" : "관제 수신 중"}
          </Badge>
          <Badge variant="outline" className="border-purple-600 text-purple-400">
            {live.mode}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            className={BUTTON}
            onClick={() =>
              void send("mode", {
                mode: live.mode === "AUTO_HOLD" ? "OBSERVE_ONLY" : "AUTO_HOLD",
              })
            }
          >
            {live.mode === "AUTO_HOLD" ? "관측 전용으로" : "자동 정지 켜기"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className={BUTTON}
            onClick={() => void send("control", { type: "arm", armed: !live.armed, source: "menu_6_5" })}
          >
            {live.armed ? "가동 허용 끄기" : "가동 허용 켜기"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-3 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {live.robots.map((robot) => (
            <RobotCard key={robot.robot_id} robot={robot} />
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <input
            aria-label="운영자"
            placeholder="운영자"
            className={`${INPUT} w-20`}
            value={operator}
            onChange={(event) => setOperator(event.target.value)}
          />
          <input
            aria-label="SKU"
            className={`${INPUT} w-20`}
            value={sku}
            onChange={(event) => setSku(event.target.value)}
          />
          <input
            aria-label="재고"
            className={`${INPUT} w-12`}
            value={stock}
            onChange={(event) => setStock(event.target.value)}
          />
          <Button
            variant="outline"
            size="sm"
            className={BUTTON}
            onClick={() =>
              void send("control", { type: "inventory", sku, available: Number(stock) })
            }
          >
            재고 설정
          </Button>
          {ROUTES.map((route) => (
            <Button
              key={route.id}
              variant="outline"
              size="sm"
              className={BUTTON}
              onClick={() => void send("control", { type: "order", order: { sku, route: route.id } })}
            >
              {route.label}
            </Button>
          ))}
          {customer.map((mission) => (
            <Button
              key={mission.mission_id}
              variant="outline"
              size="sm"
              className={BUTTON}
              onClick={() => void send("control", { type: "received", order_id: mission.mission_id })}
            >
              고객 수령 확인 {mission.mission_id}
            </Button>
          ))}
        </div>

        <section className="space-y-1">
          <h3 className="text-[11px] font-bold text-cyan-400">
            수동 승인 ({live.work.length})
            {live.adapter.blocked && (
              <span className="ml-2 text-red-400">수동 어댑터 꺼짐: {live.adapter.blocked}</span>
            )}
          </h3>
          {live.work.map((work) => (
            <div key={work.request_id} className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]">
              <span className="font-mono">
                {work.robot_id} {work.stage} ({work.target}/{work.action})
              </span>
              <Button
                variant="outline"
                size="sm"
                className={BUTTON}
                disabled={!named}
                onClick={() => void send(`work/${work.request_id}`, { decision: "approve", operator })}
              >
                승인
              </Button>
              <Button
                variant="outline"
                size="sm"
                className={BUTTON}
                disabled={!named}
                onClick={() =>
                  void send(`work/${work.request_id}`, {
                    decision: "reject",
                    operator,
                    note,
                    retry_safe: true,
                  })
                }
              >
                실패 (재시도 안전)
              </Button>
              <Button
                variant="outline"
                size="sm"
                className={BUTTON}
                disabled={!named}
                onClick={() =>
                  void send(`work/${work.request_id}`, { decision: "reject", operator, note })
                }
              >
                실패 (중단)
              </Button>
            </div>
          ))}
        </section>

        <section className="space-y-1">
          <h3 className="text-[11px] font-bold text-red-400">이상 판정 ({anomalies.length})</h3>
          {anomalies.map((row) => (
            <div key={row.event_id} className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]">
              <span className="font-mono text-amber-300">{row.judgment}</span>
              <span>{row.linked_robot_id ?? "로봇 미지정"}</span>
              <span>{row.alarm_text || row.vision_class}</span>
              <span className="font-mono text-[#888888]">
                {row.control_action} x{row.repeat_count}
              </span>
              <Button
                variant="outline"
                size="sm"
                className={BUTTON}
                disabled={!named}
                onClick={() =>
                  void send(`anomalies/${row.event_id}`, { ack_state: "RESOLVED", operator, note })
                }
              >
                확인 완료
              </Button>
              <Button
                variant="outline"
                size="sm"
                className={BUTTON}
                disabled={!named}
                onClick={() =>
                  void send(`anomalies/${row.event_id}`, { ack_state: "FALSE_ALARM", operator, note })
                }
              >
                오탐
              </Button>
            </div>
          ))}
        </section>

        {blocked.length > 0 && (
          <section className="space-y-1">
            <h3 className="text-[11px] font-bold text-amber-400">복구 요청</h3>
            <div className="flex flex-wrap items-center gap-2 text-[10px] text-[#cccccc]">
              {EVIDENCE.map((item) => (
                <label key={item.id} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={evidence[item.id]}
                    onChange={(event) =>
                      setEvidence({ ...evidence, [item.id]: event.target.checked })
                    }
                  />
                  {item.label}
                </label>
              ))}
              <input
                aria-label="확인 내용"
                placeholder="확인 내용"
                className={`${INPUT} w-40`}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            </div>
            {blocked.map((mission) => (
              <div key={mission.mission_id} className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]">
                <span className="font-mono">
                  {mission.mission_id} {mission.mission_state} {mission.current_stage}
                </span>
                {mission.hold_reason && <span className="text-red-400">{mission.hold_reason}</span>}
                {mission.recovery === "resume" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className={BUTTON}
                    disabled={!named || !confirmed || !live.armed}
                    onClick={() => void recover(mission, "resume")}
                  >
                    재개
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className={BUTTON}
                  disabled={!named || !confirmed}
                  onClick={() => void recover(mission, "fail")}
                >
                  실패 처리
                </Button>
              </div>
            ))}
            <div className="text-[9px] text-[#888888]">
              재개는 가동 허용을 켠 뒤 누릅니다. 상·하차 단계는 재개할 수 없어 실패 처리 뒤 새 주문을 냅니다.
            </div>
          </section>
        )}

        <div className="flex flex-wrap items-center gap-1.5">
          {live.robots
            .filter((robot) => robot.zone.startsWith("ZONE_") && !robot.order_id)
            .map((robot) => (
              <Button
                key={robot.robot_id}
                variant="outline"
                size="sm"
                className={BUTTON}
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

        {message && <div className="font-mono text-[10px] text-[#999999]">{message}</div>}
      </CardContent>
    </Card>
  );
}
