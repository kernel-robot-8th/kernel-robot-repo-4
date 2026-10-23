// 메뉴 6.2 ROS 2·FMS 통신 상태. DiagSnapshot 의 토픽(유일 기록자 상태)과 노드(생존·왕복)를 보인다. 읽기 전용이다.
import { useMessages } from "@/lib/dataSource";
import { num } from "@/lib/format";
import { singleWriterTone } from "@/lib/tones";
import MenuHeader from "@/shell/MenuHeader";
import Measured from "@/shell/Measured";
import Pill from "@/shell/Pill";
import ResourceSection from "@/shell/ResourceSection";
import type { MenuPageProps } from "@/shell/types";

export default function Page({ menu }: MenuPageProps) {
  const diag = useMessages("DiagSnapshot");
  return (
    <div className="max-w-5xl space-y-8">
      <MenuHeader menu={menu} kind="page" />

      <ResourceSection title="통신 진단" resource={diag}>
        {(items) => {
          const snap = items[0];
          if (!snap) return <p className="text-sm text-muted-foreground">진단 값이 아직 없습니다.</p>;
          const violations = snap.topics.filter((topic) => topic.single_writer_state === "VIOLATION");
          return (
            <>
              <p className="flex flex-wrap items-center gap-3 text-sm">
                <span>
                  ROS_DOMAIN_ID(진단 노드) <b className="tabular-nums">{snap.ros_domain_id_configured}</b>
                </span>
                <span>
                  chrony 오프셋 <Measured value={snap.chrony_offset_ms} digits={1} unit=" ms" />
                </span>
                {violations.length > 0 && <Pill tone="bad">유일 기록자 위반 {violations.length}건</Pill>}
              </p>

              <h3 className="text-base font-semibold">토픽</h3>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full min-w-[620px] text-sm">
                  <thead className="bg-muted text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">토픽</th>
                      <th className="px-3 py-2 font-medium">발행자</th>
                      <th className="px-3 py-2 font-medium">유량</th>
                      <th className="px-3 py-2 font-medium">유일 기록자</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snap.topics.map((topic) => (
                      <tr key={topic.name} className="border-t">
                        <td className="px-3 py-2 font-mono text-xs">{topic.name}</td>
                        <td className="px-3 py-2 tabular-nums">{topic.publishers}</td>
                        <td className="px-3 py-2 tabular-nums">{num(topic.measured_hz, 1, " Hz")}</td>
                        <td className="px-3 py-2">
                          <Pill tone={singleWriterTone(topic.single_writer_state)}>{topic.single_writer_state}</Pill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h3 className="text-base font-semibold">노드</h3>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full min-w-[480px] text-sm">
                  <thead className="bg-muted text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">노드</th>
                      <th className="px-3 py-2 font-medium">상태</th>
                      <th className="px-3 py-2 font-medium">서비스 왕복</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snap.nodes.map((node) => (
                      <tr key={node.name} className="border-t">
                        <td className="px-3 py-2 font-mono text-xs">{node.name}</td>
                        <td className="px-3 py-2">
                          <Pill tone={node.alive ? "ok" : "bad"}>{node.alive ? "살아 있음" : "안 보임"}</Pill>
                        </td>
                        <td className="px-3 py-2">
                          <Measured value={node.srv_rtt_ms} digits={1} unit=" ms" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          );
        }}
      </ResourceSection>
    </div>
  );
}
