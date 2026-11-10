import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import FeedbackPanel from "@/components/feedback/FeedbackPanel";
import { FmsLiveProvider, useFmsLive } from "@/lib/fmsLiveContext";

function MonitorBanner() {
  const { live, offline, lastSuccessAt, error } = useFmsLive();
  if (!offline) return live ? null : <p role="status">모니터 첫 응답 대기</p>;
  return (
    <div className="mb-4 rounded-none border border-red-700 bg-red-950/80 p-2.5 text-xs text-red-200">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse" />
          <span className="font-bold text-red-400">monitor_node(:8083) 연결 끊김</span>
          <span className="text-zinc-400">
            마지막 정상 응답: {lastSuccessAt ? new Date(lastSuccessAt).toLocaleTimeString() : "없음"}
          </span>
          {error && <span className="font-mono text-red-300">({error})</span>}
        </div>
        <span className="text-[11px] text-zinc-400 font-mono">
          /api/fms/live_state 프록시 연결 확인 필요
        </span>
      </div>
    </div>
  );
}

export default function Layout() {
  return (
    <FmsLiveProvider>
      <div className="min-h-screen bg-background text-foreground">
        <Sidebar />
        <main className="min-h-screen px-4 pb-10 pt-16 lg:ml-72 lg:px-6 lg:py-6 xl:mr-96">
          <MonitorBanner />
          <Outlet />
        </main>
        <FeedbackPanel />
      </div>
    </FmsLiveProvider>
  );
}
