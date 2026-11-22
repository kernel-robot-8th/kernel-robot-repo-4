// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 서비스 관리화면 (매장 직원용). 엔지니어 화면(/)의 스크립트와 따로 둔다 (그 화면을 고쳐도 여기가 안 깨지게).
// 1초마다 /api/service·/api/fleet·/api/arms 를 읽어 다시 그린다. 조치는 기존 명령 API 로 보낸다.
// 판단(이어서 가기 가능 단계, 상차 확인 조건, 정지 잠금 해제 조건)은 fleet_control 이 하고,
// 이 화면의 버튼 표시는 힌트다. 거절되면 fleet 이 준 이유를 그대로 보여 준다.

"use strict";

const POLL_MS = 1000;
const TOAST_MS = 6000;
const STALE_MS = 4000;            // 이만큼 못 읽으면 관제 점을 빨강으로
const OPERATOR_KEY = "cobot.operator"; // 엔지니어 화면과 같은 키 (같은 브라우저면 이름을 함께 기억)

// 순찰 노드 상태 → 직원용 말 (엔지니어 화면 cards.js STATE_TEXT 와 같은 뜻, 더 쉬운 말)
const ROBOT_STATE_TEXT = {
  MOVING: "이동 중", STARTING: "출발", RETURNING: "돌아가는 중", LEAVING_ZONE: "구역 나가는 중",
  RETREATING: "물러나는 중", QUEUEING: "순서 기다림", WAITING_ZONE: "순서 기다림", IDLE_WAIT: "대기",
  RETRY: "다시 시도", ARRIVED: "도착", HOLDING_ZONE: "작업 구역 안", DONE: "완료",
  FAILED: "실패", STOPPED: "멈춤", IDLE: "쉬는 중",
};
const HOLD_TEXT = {
  RESET_PENDING: "잠금 해제 응답 기다림", RESET_UNCONFIRMED: "잠금 해제 확인 안 됨",
  DISPATCH_FAILED: "명령 전달 실패", STOP: "정지", ESTOP: "비상정지", PAUSE: "일시정지",
  PAUSED: "일시정지", MANUAL: "수동 조작", LINK_LOST: "통신 끊김",
};
const ARM_STATE_TEXT = {
  READY: ["준비됨", "good"], BUSY: ["작업 중", "active"], OFF: ["꺼짐", "idle"],
  HOLD: ["정지 유지", "warn"], SOFT_LATCH: ["비상정지", "bad"], FAULT: ["고장", "bad"],
  STALE: ["연결 끊김", "bad"],
};
const ORDER_STATE_TEXT = {
  UNKNOWN: "결과 모름", PAUSED: "일시정지", ESTOP: "비상정지", MANUAL: "수동 조작",
};
const OUTCOME_CLASS = { sold: "good", declined: "warn", timeout: "warn", done: "good", failed: "bad" };

// 주문 취소 전 현장 확인 (fleet 이 evidence 세 칸을 모두 요구한다, api.md recover)
const CANCEL_CHECKS = [
  ["arms_safe", "로봇팔이 멈추고 안전한 자리로 물러나 있다"],
  ["cargo_reconciled", "상품을 꺼내거나 고객에게 넘겨 정리했다"],
  ["resources_clear", "작업 구역·통로에 로봇과 상품이 남아 있지 않다"],
];
// 수동 상차 확인 (confirm_loaded evidence)
const LOAD_CHECKS = [
  ["load_present", "상품이 로봇 바구니에 실려 있다"],
  ["arm_safe", "로봇팔이 로봇에서 떨어져 안전한 자리에 있다"],
  ["pickup_path_clear", "로봇이 나갈 길에 사람·물건이 없다"],
];

const view = {
  service: null, fleet: null, arms: null,
  lastOk: 0, busy: false,
};

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

