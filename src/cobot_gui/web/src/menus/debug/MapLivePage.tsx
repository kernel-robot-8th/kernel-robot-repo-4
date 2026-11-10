import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useFmsLive, type RobotView } from "@/lib/fmsLiveContext";
import { MAP_STREAM_URL, robotAgeSec, useMapView, type MapCamera } from "./useMapView";

// 모니터가 보내지만 RobotView 형식에는 아직 없는 주행 항목.
type DrivingRobot = RobotView & {
  driving?: boolean | null;
  speed_mps?: number | null;
  waypoint?: string | null;
  updated_at?: number | null;
};

/** 로봇 값이 이 시간(초)보다 오래되면 수신 끊김으로 본다. */
const ROBOT_STALE_SEC = 5;

const MARKER_TEXT: Record<string, string> = {
  OK: "마커 4개 인식",
  FIXED: "마커 일부로 보정",
  HOLD: "마커 가림 (직전 영역 유지)",
  CONFLICT: "마커 불일치 (영상 가림)",
  LOST: "마커 인식 실패 (영상 가림)",
};

const OP_TEXT: Record<string, string> = {
  OFFLINE: "연결 없음",
  IDLE: "대기",
  MOVING: "주행 중",
  DRIVING: "주행 중",
  WORKING: "작업 중",
  WAITING: "대기열 대기",
  CHARGING: "충전 중",
  HOLD_ANOMALY: "이상 정지",
  ERROR: "오류",
};

function fixed(value: number | null | undefined, digits: number, unit = ""): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "-";
}

function cameraNotice(camera: MapCamera | null, down: boolean): string | null {
  if (!camera) return down ? "영상 뷰어에 연결하지 못했습니다" : "맵 영역 카메라가 뷰어에 없습니다";
  if (camera.state !== "running") return `카메라가 멈춰 있습니다 (${camera.state})`;
  if (!camera.connected || camera.stale) return "폰 영상이 들어오지 않습니다";
  return null;
}

