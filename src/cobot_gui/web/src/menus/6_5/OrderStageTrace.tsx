// 메뉴 6.5 주문별 19단계 시나리오 타임라인 및 5대 체크포인트 상세 패널
// 관제가 요청을 보냈는지 -> 대상이 받았는지(수신 미확인) -> 결과를 냈는지 -> 관제가 수용했는지(수용 미확인) -> 다음 단계로 넘어갔는지를 한눈에 확인한다.
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export interface Checkpoints {
  requested: boolean;
  received: "CONFIRMED" | "UNCONFIRMED";
  result: "MEASURED" | "JOINED" | "MANUAL" | "NONE" | "TIMEOUT";
  accepted: "ACCEPTED" | "UNCONFIRMED" | "REJECTED" | "WAITING";
  next_stage: boolean;
}

export interface StageTraceRow {
  stage_code: string;
  stage_name: string;
  target: string;
  action: string;
  is_correction: boolean;
  attempt_no: number;
  command_id: string | null;
  request_id: string | null;
  status: "WAITING" | "RUNNING" | "COMPLETED" | "FAILED" | "BLOCKED" | "PREVIOUS" | "SKIPPED";
  checkpoints: Checkpoints;
  evidence_summary: string;
  evidence_detail: Record<string, unknown> | null;
  hold_reason: string | null;
}

interface OrderStageTraceProps {
  orderId: string;
  trace: StageTraceRow[];
  loading?: boolean;
  unmatched?: unknown[];
}

function StatusBadge({ status }: { status: StageTraceRow["status"] }) {
  switch (status) {
    case "PREVIOUS":
      return <Badge variant="outline">이전 시도</Badge>;
    case "COMPLETED":
      return <Badge className="bg-emerald-950 text-emerald-300 border-emerald-700 text-[9px] px-1.5 py-0">완료</Badge>;
    case "RUNNING":
      return <Badge className="bg-cyan-950 text-cyan-300 border-cyan-700 text-[9px] px-1.5 py-0 animate-pulse">진행 중</Badge>;
    case "BLOCKED":
    case "FAILED":
      return <Badge className="bg-red-950 text-red-300 border-red-700 text-[9px] px-1.5 py-0">실패/중단</Badge>;
    default:
      return <Badge className="bg-[#1c1d22] text-zinc-500 border-zinc-800 text-[9px] px-1.5 py-0">대기</Badge>;
  }
}

function CheckpointBadges({ cp }: { cp: Checkpoints }) {
  return (
    <div className="flex items-center gap-1 text-[9px]">
      {/* 1. 요청 */}
      {cp.requested ? (
        <span className="text-emerald-400 bg-[#14231b] px-1 border border-emerald-800">요청생성</span>
      ) : (
        <span className="text-zinc-600 bg-[#16171a] px-1 border border-zinc-800">생성 미확인</span>
      )}

      <span className="text-zinc-600">&rarr;</span>

      {/* 2. 대상 수신 */}
      {cp.received === "CONFIRMED" ? (
        <span className="text-emerald-400 bg-[#14231b] px-1 border border-emerald-800">수신확인</span>
      ) : (
        <span className="text-amber-300 bg-[#291e10] px-1 border border-amber-700 font-bold">수신 미확인</span>
      )}

      <span className="text-zinc-600">&rarr;</span>

      {/* 3. 결과 */}
      {cp.result === "MEASURED" && (
        <span className="text-cyan-300 bg-[#102329] px-1 border border-cyan-800">실측</span>
      )}
      {cp.result === "JOINED" && <span>카메라·운영자</span>}
      {cp.result === "MANUAL" && (
        <span className="text-purple-300 bg-[#231229] px-1 border border-purple-800">수동</span>
      )}
      {cp.result === "TIMEOUT" && (
        <span className="text-red-400 bg-[#2b1114] px-1 border border-red-800 font-bold">시간초과</span>
      )}
      {cp.result === "NONE" && (
        <span className="text-zinc-600 bg-[#16171a] px-1 border border-zinc-800">대기</span>
      )}

      <span className="text-zinc-600">&rarr;</span>

      {/* 4. 관제 수용 */}
      {cp.accepted === "ACCEPTED" && (
        <span className="text-emerald-400 bg-[#14231b] px-1 border border-emerald-800">수용</span>
      )}
      {cp.accepted === "UNCONFIRMED" && (
        <span className="text-amber-300 bg-[#291e10] px-1 border border-amber-700 font-bold">수용 미확인</span>
      )}
      {cp.accepted === "REJECTED" && (
        <span className="text-red-400 bg-[#2b1114] px-1 border border-red-800 font-bold">거절/보류</span>
      )}
      {cp.accepted === "WAITING" && (
        <span className="text-zinc-600 bg-[#16171a] px-1 border border-zinc-800">대기</span>
      )}

      <span className="text-zinc-600">&rarr;</span>

      {/* 5. 다음 단계 */}
      {cp.next_stage ? (
        <span className="text-emerald-400 bg-[#14231b] px-1 border border-emerald-800">진입</span>
      ) : (
        <span className="text-zinc-600 bg-[#16171a] px-1 border border-zinc-800">진입 미확인</span>
      )}
    </div>
  );
}

function timeOf(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Date(value * 1000).toLocaleTimeString() : "미확인";
}

