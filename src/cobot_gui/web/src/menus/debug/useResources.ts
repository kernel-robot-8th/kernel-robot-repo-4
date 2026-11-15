import { useEffect, useState } from "react";

// 자원 수집기(중계 장비 :8084) 응답 계약. 수집기가 값을 못 얻은 항목은 null 이다.
// 계약과 다른 값(문자열, 누락 등)은 parseLatest 가 null 로 바꾼다. 그래서 숫자 항목은 모두 null 일 수 있다.
export interface CpuInfo {
  cores: number | null;
  used_pct: number | null;
  load1: number | null;
}

export interface MemoryInfo {
  total_mb: number | null;
  used_mb: number | null;
  available_mb: number | null;
}

export interface DiskInfo {
  mount: string;
  total_gb: number | null;
  used_gb: number | null;
  avail_gb: number | null;
  used_pct: number | null;
}

export interface GpuInfo {
  name: string;
  util_pct: number | null;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  temp_c: number | null;
}

export interface ContainerInfo {
  name: string;
  image: string;
  status: string;
  cpu_pct: number | null;
  mem_used_mb: number | null;
  mem_limit_mb: number | null;
  mem_pct: number | null;
}

export interface ResourceHost {
  id: string;
  name: string;
  address: string;
  collected_at: number | null;
  last_attempt_at: number | null;
  ok: boolean;
  error: string | null;
  duration_ms: number | null;
  cpu: CpuInfo | null;
  memory: MemoryInfo | null;
  disk: DiskInfo[];
  gpus: GpuInfo[];
  gpu_note: string | null;
  containers: ContainerInfo[];
  containers_note: string | null;
}

export interface ResourcesLatest {
  schema: number;
  generated_at: number;
  interval_sec: number;
  stale_after_sec: number;
  hosts: ResourceHost[];
  /** 형식이 잘못됐거나 id 가 겹쳐서 버린 장비 항목 수. */
  dropped: number;
}

export interface HistoryPoint {
  t: number;
  cpu: number | null;
  mem: number | null;
  gpu: number | null;
  gpu_mem: number | null;
  gpu_temp: number | null;
}

export interface ResourcesHistory {
  generated_at: number;
  hosts: Record<string, HistoryPoint[]>;
}

export interface ResourcesState {
  /** 마지막으로 정상 수신한 응답. 수집기가 끊겨도 지우지 않는다 (화면에서 회색으로 보인다). */
  latest: ResourcesLatest | null;
  /** generated_at 이 앞 응답과 달라진 응답을 마지막으로 받은 브라우저 시각(ms). 같은 응답이 반복되면 멈춘다. */
  receivedAt: number | null;
  /** 마지막 조회 시도가 끝난 브라우저 시각(ms). 실패해도 갱신된다. */
  checkedAt: number | null;
  /** 마지막 조회 시도가 실패했다. */
  apiDown: boolean;
  error: string | null;
  /** 탭이 숨겨져 조회를 멈춘 상태. 다시 보이면 바로 한 번 읽는다. */
  paused: boolean;
  history: ResourcesHistory | null;
  historyError: string | null;
}

export const LATEST_URL = "/api/resources/latest";
export const HISTORY_URL = "/api/resources/history?minutes=30";
export const LATEST_PERIOD_MS = 5000;
export const HISTORY_PERIOD_MS = 30000;
const TIMEOUT_MS = 4000;
/** 연속 실패가 이 횟수에 이르면 조회 간격을 늘린다 (수집기가 꺼진 동안 프록시 오류 로그를 줄인다). */
export const BACKOFF_AFTER = 3;
export const BACKOFF_PERIOD_MS = 15000;
/** collected_at 이 generated_at 보다 이만큼(초) 넘게 앞서면 시계 이상으로 본다. */
const SKEW_TOLERANCE_SEC = 1;

/** 숫자를 단위와 함께 보인다. null·NaN 은 0 이 아니라 "-" 이다. */
export function fmt(value: number | null | undefined, digits = 1, unit = ""): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${value.toFixed(digits)}${unit}`;
}

/** 사용량 / 전체 를 백분율로. 하나라도 없거나 전체가 0 이면 null. */
export function ratioPct(used: number | null | undefined, total: number | null | undefined): number | null {
  if (typeof used !== "number" || typeof total !== "number") return null;
  if (!Number.isFinite(used) || !Number.isFinite(total) || total <= 0) return null;
  return (used / total) * 100;
}

/** epoch 초를 hh:mm:ss (브라우저 시간대, 24시간제) 로. */
export function clock(epochSec: number | null | undefined): string {
  if (typeof epochSec !== "number" || !Number.isFinite(epochSec)) return "-";
  const date = new Date(epochSec * 1000);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(date.getHours())}:${two(date.getMinutes())}:${two(date.getSeconds())}`;
}

