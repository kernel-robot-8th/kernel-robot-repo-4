import VisionControls from "./VisionControls";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useFmsLive } from "@/lib/fmsLiveContext";

interface Frame {
  stream_epoch: string;
  frame_seq: number;
  replay_rec?: string;
  replay_frame?: string;
  capture_time_rel?: number;
  zones: Record<string, string>;
}

function readFrames(text: string): Frame[] {
  return text.split(/\r?\n/).filter(line => line.trim()).map((line, index) => {
    const value = JSON.parse(line);
    if (typeof value?.stream_epoch !== "string" || !Number.isInteger(value.frame_seq)
        || !value.zones || typeof value.zones !== "object" || Array.isArray(value.zones)
        || !Object.values(value.zones).every(state => typeof state === "string")) {
      throw new Error(`${index + 1}행의 녹화 구역 증거 형식 오류`);
    }
    return value;
  });
}

function RecordingReview() {
  const [frames, setFrames] = useState<Frame[]>([]);
  const [index, setIndex] = useState(0);
  const [zone, setZone] = useState("ZA");
  const [truth, setTruth] = useState("");
  const [robot, setRobot] = useState("");
  const [order, setOrder] = useState("");
  const [error, setError] = useState("");
  const version = useRef(0);
  const frame = frames[index];
  const prediction = frame?.zones[zone];
  async function select(file?: File) {
    const current = ++version.current;
    setFrames([]); setIndex(0); setTruth(""); setOrder(""); setRobot(""); setError("");
    if (!file) return;
    try {
      const parsed = readFrames(await file.text());
      if (!parsed.length) throw new Error("녹화 표본이 없습니다");
      if (current === version.current) setFrames(parsed);
    } catch (err) {
      if (current === version.current) setError(err instanceof Error ? err.message : "파일 오류");
    }
  }
  function changeFrame(next: number) {
    setIndex(next); setTruth(""); setOrder(""); setRobot("");
  }
  return <section className="space-y-3 rounded border border-border p-4">
    <h2>주행 녹화와 YOLO 판정 대조</h2>
    <label>녹화 추론 JSONL <input type="file" accept=".jsonl" onChange={e => void select(e.target.files?.[0])}/></label>
    {error && <p role="alert">{error}</p>}
    {frame && <>
      <div>녹화 {frame.replay_rec ?? frame.stream_epoch} · {frame.stream_epoch} · 프레임 {frame.replay_frame ?? frame.frame_seq} · 순번 {frame.frame_seq} · 상대 시각 {frame.capture_time_rel ?? "미기록"}</div>
      <label>표본 행 (1–{frames.length}) <input type="number" min={1} max={frames.length} value={index + 1}
        onChange={e => { const n = e.target.valueAsNumber; if (Number.isInteger(n) && n >= 1 && n <= frames.length) changeFrame(n - 1); }}/></label>
      <label>관측 구역 <select value={zone} onChange={e => { setZone(e.target.value); changeFrame(index); }}>
        {["ZA", "ZB", "ZC"].map(z => <option key={z}>{z}</option>)}
      </select></label>
      <p>모델 판정 {prediction ?? "미기록"}</p>
      <label>영상으로 확인한 호기 <input value={robot} onChange={e => setRobot(e.target.value)} placeholder="미확인"/></label>
      <label>대조한 주문 ID <input value={order} onChange={e => setOrder(e.target.value)} placeholder="미확인"/></label>
      <label>영상 정답 <select value={truth} onChange={e => setTruth(e.target.value)}>
        <option value="">미확인</option><option value="EMPTY">빈 차</option><option value="LOADED">적재</option>
      </select></label>
      <p>대조 결과 {!truth || !prediction ? "판정 대기" : prediction === truth ? "일치" : "불일치"}</p>
      <small>현재 표본을 화면에서만 대조합니다. 구역 모델은 호기를 식별하지 않습니다.</small>
    </>}
  </section>;
}

export default function VisionAnomalyPage() {
  const { live, offline } = useFmsLive();
  const loads = live?.work.filter(w => w.stage === "VERIFY_LOAD") ?? [];
  return <div className="space-y-5">
    <h1 className="text-lg font-bold">4. 비전 적재 판정·이상 감지 로그</h1>
    <section className="space-y-2 border border-border p-4">
      <h2>7번 적재 검증 대기</h2>
      {offline || !live ? <p>모니터 미수신</p> : loads.length ? loads.map(w =>
        <p key={w.request_id}>{w.order_id} · {w.robot_id} · {w.request_id} · 표본 {w.evidence_count ?? "미기록"}/3 ·
          팔 퇴피 {w.arm_checked === true ? "확인" : "미확인"} · {w.wait_reason || "사유 미기록"}</p>
      ) : <p>{live.adapter.enabled ? "현재 대기 목록에 7번 요청 없음" : "수동 어댑터 꺼짐 · 대기 표본 미수집"}</p>}
      <Link to="/debug/trace">주문별 완료 증거 열기</Link>
    </section>
    <section className="space-y-2 border border-border p-4">
      <h2>CCTV 이상 기록</h2>
      {offline || !live ? <p>모니터 미수신</p> : !live.anomalies.length ? <p>저장된 이상 기록 없음</p> :
        live.anomalies.map(a => <p key={a.event_id}>{a.event_id} · {a.linked_robot_id ?? "호기 미확인"} ·
          {a.judgment} · {a.alarm_text || a.vision_class} · {a.ack_state} · {a.control_action}</p>)}
    </section>
    <VisionControls />
    <RecordingReview />
  </div>;
}
