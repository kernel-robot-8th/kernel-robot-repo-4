// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 지도: 크기 정하기·그리기·구역/웨이포인트/로봇 표시.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const ROBOT_RADIUS_M = 0.06;   // 지도 위 로봇 원 반지름 [m]
const ZONE_RADIUS_M = 0.12;    // 지도 위 구역 지점 원 반지름 [m] (표시용, 실제 구역 넓이 아님)
const MARK_RADIUS_M = 0.035;   // 출구·대기 슬롯·홈 표시 크기 [m]
const SHOW_LAYERS_KEY = "cobot_control_center.show_layers";
const SHOW_POINTS_KEY = "cobot_control_center.show_points";
const SIDE_MIN_PX = 340;       // 오른쪽 칸(로봇·작업·구역) 최소 폭 [화면 px]

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
  layoutMap();
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

const px = (value) => parseFloat(value) || 0;

// 지도 화면 크기를 정하고, 왼쪽 칸 폭을 지도 폭에 맞춘다 (남는 폭은 오른쪽 칸으로).
// 창 크기·범례·지점 고르기 막대가 바뀔 때만 부른다. 매초 오는 상태마다 다시 재면
// 위쪽 글자 폭(갱신 시각)이나 경고 띠 때문에 지도가 들썩인다.
function layoutMap() {
  if (!view.map) return;
  const { info } = view.map;
  const layout = document.querySelector(".layout");
  const mainCol = document.querySelector(".main-col");
  const panel = getComputedStyle(document.querySelector(".map-panel"));
  const box = getComputedStyle(layout);
  const panelEdge = px(panel.paddingLeft) + px(panel.paddingRight)
    + px(panel.borderLeftWidth) + px(panel.borderRightWidth);
  const stacked = box.gridTemplateColumns.trim().split(/\s+/).length < 2; // 좁은 화면: 한 줄로 쌓음
  const inner = layout.clientWidth - px(box.paddingLeft) - px(box.paddingRight) - panelEdge;
  // 가로로 놓일 때는 오른쪽 칸 최소 폭을 남긴다.
  const maxWidth = stacked ? inner : inner - px(box.columnGap) - SIDE_MIN_PX;

  const wrap = $("map-wrap");
  const legend = $("map-legend");
  const events = $("events-panel");
  const alerts = $("alerts");
  // 칸 폭이 바뀌면 범례 줄 수가 바뀌어 높이도 달라지므로 두 번 맞춘다.
  for (let pass = 0; pass < 2; pass++) {
    // 세로는 아래 범례·이벤트 패널까지 창 안에 들어오게 줄인다.
    const below = (legend.hidden ? 0 : legend.offsetHeight + px(getComputedStyle(legend).marginTop))
      + px(panel.paddingBottom) + px(panel.borderBottomWidth)
      + px(box.rowGap) + events.offsetHeight + px(box.paddingBottom);
    // 지도 칸 윗변은 페이지 맨 위에서 잰다 (스크롤해도 같은 값). 경고 띠는 수시로 생겼다
    // 사라지므로 없는 것으로 친다.
    const top = wrap.getBoundingClientRect().top + window.scrollY
      - (alerts.hidden ? 0 : alerts.offsetHeight);
    const availHeight = Math.max(240, window.innerHeight - top - below);
    view.mapScale = Math.min(Math.max(maxWidth, 120) / info.image_width,
      availHeight / info.image_height);
    mainCol.style.width = stacked ? "" : `${Math.round(info.image_width * view.mapScale + panelEdge)}px`;
  }
}

