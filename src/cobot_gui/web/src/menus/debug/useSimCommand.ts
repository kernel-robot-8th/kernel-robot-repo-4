import { useState } from "react";
import { useFmsLive } from "@/lib/fmsLiveContext";

export function useSimCommand() {
  const { live, offline } = useFmsLive();
  const [message, setMessage] = useState("");
  const allowed = !offline && !!live?.commands_enabled && ["77", "140"].includes(live.ros.domain_id ?? "");
  async function send(path: string, body: unknown) {
    if (!allowed) return;
    try {
      const response = await fetch(`/api/fms/${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await response.json();
      setMessage(response.ok ? `완료: ${path}` : `거절 ${response.status}: ${data.detail ?? path}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "관제 요청 실패");
    }
  }
  return { live, allowed, send, message };
}
