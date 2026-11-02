// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 관제 화면: /ws/fleet 스냅샷으로 카드·구역·지도를 그린다.
// 명령은 /api/tasks·/api/robots/{id}/stop 으로만 보내고, 작업 상태는 /ws/tasks 로 받는다.
// 로봇이 보낸 문자열(detail 등)은 textContent 로만 넣는다 (HTML 로 해석하지 않는다).

"use strict";

const RECONNECT_MS = 2000;
const HEALTH_POLL_MS = 2000;
const ROBOT_RADIUS_M = 0.06;   // 지도 위 로봇 원 반지름 [m]
const BATTERY_LOW = 30;        // [%] 이하 주황
const BATTERY_CRITICAL = 15;   // [%] 이하 빨강
const ZONE_RADIUS_M = 0.12;    // 지도 위 구역 지점 원 반지름 [m] (표시용, 실제 구역 넓이 아님)
const MARK_RADIUS_M = 0.035;   // 출구·대기 슬롯·홈 표시 크기 [m]
const SHOW_LAYERS_KEY = "cobot_control_center.show_layers";
const SHOW_POINTS_KEY = "cobot_control_center.show_points";
const EVENTS_MAX = 500;        // 화면에 들고 있을 이벤트 수 (백엔드 events_max 와 같게)

// 순찰 노드 state → 색 묶음
const STATE_GROUP = {
  MOVING: "active", STARTING: "active", RETURNING: "active",
  LEAVING_ZONE: "active", RETREATING: "active",
  QUEUEING: "warn", IDLE_WAIT: "warn", RETRY: "warn",
  ARRIVED: "good", HOLDING_ZONE: "good", DONE: "good",
  FAILED: "bad", STOPPED: "bad",
  IDLE: "idle",
};

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = (id) => document.getElementById(id);

// 기반 노드 판정(fleet_status 의 infra) → 점 색과 설명
const INFRA_STATE = {
  ok: { dot: "good", text: "정상" },
  missing: { dot: "bad", text: "없음" },
  duplicate: { dot: "bad", text: "중복" },
  unknown: { dot: "warn", text: "확인 불가 (DDS 가 달라 이름이 안 보임)" },
  "n/a": { dot: "na", text: "해당 없음 (실물 도메인 아님)" },
};
const MODE_TEXT = { real: "실물", mock: "가짜 핑키", test: "시험" };

const view = {
  snapshot: null,
  receivedAt: 0,
  healthDomain: null, // /api/health 의 domain_id (fleet_status 를 받기 전에도 보이게)
  map: null,        // {info, canvas}
  layers: null,     // /api/map/layers (구역 지점·출구·대기 슬롯·홈)
  showLayers: true, // 지도 구역 표시 켜기/끄기 (브라우저에 기억)
  showPoints: true, // 지도 일반 웨이포인트(P) 표시 켜기/끄기 (브라우저에 기억)
  cards: new Map(), // robot_id → card element
  events: [],       // 이벤트 로그 (오래된 것부터, id 오름차순)
  lastEventId: 0,
  tasks: new Map(), // task_id → 작업 (/ws/tasks)
  taskManagerOnline: false,
};

function robotColorVar(index) {
  return `--robot-${(index % 3) + 1}`;
}

// ---------- 연결 ----------

