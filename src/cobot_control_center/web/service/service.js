// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 매장 관리화면 (대시보드형). 엔지니어 화면(/)의 스크립트와 따로 둔다 (그 화면을 고쳐도 여기가 안 깨지게).
// 1초마다 /api/service·/api/fleet·/api/arms 를 읽어 다시 그린다. 조치는 기존 명령 API 로 보낸다.
// 판단(이어서 가기 가능 단계, 상차 확인 조건, 정지 잠금 해제 조건)은 fleet_control 이 하고,
// 이 화면의 버튼 표시는 힌트다. 거절되면 fleet 이 준 이유를 그대로 보여 준다.

"use strict";

const POLL_MS = 1000;
const TOAST_MS = 6000;
const STALE_MS = 4000;                  // 이만큼 못 읽으면 관제 끊김으로 본다
const LOW_STOCK = 1;                    // 이 수량 이하면 '부족' 표시
const OPERATOR_KEY = "cobot.operator";  // 엔지니어 화면과 같은 키 (같은 브라우저면 이름을 함께 기억)
const EQUIP_KEY = "cobot.service.equip_open";

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
  CARGO_ONBOARD: "신발 실려 있음",
};
// 로봇팔 상태 → [글, 색, 정상인지]
const ARM_STATE_TEXT = {
  READY: ["준비됨", "good", true], BUSY: ["작업 중", "active", true], OFF: ["꺼짐", "idle", false],
  HOLD: ["정지 유지", "warn", false], SOFT_LATCH: ["비상정지", "bad", false],
  FAULT: ["고장", "bad", false], STALE: ["연결 끊김", "bad", false],
};
const ORDER_STATE_TEXT = {
  UNKNOWN: "결과 모름", PAUSED: "일시정지", ESTOP: "비상정지", MANUAL: "수동 조작",
};
const OUTCOME_CLASS = { sold: "good", declined: "warn", timeout: "warn", done: "good", failed: "bad" };
// 주문 현황 보드 칸 이름 (백엔드 steps 와 같은 순서, 짧은 말)
const BOARD_TITLES = ["접수", "상품 준비", "이동", "고객 응대", "회수·정리", "복귀"];

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

const view = { service: null, fleet: null, arms: null, lastOk: 0, busy: false, polling: false };

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

const newRequestId = () => (crypto.randomUUID ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

// 브라우저 저장소는 막혀 있을 수 있다 (사생활 창 등). 그래도 화면은 돈다.
function load(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (err) {
    return fallback;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (err) {
    // 저장이 막혀 있어도 조치는 된다.
  }
}

// ---------- 시간 글 ----------

const two = (n) => String(n).padStart(2, "0");

// 오늘이면 "14:05", 아니면 "11-16 14:05" (며칠 전 주문이 섞여도 헷갈리지 않게)
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

// ---------- 공통 판단 ----------

const backendOk = () => Date.now() - view.lastOk < STALE_MS;
const controllerOnline = () => Boolean(view.service && view.service.controller_online);
const commandsAllowed = () => controllerOnline() && !view.service.read_only && backendOk();

function orderStateText(order) {
  return ORDER_STATE_TEXT[order.state] || HOLD_TEXT[order.state] || order.state;
}

function destinationName(order) {
  const dest = order.destination;
  if (!dest) return order.route || "—";
  const known = view.service.destinations && view.service.destinations[dest];
  return (known && known.name) || dest;
}

function button(label, className, onClick, disabled) {
  const node = el("button", className, label);
  node.type = "button";
  node.disabled = Boolean(disabled);
  node.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick(event);
  });
  return node;
}

// ---------- 위 ----------

