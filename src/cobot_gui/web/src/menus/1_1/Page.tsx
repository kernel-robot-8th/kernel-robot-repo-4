// 메뉴 1.1 전체 로봇 현황. 핑키(RobotStatus)와 팔(ArmStatus, ArmMode)의 지금 상태를 한 화면에 모은다.
// 읽기 전용이다. 데이터는 useMessages 로만 읽는다.
import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useMessages } from "@/lib/dataSource";
import { num, yawDeg } from "@/lib/format";
import { armModeTone, robotTone } from "@/lib/tones";
import MenuHeader from "@/shell/MenuHeader";
import Measured from "@/shell/Measured";
import Pill from "@/shell/Pill";
import ResourceSection from "@/shell/ResourceSection";
import type { MenuPageProps } from "@/shell/types";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

export default function Page({ menu }: MenuPageProps) {
  const robots = useMessages("RobotStatus");
  const arms = useMessages("ArmStatus");
  const modes = useMessages("ArmMode");
  const maps = useMessages("MapInfo");
  const mapHash = maps.data?.[0]?.map_hash ?? "";

  return (
    <div className="max-w-5xl space-y-8">
      <MenuHeader menu={menu} kind="page" />

      <ResourceSection title="핑키" resource={robots}>
        {(items) => (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((robot) => (
              <Card key={robot.robot_id} aria-label={robot.robot_id}>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle className="font-mono text-base">{robot.robot_id}</CardTitle>
                  <Pill tone={robotTone(robot.state)}>{robot.state}</Pill>
                </CardHeader>
                <CardContent>
                  <dl className="divide-y">
                    <Row label="위치">
                      {num(robot.current_pose.position.x, 2)}, {num(robot.current_pose.position.y, 2)} m ·{" "}
                      {num(yawDeg(robot.current_pose.orientation), 0, "°")}
                    </Row>
                    <Row label="위치 추정">
                      <Pill tone={robot.localized ? "ok" : "bad"}>{robot.localized ? "유효" : "무효"}</Pill>
                    </Row>
                    <Row label="속도">
                      <Measured value={robot.linear_vel} digits={2} unit=" m/s" />
                    </Row>
                    <Row label="배터리">
                      <Measured value={robot.battery_percentage} digits={0} unit=" %" />
                    </Row>
                    <Row label="모터 전원">
                      <Pill tone={robot.motor_power_present ? "ok" : "bad"}>
                        {robot.motor_power_present ? "있음" : "없음"}
                      </Pill>
                    </Row>
                    <Row label="맵 지문">
                      {mapHash === "" ? (
                        "—"
                      ) : (
                        <Pill tone={robot.map_hash_loaded === mapHash ? "ok" : "bad"}>
                          {robot.map_hash_loaded === mapHash ? "일치" : "불일치"}
                        </Pill>
                      )}
                    </Row>
                    <Row label="작업">{robot.current_task_id || "—"}</Row>
                    {robot.hold_reason !== "" && <Row label="정지 사유">{robot.hold_reason}</Row>}
                    <Row label="하트비트 나이">{robot.last_heartbeat_rx_age_ms} ms</Row>
                  </dl>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </ResourceSection>

      <ResourceSection title="로봇팔" resource={arms}>
        {(items) => (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((arm) => {
              const mode = modes.data?.find((item) => item.arm_id === arm.arm_id);
              return (
                <Card key={arm.arm_id} aria-label={arm.arm_id}>
                  <CardHeader className="flex-row items-center justify-between space-y-0">
                    <CardTitle className="font-mono text-base">{arm.arm_id}</CardTitle>
                    {mode ? <Pill tone={armModeTone(mode.mode)}>{mode.mode}</Pill> : <Pill tone="muted">모드 모름</Pill>}
                  </CardHeader>
                  <CardContent>
                    <dl className="divide-y">
                      <Row label="작업 단계">{arm.work_step}</Row>
                      <Row label="토크">
                        <Pill tone={arm.torque_enabled ? "ok" : "muted"}>{arm.torque_enabled ? "켜짐" : "꺼짐"}</Pill>
                      </Row>
                      <Row label="퇴피 (Z ≥ 280 mm)">
                        {arm.retract_safe_measured ? (
                          <Pill tone={arm.retract_safe ? "ok" : "warn"}>{arm.retract_safe ? "완료" : "아님"}</Pill>
                        ) : (
                          <Pill tone="muted">미측정 (통과 아님)</Pill>
                        )}
                      </Row>
                      <Row label="사람 진입 정지">
                        {arm.hold_active ? <Pill tone="bad">{arm.hold_reason || "HOLD"}</Pill> : <Pill tone="ok">없음</Pill>}
                      </Row>
                      <Row label="팔 전원">
                        <Pill tone={arm.power_present ? "ok" : "bad"}>{arm.power_present ? "있음" : "없음"}</Pill>
                      </Row>
                    </dl>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </ResourceSection>
    </div>
  );
}