function setLink(id, ok) {
  $(id).dataset.state = ok ? "good" : "bad";
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/fleet`);
  // 다시 붙으면 이벤트를 처음부터 다시 받는다 (백엔드가 다시 켜졌으면 id 가 1 부터 다시 시작).
  ws.onopen = () => {
    setLink("link-ws", true);
    loadEvents();
  };
  ws.onmessage = (event) => {
    view.snapshot = JSON.parse(event.data);
    view.receivedAt = Date.now();
    addEvents(view.snapshot.events);
    render();
  };
  ws.onclose = () => {
    setLink("link-ws", false);
    setTimeout(connect, RECONNECT_MS);
  };
  ws.onerror = () => ws.close();
}

// ---------- 도메인·기반 노드 ----------

function renderMode(infra) {
  const el = $("mode");
  const domain = infra ? infra.domain_id : view.healthDomain;
  const mode = infra ? infra.mode : "unknown";
  el.dataset.mode = mode;
  el.textContent = domain === null || domain === undefined ? "도메인 ?"
    : MODE_TEXT[mode] ? `도메인 ${domain} · ${MODE_TEXT[mode]}` : `도메인 ${domain}`;
  el.title = mode === "real" ? "실물 관제 도메인입니다"
    : mode === "unknown" ? "관제 노드 정보를 기다리는 중"
    : `실물 관제 도메인(${infra.control_domain_id})이 아닙니다`;
}

// 관제 노드가 끊기면 마지막 판정이 낡았으므로 회색으로 둔다.
function renderInfra(infra, fresh) {
  const zone = $("link-zone");
  const zoneState = infra && fresh ? infra.zone_manager.state : "n/a";
  zone.dataset.state = INFRA_STATE[zoneState].dot;
  zone.querySelector(".label").textContent = zoneState === "duplicate"
    ? `zone_manager 중복 ${infra.zone_manager.count}` : "zone_manager";
  zone.title = fresh ? `zone_manager: ${INFRA_STATE[zoneState].text}` : "관제 노드 끊김";

  const box = $("link-bridges");
  box.querySelectorAll(".dot").forEach((dot) => dot.remove());
  Object.entries((infra && infra.bridges) || {}).forEach(([robotId, bridge], index) => {
    const state = fresh ? bridge.state : "n/a";
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.dataset.state = INFRA_STATE[state].dot;
    dot.appendChild(document.createElement("i"));
    dot.appendChild(document.createTextNode(String(index + 1)));
    dot.title = fresh
      ? `${robotId} (${bridge.node}): ${INFRA_STATE[state].text}${bridge.count > 1 ? ` ${bridge.count}개` : ""}`
      : "관제 노드 끊김";
    box.appendChild(dot);
  });
}

// ---------- 카드 ----------

function ensureCard(robotId, index) {
  if (view.cards.has(robotId)) return view.cards.get(robotId);
  const card = $("card-template").content.firstElementChild.cloneNode(true);
  card.style.setProperty("--robot-color", `var(${robotColorVar(index)})`);
  card.querySelector(".name").textContent = robotId;
  setupTeach(card);
  setupCommands(card, robotId);
  $("cards").appendChild(card);
  view.cards.set(robotId, card);
  return card;
}

function formatShortAge(sec) {
  if (sec === null || sec === undefined) return "—";
  if (sec < 10) return `${sec.toFixed(1)}s`;
  if (sec < 60) return `${Math.round(sec)}s`;
  return `${Math.floor(sec / 60)}m`;
}

function formatAge(sec) {
  if (sec === null || sec === undefined) return "-";
  if (sec < 1) return "방금";
  if (sec < 60) return `${Math.round(sec)}초 전`;
  return `${Math.floor(sec / 60)}분 전`;
}

function renderCard(robotId, robot, index) {
  const card = ensureCard(robotId, index);
  const status = robot.never_seen ? "never" : robot.online ? "online" : "offline";
  card.classList.toggle("offline", status !== "online");

  const badge = card.querySelector(".badge");
  badge.dataset.state = status;
  badge.textContent = { online: "연결", offline: "끊김", never: "미수신" }[status];

  const state = card.querySelector(".state");
  state.textContent = robot.state || "상태 없음";
  const group = STATE_GROUP[robot.state] || "idle";
  state.style.setProperty("--state-color", `var(--${group})`);

  const parts = [];
  if (robot.detail) parts.push(robot.detail);
  if (robot.waypoint !== null && robot.waypoint !== undefined && robot.waypoint >= 0) {
    parts.push(`#${robot.waypoint}`);
  }
  card.querySelector(".detail").textContent = parts.join(" · ");

  const fill = card.querySelector(".battery-fill");
  const text = card.querySelector(".battery-text");
  const pct = robot.battery_percent;
  if (pct === null || pct === undefined) {
    fill.style.width = "0";
    text.textContent = "—";
  } else {
    const clamped = Math.max(0, Math.min(100, pct));
    fill.style.width = `${clamped}%`;
    fill.dataset.level = clamped <= BATTERY_CRITICAL ? "critical"
      : clamped <= BATTERY_LOW ? "low" : "ok";
    text.textContent = `${Math.round(clamped)}%`;
  }

  const meta = [];
  if (robot.pose) {
    const deg = (robot.pose.yaw * 180 / Math.PI).toFixed(0);
    meta.push(`(${robot.pose.x.toFixed(2)}, ${robot.pose.y.toFixed(2)}) m · ${deg}°`);
  }
  meta.push(`수신 ${formatAge(robot.last_seen_age)}`);
  card.querySelector(".meta").textContent = meta.join(" · ");
  const ages = robot.topic_age || {};
  card.querySelector(".topics").textContent =
    `위치 ${formatShortAge(ages.pose)} · 배터리 ${formatShortAge(ages.battery)} · 상태 ${formatShortAge(ages.status)}`;
  renderTeach(card, robotId, robot);
  renderCommands(card, robotId, robot);
}

// ---------- 위치 복사 (웨이포인트 티칭) ----------
// 로봇을 사람이 세운 뒤 버튼을 누르면 지금 위치를 [x, y, yaw] 로 클립보드에 넣는다
// (pinkyN.yaml points 의 값 형식). 서버에 저장하거나 로봇에 보내지 않는다.

