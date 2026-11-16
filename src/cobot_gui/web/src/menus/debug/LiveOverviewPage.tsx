import OrderControls from "./OrderControls";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { stopView, useFmsLive, type RobotView } from "@/lib/fmsLiveContext";

const STEP_LABELS = ["이동", "접안", "상차", "운송", "접안", "하차", "복귀"];

function cargoClass(cargo: string) {
  if (cargo === "EMPTY") return "border-zinc-600 text-zinc-400";
  if (cargo === "LOADED") return "border-emerald-600 text-emerald-400";
  return "border-amber-600 text-amber-400";
}

function RobotCard({
  robot,
  ages,
  onSelectOrder,
  reasons,
}: {
  robot: RobotView;
  ages?: Record<string, number>;
  onSelectOrder?: (orderId: string) => void;
  reasons?: string[];
}) {
  return (
    <div
      className={`border border-border p-3 space-y-2 bg-[#16171b] ${
        robot.order_id ? "cursor-pointer hover:border-cyan-500 transition-colors" : ""
      }`}
      onClick={() => {
        if (robot.order_id && onSelectOrder) onSelectOrder(robot.order_id);
      }}
    >
      <div className="flex items-center justify-between gap-2 text-xs font-bold text-white">
        <span className="flex items-center gap-1.5">
          <span className="text-cyan-400">{robot.robot_id}</span>
          {robot.order_id && (
            <span className="text-[10px] text-zinc-400 font-mono">[{robot.order_id}]</span>
          )}
        </span>
        <span className="flex items-center gap-1">
          <Badge variant="outline" className={cargoClass(robot.cargo_state)}>
            {robot.op_state === "OFFLINE" ? "적재 미확인" : robot.cargo_state}
          </Badge>
          {robot.op_state === "HOLD_ANOMALY" && (
            <Badge variant="outline" className="border-red-600 text-red-400 bg-red-950/40">
              HOLD
            </Badge>
          )}
        </span>
      </div>

      <div className="grid grid-cols-7 gap-1" aria-label={`${robot.robot_id} 7단계 진행`}>
        {STEP_LABELS.map((label, index) => (
          <span
            key={index}
            className={`text-center text-[10px] py-1 font-medium ${
              index + 1 === robot.step_seq
                ? "bg-cyan-700 text-white font-bold"
                : index + 1 < robot.step_seq
                  ? "bg-[#2a2d35] text-zinc-300"
                  : "bg-[#1c1d22] text-zinc-600"
            }`}
          >
            {label}
          </span>
        ))}
      </div>

      <div className="font-mono text-[10px] text-zinc-400 flex flex-wrap gap-x-2 gap-y-0.5">
        <span>상태: <b className="text-white">{robot.op_state}</b></span>
        <span>구역: <b className="text-white">{robot.op_state === "OFFLINE" ? "미확인" : robot.zone}</b></span>
        <span>배터리: {typeof robot.battery_percent === "number" ? `${robot.battery_percent}% (${ages?.battery?.toFixed(1) ?? "?"}초 전)` : "미수신"}</span>
        <span>정지 래치: {typeof robot.central_latched === "boolean" ? `${robot.central_latched ? "잠김" : "해제"} (${ages?.patrol_status?.toFixed(1) ?? "?"}초 전)` : "미확인"}</span>
        <span>모터 전원: 미계측</span>
        <span>단계: <b className="text-white">{robot.stage ?? "대기"}</b></span>
        <span>
          좌표:{" "}
          {robot.pose_x !== null && robot.pose_y !== null
            ? `(${robot.pose_x.toFixed(2)}, ${robot.pose_y.toFixed(2)})`
            : "미수신"}
        </span>
      </div>

      {reasons && reasons.length > 0 && (
        <div className="text-[10px] text-amber-400 bg-amber-950/30 p-1 border border-amber-900/60 rounded-none">
          배정 대기 사유: {reasons.join(", ")}
        </div>
      )}
    </div>
  );
}

