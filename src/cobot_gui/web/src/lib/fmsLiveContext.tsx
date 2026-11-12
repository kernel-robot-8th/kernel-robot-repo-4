/* eslint-disable react-refresh/only-export-components */
import { useLocation } from "react-router-dom";
import React, { createContext, useContext, useEffect, useState } from "react";
import type { StageTraceRow } from "@/menus/6_5/OrderStageTrace";

export interface RobotView {
  robot_id: string;
  op_state: string;
  cargo_state: string;
  battery_percent?: number | null;
  central_latched?: boolean | null;
  zone: string;
  step_seq: number;
  order_id: string | null;
  stage: string | null;
  pose_x: number | null;
  pose_y: number | null;
}

export interface Mission {
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

export interface Anomaly {
  event_id: string;
  vision_class: string;
  judgment: string;
  linked_robot_id: string | null;
  recommended_action: string;
  control_action: string;
  alarm_text: string;
  ack_state: string;
  repeat_count: number;
  // 정지 범위. 없으면(이전 기록·이전 감시 노드) ROBOT 으로 본다.
  stop_scope?: "ROBOT" | "ALL";
}

export interface WorkRequest {
  load_join?: boolean;
  evidence_count?: number;
  wait_reason?: string;
  arm_checked?: boolean;
  request_id: string;
  order_id: string;
  robot_id: string;
  stage: string;
  target: string;
  action: string;
  sku: string;
}

export interface Endpoints {
  publishers?: number;
  subscribers?: number;
  publisher_nodes?: string[];
  subscriber_nodes?: string[];
}

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
  ros: { domain_id?: string; rmw?: string; monitor_site?: string; site_sha256?: string };
  zones: ZoneRow[];
  links: LinkRow[];
  log: LogRow[];
  tasks: TaskRow[];
  routes: Record<string, string[]>;
}

export interface LiveState extends DebugState {
  time: number;
  ready_graph?: {
    request: Endpoints;
    tasks: Endpoints;
    robots: Record<string, { patrol_cmd: Endpoints }>;
  } | null;
  diagnostics?: {
    at: number;
    destination_domain?: number;
    source_domains?: number[];
    links: { robot: string; topic: string; source: number; destination: number; state: string }[];
    warnings: { robot: string; node: string; message: string; age_sec: number }[];
  } | null;
  allocation?: Record<string, string[]>;
  mode: "OBSERVE_ONLY" | "AUTO_HOLD";
  armed: boolean | null;
  fleet_age_sec: number | null;
  robots: RobotView[];
  holds: Record<string, string>;
  missions: Mission[];
  anomalies: Anomaly[];
  work: WorkRequest[];
  adapter: { enabled: boolean; blocked: string };
  allow_mock: boolean;
  commands_enabled: boolean;
}

// 병합 뒤 관제 규칙: 로봇 지정 정지는 그 로봇만 보류하고 armed 는 켜 둔다.
// 로봇 지정 없는 정지는 전 로봇 보류 + armed 꺼짐이다.
// 보류 없이 armed 만 꺼진 것(시작 직후)은 정지로 보지 않는다.
// armed 가 다른 사유로 꺼진 채 한 대만 보류된 것도 전체 정지가 아니다. 전 로봇이 보류이거나
// 정지가 걸린 채 열려 있는 전체 정지 사건(복구 도중 포함)이 있어야 전체 정지로 본다.
const STOP_SENT = /^(PAUSE|ESTOP)_(SENT|ACCEPTED)$/;
export function stopView(
  live:
    | (Pick<LiveState, "armed" | "holds"> & Partial<Pick<LiveState, "robots" | "anomalies">>)
    | null
    | undefined,
) {
  const held = live?.holds ? Object.keys(live.holds) : [];
  const robots = live?.robots ?? [];
  const everyone = robots.length > 0 && robots.every((robot) => held.includes(robot.robot_id));
  const event = (live?.anomalies ?? []).some(
    (row) =>
      row.stop_scope === "ALL" &&
      STOP_SENT.test(row.control_action) &&
      ["UNREAD", "ACKNOWLEDGED"].includes(row.ack_state),
  );
  const all = held.length > 0 && live?.armed === false && (everyone || event);
  return { held, all, blocks: (robot: string) => all || held.includes(robot) };
}

export interface TraceReply {
  orderId: string;
  rows: StageTraceRow[];
  unmatched?: unknown[];
  error?: string;
}

export interface FmsLiveContextType {
  live: LiveState | null;
  offline: boolean;
  lastSuccessAt: number | null;
  error: string | null;
  selectedOrderId: string | null;
  setSelectedOrderId: (id: string | null) => void;
  traceReply: TraceReply | null;
  traceLoading: boolean;
}

const defaultContext: FmsLiveContextType = {
  live: null,
  offline: false,
  lastSuccessAt: null,
  error: null,
  selectedOrderId: null,
  setSelectedOrderId: () => {},
  traceReply: null,
  traceLoading: false,
};

const FmsLiveContext = createContext<FmsLiveContextType>(defaultContext);

export function useFmsLive() {
  return useContext(FmsLiveContext);
}

export function FmsLiveProvider({ children }: { children: React.ReactNode }) {
  const tracing = useLocation().pathname === "/debug/trace";
  const [live, setLive] = useState<LiveState | null>(null);
  const [offline, setOffline] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const [traceReply, setTraceReply] = useState<TraceReply | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch("/api/fms/live_state", {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (!Array.isArray(data?.robots)) throw new Error("모니터 응답 형식 오류");
        if (controller.signal.aborted) return;
        setLive(data);
        setOffline(false);
        setLastSuccessAt(Date.now());
        setError(null);
      } catch (err) {
        if (!controller.signal.aborted) {
          setOffline(true);
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 1000);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!selectedOrderId || !tracing) {
      setTraceReply(null);
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setTraceLoading(true);

    const poll = async () => {
      try {
        const response = await fetch(`/api/fms/orders/${encodeURIComponent(selectedOrderId)}/trace`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (data.order_id !== selectedOrderId || !Array.isArray(data.trace)) {
          throw new Error("주문 추적 응답 불일치");
        }
        if (controller.signal.aborted) return;
        setTraceReply({
          orderId: selectedOrderId,
          rows: data.trace,
          unmatched: Array.isArray(data.unmatched_results) ? data.unmatched_results : [],
        });
      } catch (err) {
        if (!controller.signal.aborted) {
          setTraceReply({
            orderId: selectedOrderId,
            rows: [],
            error: err instanceof Error ? err.message : String(err),
          });
        }
      } finally {
        if (!controller.signal.aborted) setTraceLoading(false);
        if (!controller.signal.aborted) {
          timer = setTimeout(() => void poll(), 1000);
        }
      }
    };

    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [selectedOrderId, tracing]);

  return (
    <FmsLiveContext.Provider
      value={{
        live,
        offline,
        lastSuccessAt,
        error,
        selectedOrderId,
        setSelectedOrderId,
        traceReply: traceReply?.orderId === selectedOrderId ? traceReply : null,
        traceLoading: traceLoading || (!!selectedOrderId && traceReply?.orderId !== selectedOrderId),
      }}
    >
      {children}
    </FmsLiveContext.Provider>
  );
}
