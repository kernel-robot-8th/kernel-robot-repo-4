// 메뉴 4.1 실시간 카메라 모니터링. 카메라 건강(CameraHealth)과 미디어 서버 건강(MediaHealth)을 보인다.
// 영상 재생(WHEP)은 게이트웨이와 미디어 서버가 붙는 S2 에서 넣는다. 읽기 전용이다.
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMessages } from "@/lib/dataSource";
import MenuHeader from "@/shell/MenuHeader";
import Measured from "@/shell/Measured";
import Pill from "@/shell/Pill";
import ResourceSection from "@/shell/ResourceSection";
import type { MenuPageProps } from "@/shell/types";

export default function Page({ menu }: MenuPageProps) {
  const cameras = useMessages("CameraHealth");
  const media = useMessages("MediaHealth");
  return (
    <div className="max-w-5xl space-y-8">
      <MenuHeader menu={menu} kind="page" />

      <ResourceSection title="카메라" resource={cameras}>
        {(items) => (
          <div className="grid gap-4 md:grid-cols-2">
            {items.map((cam) => (
              <Card key={cam.camera_id} aria-label={cam.camera_id}>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle className="font-mono text-base">{cam.camera_id}</CardTitle>
                  <div className="flex gap-2">
                    <Pill tone="muted">{cam.role}</Pill>
                    {cam.source_kind === "SIM" && <Pill tone="warn">시뮬레이션 (제어에 쓰지 않음)</Pill>}
                  </div>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <p className="flex flex-wrap items-center gap-2">
                    프레임 나이 <Measured value={cam.frame_age_ms} digits={0} unit=" ms" />
                    {cam.frame_age_ms === null && <Pill tone="bad">프레임 없음</Pill>}
                    {cam.frame_age_ms !== null && cam.age_basis === "RECEIVE" && (
                      <Pill tone="warn">수신 시각 기준 (캡처 시각 검증 안 됨)</Pill>
                    )}
                  </p>
                  <p className="flex flex-wrap items-center gap-2">
                    {cam.frozen ? <Pill tone="bad">화면 정지 (같은 프레임 반복)</Pill> : <Pill tone="ok">움직임 있음</Pill>}
                    <span className="tabular-nums text-muted-foreground">
                      {cam.fps_measured === null ? "—" : cam.fps_measured.toFixed(1)} fps · {cam.width}×{cam.height}
                    </span>
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </ResourceSection>

      <ResourceSection title="미디어 서버 경로" resource={media}>
        {(items) => (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[520px] text-sm">
              <thead className="bg-muted text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">경로</th>
                  <th className="px-3 py-2 font-medium">송출자</th>
                  <th className="px-3 py-2 font-medium">수신율</th>
                  <th className="px-3 py-2 font-medium">화면</th>
                </tr>
              </thead>
              <tbody>
                {items.map((path) => (
                  <tr key={path.path} className="border-t">
                    <td className="px-3 py-2 font-mono text-xs">{path.path}</td>
                    <td className="px-3 py-2">
                      <Pill tone={path.publisher_online ? "ok" : "bad"}>{path.publisher_online ? "연결됨" : "끊김"}</Pill>
                    </td>
                    <td className="px-3 py-2">
                      <Measured value={path.bytes_rx_rate === null ? null : path.bytes_rx_rate / 1000} digits={0} unit=" kB/s" />
                    </td>
                    <td className="px-3 py-2">
                      <Pill tone={path.frozen_state === "LIVE" ? "ok" : path.frozen_state === "FROZEN" ? "bad" : "warn"}>
                        {path.frozen_state || "UNKNOWN"}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ResourceSection>

      <p className="text-xs text-muted-foreground">영상 재생은 미디어 서버(WHEP)가 붙는 S2 에서 넣습니다. 지금은 건강 상태만 봅니다.</p>
    </div>
  );
}
