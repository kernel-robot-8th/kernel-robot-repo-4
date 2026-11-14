// 고객 주문 화면의 서버 연결 (관제 PC 의 customer_gateway, /api/customer/*).
// API 설명: src/cobot_gui/docs/customer_app.md
// 모의 모드: 개발 서버(npm run dev)에서 VITE_DATA 가 gateway 가 아니거나, 주소에 ?mock=1 이 있으면
// 브라우저 안의 가짜 서버로 흐름을 흉내 낸다. 설치본(npm run build)은 기본으로 실제 서버를 부른다.

export type View = "preparing" | "arrived" | "paid" | "cancelled" | "failed" | "out_of_stock";
export type Decision = "PAID" | "CANCEL";

export interface Shoe {
  sku: string;
  name: string;
  brand: string;
  size: string;
  color: string;
  price: number;
  image: string;
  /** 주문할 수 있는 수량. null 이면 재고를 아직 모른다 (주문은 막지 않는다). */
  available: number | null;
}

export interface Catalog {
  location: { id: string; name: string } | null;
  items: Shoe[];
}

export interface OrderState {
  order_id: string;
  view: View;
  stage: string;
  failure_reason?: string;
}

export interface CustomerApi {
  catalog(loc: string): Promise<Catalog>;
  submit(sku: string, loc: string, clientKey: string, session: string): Promise<OrderState>;
  status(orderId: string, session: string): Promise<OrderState>;
  decide(orderId: string, decision: Decision, session: string): Promise<OrderState>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/customer${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) throw new ApiError(response.status, String(data.error ?? "ERROR"));
  return data as T;
}

export const httpApi: CustomerApi = {
  catalog: (loc) => request<Catalog>("GET", `/catalog?loc=${encodeURIComponent(loc)}`),
  submit: async (sku, loc, clientKey, session) => {
    const res = await request<{ order_id: string; view: View }>("POST", "/orders", {
      sku,
      loc,
      client_key: clientKey,
      session,
    });
    return { order_id: res.order_id, view: res.view, stage: "" };
  },
  status: (orderId, session) =>
    request<OrderState>(
      "GET",
      `/orders/${encodeURIComponent(orderId)}?session=${encodeURIComponent(session)}`,
    ),
  decide: (orderId, decision, session) =>
    request<OrderState>("POST", `/orders/${encodeURIComponent(orderId)}/decision`, {
      decision,
      session,
    }),
};

// --- 모의 서버 (화면 확인용) ---

const MOCK_ITEMS: Shoe[] = [
  { sku: "SHOE_RUN_WHITE_260", name: "에어 러너", brand: "COBOT", size: "260", color: "화이트", price: 89000, image: "", available: 3 },
  { sku: "SHOE_SNEAKER_BLACK_270", name: "클래식 스니커즈", brand: "COBOT", size: "270", color: "블랙", price: 69000, image: "", available: 2 },
  { sku: "SHOE_BOOT_BROWN_250", name: "워커 부츠", brand: "COBOT", size: "250", color: "브라운", price: 129000, image: "", available: 1 },
  { sku: "SHOE_SANDAL_BEIGE_240", name: "컴포트 샌들", brand: "COBOT", size: "240", color: "베이지", price: 49000, image: "", available: 0 },
];

const MOCK_STAGES = ["RECEIVED", "ASSIGNED", "LOADING", "IN_TRANSIT", "UNLOADING"];

const STAGE_VIEW: Record<string, View> = {
  UNLOADING: "arrived",
  HANDOVER_CONFIRMED: "paid",
  CANCELLED: "cancelled",
  FAILED: "failed",
};

export function viewOf(stage: string): View {
  return STAGE_VIEW[stage] ?? "preparing";
}

/** 단계마다 stepMs 가 지나면 넘어가는 가짜 서버. */
export function createMockApi(stepMs = 2500, now: () => number = () => Date.now()): CustomerApi {
  const orders = new Map<string, { started: number; decided?: string }>();
  const stageOf = (id: string): string => {
    const order = orders.get(id);
    if (!order) throw new ApiError(404, "UNKNOWN_ORDER");
    if (order.decided) return order.decided;
    const index = Math.min(Math.floor((now() - order.started) / stepMs), MOCK_STAGES.length - 1);
    return MOCK_STAGES[index];
  };
  const state = (id: string): OrderState => {
    const stage = stageOf(id);
    return { order_id: id, stage, view: viewOf(stage) };
  };
  return {
    catalog: async (loc) => ({
      location: loc === "BENCH_1" ? { id: "BENCH_1", name: "고객 벤치 1" } : null,
      items: MOCK_ITEMS,
    }),
    submit: async (sku) => {
      const item = MOCK_ITEMS.find((s) => s.sku === sku);
      if (!item) throw new ApiError(400, "UNKNOWN_SKU");
      const id = `ORD-${String(orders.size + 1).padStart(5, "0")}`;
      orders.set(id, { started: now() });
      if (item.available === 0) {
        orders.get(id)!.decided = "RECEIVED";
        return { order_id: id, stage: "RECEIVED", view: "out_of_stock" };
      }
      return state(id);
    },
    status: async (id) => {
      const order = orders.get(id);
      if (order?.decided === "RECEIVED") return { order_id: id, stage: "RECEIVED", view: "out_of_stock" };
      return state(id);
    },
    decide: async (id, decision) => {
      if (stageOf(id) !== "UNLOADING") throw new ApiError(409, "WRONG_STAGE");
      orders.get(id)!.decided = decision === "PAID" ? "HANDOVER_CONFIRMED" : "CANCELLED";
      return state(id);
    },
  };
}

export function isMockMode(search: string): boolean {
  if (new URLSearchParams(search).get("mock") === "1") return true;
  return import.meta.env.DEV && import.meta.env.VITE_DATA !== "gateway";
}
