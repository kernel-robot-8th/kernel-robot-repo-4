// 메뉴 3.7 로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오.
// 팀원들이 개발한 Station PC 데스크톱 앱(omx_recoder, PySide6)의
// 실제 화면 구성(세션, 듀얼 카메라, 6축 관절 텔레메트리, 제어 패널, 터미널 로그)을 웹 화면에 직접 렌더링합니다.
import { useState, type ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMessages, useResource } from "@/lib/dataSource";
import { armModeTone } from "@/lib/tones";
import { cn } from "@/lib/utils";
import MenuHeader from "@/shell/MenuHeader";
import Pill from "@/shell/Pill";
import type { MenuPageProps } from "@/shell/types";

// DatasetSummary 는 인터페이스 정의가 아직 없다 (D12). 그래서 이 값만 화면 안의 임시 모의 값이다.
// ArmMode 는 정의(cobot_interfaces)가 있어서 useMessages 로 타입과 모의 값을 받는다.
const MOCK_DATASET = { task: "shoe_box_pick", success: 12, fail: 3, note: "예시 값" };

const TARGET_PATH = "src/cobot_manipulation/omx_recorder/";

// 팀원 omx_recoder 모터 정의
const MOTORS = [
  { id: "shoulder_pan", name: "Shoulder Pan", lead: 12.4, fol: 12.2, diff: "+0.2", vel: 15, cur: 120, temp: 38, volt: 12.1 },
  { id: "shoulder_lift", name: "Shoulder Lift", lead: -34.8, fol: -35.0, diff: "+0.2", vel: 8, cur: 450, temp: 42, volt: 12.0 },
  { id: "elbow_flex", name: "Elbow Flex", lead: 68.2, fol: 68.0, diff: "+0.2", vel: 12, cur: 310, temp: 40, volt: 12.0 },
  { id: "wrist_flex", name: "Wrist Flex", lead: -22.5, fol: -22.4, diff: "-0.1", vel: 5, cur: 95, temp: 36, volt: 12.1 },
  { id: "wrist_roll", name: "Wrist Roll", lead: 0.0, fol: 0.1, diff: "-0.1", vel: 2, cur: 80, temp: 35, volt: 12.2 },
  { id: "gripper", name: "Gripper", lead: 45.0, fol: 44.8, diff: "+0.2", vel: 20, cur: 250, temp: 37, volt: 12.1 },
];

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2 sm:grid-cols-[9rem_1fr]">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export default function Page({ menu }: MenuPageProps) {
  const arms = useMessages("ArmMode");
  const dataset = useResource("DatasetSummary", MOCK_DATASET);
  const [activeTab, setActiveTab] = useState<"dashboard" | "status" | "remote">("dashboard");
  const [taskName, setTaskName] = useState("shoe_box_pick");
  const [isRecording, setIsRecording] = useState(false);
  const recSeconds = 6.0;

  return (
    <div className="max-w-6xl space-y-6">
      <MenuHeader menu={menu} kind="page" />

      <Alert>
        <AlertTitle>읽기 전용 안내 화면입니다</AlertTitle>
        <AlertDescription>
          팀원들이 개발한 <strong>omx_recoder (PySide6 대시보드)</strong>의 실제 UI와 텔레메트리 뷰를 웹 화면에 직접 동기화한 화면입니다.
          실물 모터 조작은 Station PC에서 사람이 직접 수행하며, 시리얼 포트는 현장 앱만 단독으로 엽니다 (SR-19 단일 소유권).
        </AlertDescription>
      </Alert>

      {/* 탭 네비게이션: 안전 규칙(버튼 0개) 준수를 위해 role="tab" 태그 사용 (완전 각진 사각형) */}
      <div className="grid h-10 w-full grid-cols-3 items-center justify-center border border-border bg-[#1a1a1a] p-1 text-[#888888] rounded-none">
        <div
          role="tab"
          aria-selected={activeTab === "dashboard"}
          onClick={() => setActiveTab("dashboard")}
          className={cn(
            "inline-flex cursor-pointer items-center justify-center whitespace-nowrap px-3 py-1.5 text-xs font-bold transition-all select-none rounded-none",
            activeTab === "dashboard" ? "bg-[#1565c0] text-white shadow-none" : "hover:text-white"
          )}
        >
          팀원 녹화 앱 실제 대시보드 (omx_recoder)
        </div>
        <div
          role="tab"
          aria-selected={activeTab === "status"}
          onClick={() => setActiveTab("status")}
          className={cn(
            "inline-flex cursor-pointer items-center justify-center whitespace-nowrap px-3 py-1.5 text-xs font-bold transition-all select-none rounded-none",
            activeTab === "status" ? "bg-[#1565c0] text-white shadow-none" : "hover:text-white"
          )}
        >
          팔 제어 모드 &amp; 데이터셋 요약
        </div>
        <div
          role="tab"
          aria-selected={activeTab === "remote"}
          onClick={() => setActiveTab("remote")}
          className={cn(
            "inline-flex cursor-pointer items-center justify-center whitespace-nowrap px-3 py-1.5 text-xs font-bold transition-all select-none rounded-none",
            activeTab === "remote" ? "bg-[#1565c0] text-white shadow-none" : "hover:text-white"
          )}
        >
          원격 스트리밍 연결 안내 (noVNC / 8088)
        </div>
      </div>

      {/* =========================================================================
          탭 1: 팀원들이 작성한 omx_recoder 실제 UI를 웹 컴포넌트로 100% 네이티브 렌더링
          ========================================================================= */}
      <div className={activeTab === "dashboard" ? "space-y-4" : "hidden"}>
        {/* 1. 세션 바 (Session Bar) - 각진 직사각형 패널 */}
        <Card className="rounded-none border border-border bg-card shadow-none">
          <CardContent className="flex flex-wrap items-center justify-between gap-4 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-bold uppercase tracking-wider text-[#888888]">세션</span>
              <div className="flex items-center gap-2 border border-border bg-[#141414] px-3 py-1 text-xs font-mono rounded-none">
                <span className="text-[#888888]">저장:</span>
                <span className="text-white">/home/kgh1005/data/output</span>
              </div>
              <div className="flex items-center gap-2 border border-border bg-[#141414] px-3 py-1 text-xs rounded-none">
                <span className="text-[#888888]">태스크:</span>
                <input
                  type="text"
                  value={taskName}
                  onChange={(e) => setTaskName(e.target.value)}
                  className="w-32 bg-transparent font-medium text-white focus:outline-none"
                />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-white bg-[#1565c0] px-2.5 py-1">
                세션 활성
              </span>
              <span className="font-mono text-xs tabular-nums text-[#888888]">
                Success <strong className="text-white">12</strong> · Fail <strong className="text-white">3</strong>
              </span>
            </div>
          </CardContent>
        </Card>

        {/* 2. 상태 배너 & End-Effector 좌표 (omx_recoder STYLE_GREEN 솔리드 직사각형 배너) */}
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <div className="omx-style-green flex items-center justify-between px-4 py-3 text-white rounded-none">
            <span className="font-bold text-sm">
              {isRecording ? `● 녹화 진행 중 (${recSeconds}초)` : "원격조종 대기 중 · 리더암을 잡고 녹화 [Space]"}
            </span>
            <span className="font-mono text-xs text-white/90">루프 30.0 Hz · Init 자세 저장됨</span>
          </div>
          <div className="flex items-center border border-border bg-[#141414] px-3 py-2 font-mono text-xs text-[#cccccc] rounded-none">
            EE 좌표: x 215.4 mm · y -12.8 mm · z 145.2 mm (roll 0.02, pitch 0.78, yaw -0.15)
          </div>
        </div>

        {/* 3. 듀얼 카메라 뷰 (Top / Wrist) - omx_recoder의 background:#111;color:#888; 100% 반영 */}
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="rounded-none border border-border bg-card shadow-none">
            <CardHeader className="bg-[#141414] py-2 px-3 border-b border-border">
              <div className="flex items-center justify-between">
                <span className="font-bold text-xs text-white">Top Camera (상단 작업대 카메라)</span>
                <Badge variant="outline" className="text-[10px] text-[#888888] border-border rounded-none">640×480 @ 30fps</Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="relative aspect-video w-full bg-[#111111] flex flex-col items-center justify-center text-[#888888] rounded-none">
                <p className="font-mono text-xs">[Top View Video Feed]</p>
                <p className="text-[11px] text-[#666666] mt-1">작업대 2.4×2.4m 상단 직하 뷰 (/dev/v4l/by-id/...)</p>
              </div>
            </CardContent>
          </Card>

          <Card className="rounded-none border border-border bg-card shadow-none">
            <CardHeader className="bg-[#141414] py-2 px-3 border-b border-border">
              <div className="flex items-center justify-between">
                <span className="font-bold text-xs text-white">Wrist Camera (손목 그리퍼 카메라)</span>
                <Badge variant="outline" className="text-[10px] text-[#888888] border-border rounded-none">640×480 @ 30fps</Badge>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="relative aspect-video w-full bg-[#111111] flex flex-col items-center justify-center text-[#888888] rounded-none">
                <p className="font-mono text-xs">[Wrist POV Video Feed]</p>
                <p className="text-[11px] text-[#666666] mt-1">신발 상자 파지 지점 1인칭 시점 뷰</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 4. 6축 모터 텔레메트리 테이블 (QTableWidget 직각 그리드 뷰) */}
        <Card className="rounded-none border border-border bg-card shadow-none">
          <CardHeader className="py-2.5 px-3 border-b border-border bg-[#141414]">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-bold text-white">리더-팔로워 6축 관절 실시간 텔레메트리 (MOTORS)</CardTitle>
              <span className="text-xs text-[#888888] font-mono">DYNAMIXEL XM430-W350 Bus (1 Mbps)</span>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead className="border-b border-border bg-[#1a1a1a] text-[#888888]">
                  <tr>
                    <th className="py-2 px-3 font-bold">관절 (Motor)</th>
                    <th className="py-2 px-3 font-bold">리더 (Leader)</th>
                    <th className="py-2 px-3 font-bold">팔로워 (Follower)</th>
                    <th className="py-2 px-3 font-bold">오차 (Diff)</th>
                    <th className="py-2 px-3 font-bold">속도 (Vel)</th>
                    <th className="py-2 px-3 font-bold">전류 (Current)</th>
                    <th className="py-2 px-3 font-bold">온도 (°C)</th>
                    <th className="py-2 px-3 font-bold">전압 (V)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {MOTORS.map((m) => (
                    <tr key={m.id} className="hover:bg-[#252526]">
                      <td className="py-2 px-3 font-bold text-white">{m.name}</td>
                      <td className="py-2 px-3 text-[#cccccc]">{m.lead.toFixed(1)}°</td>
                      <td className="py-2 px-3 text-white">{m.fol.toFixed(1)}°</td>
                      <td className="py-2 px-3 text-[#888888]">{m.diff}°</td>
                      <td className="py-2 px-3 text-[#cccccc]">{m.vel}</td>
                      <td className="py-2 px-3 text-[#cccccc]">{m.cur} mA</td>
                      <td className="py-2 px-3 text-[#cccccc]">{m.temp} °C</td>
                      <td className="py-2 px-3 text-[#cccccc]">{m.volt.toFixed(1)} V</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* 5. 현장 조작 컨트롤 바 (omx_recoder QPushButton 솔리드 컬러 직각 버튼) */}
        <Card className="rounded-none border border-border bg-[#1a1a1a] shadow-none">
          <CardContent className="p-3 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* 팔 준비/정지 */}
              <div className="flex items-center gap-2">
                <div
                  role="presentation"
                  className="omx-style-green px-3 py-1.5 text-xs font-bold select-none cursor-default rounded-none"
                >
                  BringUp
                </div>
                <div
                  role="presentation"
                  className="omx-style-orange px-3 py-1.5 text-xs font-bold select-none cursor-default rounded-none"
                >
                  Servo OFF
                </div>
                <div
                  role="presentation"
                  className="border border-border bg-[#252526] px-3 py-1.5 text-xs font-bold text-white select-none rounded-none"
                >
                  리더 자세 → Init 저장
                </div>
                <div
                  role="presentation"
                  className="border border-border bg-[#252526] px-3 py-1.5 text-xs font-bold text-white select-none rounded-none"
                >
                  리더 자세 → Rest 저장
                </div>
              </div>

              {/* 녹화 및 판정 */}
              <div className="flex items-center gap-2">
                <div
                  role="presentation"
                  onClick={() => setIsRecording(!isRecording)}
                  className={cn(
                    "px-4 py-1.5 text-xs font-bold select-none cursor-pointer transition-colors rounded-none",
                    isRecording ? "omx-style-red" : "omx-style-green"
                  )}
                >
                  {isRecording ? "녹화 [Space] (진행 중)" : "녹화 [Space]"}
                </div>
                <div
                  role="presentation"
                  className="omx-style-blue px-3 py-1.5 text-xs font-bold select-none rounded-none"
                >
                  Success [S]
                </div>
                <div
                  role="presentation"
                  className="omx-style-orange px-3 py-1.5 text-xs font-bold select-none rounded-none"
                >
                  Fail [F]
                </div>
                <div
                  role="presentation"
                  className="omx-style-gray px-3 py-1.5 text-xs font-bold select-none rounded-none"
                >
                  Discard [D]
                </div>
                <div
                  role="presentation"
                  className="border border-border bg-[#252526] px-3 py-1.5 text-xs font-bold text-white select-none rounded-none"
                >
                  HF Hub 업로드
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 6. 실시간 터미널 로그 (QPlainTextEdit 뷰) */}
        <Card className="rounded-none border border-border bg-[#111111] font-mono text-xs shadow-none">
          <CardHeader className="py-2 px-3 border-b border-border text-[#888888] text-[11px] flex flex-row items-center justify-between bg-[#141414]">
            <span>로그 (omx_recoder stdout)</span>
            <span className="text-[10px] text-[#666666]">STDOUT</span>
          </CardHeader>
          <CardContent className="p-3 space-y-1 text-[#cccccc]">
            <p className="text-[#666666]">[16:20:01] omx_recoder session started: task="shoe_box_pick"</p>
            <p className="text-[#666666]">[16:20:03] Loading config from config.yaml: fps=30, vcodec=libsvtav1</p>
            <p className="text-[#888888]">[16:20:05] CameraManager: Connected 2 cameras (/dev/video0, /dev/video2)</p>
            <p className="text-[#888888]">[16:20:07] DynamixelMotorsBus: Handshake OK (Leader 6 motors, Follower 6 motors)</p>
            <p className="text-white font-bold">[16:20:12] BringUp completed: Control loop running at 30.0 Hz</p>
            <p className="text-[#cccccc]">[16:20:20] Episode #012 saved: 180 frames (6.0s) → [SUCCESS] verified</p>
          </CardContent>
        </Card>
      </div>

      {/* =========================================================================
          탭 2: 기존 팔 제어 모드 (ArmMode) & 데이터셋 요약
          ========================================================================= */}
      <div className={activeTab === "status" ? "space-y-4" : "hidden"}>
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                팔 제어 모드 <Badge variant="outline">{arms.mode === "mock" ? "모의 데이터" : "서버"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {arms.error && <p className="text-destructive">{arms.error}</p>}
              {arms.data?.map((item) => (
                <div key={item.arm_id} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono">{item.arm_id}</span>
                  <Pill tone={armModeTone(item.mode)}>{item.mode}</Pill>
                  <span className="w-full text-xs text-muted-foreground">{item.source}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                데이터셋 요약 <Badge variant="outline">{dataset.mode === "mock" ? "모의 데이터" : "서버"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {dataset.error && <p className="text-destructive">{dataset.error}</p>}
              {dataset.data && (
                <>
                  <p>
                    <span className="font-mono">{dataset.data.task}</span>
                  </p>
                  <p className="tabular-nums">
                    성공 {dataset.data.success} · 실패 {dataset.data.fail}
                  </p>
                  <p className="text-muted-foreground">{dataset.data.note}</p>
                  <p className="text-xs text-muted-foreground">이 값은 인터페이스 정의가 없는 임시 값입니다 (D12).</p>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">녹화 앱 개발 정보 (Station PC 데스크톱)</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="divide-y">
              <Row label="구현이 있는 곳">{menu.implRef || "—"}</Row>
              <Row label="옮길 위치">
                <code className="font-mono text-xs">{TARGET_PATH}</code> (팀원 협의 후 이동. 이동 전에도 이 화면은 정상입니다)
              </Row>
              <Row label="실행 환경">Ubuntu 22.04, LeRobot 0.4.4 가상환경, PySide6 6.8.3 (팀 Jazzy 환경과 다름, D18)</Row>
              <Row label="실행">
                <code className="font-mono text-xs">source ~/venv/il/bin/activate</code>
                {" → "}
                <code className="font-mono text-xs">pip install -r requirements.txt</code>
                {" → "}
                <code className="font-mono text-xs">python main.py</code>
              </Row>
              <Row label="앱 기능">
                세션 시작, BringUp, 리더·팔로워 Init/Rest 자세 저장, 녹화(성공/실패/버림), HF Hub 업로드(기본 비공개)
              </Row>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">FMS 에 붙이기 전에 풀어야 할 것</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal space-y-2 pl-5 text-sm">
              <li>
                <b>팔을 한 곳만 쓰게 하기.</b> 앱이 팔 포트를 직접 엽니다. 앱이 켜져 있는 동안 FMS 는 포트를 열지 않고 팔 제어 모드로 알립니다.
              </li>
              <li>
                <b>Servo OFF 는 긴급 정지가 아닙니다.</b> 평소에는 팔을 Rest 자세로 옮긴 뒤 끕니다. 정상 종료와 정지를 나눠야 합니다.
              </li>
              <li>
                <b>데이터셋 폴더 약속.</b> 앱이 저장하는 success/fail 폴더를 읽기 전용으로 요약하려면 위치와 지문 규칙이 필요합니다.
              </li>
              <li>
                <b>실행 환경.</b> Station PC 환경이 정해져야 앱을 팀 Jazzy 구조와 맞출 수 있습니다.
              </li>
            </ol>
            <p className="mt-3 text-xs text-muted-foreground">근거: docs/fms_branch_compatibility_review.md</p>
          </CardContent>
        </Card>
      </div>

      {/* =========================================================================
          탭 3: 원격 스트리밍 연결 안내
          ========================================================================= */}
      <div className={activeTab === "remote" ? "space-y-4" : "hidden"}>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Station PC 외부 스트리밍 서비스 연결 안내</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <p className="text-muted-foreground">
              Station PC에서 실제 실행 중인 GUI 창을 웹 브라우저로 직접 공유(noVNC)하거나, 에피소드 비디오 검수 스튜디오(포트 8088)를 띄운 경우 아래 안내를 따릅니다:
            </p>
            <div className="space-y-2 rounded-none bg-muted/50 p-4 font-mono text-xs border border-border">
              <p className="font-semibold text-foreground">1. noVNC 가상 디스플레이 스트림 (포트 6080):</p>
              <code>x11vnc -forever -shared -rfbport 5900 &amp; websockify --web /usr/share/novnc/ 6080 localhost:5900 &amp;</code>
              <p className="mt-3 font-semibold text-foreground">2. LeRobot 검수 스튜디오 (포트 8088):</p>
              <code>python3 view_server.py</code>
            </div>
            <p className="text-xs text-muted-foreground">
              ※ 현장 데스크톱 앱과 FMS 웹 관제는 단일 제어권(SR-19) 계약에 따라 역할을 분리하여 안전을 보장합니다.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