const COPIED_MS = 2000; // '복사됨' 표시 시간 [ms]

function teachLine(robot) {
  const p = robot.pose;
  return `[${p.x.toFixed(3)}, ${p.y.toFixed(3)}, ${p.yaw.toFixed(2)}]`;
}

function setupTeach(card) {
  card.querySelector(".teach-btn").addEventListener("click", () => copyTeach(card));
}

// 경고는 버튼 옆에 짧게 보이고, 전체 문장은 마우스를 올리면 보인다. 복사는 막지 않는다.
function renderTeach(card, robotId, robot) {
  const warnings = (robot.teach && robot.teach.warnings) || [];
  const warn = card.querySelector(".teach-warn");
  warn.textContent = warnings.length ? `⚠ ${warnings[0].split(" (")[0]}` : "";
  warn.title = warnings.join("\n");
  card.querySelector(".teach-btn").disabled = !robot.pose;
}

async function copyTeach(card) {
  const robotId = card.querySelector(".name").textContent;
  const robot = view.snapshot && view.snapshot.robots ? view.snapshot.robots[robotId] : null;
  if (!robot || !robot.pose) return;
  const text = teachLine(robot);
  const button = card.querySelector(".teach-btn");
  const line = card.querySelector(".teach-line");
  try {
    await navigator.clipboard.writeText(text);
    line.hidden = true;
    button.textContent = "복사됨 ✓";
    setTimeout(() => { button.textContent = "위치 복사"; }, COPIED_MS);
  } catch (err) {
    // 클립보드를 못 쓰는 환경(http://localhost 가 아닌 주소 등): 줄을 보여 주고 선택해 둔다.
    line.textContent = text;
    line.hidden = false;
    const range = document.createRange();
    range.selectNodeContents(line);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    button.textContent = "Ctrl+C 로 복사";
    setTimeout(() => { button.textContent = "위치 복사"; }, COPIED_MS);
  }
}

// ---------- 경고·이벤트 ----------

function robotIndex(robotId) {
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  return robots.indexOf(robotId);
}

function renderAlerts(alerts, fresh) {
  const box = $("alerts");
  // 관제 노드가 끊기면 마지막 경고가 남아 있어 헷갈리므로 숨긴다 (끊김은 상단 점이 알려 준다).
  const list = fresh ? alerts || [] : [];
  box.hidden = list.length === 0;
  box.replaceChildren();
  for (const alert of list) {
    const item = document.createElement("li");
    item.dataset.level = alert.level;
    if (alert.robot) {
      const who = document.createElement("strong");
      who.textContent = alert.robot;
      item.appendChild(who);
    }
    item.appendChild(document.createTextNode(alert.text));
    box.appendChild(item);
  }
}

async function loadEvents() {
  try {
    const res = await fetch(`/api/events?limit=${EVENTS_MAX}`);
    if (!res.ok) return;
    view.events = [];
    view.lastEventId = 0;
    addEvents(await res.json());
  } catch (err) {
    // 다음 연결 때 다시 읽는다.
  }
}

function addEvents(events) {
  let added = false;
  for (const event of events || []) {
    if (typeof event.id !== "number" || event.id <= view.lastEventId) continue;
    view.events.push(event);
    view.lastEventId = event.id;
    added = true;
  }
  if (view.events.length > EVENTS_MAX) view.events.splice(0, view.events.length - EVENTS_MAX);
  if (added) renderEvents();
}

function renderEventFilter() {
  const select = $("event-robot");
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  const have = new Set([...select.options].map((o) => o.value));
  for (const robotId of robots) {
    if (have.has(robotId)) continue;
    const option = document.createElement("option");
    option.value = robotId;
    option.textContent = robotId;
    select.appendChild(option);
  }
}

function renderEvents() {
  const box = $("events");
  const filter = $("event-robot").value;
  const shown = view.events.filter((e) => !filter || e.robot === filter).slice().reverse();
  box.replaceChildren();
  if (shown.length === 0) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "이벤트 없음";
    box.appendChild(empty);
    return;
  }
  for (const event of shown) {
    const item = document.createElement("li");
    item.dataset.level = event.level;
    const time = document.createElement("time");
    time.textContent = new Date(event.time * 1000).toLocaleTimeString();
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = event.robot || "구역";
    const index = event.robot ? robotIndex(event.robot) : -1;
    if (index >= 0) who.style.setProperty("--robot-color", `var(${robotColorVar(index)})`);
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = event.text;
    item.append(time, who, text);
    box.appendChild(item);
  }
}

