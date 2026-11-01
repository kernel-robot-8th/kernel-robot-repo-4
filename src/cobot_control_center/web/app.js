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

const view = {
  snapshot: null,
  receivedAt: 0,
  map: null,        // {info, canvas}
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

  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  Object.keys(robots).forEach((robotId, index) => {
    const robot = robots[robotId];
    if (!robot.pose) return;
    const color = robot.online ? css(robotColorVar(index)) : css("--offline");
    drawRobot(ctx, info, robot.pose, robotId, color, scale);
  });
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
    setLink("link-source", res.ok && (await res.json()).source_online);
  } catch (err) {
    setLink("link-source", false);
  }
}

window.addEventListener("resize", drawMap);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawMap);
loadMap();
connect();
setInterval(pollHealth, HEALTH_POLL_MS);