const newRequestId = () => (crypto.randomUUID ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

function savedOperator() {
  try {
    return localStorage.getItem(OPERATOR_KEY) || "";
  } catch (err) {
    return "";
  }
}

function saveOperator(name) {
  try {
    localStorage.setItem(OPERATOR_KEY, name);
  } catch (err) {
    // 저장이 막혀 있어도 조치는 된다.
  }
}

// ---------- 시간 글 ----------

function two(n) {
  return String(n).padStart(2, "0");
}

// 오늘이면 "14:05", 아니면 "11-16 14:05" (끝난 주문 목록에 며칠 전 것이 섞여도 헷갈리지 않게)
function clockText(sec) {
  if (!sec) return "—";
  const d = new Date(sec * 1000);
  const time = `${two(d.getHours())}:${two(d.getMinutes())}`;
  return d.toDateString() === new Date().toDateString()
    ? time : `${two(d.getMonth() + 1)}-${two(d.getDate())} ${time}`;
}

function durationText(sec) {
  if (!(sec >= 0)) return "—";
  const s = Math.round(sec);
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}분`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 ${m % 60}분`;
  return `${Math.floor(h / 24)}일 ${h % 24}시간`;
}

// ---------- 통신 ----------

async function getJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}

async function postJson(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: { detail: "관제에 연결하지 못함" } };
  }
}

function errorText(result) {
  const detail = result.data && result.data.detail;
  if (typeof detail === "string") return detail;
  return detail ? JSON.stringify(detail) : `응답 ${result.status}`;
}

function toast(text, bad) {
  const box = $("toast");
  box.textContent = text;
  box.className = `toast ${bad ? "bad" : "good"}`;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, TOAST_MS);
}

async function poll() {
  // 앞 요청이 아직이면 겹쳐 보내지 않는다 (느린 망에서 요청이 쌓이지 않게).
  if (view.polling) return;
  view.polling = true;
  // fleet·arms 는 없을 수 있다 (fleet_status 미수신 503, 팔 노드 없음). 서비스 값만 있어도 그린다.
  const [service, fleet, arms] = await Promise.allSettled(
    [getJson("/api/service"), getJson("/api/fleet"), getJson("/api/arms")]);
  view.polling = false;
  if (service.status === "fulfilled") {
    view.service = service.value;
    view.lastOk = Date.now();
  }
  view.fleet = fleet.status === "fulfilled" ? fleet.value : null;
  view.arms = arms.status === "fulfilled" ? arms.value : null;
  render();
}

// ---------- 상단 ----------

function controllerOnline() {
  return Boolean(view.service && view.service.controller_online);
}

function commandsAllowed() {
  return controllerOnline() && !view.service.read_only && Date.now() - view.lastOk < STALE_MS;
}

function renderTop() {
  const backendOk = Date.now() - view.lastOk < STALE_MS;
  $("dot-backend").className = `dot ${backendOk ? "ok" : "bad"}`;
  $("dot-controller").className = `dot ${controllerOnline() ? "ok" : "bad"}`;
  const now = new Date();
  $("clock").textContent = `${two(now.getHours())}:${two(now.getMinutes())}:${two(now.getSeconds())}`;

  const infra = view.fleet && view.fleet.infra;
  const chip = $("mode-chip");
  const readOnly = view.service && view.service.read_only;
  if (!infra) {
    chip.textContent = backendOk ? "로봇 정보 기다리는 중" : "관제 연결 끊김";
    chip.className = "chip warn";
  } else {
    const real = infra.mode === "real";
    chip.textContent = `${real ? "실제 매장" : "시험 모드"}${readOnly ? " · 보기 전용" : ""}`;
    chip.className = `chip ${real && !readOnly ? "ok" : "warn"}`;
  }

  const armed = Boolean(view.service && view.service.commands_armed);
  const toggle = $("arm-toggle");
  toggle.disabled = !commandsAllowed() || view.busy;
  toggle.textContent = armed ? "주문 처리 켜짐 · 끄기" : "주문 처리 꺼짐 · 켜기";
  toggle.className = `btn ${armed ? "btn-on" : "btn-off"}`;
  // 비상정지는 주문 처리가 꺼져 있어도 보낸다 (정지는 늘 안전한 쪽).
  $("estop-all").disabled = !view.service || view.service.read_only || !backendOk;
}

async function toggleArmed() {
  const armed = Boolean(view.service && view.service.commands_armed);
  if (!armed && !confirm("주문 처리를 켤까요?\n로봇과 로봇팔이 주문에 따라 실제로 움직입니다.\n"
    + "로봇 길과 로봇팔 주변에 사람이 없는지 확인했나요?")) return;
  view.busy = true;
  renderTop();
  const result = await postJson("/api/commands/arm", { client_request_id: newRequestId(), armed: !armed });
  view.busy = false;
  toast(result.ok ? `주문 처리를 ${armed ? "껐습니다" : "켰습니다"}`
    : `바꾸지 못했습니다: ${errorText(result)}`, !result.ok);
  poll();
}