function EvidenceDrawer({ row }: { row: StageTraceRow }) {
  const d = row.evidence_detail;
  if (!d) return null;
  return <div className="mt-1 p-2 bg-[#121316] text-[10px] space-y-1">
    <strong>단계 증거 원문 ({row.stage_code})</strong>
    {row.stage_code === "VERIFY_LOAD" && <>
      <div>운영자: {String(d.operator ?? "미확인")}</div>
      <div>확인 사유: {String(d.note || "미기록")}</div>
      <div>팔 퇴피 확인 시각: {timeOf(d.arm_confirmed_at)}</div>
      {Array.isArray(d.evidence) && <>
        <div>수신된 카메라 적재 표본 ({d.evidence.length}/3개)</div>
        {d.evidence.map((frame: unknown, i: number) => {
          if (!frame || typeof frame !== "object") return null;
          const f = frame as Record<string, unknown>;
          return <div key={i}><span>표본 #{i + 1}</span> · 촬영 {timeOf(f.capture_time)}
            {" · 수신 "}{timeOf(f.received_at)} · {typeof f.frame_age_ms === "number" ? f.frame_age_ms + " ms" : "지연 미기록"}
            {" · "}{f.box_present === true ? "박스 적재 확인" : f.box_present === false ? "박스 미검출" : "박스 판정 미기록"}
            {typeof f.recorded_epoch === "string" && <div>원본 {f.recorded_epoch} · 프레임 {String(f.replay_frame ?? f.frame_seq)}</div>}
          </div>;
        })}
      </>}
    </>}
    {row.stage_code.startsWith("DOCK_") && <>
      <div>위치 오차: {typeof d.xy_m === "number" ? d.xy_m.toFixed(3) + "m" : "미확인"}</div>
      <div>각도 오차: {typeof d.yaw_deg === "number" ? d.yaw_deg.toFixed(1) + "°" : "미확인"}</div>
      <div>정지: {String(d.stopped ?? "미확인")} · 베이스 유지: {String(d.base_hold ?? "미확인")}</div>
    </>}
    <pre className="overflow-auto">{JSON.stringify(d, null, 2)}</pre>
  </div>;
}

export default function OrderStageTrace({ orderId, trace, loading, unmatched = [] }: OrderStageTraceProps) {
  const [expandedStage, setExpandedStage] = useState<string | null>("VERIFY_LOAD");

  return (
    <section className="space-y-2 border border-[#2b2d35] bg-[#16171c] p-2.5">
      <div className="flex items-center justify-between border-b border-[#2b2d35] pb-1.5">
        <div className="flex items-center gap-2">
          <h3 className="text-[11px] font-bold text-cyan-400">
            주문 {orderId} 19단계 동작 및 보정 시도 추적
          </h3>
          {loading && <span className="text-[9px] text-zinc-500 animate-pulse">갱신 중...</span>}
        </div>
        <div className="text-[9px] text-zinc-400">
          5대 관측점: 요청 &rarr; 수신(미확인 구분) &rarr; 결과 &rarr; 관제 수용 &rarr; 다음 단계
        </div>
      </div>

      {unmatched.length > 0 && <details>
        <summary>요청과 연결되지 않은 결과 {unmatched.length}건</summary>
        <pre className="overflow-auto">{JSON.stringify(unmatched, null, 2)}</pre>
      </details>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[10px] border-collapse">
          <thead>
            <tr className="border-b border-[#2a2d35] text-[9px] text-zinc-400 bg-[#121316]">
              <th className="py-1 px-1.5 w-8">상태</th>
              <th className="py-1 px-1.5 w-44">단계명 (대상/동작)</th>
              <th className="py-1 px-1.5 w-72">5대 체크포인트 생명주기</th>
              <th className="py-1 px-1.5">관측 사실 및 완료 증거</th>
              <th className="py-1 px-1.5 w-16 text-right">증거 서랍</th>
            </tr>
          </thead>
          <tbody>
            {trace.map((row) => {
              const key = `${row.stage_code}_${row.request_id ?? row.attempt_no}`;
              const isExpanded = expandedStage === key || (expandedStage === row.stage_code && row.attempt_no === 1);
              const hasDetail = Boolean(row.evidence_detail);

              return (
                <tr
                  key={key}
                  className={`border-b border-[#1f2127] transition-colors ${
                    row.is_correction ? "bg-[#181b22]" : "hover:bg-[#1a1c23]"
                  }`}
                >
                  <td className="py-1 px-1.5 align-top">
                    <StatusBadge status={row.status} />
                  </td>

                  <td className="py-1 px-1.5 align-top">
                    <div className="font-medium text-white flex items-center gap-1">
                      {row.is_correction && <span className="text-amber-400">&lfloor;</span>}
                      <span>{row.stage_name}</span>
                    </div>
                    <div className="font-mono text-[9px] text-zinc-500">
                      {row.target} / {row.action}
                      {row.command_id && ` · cmd:${row.command_id.slice(0, 8)}`}
                      {row.request_id && ` · req:${row.request_id.slice(0, 8)}`}
                    </div>
                  </td>

                  <td className="py-1 px-1.5 align-top">
                    <CheckpointBadges cp={row.checkpoints} />
                  </td>

                  <td className="py-1 px-1.5 align-top">
                    <div className={(row.status === "FAILED" || row.status === "BLOCKED") ? "text-red-400 font-medium" : "text-zinc-300"}>
                      {row.evidence_summary || "-"}
                    </div>
                    {isExpanded && hasDetail && <EvidenceDrawer row={row} />}
                  </td>

                  <td className="py-1 px-1.5 align-top text-right">
                    {hasDetail ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-5 px-1 text-[9px] text-cyan-400 hover:text-cyan-200"
                        onClick={() => setExpandedStage(isExpanded ? null : key)}
                      >
                        {isExpanded ? "닫기" : "열람"}
                      </Button>
                    ) : (
                      <span className="text-[9px] text-zinc-600">-</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
