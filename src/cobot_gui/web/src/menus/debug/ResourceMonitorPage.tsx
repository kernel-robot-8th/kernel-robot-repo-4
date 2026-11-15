import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  clock,
  fmt,
  hostAgeSec,
  hostSkewSec,
  ratioPct,
  sinceFreshSec,
  useResources,
  type HistoryPoint,
  type ResourceHost,
  type ResourcesHistory,
  type ResourcesLatest,
} from "./useResources";

// 수집 대상 3대. 수집기 응답에 빠진 장비도 카드로 남겨 "수집 끊김" 으로 보인다.
const EXPECTED_HOSTS = [
  { id: "relay", name: "중계", address: "local" },
  { id: "omen8", name: "8-OMEN", address: "192.168.0.5" },
  { id: "team11", name: "team11", address: "192.168.0.4" },
];

const TREND_WINDOW_SEC = 30 * 60;

// 화면 표시용 기준이다 (운영 경보 기준이 아니다).
const PCT_CAUTION = 75;
const PCT_HIGH = 90;
const TEMP_CAUTION = 80;
const TEMP_HIGH = 90;

type Level = "none" | "ok" | "caution" | "high";

const LEVEL_CLASS: Record<Level, string> = {
  none: "text-zinc-300",
  ok: "text-emerald-400",
  caution: "text-amber-400",
  high: "text-red-400",
};

function levelOf(value: number | null | undefined, cautionAt: number, highAt: number): Level {
  if (typeof value !== "number" || !Number.isFinite(value)) return "none";
  if (value >= highAt) return "high";
  if (value >= cautionAt) return "caution";
  return "ok";
}

/** 기준이 있는 수치. 끊긴 값은 색을 빼고 회색으로만 보인다. 색만으로 구분하지 않도록 글자도 붙인다. */
function Reading({
  value,
  unit,
  dim,
  cautionAt = PCT_CAUTION,
  highAt = PCT_HIGH,
}: {
  value: number | null | undefined;
  unit: string;
  dim: boolean;
  cautionAt?: number;
  highAt?: number;
}) {
  const level = dim ? "none" : levelOf(value, cautionAt, highAt);
  return (
    <>
      <span className={dim ? "text-zinc-500" : `font-bold ${LEVEL_CLASS[level]}`}>{fmt(value, 1, unit)}</span>
      {level === "high" && <span className="ml-1 text-[10px] text-red-400">높음</span>}
      {level === "caution" && <span className="ml-1 text-[10px] text-amber-400">주의</span>}
    </>
  );
}

/** 0~100 % 값의 최근 30분 추이. 값이 없거나 수집이 비는 구간은 선을 잇지 않는다. */
function Sparkline({
  points,
  field,
  endAt,
  intervalSec,
  label,
  dim,
}: {
  points: HistoryPoint[];
  field: "cpu" | "mem" | "gpu";
  endAt: number;
  intervalSec: number;
  label: string;
  dim: boolean;
}) {
  const width = 120;
  const height = 28;
  const pad = 2;
  const start = endAt - TREND_WINDOW_SEC;
  const gapSec = Math.max(intervalSec * 2.5, 25);

  const segments: [number, number][][] = [];
  let current: [number, number][] = [];
  let previousAt: number | null = null;
  const flush = () => {
    if (current.length > 0) segments.push(current);
    current = [];
  };
  for (const point of points) {
    const value = point[field];
    if (typeof point.t !== "number" || point.t < start || point.t > endAt + 1) continue;
    if (typeof value !== "number" || !Number.isFinite(value)) {
      flush();
      previousAt = null;
      continue;
    }
    if (previousAt !== null && point.t - previousAt > gapSec) flush();
    const x = pad + ((point.t - start) / TREND_WINDOW_SEC) * (width - 2 * pad);
    const y = height - pad - (Math.min(100, Math.max(0, value)) / 100) * (height - 2 * pad);
    current.push([x, y]);
    previousAt = point.t;
  }
  flush();

  if (segments.length === 0) {
    return <span className="text-[10px] text-zinc-600">추이 없음</span>;
  }
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={dim ? "text-zinc-600" : "text-cyan-400"}
    >
      <title>{label}</title>
      <line x1={0} y1={height - 0.5} x2={width} y2={height - 0.5} stroke="#3f3f46" strokeWidth={1} />
      {segments.map((segment, index) =>
        segment.length === 1 ? (
          <circle key={index} cx={segment[0][0]} cy={segment[0][1]} r={1.2} fill="currentColor" />
        ) : (
          <polyline
            key={index}
            points={segment.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ),
      )}
    </svg>
  );
}