// ---------- 명령 ----------
// 화면은 요청만 한다. 검증·기록·발행은 task_manager_node 가 하고, 결과는 /ws/tasks 로 온다.
// 정지는 항상 누를 수 있다. 다른 명령은 연결돼 있고, 작업 중이 아니고, 작업 노드가 살아 있을 때만.

const ACTIVE_TASK = new Set(["ACCEPTED", "SENT", "RUNNING"]);
// 로봇이 이 상태면 관제 작업이 없어도 움직이는 중이다 (유휴 복귀 등). task_manager 와 같은 목록.
const BUSY_ROBOT = new Set(["STARTING", "MOVING", "QUEUEING", "WAITING_ZONE", "ARRIVED",
  "LEAVING_ZONE", "RETREATING", "RETURNING", "RETRY"]);
const TASK_GROUP = {
  ACCEPTED: "active", SENT: "active", RUNNING: "active",
  SUCCEEDED: "good", FAILED: "bad", STOPPED: "bad", REJECTED: "warn", UNKNOWN: "bad",
};
const TASK_TEXT = {
  ACCEPTED: "받음", SENT: "보냄", RUNNING: "진행", SUCCEEDED: "성공", FAILED: "실패",
  STOPPED: "중단", REJECTED: "거절", UNKNOWN: "결과 모름",
};
const OP_TEXT = { goto: "이동", zone: "구역", leave: "나가기", home: "홈" };
const TASK_LIST_MAX = 15;
const MSG_MS = 6000;

const newRequestId = () => (crypto.randomUUID ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

// 이 로봇의 진행 중·결과 모름 작업 (최신 하나)
function robotTask(robotId, states) {
  let found = null;
  for (const task of view.tasks.values()) {
    if (task.robot_id === robotId && states.has(task.state)
        && (!found || task.created_at > found.created_at)) found = task;
  }
  return found;
}

function setupCommands(card, robotId) {
  card.querySelectorAll(".cmd-row button").forEach((button) => {
    button.addEventListener("click", () => onCommand(robotId, button.dataset.cmd));
  });
}

function renderCommands(card, robotId, robot) {
  const active = robotTask(robotId, ACTIVE_TASK);
  const unknown = robotTask(robotId, new Set(["UNKNOWN"]));
  const reason = !view.taskManagerOnline ? "작업 노드 꺼짐"
    : !robot.online ? "연결 끊김"
    : unknown ? `결과 모름 작업 ${unknown.task_id}: 현장 확인 후 해제`
    : active ? `작업 중 ${active.task_id}`
    : BUSY_ROBOT.has(robot.state) ? `로봇 작업 중 (${robot.state})` : "";
  card.querySelectorAll(".cmd-row button").forEach((button) => {
    const isStop = button.classList.contains("stop-btn");
    button.disabled = isStop ? !view.taskManagerOnline : Boolean(reason);
    if (!isStop) button.title = reason;
  });
  const line = card.querySelector(".cmd-task");
  const task = active || unknown;
  line.textContent = task
    ? `${task.command} · ${TASK_TEXT[task.state] || task.state}${task.detail ? ` · ${task.detail}` : ""}`
    : "";
  line.dataset.state = task ? task.state : "";
}

function showMessage(text, bad) {
  const el = $("cmd-msg");
  el.textContent = text;
  el.dataset.bad = bad ? "1" : "";
  el.hidden = false;
  clearTimeout(showMessage.timer);
  showMessage.timer = setTimeout(() => { el.hidden = true; }, MSG_MS);
}

async function postJson(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: { detail: "백엔드에 연결하지 못함" } };
  }
}

function errorText(result) {
  const detail = result.data && result.data.detail;
  return typeof detail === "string" ? detail : JSON.stringify(detail || result.data);
}

