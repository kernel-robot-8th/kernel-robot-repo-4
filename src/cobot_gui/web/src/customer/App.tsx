import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Check,
  CircleCheck,
  Footprints,
  LoaderCircle,
  MapPin,
  PackageCheck,
  QrCode,
  ShoppingBag,
  Truck,
  Undo2,
  X,
} from "lucide-react";

import { formatPrice } from "./format";
import { ApiError, type Catalog, type CustomerApi, type Decision, type OrderState, type Shoe } from "./api";

const POLL_MS = 1000;
const STORAGE_KEY = "cobot-customer-order";

const STEPS = [
  { label: "주문 접수", stages: ["", "RECEIVED"], icon: Check },
  { label: "신발 꺼내는 중", stages: ["ASSIGNED", "LOADING"], icon: PackageCheck },
  { label: "자리로 가는 중", stages: ["IN_TRANSIT"], icon: Truck },
  { label: "도착", stages: ["UNLOADING"], icon: MapPin },
];

const ERROR_TEXT: Record<string, string> = {
  CONTROL_CENTER_UNAVAILABLE: "매장 시스템에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
  UNKNOWN_LOCATION: "자리 정보를 알 수 없어요. 자리의 QR 코드를 다시 찍어 주세요.",
  WRONG_STAGE: "아직 신발이 도착하지 않았어요.",
};

interface Saved {
  session: string;
  orderId: string;
  sku: string;
  loc: string;
}

function randomId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function loadSaved(): Saved | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Saved) : null;
  } catch {
    return null;
  }
}

function save(value: Saved | null) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 저장이 막힌 브라우저(사생활 보호 모드)에서도 화면은 동작한다.
  }
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) return ERROR_TEXT[error.code] ?? `요청을 처리하지 못했어요 (${error.code}).`;
  return "네트워크 연결을 확인해 주세요.";
}

