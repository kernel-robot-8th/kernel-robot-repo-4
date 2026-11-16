import { useEffect, useState } from "react";

interface WirePage {
  order_id: string;
  next_cursor: number | null;
  events: { id: number; at: number; kind: string; request_id: string; payload: Record<string, unknown> }[];
}

export default function OrderHistory({ orderId }: { orderId: string }) {
  const [open, setOpen] = useState(false);
  const [cursors, setCursors] = useState([0]);
  const [version, setVersion] = useState(0);
  const [page, setPage] = useState<WirePage | null>(null);
  const [error, setError] = useState("");
  const after = cursors[cursors.length - 1];
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    async function read() {
      setPage(null); setError("");
      try {
        const res = await fetch(`/api/fms/orders/${encodeURIComponent(orderId)}/history?after=${after}`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.order_id !== orderId || !Array.isArray(data.events)) throw new Error("원문 응답 불일치");
        if (!controller.signal.aborted) setPage(data);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "원문 조회 실패");
      }
    }
    void read();
    return () => controller.abort();
  }, [open, orderId, after, version]);
  return <section className="space-y-2 border border-border p-3">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>SQLite 주문 원문 이력</button>
    {open && <div className="space-y-2 overflow-x-auto">
      {error ? <p role="alert">{error}</p> : !page ? <p>원문 조회 중</p> : page.events.length === 0 ?
        <p>저장된 주문 요청·응답 없음</p> : <table className="w-full text-left text-xs">
          <thead><tr>{["수신 시각", "종류", "요청 ID", "단계", "관제 RTT", "원문"].map(h => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{page.events.map(e => <tr key={e.id}><td>{new Date(e.at * 1000).toISOString()}</td>
            <td>{e.kind}</td><td>{e.request_id}</td><td>{String(e.payload.stage ?? "미기록")}</td>
            <td>{e.kind === "control_reply" && typeof e.payload.rtt_ms === "number" ? e.payload.rtt_ms + " ms" : "미측정"}</td>
            <td><details><summary>열람</summary><pre>{JSON.stringify(e.payload, null, 2)}</pre></details></td></tr>)}</tbody>
        </table>}
      <div className="flex gap-3">
        <button disabled={cursors.length < 2} onClick={() => setCursors(c => c.slice(0, -1))}>이전 원문</button>
        <button disabled={page?.next_cursor == null} onClick={() => { if (page?.next_cursor != null) setCursors(c => [...c, page.next_cursor!]); }}>다음 원문</button>
        <button onClick={() => setVersion(v => v + 1)}>다시 읽기</button>
      </div>
    </div>}
  </section>;
}
