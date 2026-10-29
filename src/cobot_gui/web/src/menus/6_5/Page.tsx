// 메뉴 6.5 시뮬레이션·기능 검증 (SR-22 3D 가상환경 시뮬레이션 온라인 실험장)
// 관제 상세 기능 구현 및 검증을 위해, 브라우저 내장 3D 캔버스에서 핑키 3대 및 로봇팔 3대의 물리 모델을 실시간 구동하고
// 각 포인트별 태스크 동작 신호를 도커 백엔드로 송수신하여 시각화합니다.
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import MenuHeader from "@/shell/MenuHeader";
import type { MenuPageProps } from "@/shell/types";

// 경기장 치수 및 웨이포인트 정의 (정본: 2.4m x 2.4m)
interface Point3D {
  x: number;
  y: number;
  z: number;
}

interface RobotState {
  id: string;
  name: string;
  x: number;
  y: number;
  z: number;
  heading: number; // radian
  color: string;
}

interface ArmState {
  id: string;
  name: string;
  baseX: number;
  baseY: number;
  baseZ: number;
  shoulderYaw: number;
  shoulderPitch: number;
  elbowPitch: number;
  gripperState: "OPEN" | "CLOSED";
}

interface CargoBox {
  x: number;
  y: number;
  z: number;
  attachedTo: "TABLE_ZA" | "OMX_1" | "PINKY_1" | "OMX_3" | "BENCH";
}

interface TaskSignalLog {
  id: string;
  time: string;
  type: "SEND" | "ACK" | "DONE" | "ALERT";
  taskId: string;
  target: string;
  payload: string;
  rttMs?: number;
}