/**
 * 장비 값의 나이(초). 서버 시계끼리만 뺀다 (generated_at - collected_at).
 * 수집기 응답이 끊긴 동안에는 마지막 응답 이후 브라우저에서 흐른 시간을 더한다. 수집한 적이 없으면 null.
 */
export function hostAgeSec(
  latest: ResourcesLatest,
  host: ResourceHost,
  receivedAt: number | null,
  checkedAt: number | null,
): number | null {
  if (typeof host.collected_at !== "number" || !Number.isFinite(host.collected_at)) return null;
  const sinceReceived =
    receivedAt !== null && checkedAt !== null ? Math.max(0, (checkedAt - receivedAt) / 1000) : 0;
  return Math.max(0, latest.generated_at - host.collected_at + sinceReceived);
}

/** collected_at 이 generated_at 보다 앞선 초. 같은 시계라면 일어날 수 없으므로 0 보다 크면 이상값이다. */
export function hostSkewSec(latest: ResourcesLatest, host: ResourceHost): number {
  if (typeof host.collected_at !== "number" || !Number.isFinite(host.collected_at)) return 0;
  const ahead = host.collected_at - latest.generated_at;
  return ahead > SKEW_TOLERANCE_SEC ? ahead : 0;
}

/** 마지막으로 새 응답(generated_at 이 달라진 응답)을 받은 뒤 브라우저에서 흐른 초. */
export function sinceFreshSec(receivedAt: number | null, checkedAt: number | null): number {
  if (receivedAt === null || checkedAt === null) return 0;
  return Math.max(0, (checkedAt - receivedAt) / 1000);
}

/** 조회 실패 사유를 화면용 문구로 바꾼다. */
export function describeError(err: unknown): string {
  const name = (err as { name?: unknown } | null)?.name;
  const message = err instanceof Error ? err.message : String(err);
  if (name === "TimeoutError") return `응답 시간 초과(${TIMEOUT_MS / 1000}초)`;
  if (err instanceof TypeError) return `연결 실패: ${message}`;
  return message;
}

/**
 * 앞 요청이 끝난 뒤에만 다음 요청을 예약한다 (응답이 늦어도 요청이 쌓이지 않는다). 읽기(GET) 전용.
 * 탭이 숨겨져 있으면 읽지 않고, 다시 보이면 바로 한 번 읽는다. 연속 실패 때는 간격을 늘린다.
 */
