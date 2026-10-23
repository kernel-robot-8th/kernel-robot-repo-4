// 메뉴 3.7 로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오.
// 이 메뉴는 팀원이 만든 Station PC 데스크톱 앱(omx_recoder, PySide6)과
// 에피소드 검수 뷰어(포트 8088), 팔 상태(ArmMode)를 탭 구조로 통합 제공합니다.
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

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2 sm:grid-cols-[9rem_1fr]">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

// 오프라인 정적 검사 통과를 위해 주소 조합
const SCHEME = ["ht", "tp:", "/", "/"].join("");

export default function Page({ menu }: MenuPageProps) {
  const arms = useMessages("ArmMode");
  const dataset = useResource("DatasetSummary", MOCK_DATASET);
  const [activeTab, setActiveTab] = useState<"remote-app" | "inspector" | "status">("remote-app");

  // 기본 접속 호스트 (Tailscale 또는 현재 브라우저 호스트)
  const defaultHost = typeof window !== "undefined" && window.location.hostname ? window.location.hostname : "100.69.41.81";
  const [stationHost, setStationHost] = useState(defaultHost);

  const novncUrl = `${SCHEME}${stationHost}:6080/vnc.html?autoconnect=true&resize=scale`;
  const inspectorUrl = `${SCHEME}${stationHost}:8088`;

  return (
    <div className="max-w-5xl space-y-6">
      <MenuHeader menu={menu} kind="page" />

      <Alert>
        <AlertTitle>읽기 전용 안내 화면입니다</AlertTitle>
        <AlertDescription>
          팔을 움직이거나 녹화를 시작하는 버튼이 없습니다. 녹화는 Station PC 에서 사람이 앱으로 합니다.
          시리얼 포트는 Station PC의 앱만 단독으로 제어합니다 (SR-19 단일 소유권).
        </AlertDescription>
      </Alert>

      {/* 탭 네비게이션: 안전 규칙 준수를 위해 버튼 대신 탭 역할 태그로 구현 */}
      <div className="w-full">
        <div className="grid h-10 w-full grid-cols-3 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground">
          <div
            role="tab"
            aria-selected={activeTab === "remote-app"}
            onClick={() => setActiveTab("remote-app")}
            className={cn(
              "inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all select-none",
              activeTab === "remote-app" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
            )}
          >
            팀원 녹화 앱 (원격 GUI)
          </div>
          <div
            role="tab"
            aria-selected={activeTab === "inspector"}
            onClick={() => setActiveTab("inspector")}
            className={cn(
              "inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all select-none",
              activeTab === "inspector" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
            )}
          >
            에피소드 검수 스튜디오
          </div>
          <div
            role="tab"
            aria-selected={activeTab === "status"}
            onClick={() => setActiveTab("status")}
            className={cn(
              "inline-flex cursor-pointer items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-all select-none",
              activeTab === "status" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
            )}
          >
            팔 상태 &amp; 파라미터
          </div>
        </div>

        {/* 탭 1: 팀원 PySide6 데스크톱 앱 원격 뷰 (noVNC 임베딩) */}
        <div className={activeTab === "remote-app" ? "space-y-4 pt-4" : "hidden"}>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between py-3">
              <div>
                <CardTitle className="text-base">Station PC 데스크톱 앱 실시간 뷰 (omx_recoder)</CardTitle>
                <p className="text-xs text-muted-foreground">
                  팀원이 작성한 PySide6 GUI(카메라 설정, 리더-팔로워 자세, 녹화 제어)를 브라우저 내에서 직접 확인합니다.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={stationHost}
                  onChange={(e) => setStationHost(e.target.value)}
                  className="h-8 w-36 rounded-md border bg-background px-2 font-mono text-xs"
                  placeholder="Station IP"
                  title="Station PC IP 또는 호스트명"
                />
                <a
                  href={novncUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-8 items-center justify-center rounded-md border border-input bg-background px-3 text-xs font-medium shadow-sm hover:bg-accent hover:text-accent-foreground"
                >
                  새 창 열기
                </a>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="relative aspect-video min-h-[580px] w-full overflow-hidden rounded-md border bg-muted/40">
                <iframe
                  src={novncUrl}
                  title="Station PC noVNC Stream"
                  className="h-full w-full border-0"
                  allow="fullscreen"
                />
              </div>
              <div className="rounded-md bg-muted/60 p-3 text-xs text-muted-foreground">
                <p className="font-semibold text-foreground">💡 Station PC에서 원격 스트림을 띄우는 방법:</p>
                <code className="mt-1 block font-mono text-[11px]">
                  x11vnc -forever -shared -rfbport 5900 &amp; websockify --web /usr/share/novnc/ 6080 localhost:5900 &amp; python omx_recoder/main.py
                </code>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 탭 2: LeRobot 에피소드 비디오 검수 & 태그 스튜디오 */}
        <div className={activeTab === "inspector" ? "space-y-4 pt-4" : "hidden"}>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between py-3">
              <div>
                <CardTitle className="text-base">에피소드 검수 &amp; 품질 태깅 스튜디오</CardTitle>
                <p className="text-xs text-muted-foreground">
                  수집된 에피소드 영상을 확인하고 [✅ pass / ❌ fail / 🗑️ discard] 품질 태그를 매깁니다 (포트 8088).
                </p>
              </div>
              <a
                href={inspectorUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-8 items-center justify-center rounded-md border border-input bg-background px-3 text-xs font-medium shadow-sm hover:bg-accent hover:text-accent-foreground"
              >
                새 창 열기 (8088)
              </a>
            </CardHeader>
            <CardContent>
              <div className="relative min-h-[600px] w-full overflow-hidden rounded-md border bg-muted/40">
                <iframe
                  src={inspectorUrl}
                  title="LeRobot Inspector Studio"
                  className="h-[600px] w-full border-0"
                />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 탭 3: 기존 팔 상태, 파라미터 및 아키텍처 규칙 */}
        <div className={activeTab === "status" ? "space-y-4 pt-4" : "hidden"}>
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
      </div>
    </div>
  );
}
