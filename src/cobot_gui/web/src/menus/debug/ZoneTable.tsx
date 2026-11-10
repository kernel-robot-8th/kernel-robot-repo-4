import type { ZoneRow } from "@/lib/fmsLiveContext";

export default function ZoneTable({ zones }: { zones: ZoneRow[] }) {
  return (
    <div className="overflow-x-auto border border-border bg-[#141519]">
      <table className="w-full text-[11px] font-mono">
        <thead className="bg-[#181a20] text-zinc-400 text-left border-b border-border">
          <tr>
            <th className="px-3 py-1.5 font-medium">구역 ID</th>
            <th className="px-3 py-1.5 font-medium">관리자 점유</th>
            <th className="px-3 py-1.5 font-medium">로봇 보고 위치</th>
            <th className="px-3 py-1.5 font-medium">일치 여부</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {zones.length === 0 ? (
            <tr>
              <td colSpan={4} className="p-3 text-center text-zinc-500">
                구역 정보 없음 (관제 기동 후 2~3초 후 갱신됩니다)
              </td>
            </tr>
          ) : (
            zones.map((row) => (
              <tr key={row.zone} className="hover:bg-zinc-800/20">
                <td className="px-3 py-1.5 font-bold text-white">구역 {row.zone}</td>
                <td className="px-3 py-1.5 text-zinc-300">
                  {row.manager_known ? (row.manager ?? "비어 있음") : "미수신"}
                </td>
                <td className="px-3 py-1.5 text-zinc-300">{row.robot ?? "없음"}</td>
                <td className="px-3 py-1.5 font-bold">
                  {row.match === null ? (
                    <span className="text-zinc-500">관리자 값 없음</span>
                  ) : row.match ? (
                    <span className="text-emerald-400">● 일치</span>
                  ) : (
                    <span className="text-red-400">× 불일치 (경고)</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