function renderTop() {
  const now = new Date();
  $("date-line").textContent = `${now.getMonth() + 1}월 ${now.getDate()}일 `
    + `${"일월화수목금토"[now.getDay()]}요일 · ${two(now.getHours())}:${two(now.getMinutes())}`;

  const infra = view.fleet && view.fleet.infra;
  const readOnly = view.service && view.service.read_only;
  const chip = $("mode-chip");
  const test = infra && infra.mode !== "real";
  chip.hidden = !(test || readOnly);
  chip.textContent = [test ? "시험 모드" : "", readOnly ? "보기 전용" : ""].filter(Boolean).join(" · ");

  // 영업 상태 = '작업 명령 켜기'(commands_armed). 꺼져 있으면 로봇이 새 주문을 받지 않는다.
  const box = $("open-state");
  const toggle = $("arm-toggle");
  let state = "off";
  let text = "주문 멈춤";
  if (!backendOk()) {
    state = "down";
    text = "관제 연결 끊김";
  } else if (!controllerOnline()) {
    state = "down";
    text = "주문 처리기 응답 없음";
  } else if (view.service.commands_armed) {
    state = "on";
    text = "주문 받는 중";
  }
  box.dataset.state = state;
  $("open-text").textContent = text;
  toggle.hidden = state === "down";
  toggle.textContent = state === "on" ? "멈추기" : "주문 받기";
  toggle.disabled = !commandsAllowed() || view.busy;
  // 비상정지는 주문 처리가 꺼져 있어도 보낸다 (정지는 늘 안전한 쪽).
  $("estop-all").disabled = !view.service || readOnly || !backendOk();

  $("dot-backend").className = `dot ${backendOk() ? "ok" : "bad"}`;
  $("dot-controller").className = `dot ${controllerOnline() ? "ok" : "bad"}`;

  const banner = $("banner");
  banner.hidden = backendOk();
  banner.textContent = "관제에 연결되지 않습니다. 화면의 값이 오래된 것일 수 있습니다. 관제 PC 와 네트워크를 확인하세요.";
}

async function toggleArmed() {
  const armed = Boolean(view.service && view.service.commands_armed);
  if (!armed && !confirm("주문을 받을까요?\n로봇과 로봇팔이 주문에 따라 실제로 움직입니다.\n"
    + "로봇 길과 로봇팔 주변에 사람이 없는지 확인했나요?")) return;
  view.busy = true;
  renderTop();
  const result = await postJson("/api/commands/arm", { client_request_id: newRequestId(), armed: !armed });
  view.busy = false;
  toast(result.ok ? (armed ? "주문 받기를 멈췄습니다" : "주문을 받기 시작했습니다")
    : `바꾸지 못했습니다: ${errorText(result)}`, !result.ok);
  poll();
}

async function estopAll() {
  // 확인 창 없이 바로 보낸다 (늦게 멈추는 것이 더 위험하다).
  const result = await postJson("/api/commands/estop", { client_request_id: newRequestId() });
  toast(result.ok ? "모든 로봇을 멈췄습니다. 현장을 확인한 뒤 '할 일'에서 정지 해제하세요."
    : `비상정지를 보내지 못했습니다: ${errorText(result)} — 로봇의 비상정지 버튼을 직접 누르세요`, !result.ok);
  poll();
}

// ---------- 오늘 숫자 ----------

function renderKpis() {
  const today = view.service.today || {};
  $("kpi-total").textContent = today.total || 0;
  $("kpi-active").textContent = view.service.active.length;
  $("kpi-sold").textContent = today.sold || 0;
  $("kpi-returned").textContent = today.returned || 0;
  $("kpi-failed").textContent = today.failed || 0;
}

// ---------- 할 일 ----------
// 사람이 해야 하는 것만 모은다. 버튼이 있는 것(조치)이 위, 알림만 있는 것이 아래.

function collectTodo() {
  const service = view.service;
  const items = [];
  const add = (level, title, sub, action) => items.push({ level, title, sub, action });
  if (!controllerOnline()) {
    add("bad", "주문 처리기가 응답하지 않습니다", "새 주문이 처리되지 않습니다. 엔지니어에게 알려 주세요.");
  }
  for (const order of service.active) {
    const who = `${order.robot_id || "로봇 배정 전"} · ${order.sku || "상품 ?"} · ${destinationName(order)}`;
    if (order.blocked) {
      // 상차 확인도 기다리면 둘 다 고를 수 있게 주문 상세 창으로 간다.
      add("bad", `주문 ${order.order_id} 멈춤 (${orderStateText(order)})`, `${who} · ${order.step_text}`,
        { label: "처리하기",
          run: () => (order.load_confirmable ? openOrderDialog(order) : openRecoverDialog(order)) });
    } else if (order.load_confirmable) {
      add("warn", `주문 ${order.order_id} 상차 확인 필요`, `${who} · 사람이 직접 싣고 확인`,
        { label: "확인하기", run: () => openLoadDialog(order) });
    } else if (order.failure) {
      add("warn", `주문 ${order.order_id} 문제 생김`, `${who} · ${order.failure}`,
        { label: "보기", run: () => openOrderDialog(order) });
    }
  }
  for (const [robotId, reason] of Object.entries(service.holds || {})) {
    add("bad", `${robotId} 정지 잠금 (${HOLD_TEXT[reason] || reason})`,
      reason === "CARGO_ONBOARD" ? "고객 무응답 · 로봇 위 신발을 내린 뒤 풀어 주세요" : "현장을 확인한 뒤 풀어 주세요",
      { label: "정지 해제", run: () => openReleaseDialog(robotId, reason) });
  }
  for (const alert of (view.fleet && view.fleet.alerts) || []) {
    add(alert.level === "bad" ? "bad" : "warn", `${alert.robot} ${alert.text}`, "");
  }
  for (const arm of (view.arms && view.arms.arms) || []) {
    for (const alarm of arm.alarms || []) {
      add(alarm.level === "bad" ? "bad" : "warn", `${armName(arm)} ${alarm.text}`, "");
    }
  }
  for (const item of view.service.stock || []) {
    if (!(item.available > 0)) add("info", `${item.sku} 품절`, "선반을 채운 뒤 엔지니어에게 재고 수정을 요청하세요");
  }
  const rank = { bad: 0, warn: 1, info: 2 };
  return items.sort((a, b) => (Boolean(b.action) - Boolean(a.action)) || (rank[a.level] - rank[b.level]));
}

