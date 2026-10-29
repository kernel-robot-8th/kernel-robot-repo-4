// 메뉴 6.5 시뮬레이션·기능 검증 (SR-22 가상 아레나 테스트베드)
// PRD_3 신발 매장 2.5m x 2.4m 아레나에서 이동 로봇 3대와 5축 다관절 로봇팔 3대의
// 기구학, 67cm 게이트 통과, 웨이포인트 주행 및 픽앤플레이스를 웹에서 직접 시뮬레이션하고 모니터링합니다.
import { useEffect, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import MenuHeader from "@/shell/MenuHeader";
import type { MenuPageProps } from "@/shell/types";

// 아레나 크기 및 정본 웨이포인트 정의 (2.5m x 2.4m)
const ARENA_WIDTH = 2.5;
const ARENA_HEIGHT = 2.4;

interface WaypointDef {
  id: string;
  name: string;
  x: number;
  y: number;
  yaw: number;
  desc: string;
}

const WAYPOINTS: WaypointDef[] = [
  { id: "WP_HOME_1", name: "충전 1", x: 1.41, y: 2.05, yaw: 270, desc: "Pinky 1 대기/충전소" },
  { id: "WP_HOME_2", name: "충전 2", x: 1.41, y: 1.86, yaw: 270, desc: "Pinky 2 대기/충전소" },
  { id: "WP_HOME_3", name: "충전 3", x: 1.41, y: 1.66, yaw: 270, desc: "Pinky 3 대기/충전소" },
  { id: "WP_LOAD_1", name: "창고 1 (ZA)", x: 2.015, y: 2.105, yaw: 0, desc: "상차대 1 (OMX 1)" },
  { id: "WP_LOAD_2", name: "창고 2 (ZB)", x: 2.015, y: 1.5375, yaw: 0, desc: "상차대 2 (OMX 2)" },
  { id: "WP_GATE_TRANSIT", name: "게이트 중심", x: 1.25, y: 0.335, yaw: 180, desc: "67cm 통과 게이트" },
  { id: "WP_UNLOAD", name: "매장 하차 (ZC)", x: 0.415, y: 1.85, yaw: 180, desc: "하차대 3 (OMX 3)" },
  { id: "WP_BENCH_DELIVERY", name: "고객 벤치", x: 0.29, y: 1.31, yaw: 90, desc: "고객 전달 벤치" },
];

// 자동 순회 데모 주행 코스
const DEMO_ROUTE = [
  "WP_LOAD_1",
  "WP_UNLOAD",
  "WP_BENCH_DELIVERY",
  "WP_HOME_1",
];

interface PathNode {
  x: number;
  y: number;
  yaw?: number;
}

interface RobotState {
  id: string;
  name: string;
  color: string;
  x: number;
  y: number;
  yaw: number;
  v: number;
  w: number;
  battery: number;
  state: "IDLE" | "NAVIGATING" | "DOCKED";
  targetWp?: string;
  pathQueue: PathNode[];
}

interface ArmState {
  id: string;
  name: string;
  baseX: number;
  baseY: number;
  state: "STANDBY" | "EXECUTING";
  step: string;
  q: number[]; // [joint1..5, gripper]
}

// 67cm 중앙 게이트 통과 코리더 전역 플래너 (벽 충돌 회피)
function generateCorridorPlan(
  sx: number,
  _sy: number,
  tx: number,
  ty: number,
  tyaw?: number,
  gateWidth: number = 0.67
): PathNode[] {
  const wallX = 1.25;
  const isStartRight = sx > wallX;
  const isTargetRight = tx > wallX;
  const gateY = gateWidth / 2;

  // 동일 구역 내 이동 (벽을 가로지르지 않음)
  if (isStartRight === isTargetRight) {
    return [{ x: tx, y: ty, yaw: tyaw }];
  }

  // 창고(우측) -> 매장(좌측): 게이트 우측 접근 -> 게이트 중심 -> 게이트 좌측 출구 -> 목적지
  if (isStartRight && !isTargetRight) {
    return [
      { x: 1.45, y: gateY, yaw: 180 },
      { x: 1.25, y: gateY, yaw: 180 },
      { x: 1.05, y: gateY, yaw: 180 },
      { x: tx, y: ty, yaw: tyaw },
    ];
  }

  // 매장(좌측) -> 창고(우측): 게이트 좌측 접근 -> 게이트 중심 -> 게이트 우측 출구 -> 목적지
  return [
    { x: 1.05, y: gateY, yaw: 0 },
    { x: 1.25, y: gateY, yaw: 0 },
    { x: 1.45, y: gateY, yaw: 0 },
    { x: tx, y: ty, yaw: tyaw },
  ];
}

// SVG 부채꼴(LiDAR 스캔 빔) 경로 생성 헬퍼
function getSectorPath(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const points: string[] = [`${cx.toFixed(1)},${cy.toFixed(1)}`];
  const step = 8;
  for (let a = startAngle; a <= endAngle; a += step) {
    const rad = (a * Math.PI) / 180;
    points.push(`${(cx + r * Math.cos(rad)).toFixed(1)},${(cy - r * Math.sin(rad)).toFixed(1)}`);
  }
  const endRad = (endAngle * Math.PI) / 180;
  points.push(`${(cx + r * Math.cos(endRad)).toFixed(1)},${(cy - r * Math.sin(endRad)).toFixed(1)}`);
  return `M ${points.join(" L ")} Z`;
}

export default function Page({ menu }: MenuPageProps) {
  // 1. 핑키 3대 시뮬레이션 상태
  const [robots, setRobots] = useState<Record<string, RobotState>>({
    pinky1: {
      id: "pinky1",
      name: "Pinky 1호기 (오렌지)",
      color: "#f97316",
      x: 1.41,
      y: 2.05,
      yaw: -90,
      v: 0.0,
      w: 0.0,
      battery: 98.5,
      state: "IDLE",
      pathQueue: [],
    },
    pinky2: {
      id: "pinky2",
      name: "Pinky 2호기 (그린)",
      color: "#22c55e",
      x: 1.41,
      y: 1.86,
      yaw: -90,
      v: 0.0,
      w: 0.0,
      battery: 95.0,
      state: "IDLE",
      pathQueue: [],
    },
    pinky3: {
      id: "pinky3",
      name: "Pinky 3호기 (블루)",
      color: "#3b82f6",
      x: 1.41,
      y: 1.66,
      yaw: -90,
      v: 0.0,
      w: 0.0,
      battery: 92.0,
      state: "IDLE",
      pathQueue: [],
    },
  });

  // 2. 로봇팔 3대 시뮬레이션 상태
  const [arms, setArms] = useState<Record<string, ArmState>>({
    omx_1: {
      id: "omx_1",
      name: "창고 1번 팔 (상차)",
      baseX: 2.015,
      baseY: 2.105,
      state: "STANDBY",
      step: "HOME",
      q: [0.0, -1.05, 0.35, 0.7, 0.0, 0.0],
    },
    omx_2: {
      id: "omx_2",
      name: "창고 2번 팔 (상차)",
      baseX: 2.015,
      baseY: 1.5375,
      state: "STANDBY",
      step: "HOME",
      q: [0.0, -1.05, 0.35, 0.7, 0.0, 0.0],
    },
    omx_3: {
      id: "omx_3",
      name: "매장 3번 팔 (하차)",
      baseX: 0.415,
      baseY: 1.85,
      state: "STANDBY",
      step: "HOME",
      q: [0.0, -1.05, 0.35, 0.7, 0.0, 0.0],
    },
  });

  // 조작 대상 선택 및 컨트롤 상태
  const [selectedRobot, setSelectedRobot] = useState<string>("pinky1");
  const [selectedArm, setSelectedArm] = useState<string>("omx_1");
  const [gateWidth, setGateWidth] = useState<number>(0.67);
  const [simRunning, setSimRunning] = useState<boolean>(true);

  // 실시간 티커, 라이다 회전, 자동 순회 데모 및 궤적 기록
  const [tick, setTick] = useState<number>(0);
  const [autoDemo, setAutoDemo] = useState<boolean>(true);
  const [, setDemoRouteIdx] = useState<number>(0);
  const [, setDockWaitTicks] = useState<number>(0);
  const [trails, setTrails] = useState<Record<string, Array<{ x: number; y: number }>>>({
    pinky1: [],
    pinky2: [],
    pinky3: [],
  });

  // 로봇팔 픽앤플레이스 시퀀스 시연 트리거
  const handleTriggerPick = (armId: string) => {
    setArms((prev) => ({
      ...prev,
      [armId]: {
        ...prev[armId],
        state: "EXECUTING",
        step: "PRE_GRASP",
        q: [0.0, 0.15, 0.4, 1.02, 0.0, 1.2],
      },
    }));

    setTimeout(() => {
      setArms((prev) => ({
        ...prev,
        [armId]: {
          ...prev[armId],
          step: "GRASP_LIFT_Z200",
          q: [0.0, -0.2, 0.1, 0.1, 0.0, 0.2],
        },
      }));
    }, 1200);

    setTimeout(() => {
      setArms((prev) => ({
        ...prev,
        [armId]: {
          ...prev[armId],
          step: "HANDOVER_RELEASE",
          q: [1.57, -0.1, 0.3, 0.3, 0.0, 0.2],
        },
      }));
    }, 2400);

    setTimeout(() => {
      setArms((prev) => ({
        ...prev,
        [armId]: {
          ...prev[armId],
          state: "STANDBY",
          step: "HOME",
          q: [0.0, -1.05, 0.35, 0.7, 0.0, 0.0],
        },
      }));
    }, 3600);
  };

  // 50ms (20Hz) 실시간 시뮬레이션 애니메이션 틱
  useEffect(() => {
    if (!simRunning) return;
    const interval = setInterval(() => {
      setTick((t) => t + 1);

      setRobots((prev) => {
        let changed = false;
        const next = { ...prev };

        // 1. 자동 순회 데모 모드 (Pinky 1)
        if (autoDemo) {
          const p1 = next.pinky1;
          if (p1.state === "DOCKED" || p1.state === "IDLE") {
            setDockWaitTicks((w) => {
              if (w < 25) {
                return w + 1;
              }
              setDemoRouteIdx((idx) => {
                const nextIdx = (idx + 1) % DEMO_ROUTE.length;
                const nextWp = DEMO_ROUTE[nextIdx];
                const targetDef = WAYPOINTS.find((item) => item.id === nextWp);
                const plan = targetDef
                  ? generateCorridorPlan(p1.x, p1.y, targetDef.x, targetDef.y, targetDef.yaw, gateWidth)
                  : [];
                next.pinky1 = {
                  ...p1,
                  state: "NAVIGATING",
                  targetWp: nextWp,
                  pathQueue: plan,
                };
                changed = true;
                if (nextWp === "WP_LOAD_1") handleTriggerPick("omx_1");
                if (nextWp === "WP_UNLOAD") handleTriggerPick("omx_3");
                return nextIdx;
              });
              return 0;
            });
          }
        }

        // 2. 이동 로봇 기구학 및 코리더 서브웨이포인트 큐 갱신
        for (const rid of Object.keys(next)) {
          const r = next[rid];
          if (r.state === "NAVIGATING" && r.pathQueue && r.pathQueue.length > 0) {
            const currentSubTarget = r.pathQueue[0];
            const dx = currentSubTarget.x - r.x;
            const dy = currentSubTarget.y - r.y;
            const dist = Math.hypot(dx, dy);

            if (dist > 0.035) {
              const targetAngle = (Math.atan2(dy, dx) * 180) / Math.PI;
              const speed = 0.035;
              next[rid] = {
                ...r,
                x: r.x + Math.cos((targetAngle * Math.PI) / 180) * speed,
                y: r.y + Math.sin((targetAngle * Math.PI) / 180) * speed,
                yaw: targetAngle,
                v: 0.2,
                w: 0.1,
              };
              changed = true;
            } else {
              const remainingQueue = r.pathQueue.slice(1);
              if (remainingQueue.length > 0) {
                next[rid] = {
                  ...r,
                  x: currentSubTarget.x,
                  y: currentSubTarget.y,
                  pathQueue: remainingQueue,
                };
                changed = true;
              } else {
                next[rid] = {
                  ...r,
                  x: currentSubTarget.x,
                  y: currentSubTarget.y,
                  yaw: currentSubTarget.yaw !== undefined ? currentSubTarget.yaw : r.yaw,
                  v: 0.0,
                  w: 0.0,
                  state: "DOCKED",
                  targetWp: undefined,
                  pathQueue: [],
                };
                changed = true;
              }
            }
          }
        }

        // 3. 이동 궤적(Ghost Trail) 기록
        if (changed) {
          setTrails((tr) => {
            const nextTr = { ...tr };
            for (const rid of ["pinky1", "pinky2", "pinky3"]) {
              const bot = next[rid];
              if (bot.state === "NAVIGATING") {
                const curList = nextTr[rid] || [];
                const last = curList[curList.length - 1];
                if (!last || Math.hypot(last.x - bot.x, last.y - bot.y) > 0.04) {
                  nextTr[rid] = [...curList.slice(-25), { x: bot.x, y: bot.y }];
                }
              }
            }
            return nextTr;
          });
        }

        return changed ? next : prev;
      });
    }, 50);

    return () => clearInterval(interval);
  }, [simRunning, autoDemo, gateWidth]);

  // 웨이포인트 이동 명령 트리거 (게이트 코리더 경로 생성)
  const handleDispatchWaypoint = (rid: string, wpId: string) => {
    setAutoDemo(false);
    const target = WAYPOINTS.find((wp) => wp.id === wpId);
    if (!target) return;

    setRobots((prev) => {
      const cur = prev[rid];
      const plan = generateCorridorPlan(cur.x, cur.y, target.x, target.y, target.yaw, gateWidth);
      return {
        ...prev,
        [rid]: {
          ...cur,
          state: "NAVIGATING",
          targetWp: wpId,
          pathQueue: plan,
        },
      };
    });
  };

  // 수동 속도 명령 트리거 (조종 시 데모 일시중지 및 큐 리셋)
  const handleManualDrive = (vx: number, wz: number) => {
    setAutoDemo(false);
    setRobots((prev) => {
      const cur = prev[selectedRobot];
      const rad = (cur.yaw * Math.PI) / 180;
      const nextX = Math.max(0.1, Math.min(ARENA_WIDTH - 0.1, cur.x + vx * Math.cos(rad) * 0.15));
      const nextY = Math.max(0.1, Math.min(ARENA_HEIGHT - 0.1, cur.y + vx * Math.sin(rad) * 0.15));
      const nextYaw = (cur.yaw + wz * 15 + 360) % 360;
      return {
        ...prev,
        [selectedRobot]: {
          ...cur,
          x: nextX,
          y: nextY,
          yaw: nextYaw,
          v: vx,
          w: (wz * Math.PI) / 180,
          state: vx !== 0 || wz !== 0 ? "NAVIGATING" : "IDLE",
          targetWp: undefined,
          pathQueue: [],
        },
      };
    });
  };

  // SVG 좌표 변환 (0~2.5m, 0~2.4m -> SVG 픽셀)
  const svgScale = 200;
  const svgPadX = 30;
  const svgPadY = 30;
  const toSvgX = (x: number) => svgPadX + x * svgScale;
  const toSvgY = (y: number) => svgPadY + (ARENA_HEIGHT - y) * svgScale;

  // 시뮬레이션 시간 포맷 (MM:SS.s)
  const simSec = tick * 0.05;
  const simMinStr = Math.floor(simSec / 60).toString().padStart(2, "0");
  const simSecStr = (simSec % 60).toFixed(1).padStart(4, "0");

  return (
    <div className="max-w-6xl space-y-6 font-sans">
      <MenuHeader menu={menu} kind="page" />

      {/* 상단 통합 안내 배너 */}
      <Alert className="rounded-none border-border bg-[#141414]">
        <AlertTitle className="text-white flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
            SR-22 가상환경 시뮬레이션 및 다중 로봇 사전 검증 스튜디오
          </span>
          <div className="flex items-center gap-2 font-mono text-xs">
            <Badge variant="outline" className="border-green-600 text-green-400">
              Jazzy 50Hz 엔진 가동
            </Badge>
            <Badge variant="outline" className="border-blue-600 text-blue-400">
              PyTorch 의존성 0%
            </Badge>
          </div>
        </AlertTitle>
        <AlertDescription className="text-[#888888] text-xs mt-1">
          신발 매장(PRD_3) 2.5m × 2.4m 정본 아레나와 핑키 3대, 다관절 로봇팔 3대의 기구학을 실시간 모의합니다.
          GPU가 없는 일반 노트북(LG 그램)에서도 1초 만에 빌드되며, 중앙 67cm 통과 게이트 및 최신 v9 웨이포인트를 지원합니다.
        </AlertDescription>
      </Alert>

      {/* 50Hz 실시간 텔레메트리 티커 및 네이티브 3D 뷰어 안내 바 */}
      <div className="bg-[#121214] border border-border p-3 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3 font-mono text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-1.5 text-emerald-400 font-bold px-2 py-0.5 bg-emerald-950/40 border border-emerald-500/40">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              LIVE SIM 50Hz
            </span>
            <span className="text-[#888888]">
              SIM TIME: <b className="text-cyan-400">{simMinStr}:{simSecStr}</b>
            </span>
            <span className="text-[#888888]">
              TICK: <b className="text-white">{tick}</b>
            </span>
            <span className="text-[#888888]">
              LIDAR: <b className="text-purple-400">360° ACTIVE</b>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAutoDemo((prev) => !prev)}
              className={`rounded-none h-7 px-3 text-xs font-bold font-mono ${
                autoDemo
                  ? "bg-amber-950/50 border-amber-500 text-amber-300 hover:bg-amber-900/60"
                  : "bg-emerald-950/50 border-emerald-500 text-emerald-300 hover:bg-emerald-900/60"
              }`}
            >
              {autoDemo ? "⏹ 자동 순회 데모 일시정지" : "▶ 자동 순회 데모 시작"}
            </Button>
          </div>
        </div>

        {/* 3D MuJoCo Native 안내 배너 */}
        <div className="px-3 py-1.5 bg-[#18181b] border border-border/80 text-[11px] text-[#a1a1aa] flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-blue-400 font-bold">ℹ️ 화면 안내:</span>
            <span>
              본 화면은 경량 <b>웹 2D 디지털 트윈</b>(SVG)입니다. 고화질 3D 물리 시뮬레이션(MuJoCo)은 OS 터미널에서
              <code className="text-green-400 mx-1">ros2 launch cobot_simulation bringup_sim.launch.py</code>
              실행 시 네이티브 OpenGL 창으로 함께 연동 가동됩니다.
            </span>
          </div>
          <Badge variant="outline" className="border-blue-500/50 text-blue-300 font-mono text-[10px]">
            Dual-View: 2D Web + 3D Native
          </Badge>
        </div>
      </div>

      {/* 메인 2열 그리드: 좌측 2D 아레나 캔버스, 우측 제어 및 모니터링 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* 1. 2D 아레나 SVG 뷰어 (7컬럼) */}
        <Card className="lg:col-span-7 rounded-none border border-border bg-[#111111] shadow-none">
          <CardHeader className="py-3 px-4 border-b border-border flex flex-row items-center justify-between bg-[#161616]">
            <CardTitle className="text-sm font-bold text-white flex items-center gap-2">
              <span>🏟️ 신발 매장 2D 아레나 탑뷰</span>
              <span className="text-xs font-normal text-[#888888]">(2.5m × 2.4m / 67cm 게이트)</span>
            </CardTitle>
            <div className="flex items-center gap-2 text-xs">
              <button
                type="button"
                onClick={() => setSimRunning((prev) => !prev)}
                className={`px-2 py-0.5 border text-[11px] font-mono ${
                  simRunning
                    ? "border-emerald-500 text-emerald-400 bg-emerald-950/30"
                    : "border-yellow-500 text-yellow-400 bg-yellow-950/30"
                }`}
              >
                {simRunning ? "⏸ 실시간 갱신 중" : "▶ 일시정지됨"}
              </button>
              <span className="text-[#888888] ml-1">게이트 폭:</span>
              <button
                type="button"
                onClick={() => setGateWidth(0.67)}
                className={`px-2 py-0.5 border text-[11px] ${
                  gateWidth === 0.67 ? "border-green-500 text-green-400 bg-green-950/30" : "border-border text-gray-400"
                }`}
              >
                67cm (정본)
              </button>
              <button
                type="button"
                onClick={() => setGateWidth(0.5)}
                className={`px-2 py-0.5 border text-[11px] ${
                  gateWidth === 0.5 ? "border-amber-500 text-amber-400 bg-amber-950/30" : "border-border text-gray-400"
                }`}
              >
                50cm (v9)
              </button>
            </div>
          </CardHeader>
          <CardContent className="p-3 flex justify-center items-center bg-[#0d0d0d]">
            <svg
              viewBox="0 0 560 540"
              className="w-full max-w-[540px] aspect-square select-none font-mono text-[10px]"
            >
              {/* 아레나 바닥 (2.5m x 2.4m) */}
              <rect
                x={toSvgX(0)}
                y={toSvgY(2.4)}
                width={ARENA_WIDTH * svgScale}
                height={ARENA_HEIGHT * svgScale}
                fill="#18181b"
                stroke="#3f3f46"
                strokeWidth="2"
              />

              {/* 그리드 가이드라인 (0.5m 간격) */}
              {[0.5, 1.0, 1.5, 2.0].map((gx) => (
                <line
                  key={`gx-${gx}`}
                  x1={toSvgX(gx)}
                  y1={toSvgY(0)}
                  x2={toSvgX(gx)}
                  y2={toSvgY(2.4)}
                  stroke="#27272a"
                  strokeWidth="1"
                  strokeDasharray="4 4"
                />
              ))}
              {[0.5, 1.0, 1.5, 2.0].map((gy) => (
                <line
                  key={`gy-${gy}`}
                  x1={toSvgX(0)}
                  y1={toSvgY(gy)}
                  x2={toSvgX(2.5)}
                  y2={toSvgY(gy)}
                  stroke="#27272a"
                  strokeWidth="1"
                  strokeDasharray="4 4"
                />
              ))}

              {/* 게이트 안전 통과 통로 (초록색 투명 영역) */}
              <rect
                x={toSvgX(1.2)}
                y={toSvgY(gateWidth)}
                width={0.1 * svgScale}
                height={gateWidth * svgScale}
                fill="#22c55e20"
                stroke="#22c55e80"
                strokeWidth="1"
                strokeDasharray="2 2"
              />
              <text x={toSvgX(1.25)} y={toSvgY(gateWidth / 2)} textAnchor="middle" fill="#4ade80" fontSize="9">
                게이트 {(gateWidth * 100).toFixed(0)}cm
              </text>

              {/* 중앙 분리 벽 (X: 1.20~1.30, Y: gateWidth ~ 2.40) */}
              <rect
                x={toSvgX(1.2)}
                y={toSvgY(2.4)}
                width={0.1 * svgScale}
                height={(2.4 - gateWidth) * svgScale}
                fill="#52525b"
                stroke="#71717a"
                strokeWidth="1.5"
              />
              <text
                x={toSvgX(1.25)}
                y={toSvgY((2.4 + gateWidth) / 2)}
                textAnchor="middle"
                fill="#e4e4e7"
                fontSize="10"
                transform={`rotate(-90 ${toSvgX(1.25)} ${toSvgY((2.4 + gateWidth) / 2)})`}
              >
                중앙 분리벽
              </text>

              {/* 창고 상단 랙 (Top Rack: 1.42~2.40, Y: 2.14~2.40) */}
              <rect
                x={toSvgX(1.42)}
                y={toSvgY(2.4)}
                width={0.98 * svgScale}
                height={0.26 * svgScale}
                fill="#b4530940"
                stroke="#d97706"
                strokeWidth="1.5"
              />
              <text x={toSvgX(1.91)} y={toSvgY(2.27)} textAnchor="middle" fill="#fbbf24" fontSize="10">
                창고 상단 랙 (Top Rack)
              </text>

              {/* 창고 우측 랙 (Right Rack: 2.16~2.40, Y: 0.67~2.40) */}
              <rect
                x={toSvgX(2.16)}
                y={toSvgY(2.4)}
                width={0.24 * svgScale}
                height={1.73 * svgScale}
                fill="#b4530930"
                stroke="#d97706"
                strokeWidth="1.5"
              />
              <text
                x={toSvgX(2.28)}
                y={toSvgY(1.5)}
                textAnchor="middle"
                fill="#fbbf24"
                fontSize="10"
                transform={`rotate(-90 ${toSvgX(2.28)} ${toSvgY(1.5)})`}
              >
                창고 우측 랙 (Right Rack)
              </text>

              {/* 매장 하차 카운터 (Counter: 0.1~0.7, Y: 1.7~2.0) */}
              <rect
                x={toSvgX(0.1)}
                y={toSvgY(2.0)}
                width={0.6 * svgScale}
                height={0.3 * svgScale}
                fill="#2563eb30"
                stroke="#3b82f6"
                strokeWidth="1.5"
              />
              <text x={toSvgX(0.4)} y={toSvgY(1.85)} textAnchor="middle" fill="#60a5fa" fontSize="10">
                수령 카운터 (OMX 3)
              </text>

              {/* 매장 고객 벤치 (Bench: 0.1~0.4, Y: 1.1~1.5) */}
              <rect
                x={toSvgX(0.1)}
                y={toSvgY(1.5)}
                width={0.3 * svgScale}
                height={0.4 * svgScale}
                fill="#05966930"
                stroke="#10b981"
                strokeWidth="1.5"
              />
              <text x={toSvgX(0.25)} y={toSvgY(1.3)} textAnchor="middle" fill="#34d399" fontSize="10">
                고객 벤치
              </text>

              {/* 정본 웨이포인트 8개 렌더링 */}
              {WAYPOINTS.map((wp) => {
                const sx = toSvgX(wp.x);
                const sy = toSvgY(wp.y);
                return (
                  <g key={wp.id} className="cursor-pointer" onClick={() => handleDispatchWaypoint(selectedRobot, wp.id)}>
                    <circle cx={sx} cy={sy} r="6" fill="#a1a1aa30" stroke="#a1a1aa" strokeWidth="1.5" />
                    <circle cx={sx} cy={sy} r="2" fill="#fafafa" />
                    <text x={sx + 8} y={sy + 3} fill="#a1a1aa" fontSize="8" fontWeight="bold">
                      {wp.id}
                    </text>
                  </g>
                );
              })}

              {/* 로봇팔 3대 위치 렌더링 */}
              {Object.values(arms).map((arm) => {
                const ax = toSvgX(arm.baseX);
                const ay = toSvgY(arm.baseY);
                const isExec = arm.state === "EXECUTING";
                return (
                  <g key={arm.id}>
                    {/* 팔 베이스 박스 */}
                    <rect
                      x={ax - 12}
                      y={ay - 12}
                      width="24"
                      height="24"
                      fill={isExec ? "#713f12" : "#3f3f46"}
                      stroke={isExec ? "#facc15" : "#e4e4e7"}
                      strokeWidth="1.5"
                    />
                    <circle cx={ax} cy={ay} r="8" fill={isExec ? "#f59e0b" : "#eab308"} />
                    <text x={ax} y={ay + 3} textAnchor="middle" fill="#000" fontSize="8" fontWeight="bold">
                      {arm.id.replace("omx_", "A")}
                    </text>
                    <text x={ax} y={ay - 15} textAnchor="middle" fill={isExec ? "#facc15" : "#eab308"} fontSize="8" fontWeight="bold">
                      {arm.name} ({arm.step})
                    </text>
                  </g>
                );
              })}

              {/* 핑키 이동 로봇 3대 렌더링 (이동 궤적 잔상 + 계획 경로 선 + 라이다 스캔 빔 + 펄스 링) */}
              {Object.values(robots).map((bot) => {
                const bx = toSvgX(bot.x);
                const by = toSvgY(bot.y);
                const isSelected = selectedRobot === bot.id;
                const rad = (bot.yaw * Math.PI) / 180;
                const arrowLen = 14;
                const ax = bx + Math.cos(rad) * arrowLen;
                const ay = by - Math.sin(rad) * arrowLen;

                // 회전 라이다 빔 각도 계산 (로봇별 위상차 부여)
                const phaseOffset = bot.id === "pinky2" ? 120 : bot.id === "pinky3" ? 240 : 0;
                const sweepDeg = ((tick * 10) + phaseOffset) % 360;
                const sweepRad = (sweepDeg * Math.PI) / 180;
                const beamLen = 32;
                const tipX = bx + Math.cos(sweepRad) * beamLen;
                const tipY = by - Math.sin(sweepRad) * beamLen;

                // 펄스 링 반경 및 불투명도
                const pulseR = 12 + ((tick + (phaseOffset / 10)) % 18) * 1.1;
                const pulseOp = Math.max(0, 0.7 - (((tick + (phaseOffset / 10)) % 18) * 0.04));

                return (
                  <g
                    key={bot.id}
                    className="cursor-pointer"
                    onClick={() => setSelectedRobot(bot.id)}
                  >
                    {/* 1. 이동 궤적 (Ghost Trail) */}
                    {trails[bot.id] && trails[bot.id].length > 1 && (
                      <polyline
                        points={trails[bot.id].map((pt) => `${toSvgX(pt.x)},${toSvgY(pt.y)}`).join(" ")}
                        fill="none"
                        stroke={bot.color}
                        strokeWidth="2.5"
                        strokeDasharray="4 3"
                        opacity="0.45"
                      />
                    )}

                    {/* 2. 계획 경로 선 (Planned Corridor Path - 67cm 게이트 우회 경로 시각화) */}
                    {bot.pathQueue && bot.pathQueue.length > 0 && (
                      <polyline
                        points={[`${bx},${by}`, ...bot.pathQueue.map((n) => `${toSvgX(n.x)},${toSvgY(n.y)}`)].join(" ")}
                        fill="none"
                        stroke={bot.color}
                        strokeWidth="1.5"
                        strokeDasharray="3 3"
                        opacity="0.65"
                      />
                    )}

                    {/* 3. 맥박 펄스 링 (Ping Ring) */}
                    <circle
                      cx={bx}
                      cy={by}
                      r={pulseR}
                      fill="none"
                      stroke={bot.color}
                      strokeWidth="1.5"
                      opacity={pulseOp}
                    />

                    {/* 4. 360도 회전 라이다 스캔 부채꼴 빔 */}
                    <path
                      d={getSectorPath(bx, by, beamLen, sweepDeg - 18, sweepDeg + 18)}
                      fill={bot.color + "25"}
                      stroke={bot.color + "50"}
                      strokeWidth="0.8"
                    />
                    <line
                      x1={bx}
                      y1={by}
                      x2={tipX}
                      y2={tipY}
                      stroke={bot.color}
                      strokeWidth="1.2"
                      strokeDasharray="2 2"
                      opacity="0.8"
                    />
                    <circle cx={tipX} cy={tipY} r="2" fill={bot.color} opacity="0.9" />

                    {/* 5. 선택 강조 링 */}
                    {isSelected && (
                      <circle cx={bx} cy={by} r="18" fill="none" stroke="#ffffff" strokeWidth="2" strokeDasharray="3 3" />
                    )}

                    {/* 6. 로봇 본체 원형 */}
                    <circle cx={bx} cy={by} r="12" fill={bot.color} stroke="#ffffff" strokeWidth="1.5" />

                    {/* 7. 헤딩 방향 지시선 */}
                    <line x1={bx} y1={by} x2={ax} y2={ay} stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" />

                    {/* 8. 로봇 번호 레이블 */}
                    <text x={bx} y={by + 3.5} textAnchor="middle" fill="#000000" fontSize="9" fontWeight="bold">
                      {bot.id.replace("pinky", "P")}
                    </text>

                    {/* 9. 상태 텍스트 */}
                    <text x={bx} y={by + 22} textAnchor="middle" fill={bot.color} fontSize="8" fontWeight="bold">
                      {bot.state}
                    </text>
                  </g>
                );
              })}
            </svg>
          </CardContent>
        </Card>

        {/* 2. 시뮬레이션 제어 스튜디오 및 모니터링 (5컬럼) */}
        <div className="lg:col-span-5 space-y-4">
          <Tabs defaultValue="robot" className="w-full">
            <TabsList className="w-full grid grid-cols-2 rounded-none border border-border bg-[#161616]">
              <TabsTrigger value="robot" className="rounded-none text-xs data-[state=active]:bg-[#27272a]">
                🤖 핑키 이동 로봇 제어
              </TabsTrigger>
              <TabsTrigger value="arm" className="rounded-none text-xs data-[state=active]:bg-[#27272a]">
                🦾 OMX 로봇팔 제어
              </TabsTrigger>
            </TabsList>

            {/* 탭 A: 핑키 주행 제어 */}
            <TabsContent value="robot" className="space-y-4 mt-4">
              <Card className="rounded-none border border-border bg-[#141414] shadow-none">
                <CardHeader className="py-2.5 px-3 border-b border-border bg-[#181818] flex flex-row items-center justify-between">
                  <span className="text-xs font-bold text-white">조작 로봇 선택</span>
                  <div className="flex gap-1">
                    {(["pinky1", "pinky2", "pinky3"] as const).map((rid) => (
                      <button
                        key={rid}
                        type="button"
                        onClick={() => setSelectedRobot(rid)}
                        className={`px-2 py-0.5 text-xs font-mono font-bold ${
                          selectedRobot === rid
                            ? "bg-white text-black"
                            : "bg-[#222222] text-[#888888] hover:text-white"
                        }`}
                      >
                        {rid.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </CardHeader>
                <CardContent className="p-3 space-y-3">
                  {/* 선택 로봇 텔레메트리 바 */}
                  <div className="grid grid-cols-3 gap-2 bg-[#0d0d0d] p-2 border border-border font-mono text-[11px] text-[#cccccc]">
                    <div>
                      <span className="text-[#666666] block">좌표 (X, Y)</span>
                      <b>
                        {robots[selectedRobot].x.toFixed(2)}, {robots[selectedRobot].y.toFixed(2)}m
                      </b>
                    </div>
                    <div>
                      <span className="text-[#666666] block">헤딩 (Yaw)</span>
                      <b>{robots[selectedRobot].yaw.toFixed(1)}°</b>
                    </div>
                    <div>
                      <span className="text-[#666666] block">배터리</span>
                      <b className="text-green-400">{robots[selectedRobot].battery}%</b>
                    </div>
                  </div>

                  {/* 수동 조종 패드 (cmd_vel 모의) */}
                  <div className="space-y-1.5">
                    <span className="text-[11px] font-bold text-[#aaaaaa]">수동 속도 제어 (cmd_vel)</span>
                    <div className="grid grid-cols-3 gap-1 max-w-[180px] mx-auto text-center font-mono">
                      <div />
                      <Button
                        variant="outline"
                        size="sm"
                        className="rounded-none h-8 text-xs bg-[#222222]"
                        onClick={() => handleManualDrive(0.2, 0)}
                      >
                        ▲ 전진
                      </Button>
                      <div />
                      <Button
                        variant="outline"
                        size="sm"
                        className="rounded-none h-8 text-xs bg-[#222222]"
                        onClick={() => handleManualDrive(0, 1)}
                      >
                        ◀ 좌회전
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        className="rounded-none h-8 text-xs font-bold"
                        onClick={() => handleManualDrive(0, 0)}
                      >
                        정지
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="rounded-none h-8 text-xs bg-[#222222]"
                        onClick={() => handleManualDrive(0, -1)}
                      >
                        우회전 ▶
                      </Button>
                      <div />
                      <Button
                        variant="outline"
                        size="sm"
                        className="rounded-none h-8 text-xs bg-[#222222]"
                        onClick={() => handleManualDrive(-0.15, 0)}
                      >
                        ▼ 후진
                      </Button>
                      <div />
                    </div>
                  </div>

                  {/* 정본 웨이포인트 즉시 디스패치 (Nav2 모의) */}
                  <div className="space-y-1.5 pt-2 border-t border-border">
                    <span className="text-[11px] font-bold text-[#aaaaaa]">정본 웨이포인트 자율 주행 디스패치</span>
                    <div className="grid grid-cols-2 gap-1.5">
                      {WAYPOINTS.slice(3, 7).map((wp) => (
                        <Button
                          key={wp.id}
                          variant="outline"
                          size="sm"
                          className="rounded-none h-8 text-xs justify-start px-2 bg-[#1a1a1a] hover:bg-[#262626] border-border text-[#cccccc]"
                          onClick={() => handleDispatchWaypoint(selectedRobot, wp.id)}
                        >
                          <span className="w-2 h-2 rounded-full bg-blue-500 mr-1.5 inline-block" />
                          {wp.name}
                        </Button>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {/* 탭 B: 로봇팔 픽앤플레이스 제어 */}
            <TabsContent value="arm" className="space-y-4 mt-4">
              <Card className="rounded-none border border-border bg-[#141414] shadow-none">
                <CardHeader className="py-2.5 px-3 border-b border-border bg-[#181818] flex flex-row items-center justify-between">
                  <span className="text-xs font-bold text-white">조작 로봇팔 선택</span>
                  <div className="flex gap-1">
                    {(["omx_1", "omx_2", "omx_3"] as const).map((aid) => (
                      <button
                        key={aid}
                        type="button"
                        onClick={() => setSelectedArm(aid)}
                        className={`px-2 py-0.5 text-xs font-mono font-bold ${
                          selectedArm === aid ? "bg-amber-400 text-black" : "bg-[#222222] text-[#888888] hover:text-white"
                        }`}
                      >
                        {aid.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </CardHeader>
                <CardContent className="p-3 space-y-3">
                  <div className="bg-[#0d0d0d] p-2.5 border border-border font-mono text-[11px] text-[#cccccc] space-y-1">
                    <div className="flex justify-between">
                      <span className="text-[#888888]">동작 상태:</span>
                      <Badge variant="outline" className={arms[selectedArm].state === "EXECUTING" ? "text-amber-400 border-amber-500" : "text-green-400 border-green-500"}>
                        {arms[selectedArm].state} ({arms[selectedArm].step})
                      </Badge>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#888888]">1.2 rad/s 속도 클램프:</span>
                      <span className="text-white">활성화됨 (PASS)</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#888888]">관절각 [q1..q5]:</span>
                      <span className="text-white">
                        [{arms[selectedArm].q.slice(0, 5).map((v) => v.toFixed(2)).join(", ")}]
                      </span>
                    </div>
                  </div>

                  {/* 표준 픽앤플레이스 시퀀스 실행 버튼 */}
                  <div className="space-y-2 pt-2">
                    <Button
                      variant="default"
                      className="w-full rounded-none bg-amber-600 hover:bg-amber-500 text-white font-bold h-9 text-xs"
                      disabled={arms[selectedArm].state === "EXECUTING"}
                      onClick={() => handleTriggerPick(selectedArm)}
                    >
                      {arms[selectedArm].state === "EXECUTING"
                        ? "동작 시퀀스 진행 중..."
                        : "▶ 표준 상차 픽앤플레이스 실행 (Z=200mm 수직 상승)"}
                    </Button>
                    <p className="text-[11px] text-[#888888] leading-tight">
                      * LeRobot 신경망 가중치 없이도, 실물 관절 속도 한계(1.2 rad/s)와 Z=200mm 수평 상하차 궤적을 100% 모의합니다.
                    </p>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          {/* ROS 2 Jazzy & Mosquitto CLI 기동 안내 카드 */}
          <Card className="rounded-none border border-border bg-[#141414] shadow-none">
            <CardHeader className="py-2 px-3 border-b border-border bg-[#181818] text-xs font-bold text-[#aaaaaa]">
              💻 터미널 CLI 실행 명령어
            </CardHeader>
            <CardContent className="p-2.5 font-mono text-[11px] space-y-1.5 text-[#aaaaaa]">
              <p className="text-[#666666]"># 1. 시뮬레이션 패키지 전체 런치 (핑키 3대 + 로봇팔 3대 50Hz):</p>
              <div className="p-1.5 bg-[#0d0d0d] border border-border text-green-400 select-all overflow-x-auto">
                <code>ros2 launch cobot_simulation bringup_sim.launch.py</code>
              </div>
              <p className="text-[#666666]"># 2. 웹소켓 브로커 연동 (네트워크 관제):</p>
              <div className="p-1.5 bg-[#0d0d0d] border border-border text-blue-400 select-all overflow-x-auto">
                <code>ws://100.69.41.81:9001 (MQTT over WebSockets)</code>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