function RobotCard({ robot, serverTime, offline }: { robot: DrivingRobot; serverTime: number | undefined; offline: boolean }) {
  const age = robotAgeSec(robot, serverTime);
  const lost = offline || robot.op_state === "OFFLINE" || age === null || age > ROBOT_STALE_SEC;
  const moving = !lost && robot.driving === true;
  return (
    <Card className={lost ? "border-zinc-800 opacity-70" : moving ? "border-emerald-700" : "border-zinc-700"}>
      <CardHeader className="flex flex-row items-center justify-between gap-2 p-3 pb-1">
        <CardTitle className="font-mono text-sm text-white">{robot.robot_id}</CardTitle>
        <Badge
          variant="outline"
          className={
            lost
              ? "border-red-700 text-red-400"
              : moving
                ? "border-emerald-600 text-emerald-400"
                : "border-zinc-600 text-zinc-300"
          }
        >
          {lost ? "수신 끊김" : moving ? "주행 중" : "정지"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-1 p-3 pt-1 text-xs text-zinc-300">
        <dl className="grid grid-cols-[5.5rem_1fr] gap-x-2 gap-y-0.5">
          <dt className="text-zinc-500">주행 상태</dt>
          <dd>
            {OP_TEXT[robot.op_state] ?? robot.op_state} <span className="font-mono text-zinc-500">{robot.op_state}</span>
          </dd>
          <dt className="text-zinc-500">속도</dt>
          <dd className="font-mono">{lost ? "-" : fixed(robot.speed_mps, 2, " m/s")}</dd>
          <dt className="text-zinc-500">임무 단계</dt>
          <dd>{robot.stage ? `${robot.step_seq}. ${robot.stage}` : "임무 없음"}</dd>
          <dt className="text-zinc-500">주문</dt>
          <dd className="font-mono">{robot.order_id ?? "-"}</dd>
          <dt className="text-zinc-500">현재 구역</dt>
          <dd className="font-mono">
            {lost ? "-" : robot.zone}
            {!lost && robot.waypoint ? ` → ${robot.waypoint}` : ""}
          </dd>
          <dt className="text-zinc-500">적재</dt>
          <dd>{lost ? "미확인" : robot.cargo_state}</dd>
          <dt className="text-zinc-500">배터리</dt>
          <dd className="font-mono">{fixed(robot.battery_percent, 0, " %")}</dd>
          <dt className="text-zinc-500">마지막 수신</dt>
          <dd className="font-mono">{age === null ? "수신한 적 없음" : `${age.toFixed(1)}초 전`}</dd>
        </dl>
      </CardContent>
    </Card>
  );
}

export default function MapLivePage() {
  const { live, offline } = useFmsLive();
  const view = useMapView();
  const [attempt, setAttempt] = useState(0);
  const [streamError, setStreamError] = useState(false);
  const camera = view.camera;
  const notice = cameraNotice(camera, view.down);
  const robots = (live?.robots ?? []) as DrivingRobot[];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            <span className="font-mono text-cyan-400">7.</span> 맵 실시간 화면
          </h1>
          <p className="text-xs text-zinc-400">
            천장 영상에서 마커 4개 안쪽(맵 영역)만 잘라 보여 줍니다. 박스 인식 결과와 로봇 주행 상태를 함께 봅니다 (읽기 전용)
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            variant="outline"
            className={view.down || !camera ? "border-red-600 text-red-400" : "border-emerald-600 text-emerald-400"}
          >
            {view.down ? "뷰어 연결 끊김" : camera ? "뷰어 연결됨" : "뷰어 확인 중"}
          </Badge>
          {camera && (
            <Badge
              variant="outline"
              className={camera.visible ? "border-emerald-600 text-emerald-400" : "border-amber-600 text-amber-400"}
            >
              {MARKER_TEXT[camera.markerState] ?? camera.markerState}
            </Badge>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section className="space-y-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-400">맵 영역 영상</h2>
          <div className="relative flex min-h-64 items-center justify-center border border-zinc-800 bg-black">
            {notice || streamError ? (
              <div className="p-6 text-center text-sm text-zinc-400">
                <p>{notice ?? "영상 연결이 끊겼습니다 (시청자 4명 초과이거나 뷰어가 재시작됐습니다)"}</p>
                {!notice && (
                  <button
                    type="button"
                    className="mt-3 border border-zinc-600 px-3 py-1 text-xs text-zinc-200 hover:bg-zinc-800"
                    onClick={() => {
                      setStreamError(false);
                      setAttempt((value) => value + 1);
                    }}
                  >
                    다시 연결
                  </button>
                )}
              </div>
            ) : (
              <img
                key={attempt}
                src={`${MAP_STREAM_URL}?n=${attempt}`}
                alt="마커 안쪽 맵 영역 실시간 영상"
                className="max-h-[75vh] w-full object-contain"
                onError={() => setStreamError(true)}
              />
            )}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-zinc-300 md:grid-cols-4">
            <div>
              <dt className="text-zinc-500">마커</dt>
              <dd className="font-mono">{camera ? `${fixed(camera.markersSeen, 0)}/4 ${camera.markerState}` : "-"}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">수신</dt>
              <dd className="font-mono">{fixed(camera?.fpsReceived, 1, " fps")}</dd>
            </div>
            <div>
              <dt className="text-zinc-500">추론</dt>
              <dd className="font-mono">
                {fixed(camera?.fpsProcessed, 1, " fps")} · {fixed(camera?.detectMs, 0, " ms")}
              </dd>
            </div>
            <div>
              <dt className="text-zinc-500">프레임 나이</dt>
              <dd className="font-mono">{fixed(camera?.frameAgeSec, 1, "초")}</dd>
            </div>
          </dl>
          <div className="text-xs text-zinc-300">
            <p className="text-zinc-500">
              맵 안 인식 {camera ? camera.detections.length : "-"}건 · 맵 밖이라 뺀 누계 {fixed(camera?.droppedOutside, 0)}건
              {view.model ? ` · 모델 ${view.model}` : ""}
            </p>
            {camera && camera.detections.length > 0 && (
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {camera.detections.map((item, index) => (
                  <li key={`${item.event_type}-${index}`} className="border border-zinc-700 px-1.5 py-0.5 font-mono">
                    {item.event_type} {item.confidence.toFixed(2)}
                  </li>
                ))}
              </ul>
            )}
            {view.down && view.error && <p className="mt-1 text-red-400">뷰어 조회 실패: {view.error}</p>}
          </div>
        </section>

        <section className="space-y-2">
          <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-400">로봇 주행 상태</h2>
          {offline && <p className="text-xs text-red-400">관제 모니터 응답이 없습니다. 아래 값은 마지막으로 받은 값입니다.</p>}
          <div className="grid grid-cols-1 gap-3">
            {robots.map((robot) => (
              <RobotCard key={robot.robot_id} robot={robot} serverTime={live?.time} offline={offline} />
            ))}
            {robots.length === 0 && (
              <div className="border border-dashed border-zinc-800 p-6 text-center text-sm text-zinc-500">
                로봇 상태 수신 대기 중...
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