function MetricRow({ label, children, trend }: { label: string; children: ReactNode; trend?: ReactNode }) {
  return (
    <div className="grid grid-cols-[4rem_1fr_auto] items-center gap-2 border-b border-border/60 py-1.5 last:border-b-0">
      <span className="text-[11px] text-zinc-400">{label}</span>
      <span className="min-w-0">{children}</span>
      <span className="shrink-0">{trend}</span>
    </div>
  );
}

function gb(mb: number | null | undefined): number | null {
  return typeof mb === "number" && Number.isFinite(mb) ? mb / 1024 : null;
}

function HostCard({
  expected,
  host,
  latest,
  ageSec,
  apiDown,
  paused,
  feedNote,
  history,
  historyStale,
}: {
  expected: { id: string; name: string; address: string };
  host: ResourceHost | undefined;
  latest: ResourcesLatest;
  ageSec: number | null;
  apiDown: boolean;
  /** 탭이 숨겨져 조회를 멈춘 상태. */
  paused: boolean;
  /** 장비가 아니라 수집기 쪽 문제로 값이 묵었을 때의 사유. */
  feedNote: string | null;
  history: ResourcesHistory | null;
  historyStale: boolean;
}) {
  const name = host?.name ?? expected.name;
  const rawAddress = host?.address ?? expected.address;
  const address = rawAddress === "local" ? "로컬" : rawAddress;
  // collected_at 이 generated_at 보다 앞서면 나이를 믿을 수 없으므로 끊김으로 본다.
  const skewSec = host ? hostSkewSec(latest, host) : 0;
  const stale = !host || ageSec === null || ageSec > latest.stale_after_sec || skewSec > 0;
  // 마지막 수집이 실패했으면 기한 안이어도 지금 값이 아니다.
  const failed = !!host && !host.ok;
  const dim = stale || apiDown || paused || failed;
  const points = history?.hosts?.[expected.id] ?? [];
  const trendEnd = history?.generated_at ?? latest.generated_at;
  const trendDim = dim || historyStale;
  const memoryPct = ratioPct(host?.memory?.used_mb, host?.memory?.total_mb);
  const disks = host?.disk ?? [];
  const gpus = host?.gpus ?? [];
  const containers = host?.containers ?? [];
  const errorText = !host
    ? "수집기 응답에 이 장비가 없습니다"
    : skewSec > 0
      ? `수집 시각이 응답 시각보다 ${Math.ceil(skewSec)}초 앞섬 (시계 이상)`
      : (host.error ?? feedNote ?? "보고된 사유 없음");
  // 끊김이면 올림, 아니면 내림: 화면의 초가 기준(stale_after_sec)과 어긋나 보이지 않게 한다.
  const ageText =
    skewSec > 0 ? "시각 이상" : ageSec === null ? "-" : `${stale ? Math.ceil(ageSec) : Math.floor(ageSec)}초 전`;

  return (
    <Card
      role="group"
      aria-label={`${name} 자원`}
      data-stale={dim ? "true" : "false"}
      className={`rounded-none bg-[#121316] ${stale ? "border-red-800" : "border-border"}`}
    >
      <CardHeader className="space-y-1.5 border-b border-border p-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-xs font-bold tracking-wide text-white">
          <span className="flex items-center gap-2">
            <span className="text-sm text-cyan-300">{name}</span>
            <span className="font-mono text-[11px] font-normal text-zinc-500">{address}</span>
          </span>
          {stale ? (
            <Badge variant="outline" className="border-red-600 bg-red-950/60 text-red-300">
              수집 끊김
            </Badge>
          ) : apiDown ? (
            <Badge variant="outline" className="border-red-600 text-red-400">
              갱신 중단
            </Badge>
          ) : paused ? (
            <Badge variant="outline" className="border-zinc-600 text-zinc-400">
              조회 일시 중지
            </Badge>
          ) : failed ? (
            <Badge variant="outline" className="border-amber-600 text-amber-400">
              최근 수집 실패
            </Badge>
          ) : (
            <Badge variant="outline" className="border-emerald-600 text-emerald-400">
              수집 중
            </Badge>
          )}
        </CardTitle>
        <p className={`font-mono text-[11px] ${dim ? "text-red-300" : "text-zinc-400"}`}>
          {host && ageSec !== null
            ? `마지막 수집 ${clock(host.collected_at)} (${ageText})`
            : "마지막 수집 없음"}
          {host && <span className="text-zinc-500"> · 수집 소요 {fmt(host.duration_ms, 0, " ms")}</span>}
        </p>
        {(stale || failed) && (
          <p className="border border-red-900/60 bg-red-950/30 p-1.5 text-[11px] text-red-300 break-all">
            사유: {errorText}
            {failed && host.last_attempt_at !== null && ` · 마지막 시도 ${clock(host.last_attempt_at)}`}
            {host && ageSec !== null && " · 아래 값은 마지막으로 수집된 값이며 현재 값이 아닙니다"}
          </p>
        )}
      </CardHeader>

      {host && (
        <CardContent className={`space-y-3 p-3 font-mono text-xs ${dim ? "text-zinc-500" : "text-zinc-300"}`}>
          <div>
            <MetricRow
              label="CPU"
              trend={
                <Sparkline
                  points={points}
                  field="cpu"
                  endAt={trendEnd}
                  intervalSec={latest.interval_sec}
                  label={`${name} CPU 사용률 추이 (최근 30분)`}
                  dim={trendDim}
                />
              }
            >
              <Reading value={host.cpu?.used_pct} unit=" %" dim={dim} />
              <span className="ml-2 text-[11px] text-zinc-500">
                부하(1분) {fmt(host.cpu?.load1, 2)} / {fmt(host.cpu?.cores, 0)}코어
              </span>
            </MetricRow>
            <MetricRow
              label="메모리"
              trend={
                <Sparkline
                  points={points}
                  field="mem"
                  endAt={trendEnd}
                  intervalSec={latest.interval_sec}
                  label={`${name} 메모리 사용률 추이 (최근 30분)`}
                  dim={trendDim}
                />
              }
            >
              <Reading value={memoryPct} unit=" %" dim={dim} />
              <span className="ml-2 text-[11px] text-zinc-500">
                {fmt(gb(host.memory?.used_mb), 1)} / {fmt(gb(host.memory?.total_mb), 1, " GB")} · 가용{" "}
                {fmt(gb(host.memory?.available_mb), 1, " GB")}
              </span>
            </MetricRow>
            {disks.length === 0 ? (
              <MetricRow label="디스크">
                <span className="text-zinc-500">-</span>
              </MetricRow>
            ) : (
              disks.map((disk) => (
                <MetricRow key={disk.mount} label={`디스크 ${disk.mount}`}>
                  <Reading value={disk.used_pct} unit=" %" dim={dim} />
                  <span className="ml-2 text-[11px] text-zinc-500">
                    {fmt(disk.used_gb, 1)} / {fmt(disk.total_gb, 1, " GB")} · 남음 {fmt(disk.avail_gb, 1, " GB")}
                  </span>
                </MetricRow>
              ))
            )}
          </div>

          <div>
            <div className="flex items-center justify-between gap-2 pb-1">
              <h3 className="text-[11px] font-bold text-zinc-400">GPU</h3>
              {gpus.length > 0 && (
                <Sparkline
                  points={points}
                  field="gpu"
                  endAt={trendEnd}
                  intervalSec={latest.interval_sec}
                  label={`${name} GPU 사용률 추이 (최근 30분)`}
                  dim={trendDim}
                />
              )}
            </div>
            {gpus.length === 0 ? (
              <p className="text-[11px] text-zinc-500">{host.gpu_note ?? "GPU 정보 없음"}</p>
            ) : (
              <>
                {gpus.map((gpu, index) => (
                  <div key={`${gpu.name}-${index}`} className="border border-border bg-[#16171b] p-2 text-[11px]">
                    <div className={dim ? "text-zinc-500" : "text-white"}>{gpu.name}</div>
                    <div className="flex flex-wrap gap-x-4 gap-y-0.5 pt-1">
                      <span>
                        사용률 <Reading value={gpu.util_pct} unit=" %" dim={dim} />
                      </span>
                      <span>
                        메모리 <Reading value={ratioPct(gpu.mem_used_mb, gpu.mem_total_mb)} unit=" %" dim={dim} />
                        <span className="ml-1 text-zinc-500">
                          ({fmt(gpu.mem_used_mb, 0)} / {fmt(gpu.mem_total_mb, 0, " MB")})
                        </span>
                      </span>
                      <span>
                        온도{" "}
                        <Reading
                          value={gpu.temp_c}
                          unit=" °C"
                          dim={dim}
                          cautionAt={TEMP_CAUTION}
                          highAt={TEMP_HIGH}
                        />
                      </span>
                    </div>
                  </div>
                ))}
                {host.gpu_note && <p className="pt-1 text-[11px] text-zinc-500">{host.gpu_note}</p>}
              </>
            )}
          </div>

          <div>
            <h3 className="pb-1 text-[11px] font-bold text-zinc-400">컨테이너 ({containers.length})</h3>
            {containers.length === 0 ? (
              <p className="text-[11px] text-zinc-500">{host.containers_note ?? "실행 중인 컨테이너 없음"}</p>
            ) : (
              <>
                <div className="overflow-x-auto border border-border">
                  <table className="w-full text-[11px]">
                    <thead className="border-b border-border bg-[#181a20] text-left text-zinc-400">
                      <tr>
                        <th className="px-2 py-1 font-medium">이름 / 이미지</th>
                        <th className="px-2 py-1 font-medium">상태</th>
                        <th className="px-2 py-1 font-medium">CPU</th>
                        <th className="px-2 py-1 font-medium">메모리</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/60">
                      {containers.map((container) => (
                        <tr key={container.name}>
                          <td className="px-2 py-1">
                            <div className={`font-bold ${dim ? "text-zinc-500" : "text-white"}`}>{container.name}</div>
                            <div className="break-all text-[10px] text-zinc-500">{container.image}</div>
                          </td>
                          <td className="px-2 py-1 whitespace-nowrap">{container.status}</td>
                          <td className="px-2 py-1 whitespace-nowrap">{fmt(container.cpu_pct, 1, " %")}</td>
                          <td className="px-2 py-1 whitespace-nowrap">
                            {fmt(container.mem_used_mb, 0)} / {fmt(container.mem_limit_mb, 0, " MB")}
                            <span className="ml-1 text-zinc-500">({fmt(container.mem_pct, 1, " %")})</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {host.containers_note && <p className="pt-1 text-[11px] text-zinc-500">{host.containers_note}</p>}
              </>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export default function ResourceMonitorPage() {
  const { latest, receivedAt, checkedAt, apiDown, error, paused, history, historyError } = useResources();
  // 화면의 시각은 모두 수집기(중계 장비) 시계 기준이다. 브라우저 시계와 섞지 않는다.
  const lastGood = latest ? clock(latest.generated_at) : "없음";
  // 응답은 오는데 generated_at 이 바뀌지 않은 채 기한을 넘겼다 (같은 응답 반복).
  const frozen = !!latest && !apiDown && sinceFreshSec(receivedAt, checkedAt) > latest.stale_after_sec;
  const feedNote = apiDown ? "수집기 응답 없음" : frozen ? "수집기 응답이 갱신되지 않음" : null;
  const known = new Set(EXPECTED_HOSTS.map((host) => host.id));
  const extraHosts = (latest?.hosts ?? []).filter((host) => !known.has(host.id));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
            <span className="font-mono text-cyan-400">6.</span> 자원 모니터링
          </h1>
          <p className="text-xs text-zinc-400">
            중계·8-OMEN·team11 장비의 CPU, 메모리, 디스크, GPU, 컨테이너 사용량 (읽기 전용)
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-400">
          {!apiDown && !frozen && !paused && latest && (
            <Badge variant="outline" className="border-emerald-600 text-emerald-400">
              수집기 응답 중
            </Badge>
          )}
          <span className="font-mono">
            수집 주기 {fmt(latest?.interval_sec, 0, "초")} · 화면 갱신 5초 · 마지막 정상 응답 {lastGood} (수집기 시계)
          </span>
        </div>
      </div>

      {apiDown && (
        <div role="alert" className="rounded-none border border-red-700 bg-red-950/80 p-2.5 text-xs text-red-200">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-red-400">수집기 응답 없음</span>
            <span className="text-zinc-300">마지막 정상 응답: {lastGood}</span>
            {error && <span className="font-mono text-red-300">({error})</span>}
          </div>
          <p className="pt-1 text-[11px] text-zinc-400">
            {latest
              ? "아래 값은 마지막 정상 응답 때의 값이며 현재 값이 아닙니다. "
              : "받은 값이 없습니다. "}
            중계 장비의 자원 수집기(:8084)와 /api/resources 프록시를 확인해야 합니다.
          </p>
        </div>
      )}

      {frozen && (
        <div role="alert" className="rounded-none border border-red-700 bg-red-950/80 p-2.5 text-xs text-red-200">
          <span className="font-bold text-red-400">수집기 응답이 갱신되지 않음</span>
          <span className="pl-2 text-zinc-300">
            같은 응답 시각({lastGood})이 반복됩니다. 아래 값은 현재 값이 아닙니다.
          </span>
        </div>
      )}

      {latest && (latest.schema !== 1 || latest.dropped > 0) && (
        <p role="status" className="rounded-none border border-amber-700 bg-amber-950/40 p-2 text-xs text-amber-300">
          {latest.schema !== 1 && `수집기 형식 버전 다름 (schema ${latest.schema}, 화면은 1 기준). 값이 맞지 않을 수 있습니다. `}
          {latest.dropped > 0 && `수집기 응답 형식 오류: 장비 항목 ${latest.dropped}개를 읽지 못했습니다.`}
        </p>
      )}

      {!latest ? (
        !apiDown && (
          <p role="status" className="text-xs text-zinc-500 font-mono">
            수집기 첫 응답 대기
          </p>
        )
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {EXPECTED_HOSTS.map((expected) => {
            const host = latest.hosts.find((item) => item.id === expected.id);
            return (
              <HostCard
                key={expected.id}
                expected={expected}
                host={host}
                latest={latest}
                ageSec={host ? hostAgeSec(latest, host, receivedAt, checkedAt) : null}
                apiDown={apiDown}
                paused={paused}
                feedNote={feedNote}
                history={history}
                historyStale={historyError !== null}
              />
            );
          })}
          {extraHosts.map((host) => (
            <HostCard
              key={host.id}
              expected={{ id: host.id, name: host.name, address: host.address }}
              host={host}
              latest={latest}
              ageSec={hostAgeSec(latest, host, receivedAt, checkedAt)}
              apiDown={apiDown}
              paused={paused}
              feedNote={feedNote}
              history={history}
              historyStale={historyError !== null}
            />
          ))}
        </div>
      )}

      <p className="text-[10px] text-zinc-500 font-mono">
        추이 선은 최근 30분의 0~100 % 값이며, 수집이 비는 구간은 선을 잇지 않습니다.
        {historyError && ` 추이 조회 실패 (${historyError}).`} 표시 기준(화면용 임의 기준): 사용률 {PCT_CAUTION} %
        이상 주의, {PCT_HIGH} % 이상 높음 · GPU 온도 {TEMP_CAUTION} °C 이상 주의, {TEMP_HIGH} °C 이상 높음. 값이
        없으면 "-" 로 표시합니다.
      </p>
    </div>
  );
}
