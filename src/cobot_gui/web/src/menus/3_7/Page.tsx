// 메뉴 3.7 로봇팔 파라미터 제어 및 모방학습 Teleop 스튜디오.
// 이 메뉴의 실체는 팀원이 만든 Station PC 데스크톱 앱(omx_recoder, PySide6)이다.
// 웹 화면은 앱을 대신하지 않는다. 앱 안내와 상태 요약만 보이고 팔을 움직이는 버튼은 없다.
import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/lib/dataSource";
import MenuHeader from "@/shell/MenuHeader";
import type { MenuPageProps } from "@/shell/types";

// 모의 값이다. 서버(S2)가 붙으면 같은 이름으로 서버 값을 받는다.
const MOCK_ARM_MODE = { mode: "LEROBOT_EXCLUSIVE", note: "녹화 앱이 팔 포트를 쓰는 중 (예시)" };
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

export default function Page({ menu }: MenuPageProps) {
  const arm = useResource("ArmMode", MOCK_ARM_MODE);
  const dataset = useResource("DatasetSummary", MOCK_DATASET);
  return (
    <div className="max-w-4xl space-y-6">
      <MenuHeader menu={menu} kind="page" />

      <Alert>
        <AlertTitle>읽기 전용 안내 화면입니다</AlertTitle>
        <AlertDescription>
          팔을 움직이거나 녹화를 시작하는 버튼이 없습니다. 녹화는 Station PC 에서 사람이 앱으로 합니다.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">녹화 앱 (Station PC 데스크톱)</CardTitle>
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

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              팔 제어 모드 <Badge variant="outline">{arm.mode === "mock" ? "모의 데이터" : "서버"}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {arm.error && <p className="text-destructive">{arm.error}</p>}
            {arm.data && (
              <>
                <p className="font-mono">{arm.data.mode}</p>
                <p className="text-muted-foreground">{arm.data.note}</p>
              </>
            )}
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
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">FMS 에 붙이기 전에 풀어야 할 것</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li>
              <b>팔을 한 곳만 쓰게 하기.</b> 앱이 팔 포트를 직접 엽니다. 앱이 켜져 있는 동안 FMS 는 포트를 열지 않고 팔 제어 모드로
              알립니다.
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
  );
}