async function onCommand(robotId, cmd) {
  if (cmd === "stop" || cmd === "emergency_stop") {
    // 정지는 확인 창 없이 바로 보낸다 (늦으면 안 되는 명령).
    const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/stop`,
      { client_request_id: newRequestId(), emergency: cmd === "emergency_stop" });
    if (result.ok) {
      showMessage(`${robotId} ${cmd === "stop" ? "정지" : "비상정지"} 보냄`
        + (result.data.warning ? ` · ${result.data.warning}` : ""), false);
    } else {
      showMessage(`${robotId} 정지 실패 (${result.status}): ${errorText(result)}`, true);
    }
    return;
  }
  const points = await choosePoints(robotId, cmd);
  if (points === null) return;
  const result = await postJson("/api/tasks", {
    client_request_id: newRequestId(), robot_id: robotId, operation: cmd, points,
  });
  if (result.data && result.data.task_id) upsertTask(result.data);
  if (result.data && result.data.task) upsertTask(result.data.task);
  if (result.ok) {
    showMessage(`${robotId} ${result.data.command} 보냄 (${result.data.task_id})`, false);
  } else {
    showMessage(`${robotId} ${OP_TEXT[cmd]} 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

// 지점 고르기 + 확인 창. 고른 지점 목록, 취소하면 null.
function pointChoices(robotId, cmd) {
  const layers = view.layers;
  if (!layers) return null;
  if (cmd === "goto") {
    const names = Object.keys(layers.points || {});
    const home = layers.homes && layers.homes[robotId];
    return home ? [...names, home.name] : names;
  }
  if (cmd === "zone") {
    return Object.values(layers.zones || {}).flatMap((zone) => Object.keys(zone.points || {}));
  }
  return [];
}

function choosePoints(robotId, cmd) {
  const dialog = $("cmd-dialog");
  const pick = $("cmd-pick");
  const route = [];
  const choices = pointChoices(robotId, cmd);
  const needsPoints = cmd === "goto" || cmd === "zone";
  let input = null;

  const update = () => {
    const names = input ? input.value.toUpperCase().split(/[\s,]+/).filter(Boolean) : route;
    const target = cmd === "goto" ? (names.length ? names.join(" → ") : "지점을 고르세요")
      : cmd === "zone" ? (names[0] || "구역 지점을 고르세요")
      : cmd === "home" ? "홈" : "보유 구역 출구";
    $("cmd-route").textContent = `${robotId} 을(를) ${target} (으)로 보냅니다`;
    $("cmd-ok").disabled = needsPoints && names.length === 0;
    return names;
  };

  $("cmd-title").textContent = `${robotId} · ${OP_TEXT[cmd]}`;
  pick.replaceChildren();
  $("cmd-clear").hidden = cmd !== "goto";
  $("cmd-warn").textContent = view.snapshot && view.snapshot.infra
    && view.snapshot.infra.mode === "real" ? "⚠ 실물 로봇이 움직입니다. 주변을 확인하세요." : "";
  if (needsPoints && choices === null) {
    // 지점 목록(/api/map/layers)이 없으면 직접 적는다. 로봇·작업 노드가 다시 검사한다.
    input = document.createElement("input");
    input.placeholder = cmd === "goto" ? "P1, P2" : "ZA";
    input.addEventListener("input", update);
    pick.appendChild(input);
  } else if (needsPoints) {
    for (const name of choices) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = name;
      button.addEventListener("click", () => {
        if (cmd === "zone") route.length = 0;
        route.push(name);
        update();
      });
      pick.appendChild(button);
    }
  }
  $("cmd-clear").onclick = () => { route.length = 0; update(); };
  update();

  return new Promise((resolve) => {
    dialog.onclose = () => resolve(dialog.returnValue === "ok" ? update() : null);
    dialog.returnValue = "";
    dialog.showModal();
  });
}

// ---------- 작업 목록 ----------

function upsertTask(task) {
  if (!task || !task.task_id) return;
  view.tasks.set(task.task_id, task);
}

function connectTasks() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/tasks`);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "tasks") {
      view.tasks = new Map(msg.tasks.map((t) => [t.task_id, t]));
    } else if (msg.type === "task") {
      upsertTask(msg.task);
    }
    renderTasks();
    render();
  };
  ws.onclose = () => setTimeout(connectTasks, RECONNECT_MS);
  ws.onerror = () => ws.close();
}

function formatClock(sec) {
  return sec ? new Date(sec * 1000).toLocaleTimeString() : "";
}

function renderTasks() {
  const list = $("tasks");
  const tasks = [...view.tasks.values()].sort((a, b) => b.created_at - a.created_at);
  // 결과 모름은 위로 올려 놓치지 않게 한다.
  tasks.sort((a, b) => (b.state === "UNKNOWN") - (a.state === "UNKNOWN"));
  const unknown = tasks.filter((t) => t.state === "UNKNOWN").length;
  $("tasks-meta").textContent = unknown ? `결과 모름 ${unknown}건` : "";
  if (tasks.length === 0) {
    list.innerHTML = '<li class="muted">작업 없음</li>';
    return;
  }
  list.replaceChildren(...tasks.slice(0, TASK_LIST_MAX).map((task) => {
    const el = $("task-template").content.firstElementChild.cloneNode(true);
    el.dataset.state = task.state;
    el.querySelector(".task-robot").textContent = task.robot_id;
    el.querySelector(".task-command").textContent = task.command;
    const state = el.querySelector(".task-state");
    state.textContent = TASK_TEXT[task.state] || task.state;
    state.style.setProperty("--state-color", `var(--${TASK_GROUP[task.state] || "idle"})`);
    el.querySelector(".task-detail").textContent = task.detail || "";
    el.querySelector(".task-meta").textContent =
      `${task.task_id} · ${task.spec} · ${formatClock(task.created_at)}`;
    const resolve = el.querySelector(".resolve-btn");
    resolve.hidden = task.state !== "UNKNOWN";
    resolve.addEventListener("click", () => resolveTask(task));
    return el;
  }));
}

async function resolveTask(task) {
  const note = prompt(
    `${task.robot_id} ${task.command} (${task.task_id})\n`
    + "로봇이 멈춘 것을 현장에서 확인했습니까? 확인 내용을 적으면 해제합니다 (실패로 기록).",
    "현장에서 정지 확인");
  if (note === null) return;
  const result = await postJson(`/api/tasks/${encodeURIComponent(task.task_id)}/resolve`,
    { client_request_id: newRequestId(), result: "FAILED", note });
  if (result.ok) {
    upsertTask(result.data);
    renderTasks();
    render();
    showMessage(`${task.task_id} 해제함`, false);
  } else {
    showMessage(`${task.task_id} 해제 실패 (${result.status}): ${errorText(result)}`, true);
  }
}

// ---------- 구역 ----------

function renderZones(zones) {
  const box = $("zones");
  const names = Object.keys(zones || {}).sort();
  if (names.length === 0) return;
  box.replaceChildren();
  for (const name of names) {
    const value = zones[name];
    const el = document.createElement("div");
    el.className = "zone";
    const title = document.createElement("strong");
    title.textContent = name;
    const label = document.createElement("span");
    if (value.startsWith("occupied_by:")) {
      el.classList.add("occupied");
      label.textContent = value.slice("occupied_by:".length);
    } else {
      label.textContent = value === "free" ? "비어 있음" : value;
    }
    el.append(title, label);
    box.appendChild(el);
  }
}

// ---------- 지도 ----------

// P5(바이너리 PGM) → 오프스크린 canvas. 헤더의 '#' 주석 줄은 건너뛴다.
function pgmToCanvas(buffer) {
  const bytes = new Uint8Array(buffer);
  let pos = 0;
  const token = () => {
    for (;;) {
      while (pos < bytes.length && /\s/.test(String.fromCharCode(bytes[pos]))) pos++;
      if (bytes[pos] === 35) { // '#'
        while (pos < bytes.length && bytes[pos] !== 10) pos++;
        continue;
      }
      break;
    }
    let s = "";
    while (pos < bytes.length && !/\s/.test(String.fromCharCode(bytes[pos]))) {
      s += String.fromCharCode(bytes[pos++]);
    }
    return s;
  };
  if (token() !== "P5") throw new Error("P5 PGM 이 아님");
  const width = parseInt(token(), 10);
  const height = parseInt(token(), 10);
  const maxval = parseInt(token(), 10);
  pos++; // 헤더 뒤 공백 한 바이트
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(width, height);
  for (let i = 0; i < width * height; i++) {
    const v = Math.round((bytes[pos + i] / maxval) * 255);
    image.data[i * 4] = v;
    image.data[i * 4 + 1] = v;
    image.data[i * 4 + 2] = v;
    image.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

async function loadMap() {
  try {
    const infoRes = await fetch("/api/map/info");
    if (!infoRes.ok) throw new Error(`${infoRes.status}`);
    const info = await infoRes.json();
    const imgRes = await fetch("/api/map/image");
    if (!imgRes.ok) throw new Error(`${imgRes.status}`);
    view.map = { info, canvas: pgmToCanvas(await imgRes.arrayBuffer()) };
    $("map-meta").textContent =
      `${info.image_width}×${info.image_height} px · ${info.resolution} m/px`;
  } catch (err) {
    view.map = null;
    $("map").hidden = true;
    $("map-empty").hidden = false;
  }
  drawMap();
}

async function loadLayers() {
  try {
    const res = await fetch("/api/map/layers");
    view.layers = res.ok ? await res.json() : null;
  } catch (err) {
    view.layers = null;
  }
  $("map-legend").hidden = !view.layers;
  const hidden = view.layers ? view.layers.hidden_points || 0 : 0;
  $("points-hidden").textContent = hidden ? `· 미실측 ${hidden}개 숨김` : "";
  drawMap();
}

// 선택은 이 브라우저에만 기억한다. 저장소를 못 쓰는 환경(사생활 보호 창 등)이면 켜짐으로 시작한다.
function setupToggle(boxId, storageKey, viewKey, legendOffClass) {
  try {
    view[viewKey] = localStorage.getItem(storageKey) !== "0";
  } catch (err) {
    view[viewKey] = true;
  }
  const box = $(boxId);
  box.checked = view[viewKey];
  $("map-legend").classList.toggle(legendOffClass, !view[viewKey]);
  box.addEventListener("change", () => {
    view[viewKey] = box.checked;
    $("map-legend").classList.toggle(legendOffClass, !view[viewKey]);
    try {
      localStorage.setItem(storageKey, view[viewKey] ? "1" : "0");
    } catch (err) {
      // 기억하지 못해도 지금 화면에는 반영된다.
    }
    drawMap();
  });
}

function drawMap() {
  if (!view.map) return;
  const { info, canvas: source } = view.map;
  const canvas = $("map");
  const wrap = $("map-wrap");
  // 가로는 칸에 맞추되, 세로는 아래 범례·이벤트 패널까지 창 안에 들어오게 줄인다.
  const legend = $("map-legend");
  const events = $("events-panel");
  const gap = 16;
  // 13 = 지도 패널 아래 padding 12 + 테두리 1
  const below = (legend.hidden ? 0 : legend.offsetHeight + 8) + 13 + gap + events.offsetHeight + gap;
  const availHeight = Math.max(240, window.innerHeight - wrap.getBoundingClientRect().top - below);
  const scale = Math.min(wrap.clientWidth / info.image_width, availHeight / info.image_height);
  const cssWidth = info.image_width * scale;
  const cssHeight = info.image_height * scale;
  canvas.style.width = `${cssWidth}px`;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  canvas.style.height = `${cssHeight}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(source, 0, 0);
  if (view.layers && (view.showLayers || view.showPoints)) {
    drawLayers(ctx, info, view.layers, scale);
  }

  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  Object.keys(robots).forEach((robotId, index) => {
    const robot = robots[robotId];
    if (!robot.pose) return;
    const color = robot.online ? css(robotColorVar(index)) : css("--offline");
    drawRobot(ctx, info, robot.pose, robotId, color, scale);
  });
}