async function estopAll() {
  // 확인 창 없이 바로 보낸다 (늦게 멈추는 것이 더 위험하다).
  const result = await postJson("/api/commands/estop", { client_request_id: newRequestId() });
  toast(result.ok ? "전체 비상정지를 보냈습니다. 현장을 확인한 뒤 로봇마다 '정지 해제'를 누르세요."
    : `비상정지를 보내지 못했습니다: ${errorText(result)} — 로봇의 비상정지 버튼을 직접 누르세요`, !result.ok);
  poll();
}

// ---------- 알림 띠 ----------

function collectAlerts() {
  const alerts = [];
  if (Date.now() - view.lastOk >= STALE_MS) {
    alerts.push(["bad", "관제에 연결되지 않습니다. 관제 PC 와 네트워크를 확인하세요."]);
    return alerts;
  }
  const service = view.service;
  if (!service.controller_online) {
    alerts.push(["bad", "주문 처리기(fleet_control)가 응답하지 않습니다. 새 주문이 처리되지 않습니다."]);
  }
  for (const order of service.active) {
    if (order.blocked) {
      alerts.push(["bad", `주문 ${order.order_id} 멈춤 (${orderStateText(order)}) — 주문 카드에서 조치하세요`]);
    } else if (order.load_confirmable) {
      alerts.push(["warn", `주문 ${order.order_id} 상차를 확인해 주세요 (${order.robot_id})`]);
    } else if (order.failure) {
      alerts.push(["warn", `주문 ${order.order_id} 문제 생김: ${order.failure}`]);
    }
  }
  for (const [robotId, reason] of Object.entries(service.holds || {})) {
    alerts.push(["bad", `${robotId} 정지 잠금 (${HOLD_TEXT[reason] || reason}) — 현장 확인 뒤 정지 해제`]);
  }
  for (const alert of (view.fleet && view.fleet.alerts) || []) {
    alerts.push([alert.level === "bad" ? "bad" : "warn", `${alert.robot} ${alert.text}`]);
  }
  for (const arm of (view.arms && view.arms.arms) || []) {
    for (const alarm of arm.alarms || []) {
      alerts.push([alarm.level === "bad" ? "bad" : "warn", `${armName(arm)} ${alarm.text}`]);
    }
  }
  return alerts.sort((a, b) => (a[0] === b[0] ? 0 : a[0] === "bad" ? -1 : 1));
}

function renderAlerts() {
  const box = $("alerts");
  const alerts = collectAlerts();
  box.replaceChildren(...alerts.map(([level, text]) => el("div", `alert ${level}`, text)));
  box.hidden = alerts.length === 0;
}

// ---------- 주문 ----------

function orderStateText(order) {
  return ORDER_STATE_TEXT[order.state] || HOLD_TEXT[order.state] || order.state;
}

function destinationName(order) {
  const dest = order.destination;
  if (!dest) return order.route || "—";
  const known = view.service.destinations && view.service.destinations[dest];
  return (known && known.name) || dest;
}

function stepBar(order, steps) {
  const bar = el("ol", "steps");
  steps.forEach((name, index) => {
    // 회수·정리(4)는 고객이 사지 않았을 때만 거친다. 그 밖에는 흐리게 건너뜀으로 보인다.
    let cls = "todo";
    if (index === 4 && !order.returning) cls = "skip";
    else if (order.step === null || order.step === undefined) cls = "todo";
    else if (index < order.step) cls = "done";
    else if (index === order.step) cls = order.blocked ? "now stuck" : "now";
    bar.appendChild(el("li", cls, name));
  });
  return bar;
}

