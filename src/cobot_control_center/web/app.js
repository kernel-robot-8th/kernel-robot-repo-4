// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 관제 화면: /ws/fleet 스냅샷으로 카드·구역·지도를 그린다. 읽기 전용이다.
// 로봇이 보낸 문자열(detail 등)은 textContent 로만 넣는다 (HTML 로 해석하지 않는다).

"use strict";

const RECONNECT_MS = 2000;
const HEALTH_POLL_MS = 2000;
const ROBOT_RADIUS_M = 0.06;   // 지도 위 로봇 원 반지름 [m]
const BATTERY_LOW = 30;        // [%] 이하 주황
const BATTERY_CRITICAL = 15;   // [%] 이하 빨강
const ZONE_RADIUS_M = 0.12;    // 지도 위 구역 지점 원 반지름 [m] (표시용, 실제 구역 넓이 아님)
const MARK_RADIUS_M = 0.035;   // 출구·대기 슬롯·홈 표시 크기 [m]

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
  cards: new Map(), // robot_id → card element
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
  ws.onopen = () => setLink("link-ws", true);
  ws.onmessage = (event) => {
    view.snapshot = JSON.parse(event.data);
    view.receivedAt = Date.now();
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
  $("cards").appendChild(card);
  view.cards.set(robotId, card);
  return card;
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
  drawMap();
}

function drawMap() {
  if (!view.map) return;
  const { info, canvas: source } = view.map;
  const canvas = $("map");
  const wrap = $("map-wrap");
  // 가로는 칸에 맞추되, 세로가 창을 넘지 않게 줄인다 (스크롤 없이 지도 전체가 보이게).
  const availHeight = Math.max(240, window.innerHeight - wrap.getBoundingClientRect().top - 32);
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
  if (view.layers) drawLayers(ctx, info, view.layers, scale);

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
function drawLayers(ctx, info, layers, scale) {
  const zoneStates = view.snapshot ? view.snapshot.zones || {} : {};
  const marks = [];
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
  drawMap();
}

// 관제 노드가 멈추면 새 스냅샷이 오지 않아 마지막 값이 남는다. 그래서 상태는 따로 물어본다.
async function pollHealth() {
  try {
    const res = await fetch("/api/health");
    const health = res.ok ? await res.json() : {};
    view.healthDomain = health.domain_id ?? null;
    setLink("link-source", Boolean(health.source_online));
    const infra = view.snapshot ? view.snapshot.infra : null;
    if (!infra) renderMode(null);
    renderInfra(infra, Boolean(health.source_online));
  } catch (err) {
    setLink("link-source", false);
    renderInfra(view.snapshot ? view.snapshot.infra : null, false);
  }
}

window.addEventListener("resize", drawMap);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawMap);
loadMap();
loadLayers();
connect();
setInterval(pollHealth, HEALTH_POLL_MS);