function drawMap() {
  if (!view.map) return;
  if (!view.mapScale) layoutMap();
  const { info, canvas: source } = view.map;
  const canvas = $("map");
  const scale = view.mapScale;
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
  // 지점을 고르는 동안은 꺼 둔 표시도 켠다 (고를 지점이 보여야 한다).
  const picking = Boolean(view.pick && view.pick.choices);
  const show = {
    points: view.showPoints || (picking && view.pick.cmd === "goto"),
    layers: view.showLayers || picking,
  };
  // 구역·지점 이름표는 모양 위, 로봇 아래에 고정 자리로 놓는다. 로봇 이름표는 맨 위 (placeStaticLabels).
  const labels = [];
  if (view.layers && (show.layers || show.points)) {
    drawLayers(ctx, info, view.layers, scale, show, labels);
  }

  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  if (picking) drawPick(ctx, info, scale, robots);
  const staticRects = placeStaticLabels(ctx, labels, scale, view.labelCache);
  const robotLabels = [];
  view.robotHits = [];
  Object.keys(robots).forEach((robotId, index) => {
    const robot = robots[robotId];
    if (!robot.pose) return;
    const color = robot.online ? css(robotColorVar(index)) : css("--offline");
    drawRobot(ctx, info, robot.pose, robotId, color, scale, robotLabels);
  });
  placeRobotLabels(ctx, robotLabels, scale, staticRects, view.labelCache);
}

function toPixel(info, x, y) {
  const [ox, oy] = info.origin;
  return [(x - ox) / info.resolution, info.image_height - (y - oy) / info.resolution];
}

// toPixel 의 반대: 지도 px → 지도(map) 좌표 [m]
function toWorld(info, px, py) {
  const [ox, oy] = info.origin;
  return [ox + px * info.resolution, oy + (info.image_height - py) * info.resolution];
}

// 지도 px (x, y) 에서 maxDist [지도 px] 안에 있는 가장 가까운 지점 이름. 없으면 null.
// choices: 이름 → [x, y, yaw] (지도 좌표 [m]). 전체 지도(pickAt)와 상세 지도(detailPickAt)가 함께 쓴다.
function nearestChoice(choices, x, y, maxDist) {
  let best = null;
  let bestDist = maxDist;
  for (const [name, pose] of choices) {
    const [px, py] = toPixel(view.map.info, pose[0], pose[1]);
    const dist = Math.hypot(px - x, py - y);
    if (dist <= bestDist) {
      best = name;
      bestDist = dist;
    }
  }
  return best;
}

// 지도 그림 안의 좌표인지 (지도 밖으로 AMCL 을 잡지 않게)
function insideMap(info, x, y) {
  const [px, py] = toPixel(info, x, y);
  return px >= 0 && py >= 0 && px <= info.image_width && py <= info.image_height;
}

// ---------- 이름표 ----------
// label: {text, x, y, r, kind, color, robotId}. x, y 는 점 위치, r 은 점 반지름 (모두 지도 px).
// kind: "zone"(구역 원 가운데 고정), "mark"(지점·출구·슬롯·홈), "robot"(로봇 색 알약).
// 고정 이름표(구역·지점)는 로봇을 보지 않고 자기들끼리만 겹치지 않게 놓고, 그 자리를 캐시에 둔다.
// 그래서 로봇이 움직여도 지점 글자는 제자리다 (로봇이 지나가면 로봇이 잠깐 글자를 가린다).
// 로봇 이름표는 맨 나중에 고정 이름표·로봇 몸통을 피해 놓고, 지난번 자리가 괜찮으면 그대로 둔다.
// 캐시: {key, rects, sides} — 전체 지도(view.labelCache)와 상세 지도(detail.labelCache)가 따로 가진다.

const newLabelCache = () => ({ key: null, rects: [], sides: new Map() });

function overlapArea(rect, others) {
  let area = 0;
  for (const o of others) {
    const w = Math.min(rect.x + rect.w, o.x + o.w) - Math.max(rect.x, o.x);
    const h = Math.min(rect.y + rect.h, o.y + o.h) - Math.max(rect.y, o.y);
    if (w > 0 && h > 0) area += w * h;
  }
  return area;
}