function toPixel(info, x, y) {
  const [ox, oy] = info.origin;
  return [(x - ox) / info.resolution, info.image_height - (y - oy) / info.resolution];
}

function drawLabel(ctx, text, px, py, scale) {
  ctx.save();
  ctx.font = `600 ${11 / scale}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.lineWidth = 3 / scale;
  ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
  ctx.fillStyle = "#1c2129";
  ctx.strokeText(text, px, py);
  ctx.fillText(text, px, py);
  ctx.restore();
}

// 작은 표시(출구·대기 슬롯·홈). 같은 좌표의 표시는 하나로 합치고 이름을 이어 붙인다
// (예: 구역 A·B 는 대기 위치가 같다).
function drawMarks(ctx, info, marks, scale) {
  const merged = new Map();
  for (const mark of marks) {
    const key = `${mark.kind}:${mark.pose[0].toFixed(3)},${mark.pose[1].toFixed(3)}`;
    if (merged.has(key)) merged.get(key).labels.push(mark.label);
    else merged.set(key, { ...mark, labels: [mark.label] });
  }
  const r = Math.max(MARK_RADIUS_M / info.resolution, 3 / scale);
  for (const mark of merged.values()) {
    const [px, py] = toPixel(info, mark.pose[0], mark.pose[1]);
    ctx.save();
    ctx.lineWidth = 1.5 / scale;
    ctx.strokeStyle = mark.color;
    ctx.fillStyle = mark.color;
    ctx.beginPath();
    if (mark.kind === "exit") {        // 출구: X
      ctx.moveTo(px - r, py - r); ctx.lineTo(px + r, py + r);
      ctx.moveTo(px + r, py - r); ctx.lineTo(px - r, py + r);
      ctx.stroke();
    } else if (mark.kind === "point") { // 일반 지점: 점 + 도착 방향 화살표
      ctx.arc(px, py, r * 0.8, 0, Math.PI * 2);
      ctx.fill();
      const heading = -mark.pose[2]; // 지도 y 는 위가 +, canvas y 는 아래가 +
      ctx.beginPath();
      ctx.moveTo(px, py);
      ctx.lineTo(px + Math.cos(heading) * r * 2.6, py + Math.sin(heading) * r * 2.6);
      ctx.stroke();
    } else if (mark.kind === "home") { // 홈: 마름모
      ctx.moveTo(px, py - r); ctx.lineTo(px + r, py);
      ctx.lineTo(px, py + r); ctx.lineTo(px - r, py);
      ctx.closePath();
      ctx.fill();
    } else {                           // 대기 슬롯: 빈 원
      ctx.arc(px, py, r, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
    drawLabel(ctx, mark.labels.join("·"), px, py - r - 1 / scale, scale);
  }
}

// 구역 지점 원 색은 토큰 상태(fleet_status 의 zones)를 따른다. 원 크기는 표시용이다.
// 구역 표시(구역·출구·대기 슬롯·홈)와 웨이포인트(P)는 체크박스로 따로 끄고 켠다.
function drawLayers(ctx, info, layers, scale) {
  const marks = [];
  if (view.showPoints) {
    for (const [name, pose] of Object.entries(layers.points || {})) {
      marks.push({ kind: "point", pose, label: name, color: css("--active") });
    }
  }
  if (view.showLayers) {
    const zoneStates = view.snapshot ? view.snapshot.zones || {} : {};
    for (const [zone, layer] of Object.entries(layers.zones || {})) {
      const state = zoneStates[zone] || "";
      const color = state.startsWith("occupied_by:") ? css("--warn")
        : state === "free" ? css("--good") : css("--idle");
      for (const pose of Object.values(layer.points || {})) {
        const [px, py] = toPixel(info, pose[0], pose[1]);
        ctx.save();
        ctx.globalAlpha = 0.25;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(px, py, ZONE_RADIUS_M / info.resolution, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 2 / scale;
        ctx.strokeStyle = color;
        ctx.stroke();
        ctx.restore();
        drawLabel(ctx, zone, px, py + 5 / scale, scale);
      }
      if (layer.exit) {
        marks.push({ kind: "exit", pose: layer.exit.pose, label: `${zone} 출구`, color: css("--bad") });
      }
      (layer.queue || []).forEach((pose, k) => {
        marks.push({ kind: "queue", pose, label: `${zone}${k}`, color: css("--muted") });
      });
    }
    for (const home of Object.values(layers.homes || {})) {
      marks.push({ kind: "home", pose: home.pose, label: home.name, color: css("--idle") });
    }
  }
  drawMarks(ctx, info, marks, scale);
}

function drawRobot(ctx, info, pose, label, color, scale) {
  const [ox, oy] = info.origin;
  const px = (pose.x - ox) / info.resolution;
  const py = info.image_height - (pose.y - oy) / info.resolution;
  const r = Math.max(ROBOT_RADIUS_M / info.resolution, 5 / scale);
  const heading = -pose.yaw; // 지도 y 는 위가 +, canvas y 는 아래가 +

  ctx.save();
  ctx.translate(px, py);
  ctx.fillStyle = color;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5 / scale;
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  ctx.rotate(heading);
  ctx.beginPath();
  ctx.moveTo(r * 1.9, 0);
  ctx.lineTo(r * 0.6, -r * 0.7);
  ctx.lineTo(r * 0.6, r * 0.7);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // 이름은 원 아래에 둔다. 화살표가 어느 쪽을 보든 원 반지름의 2배 밖이라 겹치지 않는다.
  ctx.save();
  ctx.font = `600 ${12 / scale}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.lineWidth = 3 / scale;
  ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
  ctx.fillStyle = "#ffffff";
  const labelY = py + r * 2 + 2 / scale;
  ctx.strokeText(label, px, labelY);
  ctx.fillText(label, px, labelY);
  ctx.restore();
}