function orderCard(order) {
  const service = view.service;
  const card = el("article", `order-card${order.blocked ? " stuck" : order.load_confirmable ? " attention" : ""}`);
  const head = el("div", "order-head");
  head.append(el("strong", "order-id", `주문 ${order.order_id}`),
    el("span", "order-age", `${clockText(order.created_at)} 접수 · ${durationText(service.now - order.created_at)}째`));
  card.appendChild(head);

  const facts = el("dl", "facts");
  for (const [label, value] of [["상품", order.sku || "—"], ["자리", destinationName(order)],
    ["로봇", order.robot_id || "배정 전"]]) {
    facts.append(el("dt", "", label), el("dd", "", value));
  }
  card.appendChild(facts);
  card.appendChild(stepBar(order, service.steps));

  const now = el("p", "order-now");
  if (order.blocked) {
    now.textContent = `멈춤: ${orderStateText(order)} · ${order.step_text}`;
    now.classList.add("bad");
  } else if (order.load_confirmable) {
    now.textContent = "상차장에서 멈춤 · 사람이 상품을 싣고 확인해 주세요";
    now.classList.add("warn");
  } else {
    now.textContent = order.step_text || "—";
  }
  card.appendChild(now);
  if (order.failure) card.appendChild(el("p", "order-failure", `문제: ${order.failure}`));

  const actions = el("div", "order-actions");
  const allowed = commandsAllowed();
  if (order.load_confirmable) {
    actions.appendChild(button("상차 확인", "btn btn-primary", () => openLoadDialog(order), !allowed));
  }
  if (order.blocked) {
    actions.appendChild(button(order.resumable ? "이어서 가기 / 주문 취소" : "주문 취소",
      "btn btn-danger", () => openRecoverDialog(order), !allowed));
  }
  if (actions.childElementCount) card.appendChild(actions);
  return card;
}

function button(label, className, onClick, disabled) {
  const node = el("button", className, label);
  node.type = "button";
  node.disabled = Boolean(disabled);
  node.addEventListener("click", onClick);
  return node;
}

function renderOrders() {
  const service = view.service;
  $("active-count").textContent = service.active.length;
  $("active-orders").replaceChildren(...service.active.map(orderCard));
  $("active-empty").hidden = service.active.length > 0;

  const rows = service.finished.map((order) => {
    const tr = el("tr");
    const result = el("td");
    result.appendChild(el("span", `badge ${OUTCOME_CLASS[order.outcome] || ""}`, order.outcome_text));
    if (order.failure) result.appendChild(el("div", "why", order.failure));
    tr.append(el("td", "", clockText(order.updated_at)), el("td", "mono", order.order_id),
      el("td", "", order.sku || "—"), el("td", "", destinationName(order)),
      el("td", "", order.robot_id || "—"), result,
      el("td", "", durationText(order.updated_at - order.created_at)));
    return tr;
  });
  $("finished").replaceChildren(...rows);
  $("finished-empty").hidden = rows.length > 0;
  const count = (code) => service.finished.filter((o) => o.outcome === code).length;
  $("finished-summary").textContent = service.finished.length
    ? `최근 ${service.finished.length}건 · 구매 ${count("sold")} · 회수 ${count("declined") + count("timeout")} · 실패 ${count("failed")}`
    : "";
}

// ---------- 로봇·로봇팔·재고 ----------

function batteryText(robot) {
  const pct = robot.battery_percent;
  if (pct === null || pct === undefined) return ["배터리 —", "idle"];
  return [`배터리 ${Math.round(pct)}%`, pct <= 15 ? "bad" : pct <= 30 ? "warn" : "good"];
}

function robotRow(robotId, robot) {
  const service = view.service;
  const hold = service.holds && service.holds[robotId];
  const order = service.active.find((o) => o.robot_id === robotId);
  const row = el("div", `mini${hold || !robot.online ? " bad" : ""}`);
  const top = el("div", "mini-top");
  const stateText = !robot.online ? "연결 끊김"
    : hold ? `정지 잠금 · ${HOLD_TEXT[hold] || hold}` : ROBOT_STATE_TEXT[robot.state] || robot.state || "상태 없음";
  top.append(el("strong", "", robotId), el("span", `badge ${!robot.online || hold ? "bad" : "active"}`, stateText));
  row.appendChild(top);
  const [battery, batteryClass] = batteryText(robot);
  const sub = el("div", "mini-sub");
  sub.append(el("span", `battery ${batteryClass}`, battery),
    el("span", "", order ? `주문 ${order.order_id}` : "주문 없음"));
  row.appendChild(sub);

  const actions = el("div", "mini-actions");
  const canCommand = !service.read_only && Date.now() - view.lastOk < STALE_MS;
  if (hold) {
    actions.appendChild(button("정지 해제", "btn btn-small btn-primary",
      () => openReleaseDialog(robotId, hold), !commandsAllowed()));
  } else if (robot.online) {
    actions.appendChild(button("정지", "btn btn-small btn-danger", () => stopRobot(robotId), !canCommand));
  }
  if (actions.childElementCount) row.appendChild(actions);
  return row;
}