function renderTodo() {
  const items = collectTodo();
  const allowed = commandsAllowed();
  $("todo").replaceChildren(...items.map((item) => {
    const li = el("li", `todo-item ${item.level}`);
    const text = el("div", "todo-text");
    text.appendChild(el("strong", "", item.title));
    if (item.sub) text.appendChild(el("span", "", item.sub));
    li.append(el("i", "todo-mark"), text);
    if (item.action) {
      const look = item.action.label === "보기";
      li.appendChild(button(item.action.label, `btn ${look ? "btn-ghost" : "btn-primary"}`,
        item.action.run, !look && !allowed));
    }
    return li;
  }));
  const actionable = items.filter((item) => item.action && item.level !== "info").length;
  $("todo-count").textContent = items.length;
  $("todo-count").className = `count${actionable ? " hot" : ""}`;
  $("todo-empty").hidden = items.length > 0;
}

// ---------- 주문 현황 보드 ----------

function orderChip(order) {
  const service = view.service;
  const cls = order.blocked ? "stuck" : order.load_confirmable ? "attention" : "";
  const chip = el("button", `order-chip ${cls}`);
  chip.type = "button";
  const top = el("div", "chip-top");
  top.append(el("strong", "", order.order_id),
    el("span", "chip-age", durationText(service.now - order.created_at)));
  chip.appendChild(top);
  chip.appendChild(el("div", "chip-item", `${order.sku || "—"} → ${destinationName(order)}`));
  chip.appendChild(el("div", "chip-now", order.blocked ? `멈춤 · ${orderStateText(order)}`
    : order.load_confirmable ? "상차 확인 필요" : order.step_text));
  chip.appendChild(el("div", "chip-robot", order.robot_id || "로봇 배정 전"));
  chip.addEventListener("click", () => openOrderDialog(order));
  return chip;
}

function renderBoard() {
  const service = view.service;
  const columns = BOARD_TITLES.map((title, index) => {
    // 모르는 단계(step null)는 맨 앞 칸에 둔다 (사라지지 않게).
    const orders = service.active.filter((o) => (o.step === null || o.step === undefined ? 0 : o.step) === index);
    const col = el("div", `board-col${orders.length ? "" : " empty"}`);
    const head = el("div", "board-head");
    head.append(el("span", "", title), el("span", "board-count", String(orders.length)));
    col.appendChild(head);
    const list = el("div", "board-list");
    list.append(...orders.map(orderChip));
    col.appendChild(list);
    return col;
  });
  $("board").replaceChildren(...columns);
}

// ---------- 재고 ----------

function renderStock() {
  const stock = view.service.stock || [];
  const top = Math.max(5, ...stock.map((s) => s.available || 0));
  $("stock").replaceChildren(...stock.map((item) => {
    const qty = item.available || 0;
    const level = qty <= 0 ? "bad" : qty <= LOW_STOCK ? "warn" : "good";
    const li = el("li", `stock-item ${level}`);
    const head = el("div", "stock-head");
    head.append(el("span", "stock-sku", item.sku),
      el("strong", "stock-qty", qty > 0 ? `${qty}개` : "품절"));
    const bar = el("div", "stock-bar");
    const fill = el("i");
    fill.style.width = `${Math.round((qty / top) * 100)}%`;
    bar.appendChild(fill);
    li.append(head, bar);
    if (item.shelf_row) li.appendChild(el("span", "stock-shelf", `선반 ${item.shelf_col}열 ${item.shelf_row}번`));
    return li;
  }));
  $("stock-empty").hidden = stock.length > 0;
  const out = stock.filter((s) => !(s.available > 0)).length;
  $("stock-summary").textContent = stock.length ? `${stock.length}종${out ? ` · 품절 ${out}` : ""}` : "";
}