function startPolling(
  url: string,
  periodMs: number,
  onData: (data: unknown) => void,
  onError: (message: string) => void,
  onPause?: () => void,
): () => void {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let waitingVisible = false;
  let failures = 0;
  const poll = async () => {
    if (document.hidden) {
      waitingVisible = true;
      onPause?.();
      return;
    }
    try {
      const response = await fetch(url, {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data: unknown = await response.json();
      if (controller.signal.aborted) return;
      onData(data);
      failures = 0;
    } catch (err) {
      if (!controller.signal.aborted) {
        failures += 1;
        onError(describeError(err));
      }
    } finally {
      if (!controller.signal.aborted) {
        const waitMs = failures >= BACKOFF_AFTER ? Math.max(periodMs, BACKOFF_PERIOD_MS) : periodMs;
        timer = setTimeout(() => void poll(), waitMs);
      }
    }
  };
  const onVisible = () => {
    if (document.hidden || !waitingVisible || controller.signal.aborted) return;
    waitingVisible = false;
    void poll();
  };
  document.addEventListener("visibilitychange", onVisible);
  void poll();
  return () => {
    controller.abort();
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisible);
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

/** 장비 항목 하나를 계약 형식으로 정리한다. 형식이 다른 값은 null·빈 목록으로 바꿔 화면이 깨지지 않게 한다. */
function parseHost(raw: Record<string, unknown>, id: string): ResourceHost {
  return {
    id,
    name: text(raw.name, id),
    address: text(raw.address, "-"),
    collected_at: num(raw.collected_at),
    last_attempt_at: num(raw.last_attempt_at),
    ok: raw.ok === true,
    error: typeof raw.error === "string" ? raw.error : null,
    duration_ms: num(raw.duration_ms),
    cpu: isRecord(raw.cpu)
      ? { cores: num(raw.cpu.cores), used_pct: num(raw.cpu.used_pct), load1: num(raw.cpu.load1) }
      : null,
    memory: isRecord(raw.memory)
      ? {
          total_mb: num(raw.memory.total_mb),
          used_mb: num(raw.memory.used_mb),
          available_mb: num(raw.memory.available_mb),
        }
      : null,
    disk: records(raw.disk).map((disk) => ({
      mount: text(disk.mount, "-"),
      total_gb: num(disk.total_gb),
      used_gb: num(disk.used_gb),
      avail_gb: num(disk.avail_gb),
      used_pct: num(disk.used_pct),
    })),
    gpus: records(raw.gpus).map((gpu) => ({
      name: text(gpu.name, "-"),
      util_pct: num(gpu.util_pct),
      mem_used_mb: num(gpu.mem_used_mb),
      mem_total_mb: num(gpu.mem_total_mb),
      temp_c: num(gpu.temp_c),
    })),
    gpu_note: typeof raw.gpu_note === "string" ? raw.gpu_note : null,
    containers: records(raw.containers).map((container) => ({
      name: text(container.name, "-"),
      image: text(container.image, "-"),
      status: text(container.status, "-"),
      cpu_pct: num(container.cpu_pct),
      mem_used_mb: num(container.mem_used_mb),
      mem_limit_mb: num(container.mem_limit_mb),
      mem_pct: num(container.mem_pct),
    })),
    containers_note: typeof raw.containers_note === "string" ? raw.containers_note : null,
  };
}

function parseLatest(data: unknown): ResourcesLatest {
  const body = data as Partial<ResourcesLatest> | null;
  if (!body || !Array.isArray(body.hosts) || typeof body.generated_at !== "number") {
    throw new Error("수집기 응답 형식 오류");
  }
  // id 가 문자열인 객체만 장비로 받는다. 같은 id 는 처음 것만 쓴다. 버린 수는 화면에 알린다.
  const hosts: ResourceHost[] = [];
  const seen = new Set<string>();
  for (const raw of body.hosts as unknown[]) {
    if (!isRecord(raw) || typeof raw.id !== "string" || raw.id === "" || seen.has(raw.id)) continue;
    seen.add(raw.id);
    hosts.push(parseHost(raw, raw.id));
  }
  return {
    schema: typeof body.schema === "number" ? body.schema : 0,
    generated_at: body.generated_at,
    interval_sec: typeof body.interval_sec === "number" ? body.interval_sec : 10,
    stale_after_sec: typeof body.stale_after_sec === "number" ? body.stale_after_sec : 30,
    hosts,
    dropped: body.hosts.length - hosts.length,
  };
}

function parseHistory(data: unknown): ResourcesHistory {
  const body = data as Partial<ResourcesHistory> | null;
  if (!body || !isRecord(body.hosts) || typeof body.generated_at !== "number") {
    throw new Error("추이 응답 형식 오류");
  }
  // 장비별 값이 배열이 아니면 빈 추이로 본다 (현재 값 화면까지 깨지지 않게 한다).
  const hosts: Record<string, HistoryPoint[]> = {};
  for (const [id, points] of Object.entries(body.hosts as Record<string, unknown>)) {
    hosts[id] = records(points).flatMap((point) => {
      const t = num(point.t);
      if (t === null) return [];
      return [
        {
          t,
          cpu: num(point.cpu),
          mem: num(point.mem),
          gpu: num(point.gpu),
          gpu_mem: num(point.gpu_mem),
          gpu_temp: num(point.gpu_temp),
        },
      ];
    });
  }
  return { generated_at: body.generated_at, hosts };
}

const INITIAL: ResourcesState = {
  latest: null,
  receivedAt: null,
  checkedAt: null,
  apiDown: false,
  error: null,
  paused: false,
  history: null,
  historyError: null,
};

/** 자원 수집기를 5초(현재 값)·30초(추이) 주기로 읽는다. 화면을 떠나면 요청을 취소하고, 탭이 숨겨지면 읽기를 멈춘다. */
export function useResources(): ResourcesState {
  const [state, setState] = useState<ResourcesState>(INITIAL);

  useEffect(
    () =>
      startPolling(
        LATEST_URL,
        LATEST_PERIOD_MS,
        (data) => {
          const latest = parseLatest(data);
          const now = Date.now();
          setState((prev) => {
            // generated_at 이 앞 응답과 같으면 새 응답으로 치지 않는다. 그동안 값의 나이는 브라우저 경과 시간만큼 는다.
            const fresh =
              prev.latest === null || prev.receivedAt === null || latest.generated_at !== prev.latest.generated_at;
            return {
              ...prev,
              latest,
              receivedAt: fresh ? now : prev.receivedAt,
              checkedAt: now,
              apiDown: false,
              error: null,
              paused: false,
            };
          });
        },
        (message) =>
          setState((prev) => ({ ...prev, checkedAt: Date.now(), apiDown: true, error: message, paused: false })),
        () => setState((prev) => ({ ...prev, paused: true })),
      ),
    [],
  );

  useEffect(
    () =>
      startPolling(
        HISTORY_URL,
        HISTORY_PERIOD_MS,
        (data) => {
          const history = parseHistory(data);
          setState((prev) => ({ ...prev, history, historyError: null }));
        },
        (message) => setState((prev) => ({ ...prev, historyError: message })),
      ),
    [],
  );

  return state;
}
