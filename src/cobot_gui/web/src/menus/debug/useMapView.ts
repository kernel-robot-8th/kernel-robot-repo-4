import { useEffect, useState } from "react";

// 중계 장비 영상 뷰어(:8893 웹 창구)의 상태 응답 중 화면에서 쓰는 항목. 창구는 읽기 전용이고 맵 영역으로 자른 카메라만 내준다.
export interface MapDetection {
  event_type: string;
  confidence: number;
}

export interface MapCamera {
  id: string;
  name: string;
  /** running 이 아니면 영상이 없다. */
  state: string;
  connected: boolean;
  stale: boolean;
  frameAgeSec: number | null;
  fpsReceived: number | null;
  fpsProcessed: number | null;
  detectMs: number | null;
  /** OK·FIXED·HOLD 는 영상이 보이고, CONFLICT·LOST 는 안내 화면으로 가려진다. */
  markerState: string;
  markersSeen: number | null;
  visible: boolean;
  droppedOutside: number | null;
  detections: MapDetection[];
}

export interface MapViewState {
  camera: MapCamera | null;
  model: string | null;
  /** 마지막 조회가 실패했다. camera 는 마지막으로 받은 값을 그대로 둔다. */
  down: boolean;
  error: string | null;
  checkedAt: number | null;
}

export const MAP_CAMERA_ID = "ceiling";
export const MAP_STATE_URL = "/api/mapview/api/state";
export const MAP_STREAM_URL = `/api/mapview/cameras/${MAP_CAMERA_ID}/stream.mjpg`;
export const MAP_PERIOD_MS = 2000;
const TIMEOUT_MS = 4000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** 뷰어 상태 응답에서 맵 카메라 하나를 꺼낸다. 형식이 다른 값은 null 로 바꾼다. 카메라가 없으면 null. */
export function parseMapState(data: unknown): { camera: MapCamera | null; model: string | null } {
  if (!isRecord(data) || !Array.isArray(data.cameras)) throw new Error("뷰어 응답 형식 오류");
  const model = typeof data.model === "string" ? data.model : null;
  const raw = (data.cameras as unknown[]).find((item) => isRecord(item) && item.id === MAP_CAMERA_ID);
  if (!isRecord(raw)) return { camera: null, model };
  const map = isRecord(raw.map) ? raw.map : {};
  const input = isRecord(raw.input) ? raw.input : {};
  const current = Array.isArray(raw.current) ? raw.current.filter(isRecord) : [];
  return {
    model,
    camera: {
      id: MAP_CAMERA_ID,
      name: typeof raw.name === "string" ? raw.name : MAP_CAMERA_ID,
      state: typeof raw.state === "string" ? raw.state : "unknown",
      connected: raw.connected === true,
      stale: raw.stale !== false,
      frameAgeSec: num(raw.frame_age_sec),
      fpsReceived: num(input.fps_received),
      fpsProcessed: num(raw.fps_processed),
      detectMs: num(raw.detect_ms_recent),
      markerState: typeof map.state === "string" ? map.state : "UNKNOWN",
      markersSeen: num(map.markers_seen),
      visible: map.visible === true,
      droppedOutside: num(map.dropped_outside),
      detections: current.flatMap((item) => {
        const confidence = num(item.confidence);
        return typeof item.event_type === "string" && confidence !== null
          ? [{ event_type: item.event_type, confidence }]
          : [];
      }),
    },
  };
}

/** 로봇 값의 나이(초). 모니터 시계끼리만 뺀다. 갱신 시각이 없으면 null. */
export function robotAgeSec(robot: { updated_at?: number | null }, serverTime: number | undefined): number | null {
  if (typeof robot.updated_at !== "number" || typeof serverTime !== "number") return null;
  return Math.max(0, serverTime - robot.updated_at);
}

const INITIAL: MapViewState = { camera: null, model: null, down: false, error: null, checkedAt: null };

/** 뷰어 상태를 2초마다 읽는다 (GET 전용). 앞 요청이 끝난 뒤에만 다음을 예약하고, 탭이 숨겨지면 쉰다. */
export function useMapView(): MapViewState {
  const [state, setState] = useState<MapViewState>(INITIAL);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (!document.hidden) {
        try {
          const response = await fetch(MAP_STATE_URL, {
            signal: AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]),
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const parsed = parseMapState(await response.json());
          if (controller.signal.aborted) return;
          setState({ ...parsed, down: false, error: null, checkedAt: Date.now() });
        } catch (err) {
          if (controller.signal.aborted) return;
          const message = err instanceof Error ? err.message : String(err);
          setState((prev) => ({ ...prev, down: true, error: message, checkedAt: Date.now() }));
        }
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), MAP_PERIOD_MS);
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  return state;
}