// 이름표 크기와 놓을 수 있는 자리 후보 (이름 → [x, y]). 글꼴도 맞춰 둔다.
function labelBox(ctx, label, scale) {
  const robot = label.kind === "robot";
  const size = (robot ? 12 : 11) / scale;
  ctx.font = `${robot ? 700 : 600} ${size}px system-ui, sans-serif`;
  const padX = (robot ? 5 : 1) / scale;
  const padY = (robot ? 2 : 0) / scale;
  const w = ctx.measureText(label.text).width + padX * 2;
  const h = size * 1.25 + padY * 2;
  const gap = label.r + 2 / scale;
  const spots = {
    below: [label.x - w / 2, label.y + gap],
    above: [label.x - w / 2, label.y - gap - h],
    right: [label.x + gap, label.y - h / 2],
    left: [label.x - gap - w, label.y - h / 2],
    center: [label.x - w / 2, label.y - h / 2],
  };
  return { size, padX, padY, w, h, spots };
}

// 후보 중 cost 가 가장 작은 자리 (0 이면 바로 고름). {side, rect}
function bestSpot(box, sides, cost) {
  let best = null;
  let bestCost = Infinity;
  for (const side of sides) {
    const [x, y] = box.spots[side];
    const rect = { x, y, w: box.w, h: box.h };
    const c = cost(rect);
    if (c < bestCost) {
      best = { side, rect };
      bestCost = c;
      if (c === 0) break;
    }
  }
  return best;
}

// 고정 이름표(구역·지점)를 놓고 그린다. 목록·배율이 같으면 캐시한 자리를 그대로 쓴다.
function placeStaticLabels(ctx, labels, scale, cache) {
  const key = `${scale}|` + labels.map((l) => `${l.kind}:${l.text}:${l.x}:${l.y}:${l.r}`).join("|");
  const order = [...labels].sort((a, b) => (a.kind === "zone" ? 0 : 1) - (b.kind === "zone" ? 0 : 1));
  const fresh = cache.key !== key;
  if (fresh) cache.rects = [];
  order.forEach((label, i) => {
    const box = labelBox(ctx, label, scale);
    if (fresh) {
      const sides = label.kind === "zone" ? ["center"] : ["above", "right", "left", "below"];
      cache.rects.push(bestSpot(box, sides, (rect) => overlapArea(rect, cache.rects)).rect);
    }
    drawLabelBox(ctx, label, cache.rects[i], box.size, box.padX, box.padY, false, scale);
  });
  cache.key = key;
  return cache.rects;
}

// 로봇 이름표를 고정 이름표·로봇 몸통·앞서 놓은 로봇 이름표를 피해 놓는다.
// 지난번 자리(cache.sides)가 지금도 안 겹치면 그대로 둬 아래·위로 오가지 않게 한다.
const ROBOT_SIDES = ["below", "above", "right", "left"];

function placeRobotLabels(ctx, labels, scale, staticRects, cache) {
  const bodies = labels.map((l) => ({ x: l.x - l.r, y: l.y - l.r, w: l.r * 2, h: l.r * 2 }));
  const placed = [];
  for (const label of labels) {
    const box = labelBox(ctx, label, scale);
    // 자기 몸통은 이름표 후보가 이미 비켜 있으므로 다른 로봇 몸통만 본다.
    const others = bodies.filter((_, i) => labels[i] !== label);
    const cost = (rect) => overlapArea(rect, staticRects) + overlapArea(rect, placed) * 4
      + overlapArea(rect, others) * 4;
    const last = cache.sides.get(label.robotId);
    const keep = last ? bestSpot(box, [last], cost) : null;
    const spot = keep && cost(keep.rect) === 0 ? keep : bestSpot(box, ROBOT_SIDES, cost);
    cache.sides.set(label.robotId, spot.side);
    placed.push(spot.rect);
    drawLabelBox(ctx, label, spot.rect, box.size, box.padX, box.padY, true, scale);
  }
}