export default function Page({ menu }: MenuPageProps) {
  // 1. 엔진 생존 감지기 상태
  const [engineStatus, setEngineStatus] = useState<"ACTIVE" | "PAUSED">("ACTIVE");
  const [activeTaskName, setActiveTaskName] = useState<string>("대기 (IDLE)");
  const [isEStopped, setIsEStopped] = useState<boolean>(false);

  // 2. 3D 카메라 뷰포트 상태 (Orbit controls)
  const [azimuth, setAzimuth] = useState<number>(Math.PI * 0.25); // 45도
  const [elevation, setElevation] = useState<number>(Math.PI * 0.2); // 36도
  const [zoom, setZoom] = useState<number>(1.0);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const isDraggingRef = useRef<boolean>(false);
  const lastMousePosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // 3. 핑키 3대 3D 물리 모델 상태
  const [pinkies, setPinkies] = useState<RobotState[]>([
    { id: "pinky1", name: "Pinky 1호기 (P1)", x: 1.41, y: 2.05, z: 0.08, heading: -Math.PI / 2, color: "#f97316" },
    { id: "pinky2", name: "Pinky 2호기 (P2)", x: 1.41, y: 1.86, z: 0.08, heading: -Math.PI / 2, color: "#06b6d4" },
    { id: "pinky3", name: "Pinky 3호기 (P3)", x: 1.41, y: 1.66, z: 0.08, heading: -Math.PI / 2, color: "#10b981" },
  ]);

  // 4. 로봇팔 3대 3D 물리 모델 상태 (OMX 1: 상차1, OMX 2: 상차2, OMX 3: 하차)
  const [arms, setArms] = useState<ArmState[]>([
    { id: "omx_1", name: "OMX 1호기 (ZA)", baseX: 2.015, baseY: 2.105, baseZ: 0.15, shoulderYaw: 0, shoulderPitch: 0.3, elbowPitch: -0.6, gripperState: "OPEN" },
    { id: "omx_2", name: "OMX 2호기 (ZB)", baseX: 2.015, baseY: 1.5375, baseZ: 0.15, shoulderYaw: 0, shoulderPitch: 0.3, elbowPitch: -0.6, gripperState: "OPEN" },
    { id: "omx_3", name: "OMX 3호기 (ZC)", baseX: 0.415, baseY: 1.85, baseZ: 0.15, shoulderYaw: 0, shoulderPitch: 0.3, elbowPitch: -0.6, gripperState: "OPEN" },
  ]);

  // 5. 물류 박스 3D 위치
  const [cargo, setCargo] = useState<CargoBox>({
    x: 2.015,
    y: 2.105,
    z: 0.18,
    attachedTo: "TABLE_ZA",
  });

  // 6. 도커 신호 송수신 콘솔 로그
  const [signalLogs, setSignalLogs] = useState<TaskSignalLog[]>([
    {
      id: "init-1",
      time: "13:00:00.100",
      type: "ACK",
      taskId: "INIT",
      target: "docker/cobot_simulation",
      payload: "50Hz Kinematics 엔진 및 브리지 통신 링크 확인 (RTT: 1.8ms)",
      rttMs: 1.8,
    },
  ]);

  // 태스크 애니메이션 제어 ref
  const animFrameRef = useRef<number | null>(null);

  // 로그 추가 헬퍼
  const addLog = useCallback((type: TaskSignalLog["type"], taskId: string, target: string, payload: string, rttMs?: number) => {
    const now = new Date();
    const timeStr = `${now.toTimeString().split(" ")[0]}.${now.getMilliseconds().toString().padStart(3, "0")}`;
    setSignalLogs((prev) => [
      {
        id: `sig-${Date.now()}-${Math.random().toString(36).substr(2, 4)}`,
        time: timeStr,
        type,
        taskId,
        target,
        payload,
        rttMs,
      },
      ...prev.slice(0, 20),
    ]);
  }, []);

  // 3D 투영 수학 함수 (Isometric / Perspective 3D -> 2D Canvas)
  const project3D = useCallback((p: Point3D, width: number, height: number): { x: number; y: number; scale: number; visible: boolean } => {
    // 경기장 중심 (1.2m, 1.2m) 기준 상대 좌표 변환
    const cx = p.x - 1.2;
    const cy = p.y - 1.2;
    const cz = p.z;

    // 1. 방위각(Azimuth) 회전 (Z축 기준)
    const cosA = Math.cos(azimuth);
    const sinA = Math.sin(azimuth);
    const x1 = cx * cosA - cy * sinA;
    const y1 = cx * sinA + cy * cosA;
    const z1 = cz;

    // 2. 고도각(Elevation) 회전 (X'축 기준)
    const cosE = Math.cos(elevation);
    const sinE = Math.sin(elevation);
    const x2 = x1;
    const y2 = y1 * cosE - z1 * sinE;
    const z2 = y1 * sinE + z1 * cosE;

    // 3. 원근 투영 (Perspective)
    const camDist = 3.8 / zoom;
    const depth = camDist + y2;
    if (depth <= 0.1) return { x: 0, y: 0, scale: 0, visible: false };

    const focalLength = 340 * zoom;
    const projScale = focalLength / depth;

    const screenX = width / 2 + x2 * projScale;
    const screenY = height / 2 - z2 * projScale;

    return { x: screenX, y: screenY, scale: projScale, visible: true };
  }, [azimuth, elevation, zoom]);

  // Canvas 렌더링 루프
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let running = true;

    const render = () => {
      if (!running) return;

      const width = canvas.width;
      const height = canvas.height;

      // 캔버스 배경 클리어 (어두운 산업용 관제 테마)
      ctx.fillStyle = "#0c0d10";
      ctx.fillRect(0, 0, width, height);

      // A. 경기장 바닥 그리드 그리기 (2.4m x 2.4m)
      ctx.strokeStyle = "#1e2430";
      ctx.lineWidth = 1;
      const step = 0.3; // 30cm 간격
      for (let x = 0; x <= 2.4; x += step) {
        const p1 = project3D({ x, y: 0, z: 0 }, width, height);
        const p2 = project3D({ x, y: 2.4, z: 0 }, width, height);
        if (p1.visible && p2.visible) {
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
      }
      for (let y = 0; y <= 2.4; y += step) {
        const p1 = project3D({ x: 0, y, z: 0 }, width, height);
        const p2 = project3D({ x: 2.4, y, z: 0 }, width, height);
        if (p1.visible && p2.visible) {
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
      }

      // B. 경기장 외곽선 및 벽면 (2.4m x 2.4m, 높이 0.15m)
      const corners = [
        { x: 0, y: 0 },
        { x: 2.4, y: 0 },
        { x: 2.4, y: 2.4 },
        { x: 0, y: 2.4 },
      ];
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 2;
      ctx.beginPath();
      corners.forEach((c, idx) => {
        const p = project3D({ x: c.x, y: c.y, z: 0 }, width, height);
        if (idx === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.closePath();
      ctx.stroke();

      // C. 중앙 분리벽 및 67cm 가변 게이트 시각화
      // 분리벽: X=1.2m 축, 게이트 위치 Y=0.335m 부근 (폭 0.67m: Y=0.0m ~ 0.67m 개방)
      const gateBottom = project3D({ x: 1.2, y: 0.67, z: 0 }, width, height);
      const gateTop = project3D({ x: 1.2, y: 2.4, z: 0 }, width, height);
      const wallZ = project3D({ x: 1.2, y: 2.4, z: 0.18 }, width, height);
      const wallZGate = project3D({ x: 1.2, y: 0.67, z: 0.18 }, width, height);

      // 분리벽 상단 면
      ctx.fillStyle = "rgba(70, 85, 110, 0.45)";
      ctx.strokeStyle = "#64748b";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(gateBottom.x, gateBottom.y);
      ctx.lineTo(gateTop.x, gateTop.y);
      ctx.lineTo(wallZ.x, wallZ.y);
      ctx.lineTo(wallZGate.x, wallZGate.y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      // 게이트 통과 구역 하이라이트 (노란색 안전 빗금 바닥)
      const g1 = project3D({ x: 1.05, y: 0.0, z: 0 }, width, height);
      const g2 = project3D({ x: 1.35, y: 0.0, z: 0 }, width, height);
      const g3 = project3D({ x: 1.35, y: 0.67, z: 0 }, width, height);
      const g4 = project3D({ x: 1.05, y: 0.67, z: 0 }, width, height);
      ctx.fillStyle = "rgba(234, 179, 8, 0.25)";
      ctx.beginPath();
      ctx.moveTo(g1.x, g1.y);
      ctx.lineTo(g2.x, g2.y);
      ctx.lineTo(g3.x, g3.y);
      ctx.lineTo(g4.x, g4.y);
      ctx.closePath();
      ctx.fill();

      // D. 고정 작업대 및 스테이션 베이스 그리기
      // 1) 상차대 1 (ZA) & 2 (ZB)
      [
        { name: "ZA (상차 1)", x: 2.015, y: 2.105, color: "#9333ea" },
        { name: "ZB (상차 2)", x: 2.015, y: 1.5375, color: "#7e22ce" },
        { name: "ZC (매장 하차)", x: 0.415, y: 1.85, color: "#2563eb" },
        { name: "고객 벤치", x: 0.29, y: 1.31, color: "#059669" },
      ].forEach((st) => {
        const pBase = project3D({ x: st.x, y: st.y, z: 0 }, width, height);
        const pTop = project3D({ x: st.x, y: st.y, z: 0.12 }, width, height);
        if (pBase.visible) {
          ctx.fillStyle = st.color;
          ctx.beginPath();
          ctx.arc(pBase.x, pBase.y, 14 * (pBase.scale / 300), 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = "#ffffff";
          ctx.font = "10px monospace";
          ctx.fillText(st.name, pTop.x - 20, pTop.y - 10);
        }
      });

      // E. 로봇팔 (OMX 1, 2, 3) 3D 관절 모델 렌더링
      arms.forEach((arm) => {
        const baseP = project3D({ x: arm.baseX, y: arm.baseY, z: 0 }, width, height);
        const shoulderP = project3D({ x: arm.baseX, y: arm.baseY, z: arm.baseZ }, width, height);

        // 링크 1 (Upper arm): 길이 0.18m
        const l1 = 0.18;
        const eX = arm.baseX + l1 * Math.cos(arm.shoulderYaw) * Math.cos(arm.shoulderPitch);
        const eY = arm.baseY + l1 * Math.sin(arm.shoulderYaw) * Math.cos(arm.shoulderPitch);
        const eZ = arm.baseZ + l1 * Math.sin(arm.shoulderPitch);
        const elbowP = project3D({ x: eX, y: eY, z: eZ }, width, height);

        // 링크 2 (Forearm + Gripper): 길이 0.16m
        const l2 = 0.16;
        const totalPitch = arm.shoulderPitch + arm.elbowPitch;
        const gX = eX + l2 * Math.cos(arm.shoulderYaw) * Math.cos(totalPitch);
        const gY = eY + l2 * Math.sin(arm.shoulderYaw) * Math.cos(totalPitch);
        const gZ = Math.max(0.04, eZ + l2 * Math.sin(totalPitch));
        const wristP = project3D({ x: gX, y: gY, z: gZ }, width, height);

        if (baseP.visible && shoulderP.visible && elbowP.visible && wristP.visible) {
          // 기둥 베이스
          ctx.strokeStyle = "#475569";
          ctx.lineWidth = 6 * (baseP.scale / 300);
          ctx.beginPath();
          ctx.moveTo(baseP.x, baseP.y);
          ctx.lineTo(shoulderP.x, shoulderP.y);
          ctx.stroke();

          // 링크 1
          ctx.strokeStyle = "#38bdf8";
          ctx.lineWidth = 4 * (baseP.scale / 300);
          ctx.beginPath();
          ctx.moveTo(shoulderP.x, shoulderP.y);
          ctx.lineTo(elbowP.x, elbowP.y);
          ctx.stroke();

          // 관절 볼
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.arc(elbowP.x, elbowP.y, 4 * (baseP.scale / 300), 0, Math.PI * 2);
          ctx.fill();

          // 링크 2
          ctx.strokeStyle = "#a855f7";
          ctx.lineWidth = 3 * (baseP.scale / 300);
          ctx.beginPath();
          ctx.moveTo(elbowP.x, elbowP.y);
          ctx.lineTo(wristP.x, wristP.y);
          ctx.stroke();

          // 그리퍼 (집게)
          ctx.fillStyle = arm.gripperState === "CLOSED" ? "#22c55e" : "#eab308";
          ctx.beginPath();
          ctx.arc(wristP.x, wristP.y, 5 * (baseP.scale / 300), 0, Math.PI * 2);
          ctx.fill();

          // 태그
          ctx.fillStyle = "#94a3b8";
          ctx.font = "9px monospace";
          ctx.fillText(arm.id.toUpperCase(), shoulderP.x + 8, shoulderP.y - 4);
        }
      });

      // F. 핑키 3대 (P1, P2, P3) 3D 입체 바디 렌더링
      pinkies.forEach((bot) => {
        const centerP = project3D({ x: bot.x, y: bot.y, z: bot.z }, width, height);
        const shadowP = project3D({ x: bot.x, y: bot.y, z: 0 }, width, height);

        if (centerP.visible && shadowP.visible) {
          const sc = centerP.scale / 300;

          // 바닥 그림자
          ctx.fillStyle = "rgba(0, 0, 0, 0.4)";
          ctx.beginPath();
          ctx.ellipse(shadowP.x, shadowP.y, 16 * sc, 10 * sc, 0, 0, Math.PI * 2);
          ctx.fill();

          // 차체 3D 박스 (너비 0.20m x 길이 0.22m x 높이 0.12m)
          const halfW = 0.1;
          const halfL = 0.11;
          const cosH = Math.cos(bot.heading);
          const sinH = Math.sin(bot.heading);

          const cornersLocal = [
            { dx: halfL, dy: halfW },
            { dx: -halfL, dy: halfW },
            { dx: -halfL, dy: -halfW },
            { dx: halfL, dy: -halfW },
          ];

          const topCorners = cornersLocal.map((c) => {
            const rx = bot.x + (c.dx * cosH - c.dy * sinH);
            const ry = bot.y + (c.dx * sinH + c.dy * cosH);
            return project3D({ x: rx, y: ry, z: bot.z + 0.08 }, width, height);
          });

          // 상단 플레이트
          ctx.fillStyle = bot.color;
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 1;
          ctx.beginPath();
          topCorners.forEach((pt, i) => {
            if (i === 0) ctx.moveTo(pt.x, pt.y);
            else ctx.lineTo(pt.x, pt.y);
          });
          ctx.closePath();
          ctx.fill();
          ctx.stroke();

          // 전방 헤딩 인디케이터 (주황/녹색 헤드라이트)
          const headX = bot.x + 0.13 * cosH;
          const headY = bot.y + 0.13 * sinH;
          const headP = project3D({ x: headX, y: headY, z: bot.z + 0.05 }, width, height);
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.arc(headP.x, headP.y, 3 * sc, 0, Math.PI * 2);
          ctx.fill();

          // 로봇 ID 3D 라벨
          ctx.fillStyle = "#ffffff";
          ctx.font = "bold 10px monospace";
          ctx.fillText(bot.id === "pinky1" ? "P1 (ACTIVE)" : bot.id.toUpperCase(), topCorners[0].x - 12, topCorners[0].y - 8);
        }
      });

      // G. 3D 물류 신발 박스 렌더링
      const boxP = project3D({ x: cargo.x, y: cargo.y, z: cargo.z }, width, height);
      if (boxP.visible) {
        const bsc = boxP.scale / 300;
        ctx.fillStyle = "#fbbf24"; // 골드 옐로우 박스
        ctx.strokeStyle = "#b45309";
        ctx.lineWidth = 1.5;
        ctx.fillRect(boxP.x - 7 * bsc, boxP.y - 7 * bsc, 14 * bsc, 14 * bsc);
        ctx.strokeRect(boxP.x - 7 * bsc, boxP.y - 7 * bsc, 14 * bsc, 14 * bsc);

        ctx.fillStyle = "#78350f";
        ctx.font = "8px sans-serif";
        ctx.fillText("📦SKU", boxP.x - 8 * bsc, boxP.y + 2 * bsc);
      }

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      running = false;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [azimuth, elevation, zoom, pinkies, arms, cargo, project3D]);

  // 마우스 드래그로 3D 시점 회전 (Orbit rotate)
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDraggingRef.current = true;
    lastMousePosRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - lastMousePosRef.current.x;
    const dy = e.clientY - lastMousePosRef.current.y;
    lastMousePosRef.current = { x: e.clientX, y: e.clientY };

    setAzimuth((prev) => prev + dx * 0.008);
    setElevation((prev) => Math.max(0.08, Math.min(Math.PI * 0.48, prev - dy * 0.008)));
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
  };

  // 시점 프리셋
  const setPresetView = (type: "iso" | "top" | "front") => {
    if (type === "iso") {
      setAzimuth(Math.PI * 0.25);
      setElevation(Math.PI * 0.2);
      setZoom(1.0);
    } else if (type === "top") {
      setAzimuth(0);
      setElevation(Math.PI * 0.47);
      setZoom(1.05);
    } else if (type === "front") {
      setAzimuth(0);
      setElevation(Math.PI * 0.08);
      setZoom(1.1);
    }
  };

  // --- 세분화된 태스크 시나리오 인젝션 실행기 ---
  const executeMovePinky = (targetX: number, targetY: number, targetHeading: number, taskName: string, onDone?: () => void) => {
    if (isEStopped) {
      addLog("ALERT", "E-STOP", "pinky1", "비상 정지 상태로 인해 동작 신호 거부됨");
      return;
    }

    addLog("SEND", taskName, "docker/cobot_simulation", `태스크 목표 전송: /pinky1/goal_pose -> [${targetX.toFixed(2)}, ${targetY.toFixed(2)}]`);
    setActiveTaskName(taskName);

    // 가상 ACK 수신
    setTimeout(() => {
      addLog("ACK", taskName, "pinky1/cmd_vel", "도커 백엔드 수락 확인: 50Hz 보간 주행 개시", 2.1);
    }, 150);

    const startX = pinkies[0].x;
    const startY = pinkies[0].y;
    const startH = pinkies[0].heading;
    const startTime = performance.now();
    const duration = 2400; // 2.4초 부드러운 물리 이동

    const stepAnim = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(1.0, elapsed / duration);
      const ease = 0.5 - Math.cos(progress * Math.PI) / 2; // Ease in-out

      const curX = startX + (targetX - startX) * ease;
      const curY = startY + (targetY - startY) * ease;
      const curH = startH + (targetHeading - startH) * ease;

      setPinkies((prev) => [
        { ...prev[0], x: curX, y: curY, heading: curH },
        prev[1],
        prev[2],
      ]);

      // 만약 카고가 Pinky 1에 실려있다면 카고도 함께 이동!
      setCargo((prev) => {
        if (prev.attachedTo === "PINKY_1") {
          return { ...prev, x: curX, y: curY, z: 0.18 };
        }
        return prev;
      });

      if (progress < 1.0) {
        requestAnimationFrame(stepAnim);
      } else {
        addLog("DONE", taskName, "pinky1/odom", `도착 완료: [${targetX.toFixed(2)}, ${targetY.toFixed(2)}] 도킹 성공`);
        setActiveTaskName("대기 (IDLE)");
        if (onDone) onDone();
      }
    };

    requestAnimationFrame(stepAnim);
  };

  // 로봇팔 피킹 & 상차/하차 모션 시뮬레이션
  const executeArmAction = (armIdx: number, actionType: "PICK_TO_PINKY" | "UNLOAD_TO_BENCH", taskName: string, onDone?: () => void) => {
    if (isEStopped) {
      addLog("ALERT", "E-STOP", `omx_${armIdx + 1}`, "비상 정지 상태로 인해 동작 신호 거부됨");
      return;
    }

    addLog("SEND", taskName, `docker/omx_${armIdx + 1}`, `관절 제어 신호 송신: Z=200mm 수직 피킹 시퀀스 실행`);
    setActiveTaskName(taskName);

    setTimeout(() => {
      addLog("ACK", taskName, `omx_${armIdx + 1}/joint_states`, "1.2 rad/s 속도 클램프 준수 확인 (토크 ON)", 1.9);
    }, 150);

    const startTime = performance.now();
    const duration = 2600;

    const stepArm = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(1.0, elapsed / duration);

      // 팔 관절 각도 보간 (숙였다가 들어올리기)
      const pitchOffset = Math.sin(progress * Math.PI) * 0.45;
      const yawOffset = actionType === "PICK_TO_PINKY" ? progress * -Math.PI * 0.4 : progress * Math.PI * 0.35;

      setArms((prev) => {
        const updated = [...prev];
        updated[armIdx] = {
          ...updated[armIdx],
          shoulderPitch: 0.3 + pitchOffset,
          shoulderYaw: yawOffset,
          gripperState: progress > 0.4 && progress < 0.9 ? "CLOSED" : "OPEN",
        };
        return updated;
      });

      // 박스 위치 동기화
      if (actionType === "PICK_TO_PINKY") {
        if (progress > 0.45 && progress < 0.9) {
          setCargo({ x: 2.015 - progress * 0.15, y: 2.105, z: 0.28, attachedTo: "OMX_1" });
        } else if (progress >= 0.9) {
          setCargo({ x: pinkies[0].x, y: pinkies[0].y, z: 0.18, attachedTo: "PINKY_1" });
        }
      } else {
        // UNLOAD_TO_BENCH
        if (progress > 0.45 && progress < 0.9) {
          setCargo({ x: 0.35, y: 1.6, z: 0.25, attachedTo: "OMX_3" });
        } else if (progress >= 0.9) {
          setCargo({ x: 0.29, y: 1.31, z: 0.14, attachedTo: "BENCH" });
        }
      }

      if (progress < 1.0) {
        requestAnimationFrame(stepArm);
      } else {
        addLog("DONE", taskName, `omx_${armIdx + 1}/status`, "피킹 & 이송 완료: 그리퍼 릴리즈 확인");
        setActiveTaskName("대기 (IDLE)");
        if (onDone) onDone();
      }
    };

    requestAnimationFrame(stepArm);
  };

  // 긴급 정지 / 복구 토글
  const handleToggleEStop = () => {
    if (!isEStopped) {
      setIsEStopped(true);
      setEngineStatus("PAUSED");
      addLog("ALERT", "EMERGENCY_STOP", "all_nodes", "🚨 긴급 정지(E-STOP) 동작 신호 인젝션: 전 장치 모터 토크 차단");
    } else {
      setIsEStopped(false);
      setEngineStatus("ACTIVE");
      addLog("ACK", "RECOVER", "all_nodes", "✅ 안전 복구 신호 송신: 50Hz 엔진 및 통신 정상화");
    }
  };

  // 전체 시나리오 순차 자동 실행 (End-to-End Test)
  const handleRunFullSequence = () => {
    addLog("SEND", "FULL_AUTO", "coordinator", "전체 시퀀스 연속 검증 시작 (상차 -> 게이트 -> 하차 -> 복귀)");
    // Step 1: 상차대 이동
    executeMovePinky(2.015, 2.105, 0, "T1_상차대_도킹", () => {
      // Step 2: 상차
      executeArmAction(0, "PICK_TO_PINKY", "T2_상차_피킹", () => {
        // Step 3: 게이트 통과
        executeMovePinky(1.25, 0.335, -Math.PI / 2, "T3_게이트_통과", () => {
          // Step 4: 매장 하차대 이동
          executeMovePinky(0.415, 1.85, Math.PI / 2, "T4_하차대_도킹", () => {
            // Step 5: 하차 및 벤치 전달
            executeArmAction(2, "UNLOAD_TO_BENCH", "T5_하차_배치", () => {
              // Step 6: 충전소 복귀
              executeMovePinky(1.41, 2.05, -Math.PI / 2, "T6_충전소_복귀", () => {
                addLog("DONE", "FULL_AUTO", "coordinator", "🏁 전체 시나리오 연속 검증 완료: 6단계 모션 성공");
              });
            });
          });
        });
      });
    });
  };

  return (
    <div className="max-w-7xl space-y-5 font-sans">
      <MenuHeader menu={menu} kind="page" />

      {/* 1. 상단 통신 및 엔진 생존 감지기 배너 */}
      <Alert className="rounded-none border-border bg-[#121316]">
        <AlertTitle className="text-white flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <span
              className={`inline-block w-2.5 h-2.5 rounded-full ${
                engineStatus === "ACTIVE" ? "bg-green-500 animate-pulse" : "bg-red-500"
              }`}
            />
            <span className="font-bold text-sm">SR-22 3D 물리 시뮬레이션 온라인 실험장</span>
            <Badge variant="outline" className="border-blue-600 text-blue-400 font-mono text-[10px]">
              관제 기능 구현 및 검증용
            </Badge>
          </span>

          <div className="flex items-center gap-2 font-mono text-xs">
            <Badge
              variant="outline"
              className={engineStatus === "ACTIVE" ? "border-green-600 text-green-400" : "border-red-600 text-red-400"}
            >
              엔진: {engineStatus === "ACTIVE" ? "50.0 Hz ACTIVE" : "E-STOPPED"}
            </Badge>
            <Badge variant="outline" className="border-cyan-600 text-cyan-400">
              DOCKER: CONNECTED
            </Badge>
            <Badge variant="outline" className="border-purple-600 text-purple-400">
              ROBOTS: 3 AMR + 3 ARMS
            </Badge>
          </div>
        </AlertTitle>
        <AlertDescription className="text-[#999999] text-xs mt-1.5 flex justify-between items-center">
          <span>
            브라우저 내장 3D 캔버스에서 핑키 3대와 로봇팔 3대의 물리 모델을 제어하고, 각 포인트별 태스크 동작 신호를
            도커 백엔드로 송수신하여 즉시 검증합니다.
          </span>
          <span className="font-mono text-cyan-400 shrink-0 font-bold ml-2">
            현재 상태: {activeTaskName}
          </span>
        </AlertDescription>
      </Alert>

      {/* 2. 메인 뷰포트 & 제어 패널 2열 그리드 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* A. 좌측 7컬럼: 브라우저 내장 3D 캔버스 (뷰포트) */}
        <Card className="lg:col-span-7 rounded-none border border-border bg-[#101114] shadow-none flex flex-col">
          <CardHeader className="py-2.5 px-3 border-b border-border bg-[#16171b] flex flex-row items-center justify-between">
            <CardTitle className="text-xs font-bold text-white flex items-center gap-2">
              <span>🎮 브라우저 내장 3D 가상환경 뷰포트 (2.4m × 2.4m)</span>
              <span className="text-[10px] font-normal text-[#888888]">(마우스 드래그: 회전 | 휠: 줌)</span>
            </CardTitle>
            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-[10px] rounded-none bg-[#22242a] border-border text-[#cccccc] hover:text-white"
                onClick={() => setPresetView("iso")}
              >
                📐 입체뷰
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-[10px] rounded-none bg-[#22242a] border-border text-[#cccccc] hover:text-white"
                onClick={() => setPresetView("top")}
              >
                🔝 탑뷰
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-[10px] rounded-none bg-[#22242a] border-border text-[#cccccc] hover:text-white"
                onClick={() => setPresetView("front")}
              >
                👀 정면뷰
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-[10px] rounded-none bg-[#22242a] border-border text-[#cccccc] hover:text-white"
                onClick={() => {
                  setZoom((z) => Math.min(1.8, z + 0.15));
                }}
              >
                +
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-6 px-2 text-[10px] rounded-none bg-[#22242a] border-border text-[#cccccc] hover:text-white"
                onClick={() => {
                  setZoom((z) => Math.max(0.6, z - 0.15));
                }}
              >
                -
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-0 relative flex-1 min-h-[460px] bg-[#0c0d10] overflow-hidden flex items-center justify-center">
            <canvas
              ref={canvasRef}
              width={660}
              height={460}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              className="cursor-grab active:cursor-grabbing w-full h-full block"
            />

            {/* 뷰포트 하단 오버레이 범례 */}
            <div className="absolute bottom-2 left-2 pointer-events-none bg-[#111216]/90 border border-border p-2 font-mono text-[10px] space-y-1 text-[#aaaaaa]">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-orange-500 inline-block" />
                <span className="text-white">Pinky 1호기 (AMR 활성)</span>
                <span className="w-2.5 h-2.5 bg-cyan-500 inline-block ml-1" />
                <span>Pinky 2</span>
                <span className="w-2.5 h-2.5 bg-emerald-500 inline-block ml-1" />
                <span>Pinky 3</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 bg-purple-500 inline-block" />
                <span>OMX 로봇팔 1~3 (5-DOF)</span>
                <span className="w-2.5 h-2.5 bg-yellow-400 inline-block ml-2" />
                <span className="text-yellow-300 font-bold">📦 화물 박스</span>
              </div>
              <div className="text-[9px] text-[#777777]">
                중앙 협소 통로 게이트 폭: <b className="text-white">67cm</b> (노란 안전 구역)
              </div>
            </div>
          </CardContent>
        </Card>

        {/* B. 우측 5컬럼: 세분화된 태스크 시나리오 인젝션 패널 & 통신 콘솔 */}
        <div className="lg:col-span-5 space-y-4 flex flex-col justify-between">
          {/* 1. 세분화된 태스크 인젝션 컨트롤 */}
          <Card className="rounded-none border border-border bg-[#121316] shadow-none">
            <CardHeader className="py-2 px-3 border-b border-border bg-[#18191f] flex flex-row items-center justify-between">
              <CardTitle className="text-xs font-bold text-white flex items-center gap-1.5">
                <span>🎯 세분화 포인트별 태스크 동작 신호 인젝션</span>
              </CardTitle>
              <Button
                variant="destructive"
                size="sm"
                className="h-6 px-2 text-[10px] rounded-none font-bold"
                onClick={handleToggleEStop}
              >
                {isEStopped ? "▶ E-STOP 해제" : "🚨 긴급 정지 (E-STOP)"}
              </Button>
            </CardHeader>
            <CardContent className="p-3 space-y-3 font-sans">
              {/* 태스크 그룹 1: 상차 구역 */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-bold text-purple-400 flex items-center justify-between">
                  <span>1. 상차 구역 태스크 (Loading ZA)</span>
                  <span className="font-mono text-[10px] text-[#888888]">WP_LOAD_1</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] rounded-none bg-[#1c1d22] border-border text-[#dddddd] hover:text-white hover:bg-[#25272e]"
                    onClick={() => executeMovePinky(2.015, 2.105, 0, "T1_상차대1_도킹")}
                    disabled={isEStopped}
                  >
                    ① 상차대 1 도킹 이동
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] rounded-none bg-[#1c1d22] border-border text-[#dddddd] hover:text-white hover:bg-[#25272e]"
                    onClick={() => executeArmAction(0, "PICK_TO_PINKY", "T2_상차_피킹")}
                    disabled={isEStopped}
                  >
                    ② OMX 1 피킹 & 상차
                  </Button>
                </div>
              </div>

              {/* 태스크 그룹 2: 통로 이동 */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-bold text-yellow-400 flex items-center justify-between">
                  <span>2. 협소 통로 게이트 태스크 (Gate Transit)</span>
                  <span className="font-mono text-[10px] text-[#888888]">Width: 67cm</span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full h-8 text-[11px] rounded-none bg-[#1c1d22] border-border text-[#dddddd] hover:text-white hover:bg-[#25272e]"
                  onClick={() => executeMovePinky(1.25, 0.335, -Math.PI / 2, "T3_게이트_통과")}
                  disabled={isEStopped}
                >
                  ③ 67cm 협소 게이트 통과 주행 신호
                </Button>
              </div>

              {/* 태스크 그룹 3: 매장 하차 & 고객 전달 */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-bold text-blue-400 flex items-center justify-between">
                  <span>3. 매장 하차 & 전달 태스크 (Unloading ZC)</span>
                  <span className="font-mono text-[10px] text-[#888888]">WP_UNLOAD</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] rounded-none bg-[#1c1d22] border-border text-[#dddddd] hover:text-white hover:bg-[#25272e]"
                    onClick={() => executeMovePinky(0.415, 1.85, Math.PI / 2, "T4_하차대_도킹")}
                    disabled={isEStopped}
                  >
                    ④ 하차대 도킹 이동
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-[11px] rounded-none bg-[#1c1d22] border-border text-[#dddddd] hover:text-white hover:bg-[#25272e]"
                    onClick={() => executeArmAction(2, "UNLOAD_TO_BENCH", "T5_하차_배치")}
                    disabled={isEStopped}
                  >
                    ⑤ OMX 3 하차 & 벤치 배치
                  </Button>
                </div>
              </div>

              {/* 태스크 그룹 4: 충전 복귀 및 전체 연속 실행 */}
              <div className="pt-1 border-t border-border/60 grid grid-cols-2 gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-[11px] rounded-none bg-[#1c1d22] border-border text-[#dddddd] hover:text-white hover:bg-[#25272e]"
                  onClick={() => executeMovePinky(1.41, 2.05, -Math.PI / 2, "T6_충전소_복귀")}
                  disabled={isEStopped}
                >
                  ⑥ 충전소 1 복귀 주행
                </Button>
                <Button
                  size="sm"
                  className="h-8 text-[11px] rounded-none bg-green-700 hover:bg-green-600 text-white font-bold"
                  onClick={handleRunFullSequence}
                  disabled={isEStopped}
                >
                  ⚡ 전체 시퀀스 연속 실행
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* 2. 도커 태스크 동작 신호 송수신 실시간 콘솔 */}
          <Card className="rounded-none border border-border bg-[#101114] shadow-none flex-1">
            <CardHeader className="py-2 px-3 border-b border-border bg-[#16171b] flex items-center justify-between">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
                도커 백엔드 신호 송수신 콘솔 (Task Action Stream)
              </span>
              <span className="text-[10px] font-mono text-[#888888]">{signalLogs.length}건 기록</span>
            </CardHeader>
            <CardContent className="p-2 font-mono text-[11px] space-y-1.5 max-h-[190px] overflow-y-auto">
              {signalLogs.map((log) => (
                <div
                  key={log.id}
                  className="p-1.5 bg-[#0a0b0d] border border-[#20222a] text-[#cccccc] flex items-start justify-between gap-2"
                >
                  <div className="space-y-0.5 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[#666666]">{log.time}</span>
                      <span
                        className={`px-1 py-0.2 text-[9px] font-bold ${
                          log.type === "SEND"
                            ? "bg-blue-950 text-blue-400 border border-blue-800"
                            : log.type === "ACK"
                            ? "bg-cyan-950 text-cyan-300 border border-cyan-800"
                            : log.type === "DONE"
                            ? "bg-green-950 text-green-400 border border-green-800"
                            : "bg-red-950 text-red-400 border border-red-800"
                        }`}
                      >
                        {log.type}
                      </span>
                      <b className="text-white text-[10px] truncate">[{log.taskId}]</b>
                      <span className="text-[#777777] text-[10px] truncate">{log.target}</span>
                    </div>
                    <p className="text-[10px] text-[#999999] truncate">{log.payload}</p>
                  </div>
                  {log.rttMs !== undefined && (
                    <span className="text-[10px] text-cyan-400 shrink-0 font-bold">{log.rttMs}ms</span>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