function renderRobots() {
  const robots = (view.fleet && view.fleet.robots) || {};
  const names = Object.keys(robots).sort();
  $("robots").replaceChildren(...names.map((name) => robotRow(name, robots[name])));
  $("robots-empty").hidden = names.length > 0;
}

function armName(arm) {
  const station = arm.site && arm.site.station;
  return `${arm.alias || arm.arm_id}${station ? ` (${station})` : ""}`;
}

function armRow(arm) {
  const [text, cls] = ARM_STATE_TEXT[arm.state] || [arm.state || "모름", "idle"];
  const row = el("div", `mini${cls === "bad" ? " bad" : ""}`);
  const top = el("div", "mini-top");
  top.append(el("strong", "", armName(arm)), el("span", `badge ${cls}`, text));
  row.appendChild(top);
  const work = arm.work && arm.work.state === "RUNNING" ? arm.work : null;
  if (work) {
    row.appendChild(el("div", "mini-sub", work.order_id ? `주문 ${work.order_id} 작업 중` : "시험 작업 중"));
  }
  return row;
}

function renderArms() {
  const arms = (view.arms && view.arms.arms) || [];
  $("arms").replaceChildren(...arms.map(armRow));
  $("arms-empty").hidden = arms.length > 0;
}

function renderStock() {
  const stock = view.service.stock || [];
  $("stock").replaceChildren(...stock.map((item) => {
    const tr = el("tr", item.available > 0 ? "" : "soldout");
    const shelf = item.shelf_row ? `${item.shelf_col}열 ${item.shelf_row}번` : "—";
    tr.append(el("td", "", item.sku), el("td", "", shelf),
      el("td", "num", item.available > 0 ? String(item.available) : "품절"));
    return tr;
  }));
  $("stock-empty").hidden = stock.length > 0;
}

// ---------- 조치 창 ----------
// 체크 항목은 버튼마다 필요한 것을 정한다. 모두 체크하고 이름을 적어야 그 버튼이 켜진다.

function openDialog({ title, lines, checks, actions }) {
  $("dialog-title").textContent = title;
  $("dialog-lines").replaceChildren(...lines.filter(Boolean).map((line) => el("p", "", line)));
  const boxes = {};
  $("dialog-checks").replaceChildren(...checks.map(([key, text]) => {
    const label = el("label", "check");
    const box = el("input");
    box.type = "checkbox";
    boxes[key] = box;
    label.append(box, el("span", "", text));
    return label;
  }));
  $("dialog-checks").hidden = checks.length === 0;
  $("dialog-operator").value = savedOperator();
  const buttons = actions.map((action) => {
    const node = button(action.label, `btn ${action.className || "btn-primary"}`, async () => {
      const operator = $("dialog-operator").value.trim();
      saveOperator(operator);
      const evidence = Object.fromEntries(action.needs.map((key) => [key, true]));
      $("dialog").close();
      await action.run(operator, evidence);
      poll();
    });
    node.dataset.needs = action.needs.join(",");
    return node;
  });
  buttons.push(button("닫기", "btn btn-plain", () => $("dialog").close()));
  $("dialog-actions").replaceChildren(...buttons);

  const update = () => {
    const named = $("dialog-operator").value.trim() !== "";
    for (const node of buttons) {
      if (node.dataset.needs === undefined) continue;
      const needs = node.dataset.needs ? node.dataset.needs.split(",") : [];
      node.disabled = !named || !needs.every((key) => boxes[key].checked) || !commandsAllowed();
    }
  };
  $("dialog-checks").onchange = update;
  $("dialog-operator").oninput = update;
  update();
  $("dialog").showModal();
}