// ---------- 전체 ----------

function render() {
  const snap = view.snapshot;
  if (!snap) return;
  setLink("link-source", snap.source_online);
  renderMode(snap.infra);
  renderInfra(snap.infra, snap.source_online);
  $("updated").textContent = `갱신 ${new Date(view.receivedAt).toLocaleTimeString()}`;
  Object.entries(snap.robots || {}).forEach(([robotId, robot], index) => {
    renderCard(robotId, robot, index);
  });
  renderZones(snap.zones);
  renderAlerts(snap.alerts, snap.source_online);
  renderEventFilter();
  drawMap();
}

// 관제 노드가 멈추면 새 스냅샷이 오지 않아 마지막 값이 남는다. 그래서 상태는 따로 물어본다.
async function pollHealth() {
  try {
    const res = await fetch("/api/health");
    const health = res.ok ? await res.json() : {};
    view.healthDomain = health.domain_id ?? null;
    setLink("link-source", Boolean(health.source_online));
    if (view.taskManagerOnline !== Boolean(health.task_manager_online)) {
      view.taskManagerOnline = Boolean(health.task_manager_online);
      render();
    }
    setLink("link-tasks", view.taskManagerOnline);
    const infra = view.snapshot ? view.snapshot.infra : null;
    if (!infra) renderMode(null);
    renderInfra(infra, Boolean(health.source_online));
    if (!health.source_online) renderAlerts(null, false);
  } catch (err) {
    setLink("link-source", false);
    renderAlerts(null, false);
    setLink("link-tasks", false);
    renderInfra(view.snapshot ? view.snapshot.infra : null, false);
  }
}

window.addEventListener("resize", drawMap);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawMap);
$("event-robot").addEventListener("change", renderEvents);
setupToggle("show-layers", SHOW_LAYERS_KEY, "showLayers", "off");
setupToggle("show-points", SHOW_POINTS_KEY, "showPoints", "points-off");
loadMap();
loadLayers();
connect();
connectTasks();
pollHealth();
setInterval(pollHealth, HEALTH_POLL_MS);