function drawLabelBox(ctx, label, rect, size, padX, padY, robot, scale) {
  ctx.save();
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  if (robot) {
    // 로봇: 로봇 색 알약에 흰 글자 (지점 이름과 한눈에 구분되게)
    ctx.fillStyle = label.color;
    ctx.beginPath();
    ctx.roundRect(rect.x, rect.y, rect.w, rect.h, rect.h / 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
  } else {
    ctx.lineWidth = 3 / scale;   // 상세 지도는 배율이 달라 그 지도 배율을 쓴다
    ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
    ctx.fillStyle = "#1c2129";
    ctx.strokeText(label.text, rect.x + padX, rect.y + padY + size * 0.1);
  }
  ctx.fillText(label.text, rect.x + padX, rect.y + padY + size * 0.1);
  ctx.restore();
}

// 지도에서 누른 곳의 로봇 (몸통 반지름 + 여유 안). 없으면 null.
function robotAt(event) {
  if (!view.robotHits || !view.mapScale) return null;
  const rect = $("map").getBoundingClientRect();
  const x = (event.clientX - rect.left) / view.mapScale;
  const y = (event.clientY - rect.top) / view.mapScale;
  const hit = view.robotHits.find((h) => Math.hypot(h.x - x, h.y - y) <= h.r + 4 / view.mapScale);
  return hit ? hit.robotId : null;
}

// 작은 표시(출구·대기 슬롯·홈). 같은 좌표의 표시는 하나로 합치고 이름을 이어 붙인다
// (예: 구역 A·B 는 대기 위치가 같다).
function drawMarks(ctx, info, marks, scale, labels) {
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
    labels.push({ text: mark.labels.join("·"), x: px, y: py, r, kind: "mark" });
  }
}

// 구역 지점 원 색은 토큰 상태(fleet_status 의 zones)를 따른다. 원 크기는 표시용이다.
// 구역 표시(구역·출구·대기 슬롯·홈)와 웨이포인트(P)는 체크박스로 따로 끄고 켠다.
function drawLayers(ctx, info, layers, scale, show, labels) {
  const marks = [];
  if (show.points) {
    for (const [name, pose] of Object.entries(layers.points || {})) {
      marks.push({ kind: "point", pose, label: name, color: css("--active") });
    }
  }
  if (show.layers) {
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
        labels.push({ text: zone, x: px, y: py, r: 0, kind: "zone" });
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
  drawMarks(ctx, info, marks, scale, labels);
}

// 지점 고르는 중: 고를 수 있는 지점은 고리로, 고른 경로는 로봇 위치부터 점선과 순번으로 그린다.
function drawPick(ctx, info, scale, robots) {
  const pick = view.pick;
  const index = Object.keys(robots).indexOf(pick.robotId);
  const color = css(robotColorVar(Math.max(0, index)));
  ctx.save();
  ctx.lineWidth = 2 / scale;
  ctx.strokeStyle = color;
  for (const pose of pick.choices.values()) {
    const [px, py] = toPixel(info, pose[0], pose[1]);
    ctx.beginPath();
    ctx.arc(px, py, 9 / scale, 0, Math.PI * 2);
    ctx.stroke();
  }

  const path = pick.names().map((name) => pick.choices.get(name)).filter(Boolean)
    .map((pose) => toPixel(info, pose[0], pose[1]));
  const robot = robots[pick.robotId];
  const start = robot && robot.pose ? toPixel(info, robot.pose.x, robot.pose.y) : null;
  const line = start ? [start, ...path] : path;
  if (line.length > 1) {
    ctx.setLineDash([6 / scale, 4 / scale]);
    ctx.beginPath();
    line.forEach(([px, py], i) => (i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)));
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.font = `700 ${10 / scale}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  path.forEach(([px, py], i) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(px, py, 8 / scale, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.fillText(String(i + 1), px, py);
  });
  ctx.restore();
}

function drawRobot(ctx, info, pose, robotId, color, scale, labels) {
  const [px, py] = toPixel(info, pose.x, pose.y);
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

  // 이름표 자리는 화살표 끝(반지름 1.9배) 밖에서 찾는다. 지도 클릭으로 로봇을 고를 수 있게 위치도 남긴다.
  labels.push({ text: robotId, x: px, y: py, r: r * 1.9, kind: "robot", color, robotId });
  view.robotHits.push({ robotId, x: px, y: py, r });
}