function openLoadDialog(order) {
  openDialog({
    title: `주문 ${order.order_id} 상차 확인`,
    lines: [`${order.robot_id} · 상품 ${order.sku}`,
      "로봇팔이 상품을 싣지 못했습니다. 사람이 직접 실은 뒤 아래를 확인하세요.",
      "확인하면 로봇이 상차장을 나와 고객 자리로 갑니다."],
    checks: LOAD_CHECKS,
    actions: [{
      label: "상차 확인 · 출발", needs: LOAD_CHECKS.map(([key]) => key),
      run: async (operator, evidence) => {
        const result = await postJson(`/api/orders/${encodeURIComponent(order.order_id)}/confirm_loaded`,
          { client_request_id: newRequestId(), operator, note: "서비스 화면 수동 상차",
            evidence: { ...evidence, sku: order.sku } });
        toast(result.ok ? `주문 ${order.order_id} 상차 확인 · 출발합니다`
          : `상차 확인 거절: ${errorText(result)}`, !result.ok);
      },
    }],
  });
}

function openRecoverDialog(order) {
  const recover = (decision) => async (operator, evidence) => {
    const result = await postJson(`/api/orders/${encodeURIComponent(order.order_id)}/recover`,
      { client_request_id: newRequestId(), decision, operator, note: "서비스 화면", evidence });
    toast(result.ok ? (decision === "resume" ? `주문 ${order.order_id} 이어서 갑니다 (로봇 응답 기다림)`
      : `주문 ${order.order_id} 취소했습니다 (로봇 잠금 해제 기다림)`)
      : `처리 거절: ${errorText(result)}`, !result.ok);
  };
  const actions = [];
  const checks = [];
  if (order.resumable) {
    checks.push(["site_checked", "[이어서 가기] 로봇·상품·주변을 현장에서 확인했고 다시 움직여도 안전하다"]);
    actions.push({ label: "이어서 가기", needs: ["site_checked"], run: recover("resume") });
  }
  checks.push(...CANCEL_CHECKS.map(([key, text]) => [key, `[주문 취소] ${text}`]));
  actions.push({ label: "주문 취소", className: "btn-danger", needs: CANCEL_CHECKS.map(([key]) => key),
    run: recover("fail") });
  openDialog({
    title: `주문 ${order.order_id} 멈춤`,
    lines: [`${order.robot_id} · 상품 ${order.sku} · ${orderStateText(order)}`, `멈춘 곳: ${order.step_text}`,
      order.failure ? `문제: ${order.failure}` : "",
      order.resumable ? "이어서 가거나 주문을 취소할 수 있습니다." : "이 단계에서는 이어서 갈 수 없어 취소만 할 수 있습니다.",
      "고객에게는 주문을 처리하지 못했다고 안내됩니다 (취소할 때)."],
    checks,
    actions,
  });
}

function openReleaseDialog(robotId, hold) {
  openDialog({
    title: `${robotId} 정지 해제`,
    lines: [`정지 이유: ${HOLD_TEXT[hold] || hold}`, "해제하면 로봇이 다시 명령을 받습니다.",
      "작업 구역 안에서 멈췄다면 해제 뒤 엔지니어 화면에서 '나가기'로 빼냅니다."],
    checks: [["safe", "로봇이 멈춰 있고 주변에 사람·물건이 없다"]],
    actions: [{
      label: "정지 해제", needs: ["safe"],
      run: async (operator) => {
        const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/release_control`,
          { client_request_id: newRequestId(), operator, note: "서비스 화면" });
        toast(result.ok ? `${robotId} 정지 해제 요청 · 로봇 응답 기다림`
          : `정지 해제 거절: ${errorText(result)}`, !result.ok);
      },
    }],
  });
}

async function stopRobot(robotId) {
  // 정지는 확인 없이 바로 (안전한 쪽). 진행 중 주문은 멈추고, 이어 가려면 주문 카드에서 조치한다.
  const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/stop`,
    { client_request_id: newRequestId() });
  toast(result.ok ? `${robotId} 정지를 보냈습니다` : `정지를 보내지 못했습니다: ${errorText(result)}`, !result.ok);
  poll();
}

// ---------- 그리기 ----------

function render() {
  renderTop();
  renderAlerts();
  if (!view.service) return;
  // 창이 열려 있는 동안 목록을 다시 그려도 창 안 입력은 그대로다 (창은 목록 밖에 있다).
  renderOrders();
  renderRobots();
  renderArms();
  renderStock();
}

function start() {
  $("arm-toggle").addEventListener("click", toggleArmed);
  $("estop-all").addEventListener("click", estopAll);
  poll();
  setInterval(poll, POLL_MS);
}

start();
