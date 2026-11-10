import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useSimCommand } from "./useSimCommand";
const BUTTON = "h-7 text-[10px] rounded-none bg-[#1c1d22] border-border text-[#dddddd]";
const INPUT = "h-7 px-1.5 text-[10px] bg-[#1c1d22] border border-border text-white";
// 팀 scenario.yaml 에 등록된 이름이어야 관제가 주문을 받는다.
const ROUTES = [
  { id: "lab_delivery", label: "시나리오 A 출고 (ZA)" },
  { id: "lab_delivery_zb", label: "시나리오 B 출고 (ZB)" },
];

export default function OrderControls() {
  const { live, allowed, send, message } = useSimCommand();
  const [sku, setSku] = useState("SHOE42");
  const [stock, setStock] = useState("10");
  const [quantity, setQuantity] = useState("1");
  if (!live || !allowed) return null;
  const stopped = Object.keys(live.holds).length > 0;
  const customer = live.missions.filter(
    (mission) => mission.current_stage === "CUSTOMER" && mission.mission_state === "RUNNING",
  );
  return <section aria-label="시뮬 관제 주문" className="space-y-2 border border-border p-3">
    <h2>격리 시뮬 관제 주문</h2>
    <Button variant="outline" size="sm" onClick={() => void send("control", { type: "pause" })}>
      전체 일시정지 요청
    </Button>
    <Button
      variant="destructive"
      size="sm"
      className="h-7 text-[10px] rounded-none font-bold"
      onClick={() => void send("control", { type: "estop" })}
    >
      전체 비상 정지 요청
    </Button>
    <Button
      variant="outline"
      size="sm"
      className={BUTTON}
      onClick={() =>
        void send("mode", {
          mode: live.mode === "AUTO_HOLD" ? "OBSERVE_ONLY" : "AUTO_HOLD",
        })
      }
    >
      {live.mode === "AUTO_HOLD" ? "관측 전용으로" : "자동 정지 켜기"}
    </Button>
    <Button
      variant="outline"
      size="sm"
      className={BUTTON}
      onClick={() =>
        void send("control", { type: "arm", armed: !live.armed, source: "menu_6_5" })
      }
    >
      {live.armed ? "가동 허용 끄기" : "가동 허용 켜기"}
    </Button>
    <label>주문 수량 <input type="number" min="1" max="100" value={quantity} onChange={e => setQuantity(e.target.value)}/></label>
    <div className="flex flex-wrap items-center gap-1.5">
      <input
        aria-label="SKU"
        className={`${INPUT} w-20`}
        value={sku}
        onChange={(event) => setSku(event.target.value)}
      />
      <input
        aria-label="재고"
        className={`${INPUT} w-12`}
        value={stock}
        onChange={(event) => setStock(event.target.value)}
      />
      <Button
        variant="outline"
        size="sm"
        className={BUTTON}
        onClick={() =>
          void send("control", { type: "inventory", sku, available: Number(stock) })
        }
      >
        재고 설정
      </Button>
      {ROUTES.map((route) => (
        <Button
          key={route.id}
          variant="outline"
          size="sm"
          className={BUTTON}
          disabled={stopped || !Number.isInteger(Number(quantity)) || Number(quantity) < 1 || Number(quantity) > 100}
          onClick={() =>
            void send("control", { type: "order", order: { sku, route: route.id, quantity: Number(quantity) } })
          }
        >
          {route.label}
        </Button>
      ))}
      {customer.map((mission) => (
        <Button
          key={mission.mission_id}
          variant="outline"
          size="sm"
          className={BUTTON}
          onClick={() =>
            void send("control", { type: "received", order_id: mission.mission_id })
          }
        >
          고객 수령 확인 {mission.mission_id}
        </Button>
      ))}
    </div>
    {message && <p role="status">{message}</p>}
  </section>;
}