// ---------- 장비 ----------

function armName(arm) {
  const station = arm.site && arm.site.station;
  return `${arm.alias || arm.arm_id}${station ? ` (${station})` : ""}`;
}

function batteryText(robot) {
  const pct = robot.battery_percent;
  if (pct === null || pct === undefined) return ["배터리 —", "idle"];
  return [`배터리 ${Math.round(pct)}%`, pct <= 15 ? "bad" : pct <= 30 ? "warn" : "good"];
}

function robotTile(robotId, robot) {
  const service = view.service;
  const hold = service.holds && service.holds[robotId];
  const order = service.active.find((o) => o.robot_id === robotId);
  const bad = hold || !robot.online;
  const tile = el("div", `equip-tile${bad ? " bad" : ""}`);
  const top = el("div", "tile-top");
  const stateText = !robot.online ? "연결 끊김"
    : hold ? `정지 잠금` : ROBOT_STATE_TEXT[robot.state] || robot.state || "상태 없음";
  top.append(el("strong", "", robotId), el("span", `badge ${bad ? "bad" : "active"}`, stateText));
  const [battery, batteryClass] = batteryText(robot);
  const sub = el("div", "tile-sub");
  sub.append(el("span", `battery ${batteryClass}`, battery),
    el("span", "", order ? `주문 ${order.order_id}` : "주문 없음"));
  tile.append(top, sub);
  const canCommand = !service.read_only && backendOk();
  if (hold) {
    tile.appendChild(button("정지 해제", "btn btn-small btn-primary",
      () => openReleaseDialog(robotId, hold), !commandsAllowed()));
  } else if (robot.online) {
    tile.appendChild(button("이 로봇 정지", "btn btn-small btn-ghost-danger", () => stopRobot(robotId), !canCommand));
  }
  return tile;
}

function armTile(arm) {
  const [text, cls] = ARM_STATE_TEXT[arm.state] || [arm.state || "모름", "idle"];
  const tile = el("div", `equip-tile${cls === "bad" ? " bad" : ""}`);
  const top = el("div", "tile-top");
  top.append(el("strong", "", armName(arm)), el("span", `badge ${cls}`, text));
  tile.appendChild(top);
  const work = arm.work && arm.work.state === "RUNNING" ? arm.work : null;
  tile.appendChild(el("div", "tile-sub", work ? (work.order_id ? `주문 ${work.order_id} 작업 중` : "시험 작업 중") : ""));
  return tile;
}

function renderEquip() {
  const robots = (view.fleet && view.fleet.robots) || {};
  const names = Object.keys(robots).sort();
  const holds = view.service.holds || {};
  const robotsOk = names.filter((n) => robots[n].online && !holds[n]).length;
  const arms = (view.arms && view.arms.arms) || [];
  const armsOk = arms.filter((a) => (ARM_STATE_TEXT[a.state] || [])[2]).length;
  const summary = $("equip-summary");
  summary.replaceChildren(
    equipPart("로봇", robotsOk, names.length),
    equipPart("로봇팔", armsOk, arms.length));
  $("robots").replaceChildren(...(names.length ? names.map((n) => robotTile(n, robots[n]))
    : [el("p", "empty", "로봇 정보를 아직 받지 못했습니다.")]));
  $("arms").replaceChildren(...(arms.length ? arms.map(armTile)
    : [el("p", "empty", "로봇팔 정보가 없습니다.")]));
}

function equipPart(name, ok, total) {
  const level = !total ? "idle" : ok === total ? "good" : ok === 0 ? "bad" : "warn";
  const part = el("span", `equip-part ${level}`);
  part.append(el("i"), document.createTextNode(total ? `${name} ${ok}/${total} 정상` : `${name} 정보 없음`));
  return part;
}

function setEquipOpen(open) {
  $("equip-detail").hidden = !open;
  $("equip-toggle").setAttribute("aria-expanded", String(open));
  $("equip-toggle").querySelector(".equip-more").textContent = open ? "접기" : "자세히";
  store(EQUIP_KEY, open ? "1" : "0");
}

