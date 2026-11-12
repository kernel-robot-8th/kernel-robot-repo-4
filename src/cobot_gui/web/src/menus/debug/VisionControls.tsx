import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useSimCommand } from "./useSimCommand";
import { stopView, type WorkRequest, type Mission } from "@/lib/fmsLiveContext";
const BUTTON = "h-7 text-[10px] rounded-none bg-[#1c1d22] border-border text-[#dddddd]";
const INPUT = "h-7 px-1.5 text-[10px] bg-[#1c1d22] border border-border text-white";
function LoadApproval({
  work,
  operator,
  enabled,
  send,
}: {
  work: WorkRequest;
  operator: string;
  enabled: boolean;
  send: (path: string, body: unknown) => Promise<void>;
}) {
  const [manual, setManual] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [safe, setSafe] = useState(false);
  const [reason, setReason] = useState("");
  const path = `work/${work.request_id}`;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span>
        적재 근거 {work.evidence_count ?? 0}/3 · {work.wait_reason}
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={!enabled}
        onClick={() => void send(path, { decision: "confirm_arm", operator })}
      >
        팔 퇴피 확인
      </Button>
      <Button size="sm" variant="outline" disabled={!enabled} onClick={() => setManual(!manual)}>
        전체 수동 확인
      </Button>
      {manual && (
        <fieldset className="flex flex-wrap items-center gap-2">
          <label>
            <input
              type="checkbox"
              checked={loaded}
              onChange={(e) => setLoaded(e.target.checked)}
            />{" "}
            실제 적재 확인
          </label>
          <label>
            <input
              type="checkbox"
              checked={safe}
              onChange={(e) => setSafe(e.target.checked)}
            />{" "}
            팔 퇴피 확인
          </label>
          <input
            aria-label="수동 전환 사유"
            placeholder="수동 전환 사유"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button
            size="sm"
            disabled={!enabled || !loaded || !safe || !reason.trim()}
            onClick={() =>
              void send(path, {
                decision: "manual_load",
                operator,
                note: reason,
                load_present: loaded,
                arm_safe: safe,
              })
            }
          >
            수동 결과 확정
          </Button>
        </fieldset>
      )}
    </div>
  );
}
const EVIDENCE = [
  { id: "base_stopped", label: "로봇 정지" },
  { id: "arms_safe", label: "팔 퇴피" },
  { id: "cargo_reconciled", label: "화물 확인" },
  { id: "resources_clear", label: "통로·구역 확인" },
] as const;
type EvidenceId = (typeof EVIDENCE)[number]["id"];

export default function VisionControls() {
  const { live, allowed, send, message } = useSimCommand();
  const [operator, setOperator] = useState("");
  const [note, setNote] = useState("");
  const [evidence, setEvidence] = useState<Record<EvidenceId, boolean>>({
    base_stopped: false,
    arms_safe: false,
    cargo_reconciled: false,
    resources_clear: false,
  });
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

  if (!live || !allowed) return null;
  const blocked = live.missions.filter((mission) => mission.recovery);
  const anomalies = live.anomalies.filter(row => ["UNREAD","ACKNOWLEDGED"].includes(row.ack_state));
  const { held, all: allStopped } = stopView(live);
  const releasable = live.robots.filter(
    (robot) => held.includes(robot.robot_id) && !robot.order_id,
  );
  return <details className="border border-border p-3">
    <summary>격리 시뮬 승인·복구</summary>
    <label>운영자 <input aria-label="운영자" value={operator} onChange={e => setOperator(e.target.value)}/></label>
          <section className="space-y-1">
            <h3 className="text-[11px] font-bold text-cyan-400">
              수동 승인 ({live.work.length})
              {live.adapter.blocked && (
                <span className="ml-2 text-red-400">수동 어댑터 꺼짐: {live.adapter.blocked}</span>
              )}
            </h3>
            {live.work.map((work) => (
              <div
                key={work.request_id}
                className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]"
              >
                <span className="font-mono">
                  {work.robot_id} {work.stage} ({work.target}/{work.action})
                </span>
                {work.load_join ? (
                  <LoadApproval
                    work={work}
                    operator={operator}
                    enabled={named && allowed && !live.adapter.blocked}
                    send={send}
                  />
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    className={BUTTON}
                    disabled={!named}
                    onClick={() =>
                      void send(`work/${work.request_id}`, { decision: "approve", operator })
                    }
                  >
                    승인
                  </Button>
                )}
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
              <div
                key={row.event_id}
                className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]"
              >
                <span className="font-mono text-amber-300">{row.judgment}</span>
                <span>{row.linked_robot_id ?? "로봇 미지정"}</span>
                <span>{row.alarm_text || row.vision_class}</span>
                {row.recommended_action !== "NONE" && (
                  <span className={row.stop_scope === "ALL" ? "font-bold text-red-400" : "text-[#888888]"}>
                    정지 범위: {row.stop_scope === "ALL" ? "전체 로봇" : "해당 로봇"}
                  </span>
                )}
                <span className="font-mono text-[#888888]">
                  {row.control_action} x{row.repeat_count}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className={BUTTON}
                  disabled={!named}
                  onClick={() =>
                    void send(`anomalies/${row.event_id}`, {
                      ack_state: "RESOLVED",
                      operator,
                      note,
                    })
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
                    void send(`anomalies/${row.event_id}`, {
                      ack_state: "FALSE_ALARM",
                      operator,
                      note,
                    })
                  }
                >
                  오탐
                </Button>
              </div>
            ))}
          </section>

          {(blocked.length > 0 || releasable.length > 0) && (
            <section className="space-y-1">
              <h3 className="text-[11px] font-bold text-amber-400">복구 요청</h3>
              {allStopped && (
                <div className="border border-red-700 bg-red-950/60 p-2 text-[10px] text-red-200">
                  <p className="font-bold text-red-300">전체 정지 복구 순서</p>
                  <p>1. 관제 웹에서 작업 명령(가동 허용)을 켭니다. 켜기 전에는 재개가 거절됩니다.</p>
                  <p>2. 멈춘 주문을 재개하거나 실패 처리합니다.</p>
                  <p>3. 주문이 없는 로봇은 로봇마다 제어권 반환을 누릅니다.</p>
                </div>
              )}
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
                <div
                  key={mission.mission_id}
                  className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]"
                >
                  <span className="font-mono">
                    {mission.mission_id} {mission.mission_state} {mission.current_stage}
                  </span>
                  {mission.hold_reason && (
                    <span className="text-red-400">{mission.hold_reason}</span>
                  )}
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
              {releasable.map((robot) => (
                <div
                  key={robot.robot_id}
                  className="flex flex-wrap items-center gap-1.5 text-[10px] text-[#cccccc]"
                >
                  <span className="font-mono">
                    {robot.robot_id} 정지 ({live.holds[robot.robot_id]})
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className={BUTTON}
                    disabled={!named || !confirmed}
                    onClick={() =>
                      void send("control", {
                        type: "release_control",
                        robot_id: robot.robot_id,
                        operator,
                        note,
                        evidence,
                      })
                    }
                  >
                    제어권 반환
                  </Button>
                </div>
              ))}
              <div className="text-[9px] text-[#888888]">
                재개는 가동 허용을 켠 뒤 누릅니다. 상·하차 단계는 재개할 수 없어 실패 처리 뒤 새
                주문을 냅니다.
              </div>
            </section>
          )}
    {message && <p role="status">{message}</p>}
  </details>;
}