export default function App({ api, search }: { api: CustomerApi; search: string }) {
  const loc = useMemo(() => new URLSearchParams(search).get("loc") ?? "", [search]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<Shoe | null>(null);
  const [saved, setSaved] = useState<Saved | null>(() => {
    const value = loadSaved();
    return value && value.loc === loc ? value : null;
  });
  const [order, setOrder] = useState<OrderState | null>(null);
  const [paying, setPaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const session = useRef(saved?.session ?? randomId());

  useEffect(() => {
    api
      .catalog(loc)
      .then(setCatalog)
      .catch((e) => setLoadError(errorText(e)));
  }, [api, loc]);

  const view = order?.view ?? (saved ? "preparing" : null);
  const polling = saved !== null && (view === "preparing" || view === "arrived");

  useEffect(() => {
    if (!saved) return;
    let alive = true;
    const tick = () =>
      api
        .status(saved.orderId, saved.session)
        .then((state) => alive && setOrder(state))
        .catch((e) => {
          if (!alive) return;
          if (e instanceof ApiError && e.status === 404) {
            save(null);
            setSaved(null);
            setOrder(null);
          }
        });
    tick();
    if (!polling) return () => {
      alive = false;
    };
    const timer = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [api, saved, polling]);

  const submit = useCallback(
    async (shoe: Shoe) => {
      setBusy(true);
      setNotice("");
      try {
        const state = await api.submit(shoe.sku, loc, randomId(), session.current);
        const value = { session: session.current, orderId: state.order_id, sku: shoe.sku, loc };
        save(value);
        setSaved(value);
        setOrder(state);
        setSelected(null);
      } catch (e) {
        setNotice(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [api, loc],
  );

  const decide = useCallback(
    async (decision: Decision) => {
      if (!saved) return;
      setBusy(true);
      setNotice("");
      try {
        setOrder(await api.decide(saved.orderId, decision, saved.session));
        setPaying(false);
      } catch (e) {
        setNotice(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [api, saved],
  );

  const restart = useCallback(() => {
    save(null);
    setSaved(null);
    setOrder(null);
    setPaying(false);
    setNotice("");
  }, []);

  const shoe = catalog?.items.find((s) => s.sku === saved?.sku) ?? null;

  let body;
  if (loadError) {
    body = <Message icon={X} title="화면을 불러오지 못했어요" text={loadError} />;
  } else if (!catalog) {
    body = <Message icon={LoaderCircle} spin title="불러오는 중이에요" />;
  } else if (!catalog.location) {
    body = (
      <Message
        icon={QrCode}
        title="자리의 QR 코드를 찍어 주세요"
        text="자리에 붙은 QR 코드로 들어오면 Cobot이 그 자리로 신발을 가져다 드려요."
      />
    );
  } else if (saved && view === "preparing") {
    body = <Preparing stage={order?.stage ?? ""} shoe={shoe} />;
  } else if (saved && view === "arrived" && paying && shoe) {
    body = <Payment shoe={shoe} busy={busy} onPaid={() => decide("PAID")} onBack={() => setPaying(false)} />;
  } else if (saved && view === "arrived") {
    body = <Arrived shoe={shoe} busy={busy} onBuy={() => setPaying(true)} onCancel={() => decide("CANCEL")} />;
  } else if (saved && view) {
    body = <Finished view={view} shoe={shoe} onRestart={restart} />;
  } else {
    body = <ShoeList items={catalog.items} onSelect={setSelected} />;
  }

  return (
    <div className="c-app">
      <header className="c-header">
        <div className="c-brand">
          <Footprints aria-hidden size={20} />
          <span>Cobot Shoes</span>
        </div>
        {catalog?.location && (
          <div className="c-chip" aria-label="주문 자리">
            <MapPin aria-hidden size={14} />
            {catalog.location.name}
          </div>
        )}
      </header>
      <main className="c-main">{body}</main>
      {notice && (
        <div role="alert" className="c-toast">
          {notice}
        </div>
      )}
      {selected && !saved && (
        <Detail shoe={selected} busy={busy} onClose={() => setSelected(null)} onOrder={() => submit(selected)} />
      )}
    </div>
  );
}

function ShoeImage({ shoe, large = false }: { shoe: Shoe; large?: boolean }) {
  const [broken, setBroken] = useState(false);
  if (shoe.image && !broken) {
    return (
      <img
        className={large ? "c-img c-img-lg" : "c-img"}
        src={`/customer/shoes/${shoe.image}`}
        alt={shoe.name}
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <div className={large ? "c-img c-img-lg c-img-empty" : "c-img c-img-empty"} aria-hidden>
      <Footprints size={large ? 56 : 36} />
    </div>
  );
}

function ShoeList({ items, onSelect }: { items: Shoe[]; onSelect: (shoe: Shoe) => void }) {
  return (
    <section>
      <h1 className="c-title">어떤 신발을 신어 볼까요?</h1>
      <p className="c-sub">고르시면 Cobot이 지금 계신 자리로 가져다 드려요.</p>
      <ul className="c-grid">
        {items.map((shoe) => {
          const soldOut = shoe.available === 0;
          return (
            <li key={shoe.sku}>
              <button
                type="button"
                className="c-card"
                disabled={soldOut}
                aria-label={`${shoe.name} ${shoe.size}`}
                onClick={() => onSelect(shoe)}
              >
                <ShoeImage shoe={shoe} />
                {soldOut && <span className="c-badge">품절</span>}
                <span className="c-card-brand">{shoe.brand}</span>
                <span className="c-card-name">{shoe.name}</span>
                <span className="c-card-meta">
                  {shoe.size} · {shoe.color}
                </span>
                <span className="c-card-price">{formatPrice(shoe.price)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Detail({
  shoe,
  busy,
  onClose,
  onOrder,
}: {
  shoe: Shoe;
  busy: boolean;
  onClose: () => void;
  onOrder: () => void;
}) {
  return (
    <div className="c-sheet-backdrop" onClick={onClose}>
      <div
        className="c-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={`${shoe.name} 주문`}
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className="c-sheet-close" aria-label="닫기" onClick={onClose}>
          <X size={20} />
        </button>
        <ShoeImage shoe={shoe} large />
        <p className="c-card-brand">{shoe.brand}</p>
        <h2 className="c-sheet-title">{shoe.name}</h2>
        <dl className="c-spec">
          <div>
            <dt>사이즈</dt>
            <dd>{shoe.size}</dd>
          </div>
          <div>
            <dt>색상</dt>
            <dd>{shoe.color}</dd>
          </div>
          <div>
            <dt>가격</dt>
            <dd>{formatPrice(shoe.price)}</dd>
          </div>
        </dl>
        <p className="c-hint">신어 보고 마음에 들 때만 구매하시면 돼요.</p>
        <button type="button" className="c-btn c-btn-primary" disabled={busy} onClick={onOrder}>
          {busy ? <LoaderCircle className="c-spin" size={18} /> : <Bot size={18} />}
          Cobot에게 가져다 달라고 하기
        </button>
      </div>
    </div>
  );
}

function Preparing({ stage, shoe }: { stage: string; shoe: Shoe | null }) {
  const current = Math.max(
    0,
    STEPS.findIndex((step) => step.stages.includes(stage)),
  );
  return (
    <section className="c-center">
      <div className="c-robot" aria-hidden>
        <Bot size={56} />
      </div>
      <h1 className="c-title">Cobot이 물건을 준비 중이에요</h1>
      {shoe && (
        <p className="c-sub">
          {shoe.name} · {shoe.size}
        </p>
      )}
      <ol className="c-steps" aria-label="진행 단계">
        {STEPS.map((step, index) => {
          const state = index < current ? "done" : index === current ? "now" : "todo";
          const Icon = step.icon;
          return (
            <li key={step.label} className={`c-step c-step-${state}`} aria-current={state === "now" ? "step" : undefined}>
              <span className="c-step-dot">
                {state === "done" ? <Check size={14} /> : <Icon size={14} />}
              </span>
              {step.label}
            </li>
          );
        })}
      </ol>
      <p className="c-hint">이 화면을 열어 두시면 도착했을 때 알려 드려요.</p>
    </section>
  );
}

function Arrived({
  shoe,
  busy,
  onBuy,
  onCancel,
}: {
  shoe: Shoe | null;
  busy: boolean;
  onBuy: () => void;
  onCancel: () => void;
}) {
  return (
    <section className="c-center">
      <div className="c-robot c-robot-ok" aria-hidden>
        <PackageCheck size={56} />
      </div>
      <h1 className="c-title">신발이 도착했어요!</h1>
      <p className="c-sub">Cobot에서 신발을 꺼내 신어 보세요.</p>
      {shoe && (
        <div className="c-summary">
          <ShoeImage shoe={shoe} />
          <div>
            <p className="c-card-name">{shoe.name}</p>
            <p className="c-card-meta">
              {shoe.size} · {shoe.color}
            </p>
            <p className="c-card-price">{formatPrice(shoe.price)}</p>
          </div>
        </div>
      )}
      <div className="c-actions">
        <button type="button" className="c-btn c-btn-primary" disabled={busy} onClick={onBuy}>
          <ShoppingBag size={18} />
          구매하기
        </button>
        <button type="button" className="c-btn c-btn-ghost" disabled={busy} onClick={onCancel}>
          <X size={18} />
          구매하지 않을게요
        </button>
      </div>
      <p className="c-hint">구매하지 않으셔도 괜찮아요. 신발은 그대로 두시면 Cobot이 정리해서 가져갈게요.</p>
    </section>
  );
}

function Payment({
  shoe,
  busy,
  onPaid,
  onBack,
}: {
  shoe: Shoe;
  busy: boolean;
  onPaid: () => void;
  onBack: () => void;
}) {
  return (
    <section className="c-center">
      <h1 className="c-title">QR 코드로 결제해 주세요</h1>
      <p className="c-amount">{formatPrice(shoe.price)}</p>
      <div className="c-qr">
        <img src="/customer/pay_qr.svg" alt="결제 QR 코드 (예시)" />
      </div>
      <p className="c-hint">시연용 결제 화면이에요. 실제로 결제되지 않아요.</p>
      <div className="c-actions">
        <button type="button" className="c-btn c-btn-primary" disabled={busy} onClick={onPaid}>
          {busy ? <LoaderCircle className="c-spin" size={18} /> : <CircleCheck size={18} />}
          결제를 완료했어요
        </button>
        <button type="button" className="c-btn c-btn-ghost" disabled={busy} onClick={onBack}>
          <Undo2 size={18} />
          이전으로
        </button>
      </div>
    </section>
  );
}

const FINISHED: Record<string, { title: string; text: string; icon: typeof Check }> = {
  paid: { title: "구매가 완료됐어요", text: "감사합니다! 새 신발과 즐거운 하루 보내세요.", icon: CircleCheck },
  cancelled: {
    title: "구매를 취소했어요",
    text: "Cobot이 신발을 정리해서 창고로 돌아가요. 다른 신발도 둘러보세요.",
    icon: Undo2,
  },
  out_of_stock: { title: "지금은 재고가 없어요", text: "다른 신발을 골라 주세요.", icon: X },
  failed: { title: "주문을 처리하지 못했어요", text: "직원에게 말씀해 주세요.", icon: X },
};

function Finished({ view, shoe, onRestart }: { view: string; shoe: Shoe | null; onRestart: () => void }) {
  const info = FINISHED[view] ?? FINISHED.failed;
  const Icon = info.icon;
  return (
    <section className="c-center">
      <div className={view === "paid" ? "c-robot c-robot-ok" : "c-robot"} aria-hidden>
        <Icon size={56} />
      </div>
      <h1 className="c-title">{info.title}</h1>
      {shoe && view === "paid" && (
        <p className="c-sub">
          {shoe.name} · {formatPrice(shoe.price)}
        </p>
      )}
      <p className="c-sub">{info.text}</p>
      <div className="c-actions">
        <button type="button" className="c-btn c-btn-primary" onClick={onRestart}>
          <Footprints size={18} />
          다른 신발 보기
        </button>
      </div>
    </section>
  );
}

function Message({
  icon: Icon,
  title,
  text,
  spin = false,
}: {
  icon: typeof Check;
  title: string;
  text?: string;
  spin?: boolean;
}) {
  return (
    <section className="c-center">
      <div className="c-robot" aria-hidden>
        <Icon size={48} className={spin ? "c-spin" : undefined} />
      </div>
      <h1 className="c-title">{title}</h1>
      {text && <p className="c-sub">{text}</p>}
    </section>
  );
}