export default function LiveOverviewPage() {
  const { live, offline, selectedOrderId, setSelectedOrderId } = useFmsLive();

  const fleetStale = !live || live.fleet_age_sec == null || live.fleet_age_sec > 5;
  const { held, all: allStopped } = stopView(live);
  const stopped = held.length > 0;
  const armUnknown = fleetStale || offline || live?.armed == null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            <span className="font-mono text-cyan-400">1.</span> 실시간 실행·배정 현황
          </h1>
          <p className="text-xs text-zinc-400">
            시나리오 7단계 E2E 진행 상태, 호기별 배정 가능 조건(P7/P8), 주문 배정 상태
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            variant="outline"
            className={fleetStale || offline ? "border-red-600 text-red-400" : "border-emerald-600 text-emerald-400"}
          >
            {fleetStale || offline ? "관제 수신 끊김" : "관제 수신 중"}
          </Badge>
          <Badge
            variant="outline"
            className={
              !armUnknown && allStopped
                ? "border-red-600 text-red-400"
                : live?.armed ? "border-emerald-600 text-emerald-400" : "border-zinc-600 text-zinc-400"
            }
          >
            {armUnknown
              ? "가동 상태 미확인"
              : allStopped
                ? "전체 정지 (가동 꺼짐)"
                : live?.armed ? "가동 허용됨" : "가동 대기 (Unarmed)"}
          </Badge>
          {!armUnknown && stopped && !allStopped && (
            <Badge variant="outline" className="border-amber-600 text-amber-400">
              일부 정지 {held.length}대
            </Badge>
          )}
          <Badge
            variant="outline"
            className={live?.mode === "AUTO_HOLD" ? "border-amber-600 text-amber-400" : "border-zinc-600 text-zinc-400"}
          >
            {live?.mode === "AUTO_HOLD" ? "자동 정지 모드" : "관측 전용 모드"}
          </Badge>
          <Badge
            variant="outline"
            className={live?.commands_enabled ? "border-emerald-600 text-emerald-400" : "border-zinc-600 text-zinc-400"}
          >
            {live?.commands_enabled ? "명령 가능" : "읽기 전용"}
          </Badge>
          {live?.ros?.domain_id && (
            <Badge variant="outline" className="border-cyan-700 text-cyan-300 font-mono">
              도메인 {live.ros.domain_id}
            </Badge>
          )}
        </div>
      </div>

    <OrderControls />
      {stopped && allStopped && (
        <div className="border border-red-700 bg-red-950/60 p-3 text-xs text-red-200">
          <p className="font-bold text-red-300">
            전체 정지 상태 ({held.join(", ")}): 모든 로봇 명령이 거부됩니다. 관제 웹에서 작업 명령을 켠 뒤 4번 메뉴에서 복구합니다.
          </p>
        </div>
      )}
      {stopped && !allStopped && (
        <div className="border border-amber-700 bg-amber-950/40 p-3 text-xs text-amber-200">
          <p className="font-bold text-amber-300">
            로봇 지정 정지 ({held.join(", ")}): 이 로봇 명령만 거부됩니다. 다른 로봇은 계속 동작합니다. 복구는 4번 메뉴에서 합니다.
          </p>
        </div>
      )}

      {/* 로봇 3대 상태 카드 */}
      <section className="space-y-2">
        <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
          로봇별 7단계 실행 현황 (Fleet Overview)
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {(live?.robots ?? []).map((robot) => (
            <RobotCard
              key={robot.robot_id}
              robot={robot} ages={live?.links.find(link => link.robot_id === robot.robot_id)?.ages}
              reasons={live?.allocation?.[robot.robot_id]}
              onSelectOrder={(oid) => setSelectedOrderId(oid)}
            />
          ))}
          {(!live?.robots || live.robots.length === 0) && (
            <div className="col-span-3 p-6 text-center text-sm text-zinc-500 border border-dashed border-zinc-800">
              로봇 상태 수신 대기 중...
            </div>
          )}
        </div>
      </section>

      {/* 활성 주문 목록 바 */}
      {live?.missions && live.missions.length > 0 && (
        <section className="space-y-2 border border-border bg-[#121316] p-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold text-cyan-400 flex items-center gap-1.5">
              <span>주문 목록 ({live.missions.length})</span>
              <span className="text-zinc-500 font-normal">
                · 주문을 선택하면 2번 메뉴(19단계 실행 추적)에서 상세 타임라인을 확인합니다
              </span>
            </h2>
            <Link
              to="/debug/trace"
              className="text-[11px] text-cyan-400 hover:underline font-mono"
            >
              19단계 전체 화면 &rarr;
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {live.missions.map((m) => (
              <button
                key={m.mission_id}
                type="button"
                onClick={() => setSelectedOrderId(m.mission_id)}
                className={`text-left px-2.5 py-1.5 text-xs font-mono border transition-colors ${
                  selectedOrderId === m.mission_id
                    ? "border-cyan-400 bg-[#1c2a38] text-white font-bold"
                    : "border-border bg-[#181a1f] text-zinc-300 hover:border-zinc-500"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span>{m.mission_id}</span>
                  <Badge variant="outline" className="text-[10px] px-1 py-0">
                    {m.robot_id ?? "미배정"}
                  </Badge>
                  <span className="text-zinc-400">{m.current_step_code}</span>
                  <span
                    className={
                      m.mission_state === "COMPLETED"
                        ? "text-emerald-400"
                        : m.mission_state === "FAILED"
                          ? "text-red-400"
                          : "text-cyan-300"
                    }
                  >
                    [{m.mission_state}]
                  </span>
                </div>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* P7 배정 대기 사유 & P8 주문 상태 */}
      <section className="space-y-2">
        <Card className="rounded-none border-border bg-[#121316]">
          <CardHeader className="p-3 border-b border-border">
            <CardTitle className="text-xs font-bold text-white tracking-wide">
              P7 배정 대기 사유 & P8 주문 상태
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3 space-y-2 text-xs">
            <div className="space-y-1">
              <span className="font-bold text-zinc-400">대기 중인 주문 (WAITING):</span>
              {live?.missions.filter((m) => m.mission_state === "WAITING").length === 0 ? (
                <p className="text-zinc-500 font-mono text-[11px]">대기 중인 주문 없음</p>
              ) : (
                live?.missions
                  .filter((m) => m.mission_state === "WAITING")
                  .map((m) => (
                    <div key={m.mission_id} className="font-mono text-amber-300">
                      • 주문 {m.mission_id} ({m.route})
                    </div>
                  ))
              )}
            </div>

            <div className="border-t border-border/60 pt-2 space-y-1">
              <span className="font-bold text-zinc-400">호기별 배정 대기 사유:</span>
              {live?.allocation ? (
                Object.entries(live.allocation).map(([robot, reasons]) => (
                  <div key={robot} className="font-mono text-[11px] text-zinc-300">
                    <span className="text-white font-bold">{robot}</span>:{" "}
                    {reasons.length > 0 ? (
                      <span className="text-amber-400">{reasons.join(" / ")}</span>
                    ) : (
                      <span className="text-emerald-400">배정 가능 (조건 통과)</span>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-zinc-500 font-mono text-[11px]">배정 진단 정보 수신 대기</p>
              )}
            </div>
          </CardContent>
        </Card>

      </section>

      {/* 수동 개입/시험 도구 바로가기 안내 */}
      <div className="border border-zinc-800 bg-[#141518] p-3 flex items-center justify-between text-xs text-zinc-400">
        <span>
          시나리오 주문 수동 생성, 3D 가상환경 시험장 및 E-Stop 조작은 <b>5. 시뮬레이션·수동 보조 도구</b> 메뉴에서 수행할 수 있습니다.
        </span>
        <Link
          to="/debug/sim-tools"
          className="text-cyan-400 hover:underline font-mono shrink-0 ml-2"
        >
          5번 시뮬 도구 바로가기 &rarr;
        </Link>
      </div>
    </div>
  );
}