// ---------- 최근 주문 내역 ----------

function renderHistory() {
  const finished = view.service.finished;
  $("history").replaceChildren(...finished.map((order) => {
    const tr = el("tr");
    const result = el("td");
    result.appendChild(el("span", `badge ${OUTCOME_CLASS[order.outcome] || ""}`, order.outcome_text));
    if (order.failure) result.appendChild(el("div", "why", order.failure));
    tr.append(el("td", "", clockText(order.updated_at)), el("td", "mono", order.order_id),
      el("td", "", order.sku || "—"), el("td", "", destinationName(order)), result,
      el("td", "num", durationText(order.updated_at - order.created_at)));
    tr.addEventListener("click", () => openOrderDialog(order));
    return tr;
  }));
  $("history-empty").hidden = finished.length > 0;
  $("history-summary").textContent = finished.length ? `최근 ${finished.length}건` : "";
}

// ---------- 창 ----------
// 체크 항목은 버튼마다 필요한 것(needs)을 정한다. needs 가 있는 버튼은 그 칸을 모두 체크하고
// 처리한 사람 이름을 적어야 켜진다. needs 가 없는 버튼(다른 창 열기)은 늘 켜져 있다.

function openDialog({ title, body, checks = [], actions = [] }) {
  $("dialog-title").textContent = title;
  $("dialog-body").replaceChildren(...body.filter(Boolean).map(
    (part) => (typeof part === "string" ? el("p", "", part) : part)));
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
  const needsOperator = actions.some((action) => action.needs);
  $("dialog-operator-row").hidden = !needsOperator;
  $("dialog-operator").value = load(OPERATOR_KEY, "");
  const buttons = actions.map((action) => {
    const node = button(action.label, `btn ${action.className || "btn-primary"}`, async () => {
      const operator = $("dialog-operator").value.trim();
      if (action.needs) store(OPERATOR_KEY, operator);
      const evidence = Object.fromEntries((action.needs || []).map((key) => [key, true]));
      $("dialog").close();
      await action.run(operator, evidence);
      poll();
    });
    node.needs = action.needs || null;
    node.locked = Boolean(action.disabled);
    return node;
  });
  buttons.push(button("닫기", "btn btn-ghost", () => $("dialog").close()));
  $("dialog-actions").replaceChildren(...buttons);

  const update = () => {
    const named = $("dialog-operator").value.trim() !== "";
    for (const node of buttons) {
      if (node.needs === undefined) continue;  // 닫기
      if (node.needs === null) {
        node.disabled = node.locked;
        continue;
      }
      node.disabled = node.locked || !named || !node.needs.every((key) => boxes[key].checked)
        || !commandsAllowed();
    }
  };
  $("dialog-checks").onchange = update;
  $("dialog-operator").oninput = update;
  update();
  if (!$("dialog").open) $("dialog").showModal();
}

function stepBar(order) {
  const bar = el("ol", "steps");
  BOARD_TITLES.forEach((name, index) => {
    // 회수·정리(4)는 고객이 사지 않았을 때만 거친다. 그 밖에는 흐리게 건너뜀으로 보인다.
    let cls = "todo";
    if (index === 4 && !order.returning) cls = "skip";
    else if (order.outcome) cls = "done";
    else if (order.step === null || order.step === undefined) cls = "todo";
    else if (index < order.step) cls = "done";
    else if (index === order.step) cls = order.blocked ? "now stuck" : "now";
    bar.appendChild(el("li", cls, name));
  });
  return bar;
}

function factList(pairs) {
  const dl = el("dl", "facts");
  for (const [label, value] of pairs) dl.append(el("dt", "", label), el("dd", "", value));
  return dl;
}

