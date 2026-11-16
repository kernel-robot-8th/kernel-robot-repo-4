import OrderHistory from "./OrderHistory";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useFmsLive } from "@/lib/fmsLiveContext";
import OrderStageTrace from "@/menus/6_5/OrderStageTrace";

export default function OrderTracePage() {
  const { live, selectedOrderId, setSelectedOrderId, traceReply, traceLoading } = useFmsLive();

  const missions = live?.missions ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            <span className="font-mono text-cyan-400">2.</span> 주문 19단계 실행 추적 및 생명주기 로깅
          </h1>
          <p className="text-xs text-zinc-400">
            배송 주문별 19개 동작과 도킹 보정(3a/11a)·재시도, 5대 체크포인트(요청 &rarr; 수신 &rarr; 결과 &rarr; 수용 &rarr; 진입) 전수 로깅
          </p>
        </div>
        {selectedOrderId && (
          <Badge variant="outline" className="border-cyan-600 text-cyan-300 font-mono">
            선택된 주문: {selectedOrderId}
          </Badge>
        )}
      </div>

      {/* 주문 선택 바 */}
      <Card className="rounded-none border-border bg-[#121316]">
        <CardHeader className="p-3 border-b border-border flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-xs font-bold text-white tracking-wide">
            주문 선택 ({missions.length})
          </CardTitle>
          <span className="text-[11px] text-zinc-400">
            주문을 클릭하면 해당 주문의 19단계 시퀀스와 실측 증거가 펼쳐집니다.
          </span>
        </CardHeader>
        <CardContent className="p-3">
          {missions.length === 0 ? (
            <div className="p-4 text-center text-xs text-zinc-500 font-mono">
              현재 등록된 주문이 없습니다. 1번(실시간 실행·배정 현황) 메뉴에서 시나리오 출고를 요청할 수 있습니다.
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {missions.map((m) => (
                <button
                  key={m.mission_id}
                  type="button"
                  onClick={() => setSelectedOrderId(m.mission_id)}
                  className={`text-left px-3 py-1.5 text-xs font-mono border transition-colors ${
                    selectedOrderId === m.mission_id
                      ? "border-cyan-400 bg-[#1c2a38] text-white font-bold"
                      : "border-border bg-[#181a1f] text-zinc-300 hover:border-zinc-500"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-bold">{m.mission_id}</span>
                    <Badge variant="outline" className="text-[10px] px-1 py-0">
                      {m.robot_id ?? "미배정"}
                    </Badge>
                    <span className="text-zinc-400">{m.current_step_code}</span>
                    <span
                      className={
                        m.mission_state === "COMPLETED"
                          ? "text-emerald-400 font-bold"
                          : m.mission_state === "FAILED"
                            ? "text-red-400 font-bold"
                            : "text-cyan-300 font-bold"
                      }
                    >
                      [{m.mission_state}]
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {selectedOrderId && <OrderHistory key={selectedOrderId} orderId={selectedOrderId} />}
      {/* 주문 19단계 추적 패널 */}
      {selectedOrderId ? (
        traceLoading && !traceReply ? (
          <div className="border border-border bg-[#121316] p-8 text-center text-xs text-zinc-400 font-mono">
            주문 {selectedOrderId} 추적 기록 조회 중...
          </div>
        ) : traceReply?.error ? (
          <div className="border border-red-700 bg-red-950/60 p-4 text-xs text-red-200 font-mono" role="status">
            주문 추적 조회 실패: {traceReply.error}
          </div>
        ) : (
          <OrderStageTrace
            key={selectedOrderId}
            orderId={selectedOrderId}
            trace={traceReply?.rows ?? []}
            unmatched={traceReply?.unmatched}
          />
        )
      ) : (
        <div className="border border-dashed border-zinc-800 bg-[#121316]/50 p-8 text-center text-xs text-zinc-500">
          위 주문 목록에서 주문을 선택하면 19단계 동작, 도킹 보정 및 5대 체크포인트 생명주기가 표시됩니다.
        </div>
      )}
    </div>
  );
}