function openOrderDialog(order) {
  const service = view.service;
  const finished = Boolean(order.outcome);
  const status = finished ? order.outcome_text
    : order.blocked ? `멈춤 (${orderStateText(order)}) · ${order.step_text}`
      : order.load_confirmable ? "상차장에서 멈춤 · 상차 확인 필요" : order.step_text;
  const actions = [];
  if (!finished && order.load_confirmable) {
    actions.push({ label: "상차 확인", run: () => openLoadDialog(order), disabled: !commandsAllowed() });
  }
  if (!finished && order.blocked) {
    actions.push({ label: order.resumable ? "이어서 가기 / 취소" : "주문 취소", className: "btn-danger",
      run: () => openRecoverDialog(order), disabled: !commandsAllowed() });
  }
  openDialog({
    title: `주문 ${order.order_id}`,
    body: [
      el("p", `dialog-status ${finished ? OUTCOME_CLASS[order.outcome] || "" : order.blocked ? "bad" : ""}`, status),
      stepBar(order),
      factList([["상품", order.sku || "—"], ["자리", destinationName(order)],
        ["로봇", order.robot_id || "배정 전"], ["접수", clockText(order.created_at)],
        [finished ? "끝남" : "경과", finished ? `${clockText(order.updated_at)} (${durationText(order.updated_at - order.created_at)})`
          : durationText(service.now - order.created_at)],
        ...(order.failure ? [["문제", order.failure]] : [])]),
    ],
    actions,
  });
}

function openLoadDialog(order) {
  openDialog({
    title: `주문 ${order.order_id} 상차 확인`,
    body: [`${order.robot_id} · 상품 ${order.sku}`,
      "로봇팔이 상품을 싣지 못했습니다. 사람이 직접 실은 뒤 아래를 확인하세요.",
      "확인하면 로봇이 상차장을 나와 고객 자리로 갑니다."],
    checks: LOAD_CHECKS,
    actions: [{
      label: "상차 확인 · 출발", needs: LOAD_CHECKS.map(([key]) => key),
      run: async (operator, evidence) => {
        const result = await postJson(`/api/orders/${encodeURIComponent(order.order_id)}/confirm_loaded`,
          { client_request_id: newRequestId(), operator, note: "관리화면 수동 상차",
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
      { client_request_id: newRequestId(), decision, operator, note: "관리화면", evidence });
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
    body: [`${order.robot_id} · 상품 ${order.sku} · ${orderStateText(order)}`, `멈춘 곳: ${order.step_text}`,
      order.failure ? `문제: ${order.failure}` : "",
      order.resumable ? "이어서 가거나 주문을 취소할 수 있습니다." : "이 단계에서는 이어서 갈 수 없어 취소만 할 수 있습니다.",
      "취소하면 고객 화면에는 주문을 처리하지 못했다고 나옵니다."],
    checks,
    actions,
  });
}

function openReleaseDialog(robotId, hold) {
  const cargo = hold === "CARGO_ONBOARD";
  openDialog({
    title: `${robotId} 정지 해제`,
    body: [`정지 이유: ${HOLD_TEXT[hold] || hold}`, "해제하면 로봇이 다시 명령을 받습니다.",
      "작업 구역 안에서 멈췄다면 해제 뒤 엔지니어에게 '나가기'를 요청하세요."],
    checks: [["safe", "로봇이 멈춰 있고 주변에 사람·물건이 없다"],
      ...(cargo ? [["unloaded", "로봇 위 신발을 내렸다"]] : [])],
    actions: [{
      label: "정지 해제", needs: cargo ? ["safe", "unloaded"] : ["safe"],
      run: async (operator) => {
        const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/release_control`,
          { client_request_id: newRequestId(), operator, note: "관리화면" });
        toast(result.ok ? `${robotId} 정지 해제 요청 · 로봇 응답 기다림`
          : `정지 해제 거절: ${errorText(result)}`, !result.ok);
      },
    }],
  });
}

async function stopRobot(robotId) {
  // 정지는 확인 없이 바로 (안전한 쪽). 진행 중 주문은 멈추고, 이어 가려면 '할 일'에서 조치한다.
  const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/stop`,
    { client_request_id: newRequestId() });
  toast(result.ok ? `${robotId} 정지를 보냈습니다` : `정지를 보내지 못했습니다: ${errorText(result)}`, !result.ok);
  poll();
}

// ---------- 그리기 ----------

function render() {
  renderTop();
  if (!view.service) return;
  // 창은 목록 밖에 있어서 목록을 다시 그려도 창 안 체크·이름은 그대로다.
  renderKpis();
  renderTodo();
  renderBoard();
  renderStock();
  renderEquip();
  renderHistory();
}

function start() {
  $("arm-toggle").addEventListener("click", toggleArmed);
  $("estop-all").addEventListener("click", estopAll);
  $("equip-toggle").addEventListener("click",
    () => setEquipOpen($("equip-detail").hidden));
  setEquipOpen(load(EQUIP_KEY, "0") === "1");
  poll();
  setInterval(poll, POLL_MS);
}

start();
