// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 로봇 상세 화면 (주소 #/robot/<id>).
// 전체 화면(.layout)을 숨기고 한 로봇 전용 배치(#detail-page)를 보인다:
//   상태줄(명령 포함) → 카메라 | 확대 지도 → 요약 칸 → 타임라인 | 진단.
// 연결·작업 목록·명령 함수는 전체 화면과 같은 것을 쓴다 (renderCommands, onCommand, drawLayers ...).
// 로봇 직접 조종(cmd_vel)은 두지 않는다. 명령은 작업 관리(task_manager)를 거치는 버튼만 쓴다.
// 로봇이 보낸 문자열은 textContent 로만 넣는다.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

// 마지막 영상 프레임이 이보다 오래되면 '영상 없음'으로 본다 [s]. /api/health 를 2초마다 보므로 그보다 길게.
const CAMERA_STALE_SEC = 3;
// 진단 색 기준 [s]: 연결 판정(fleet_status stale_timeout_sec 8초) 안이면 초록, 30초 안이면 주황.
// 실물 배터리는 5초 주기, 서 있는 로봇은 amcl_pose 를 거의 안 내므로 초록 기준을 짧게 잡지 않는다.
const DIAG_OK_SEC = 8;
const DIAG_WARN_SEC = 30;
// 확대 지도에 보이는 가로 폭 [m]. null 은 지도 전체.
const ZOOM_SPANS_M = [0.8, 1.4, null];
const ZOOM_DEFAULT = 1;
const TIMELINE_MAX = 50;
const ROUTE_PREFIX = "#/robot/";

const detail = {
  cameraFor: null, // 지금 <img> 가 받고 있는 영상 스트림의 로봇 (없으면 null)
  zoom: ZOOM_DEFAULT,
  xf: null,        // 확대 지도 변환 {scale, ox, oy}: 화면 px = 지도 px * scale + o
  hits: [],        // 확대 지도 위 로봇 위치 (클릭으로 그 로봇 상세로)
};

function detailHref(robotId) {
  return ROUTE_PREFIX + encodeURIComponent(robotId);
}

function openDetail(robotId) {
  location.hash = detailHref(robotId);
}

function routeRobot() {
  if (!location.hash.startsWith(ROUTE_PREFIX)) return null;
  const id = decodeURIComponent(location.hash.slice(ROUTE_PREFIX.length));
  return id || null;
}

// 주소가 바뀌면 상세 화면을 켜고 끈다.
function applyRoute() {
  const robotId = routeRobot();
  if (robotId === view.detailRobot) return;
  // 고르던 지점·해제 확인은 그 자리(카드 또는 상태줄 아래)와 함께 접는다.
  cancelPick();
  closeResolve();
  view.detailRobot = robotId;
  const on = robotId !== null;
  document.body.classList.toggle("detail-mode", on);
  $("detail-page").hidden = !on;
  document.title = on ? `${robotId} · 로봇 관제` : "로봇 관제";
  stopCamera();
  detail.zoom = ZOOM_DEFAULT;
  window.scrollTo(0, 0);
  if (on) {
    renderDetail();
    updateCamera();
  } else {
    // 숨어 있던 동안 잰 크기가 틀렸을 수 있어 전체 지도를 다시 잰다.
    layoutMap();
    drawMap();
  }
}

// render()·renderTasks()·showMessage 가 부른다. 상세 화면이 아니면 아무것도 하지 않는다.
function renderDetail() {
  const robotId = view.detailRobot;
  if (robotId === null) return;
  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  const robot = robots[robotId];
  // 스냅샷을 받았는데 그 로봇이 없을 때만 '등록되지 않은 로봇' (받기 전에는 모름).
  const missing = Boolean(view.snapshot) && !robot;
  $("detail-page").dataset.missing = missing ? "1" : "";
  $("dt-missing").hidden = !missing;
  renderHead(robotId, robot, Object.keys(robots).indexOf(robotId));
  if (!robot) return;
  renderStats(robotId, robot);
  renderTimeline(robotId);
  renderDiag(robotId, robot);
  drawDetailMap();
}

// ---------- 상태줄 ----------

function renderHead(robotId, robot, index) {
  const head = document.querySelector(".detail-head");
  head.style.setProperty("--robot-color", index >= 0 ? `var(${robotColorVar(index)})` : "var(--idle)");
  $("dt-name").textContent = robotId;
  const badge = $("dt-badge");
  const state = $("dt-state");
  const battery = $("dt-battery");
  if (!robot) {
    badge.dataset.state = "never";
    badge.textContent = "미수신";
    state.textContent = "상태 없음";
    battery.textContent = "";
    return;
  }
  const status = robot.never_seen ? "never" : robot.online ? "online" : "offline";
  badge.dataset.state = status;
  badge.textContent = { online: "연결", offline: "끊김", never: "미수신" }[status];
  state.textContent = STATE_TEXT[robot.state] || robot.state || "상태 없음";
  state.title = robot.state || "";
  state.style.setProperty("--state-color", `var(--${STATE_GROUP[robot.state] || "idle"})`);
  const pct = robot.battery_percent;
  if (pct === null || pct === undefined) {
    battery.textContent = "배터리 —";
    battery.dataset.level = "";
  } else {
    battery.textContent = `배터리 ${Math.round(pct)}%`;
    battery.dataset.level = pct <= BATTERY_CRITICAL ? "critical" : pct <= BATTERY_LOW ? "low" : "";
  }
  renderCommands($("detail-cmds"), robotId, robot);
}

function setupHead() {
  const box = $("detail-cmds");
  box.querySelectorAll("button[data-cmd]").forEach((button) => {
    button.addEventListener("click", () => {
      if (view.detailRobot) onCommand(view.detailRobot, button.dataset.cmd);
    });
  });
  // 빨간 '결과 모름' 줄을 누르면 해제 확인을 연다 (카드와 같다).
  box.querySelector(".cmd-head").addEventListener("click", () => {
    const unknown = view.detailRobot && robotTask(view.detailRobot, new Set(["UNKNOWN"]));
    if (unknown) openResolve(unknown);
  });
}

// ---------- 요약 칸 ----------

function stat(label, value, sub) {
  const el = document.createElement("div");
  el.className = "stat";
  const head = document.createElement("div");
  head.className = "stat-label";
  head.textContent = label;
  const body = document.createElement("div");
  body.className = "stat-value";
  body.textContent = value;
  body.title = value;
  const foot = document.createElement("div");
  foot.className = "stat-sub";
  foot.textContent = sub || "";
  foot.title = foot.textContent;
  el.append(head, body, foot);
  return el;
}

// 이 로봇이 점유한 구역과 대기 순번. 구역 상태를 못 받았으면 null.
function zoneText(robotId) {
  const held = heldZones(robotId);
  const queues = (view.snapshot && view.snapshot.queues) || {};
  const waiting = Object.keys(queues).filter((name) => (queues[name] || []).includes(robotId))
    .map((name) => `${name} 대기 ${queues[name].indexOf(robotId) + 1}번째`);
  if (held === null && waiting.length === 0) return null;
  return [...(held || []).map((name) => `${name} 점유`), ...waiting].join(" · ") || "없음";
}

function renderStats(robotId, robot) {
  const task = robotTask(robotId, new Set(["UNKNOWN"])) || robotTask(robotId, ACTIVE_TASK);
  const taskStat = task
    ? stat("현재 작업", taskCommandText(task),
      [TASK_TEXT[task.state] || task.state, task.detail].filter(Boolean).join(" · "))
    : stat("현재 작업", "없음", robot.detail ? `순찰 노드: ${robot.detail}` : "");

  let poseStat;
  if (robot.pose) {
    const deg = (robot.pose.yaw * 180 / Math.PI).toFixed(0);
    const wp = robot.waypoint !== null && robot.waypoint !== undefined && robot.waypoint >= 0
      ? ` · 웨이포인트 #${robot.waypoint}` : "";
    poseStat = stat("위치", `(${robot.pose.x.toFixed(2)}, ${robot.pose.y.toFixed(2)}) m`, `${deg}°${wp}`);
  } else {
    poseStat = stat("위치", "—", "위치를 받은 적 없음");
  }

  const zones = zoneText(robotId);
  const zoneStat = stat("구역", zones === null ? "모름" : zones,
    zones === null ? "구역 상태 없음 (zone_manager)" : "");

  // 작업 목록은 최근 것만 받으므로 '오늘 전체'가 아니라 받은 목록 안의 수다.
  const mine = [...view.tasks.values()].filter((t) => t.robot_id === robotId);
  const count = (states) => mine.filter((t) => states.includes(t.state)).length;
  const recentStat = mine.length
    ? stat("최근 작업", `성공 ${count(["SUCCEEDED"])} · 실패 ${count(["FAILED", "UNKNOWN"])}`,
      `중단 ${count(["STOPPED"])} · 거절 ${count(["REJECTED"])} (최근 ${mine.length}개)`)
    : stat("최근 작업", "없음", "");
  $("dt-stats").replaceChildren(taskStat, poseStat, zoneStat, recentStat);
}

// ---------- 타임라인 (작업 + 이벤트) ----------

function renderTimeline(robotId) {
  const items = view.events.filter((e) => e.robot === robotId).map((e) => ({
    time: e.time, kind: "상태", level: e.level, text: e.text,
  }));
  for (const task of view.tasks.values()) {
    if (task.robot_id !== robotId) continue;
    items.push({
      time: task.updated_at || task.created_at,
      kind: "작업",
      level: TASK_GROUP[task.state] || "",
      text: [taskCommandText(task), TASK_TEXT[task.state] || task.state, task.detail]
        .filter(Boolean).join(" · "),
      title: task.task_id,
    });
  }
  items.sort((a, b) => (b.time || 0) - (a.time || 0));
  const box = $("dt-timeline");
  if (items.length === 0) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "기록 없음";
    box.replaceChildren(empty);
    return;
  }
  box.replaceChildren(...items.slice(0, TIMELINE_MAX).map((item) => {
    const li = document.createElement("li");
    li.dataset.level = item.level || "";
    if (item.title) li.title = item.title;
    const time = document.createElement("time");
    time.textContent = item.time ? formatTime(item.time) : "";
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = item.kind;
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = item.text;
    li.append(time, kind, text);
    return li;
  }));
}

// ---------- 진단 ----------

function ageLevel(age) {
  if (age === null || age === undefined) return "none";
  return age <= DIAG_OK_SEC ? "good" : age <= DIAG_WARN_SEC ? "warn" : "bad";
}

function addDiag(box, label, value, level) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  dd.dataset.level = level || "";
  box.append(dt, dd);
}

function renderDiag(robotId, robot) {
  const box = $("dt-diag");
  box.replaceChildren();
  addDiag(box, "연결", `마지막 수신 ${formatAge(robot.last_seen_age)}`, ageLevel(robot.last_seen_age));
  const ages = robot.topic_age || {};
  for (const [key, label] of [["pose", "위치"], ["battery", "배터리"], ["status", "순찰 상태"]]) {
    const age = ages[key];
    addDiag(box, label, age === null || age === undefined ? "받은 적 없음" : `${formatShortAge(age)} 전`,
      ageLevel(age));
  }
  const cam = (view.cameras || {})[robotId];
  const camAge = cam ? cam.age_sec : null;
  addDiag(box, "카메라", !cam ? "구독 안 함"
    : camAge === null || camAge === undefined ? "받은 적 없음"
    : `${formatShortAge(camAge)} 전 · ${cam.frames}장`,
  !cam || camAge === null || camAge === undefined ? "none"
    : camAge <= CAMERA_STALE_SEC ? "good" : "warn");
  const spec = view.spec && typeof view.spec === "object" ? view.spec[robotId] : view.spec;
  addDiag(box, "명령 규격", spec || "모름 (작업 노드 꺼짐)", spec ? "" : "none");
  const extra = robot.extra || {};
  $("dt-extra").textContent = Object.keys(extra).length ? JSON.stringify(extra, null, 2) : "없음";
}

// ---------- 카메라 ----------

function stopCamera() {
  const img = $("camera-img");
  // src 를 떼면 브라우저가 MJPEG 연결을 닫는다.
  img.removeAttribute("src");
  img.hidden = true;
  detail.cameraFor = null;
}

// /api/health 의 cameras 로 영상이 들어오는지 판단한다 (pollHealth 가 부른다).
// 들어오기 시작하면 스트림을 붙이고, 끊기면 떼어 '영상 없음'을 띄운다.
function updateCamera() {
  const robotId = view.detailRobot;
  if (robotId === null) return;
  const info = (view.cameras || {})[robotId];
  const age = info ? info.age_sec : null;
  const live = age !== null && age !== undefined && age <= CAMERA_STALE_SEC;
  const img = $("camera-img");
  if (live && detail.cameraFor !== robotId) {
    img.src = `/api/robots/${encodeURIComponent(robotId)}/camera?t=${Date.now()}`;
    img.hidden = false;
    detail.cameraFor = robotId;
  } else if (!live && detail.cameraFor !== null) {
    stopCamera();
  }
  const empty = $("camera-empty");
  empty.hidden = live;
  empty.textContent = !info ? "카메라를 구독하지 않는 로봇입니다 (camera_robots)"
    : age === null || age === undefined ? "영상 없음 (아직 받은 적 없음)"
    : `영상 없음 · 마지막 수신 ${formatAge(age)}`;
  const tag = $("camera-age");
  tag.hidden = !live;
  tag.textContent = live ? `${formatShortAge(age)} 전 · ${info.frames}장` : "";
  $("camera-meta").textContent = "";
  // 진단 칸의 카메라 줄도 같은 값으로 바뀐다.
  const robot = view.snapshot && (view.snapshot.robots || {})[robotId];
  if (robot) renderDiag(robotId, robot);
}

// ---------- 확대 지도 ----------

// 진행 중인 작업의 지점 이름 → [x, y, yaw]. 이동·구역 지점 목록을 합쳐 찾는다.
function routePoses(robotId, task) {
  const lookup = new Map([...(pointChoices(robotId, "goto") || []),
    ...(pointChoices(robotId, "zone") || [])]);
  return (task.points || []).map((name) => lookup.get(name)).filter(Boolean);
}

// 진행 중인 작업 경로: 로봇 위치에서 지점까지 점선과 순번.
function drawRoute(ctx, info, scale, robotId, robot, color) {
  const task = robotTask(robotId, ACTIVE_TASK);
  if (!task || !robot.pose) return;
  const path = routePoses(robotId, task).map((pose) => toPixel(info, pose[0], pose[1]));
  if (path.length === 0) return;
  const line = [toPixel(info, robot.pose.x, robot.pose.y), ...path];
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2 / scale;
  ctx.setLineDash([6 / scale, 4 / scale]);
  ctx.beginPath();
  line.forEach(([px, py], i) => (i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)));
  ctx.stroke();
  ctx.setLineDash([]);
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

function drawDetailMap() {
  const robotId = view.detailRobot;
  const canvas = $("dt-map");
  const wrap = $("dt-map-wrap");
  $("dt-map-empty").hidden = Boolean(view.map);
  canvas.hidden = !view.map;
  if (!view.map || robotId === null) return;
  const cssW = wrap.clientWidth;
  const cssH = wrap.clientHeight;
  if (!cssW || !cssH) return;
  const { info, canvas: source } = view.map;
  const W = info.image_width;
  const H = info.image_height;
  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  const robot = robots[robotId];

  // 정한 폭 [m] 이 칸 가로에 들어가게 확대하고, 로봇을 가운데에 둔다 (지도 끝에서는 멈춘다).
  const span = ZOOM_SPANS_M[detail.zoom];
  const fit = Math.min(cssW / W, cssH / H);
  const scale = span === null ? fit : Math.max(fit, cssW / (span / info.resolution));
  let [cx, cy] = robot && robot.pose && span !== null
    ? toPixel(info, robot.pose.x, robot.pose.y) : [W / 2, H / 2];
  const viewW = cssW / scale;
  const viewH = cssH / scale;
  cx = viewW >= W ? W / 2 : Math.min(Math.max(cx, viewW / 2), W - viewW / 2);
  cy = viewH >= H ? H / 2 : Math.min(Math.max(cy, viewH / 2), H - viewH / 2);
  const ox = cssW / 2 - cx * scale;
  const oy = cssH / 2 - cy * scale;
  detail.xf = { scale, ox, oy };

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = css("--bg");
  ctx.fillRect(0, 0, cssW, cssH);
  ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * ox, dpr * oy);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(source, 0, 0);

  const picking = Boolean(view.pick && view.pick.choices && view.pick.robotId === robotId);
  canvas.classList.toggle("picking", picking);
  const labels = [];
  const show = {
    points: view.showPoints || (picking && view.pick.cmd === "goto"),
    layers: view.showLayers || picking,
  };
  if (view.layers && (show.layers || show.points)) {
    drawLayers(ctx, info, view.layers, scale, show, labels);
  }
  const index = Object.keys(robots).indexOf(robotId);
  const color = css(robotColorVar(Math.max(0, index)));
  if (picking) drawPick(ctx, info, scale, robots);
  else if (robot) drawRoute(ctx, info, scale, robotId, robot, color);

  // drawRobot 은 전체 지도의 클릭 자리(view.robotHits)에 쓰므로 잠시 바꿔 끼운다.
  const overviewHits = view.robotHits;
  view.robotHits = [];
  // 보는 로봇을 맨 위에 그리고, 다른 로봇은 흐리게.
  const ids = Object.keys(robots).sort((a, b) => (a === robotId) - (b === robotId));
  for (const id of ids) {
    const other = robots[id];
    if (!other.pose) continue;
    const i = Object.keys(robots).indexOf(id);
    ctx.globalAlpha = id === robotId ? 1 : 0.35;
    drawRobot(ctx, info, other.pose, id, other.online ? css(robotColorVar(i)) : css("--offline"),
      scale, labels);
  }
  ctx.globalAlpha = 1;
  detail.hits = view.robotHits;
  view.robotHits = overviewHits;
  placeLabels(ctx, labels, scale);

  $("dt-zoom-in").disabled = detail.zoom === 0;
  $("dt-zoom-out").disabled = detail.zoom === ZOOM_SPANS_M.length - 1;
}

// 확대 지도에서 누른 곳 → 지도 px
function detailMapPoint(event) {
  if (!detail.xf) return null;
  const rect = $("dt-map").getBoundingClientRect();
  const { scale, ox, oy } = detail.xf;
  return [(event.clientX - rect.left - ox) / scale, (event.clientY - rect.top - oy) / scale];
}

// 지점 고르는 중이면 가장 가까운 지점 이름 (PICK_HIT_PX 안), 아니면 null.
function detailPickAt(event) {
  const pick = view.pick;
  const point = detailMapPoint(event);
  if (!pick || !pick.choices || pick.robotId !== view.detailRobot || !point || !view.map) return null;
  const { scale } = detail.xf;
  let best = null;
  let bestDist = PICK_HIT_PX / scale;
  for (const [name, pose] of pick.choices) {
    const [px, py] = toPixel(view.map.info, pose[0], pose[1]);
    const dist = Math.hypot(px - point[0], py - point[1]);
    if (dist <= bestDist) {
      best = name;
      bestDist = dist;
    }
  }
  return best;
}

function detailRobotAt(event) {
  const point = detailMapPoint(event);
  if (!point) return null;
  const hit = detail.hits.find((h) => Math.hypot(h.x - point[0], h.y - point[1]) <= h.r + 4 / detail.xf.scale);
  return hit ? hit.robotId : null;
}

function setupDetailMap() {
  const canvas = $("dt-map");
  canvas.addEventListener("click", (event) => {
    const name = detailPickAt(event);
    if (name) {
      view.pick.add(name);
      return;
    }
    const robotId = detailRobotAt(event);
    if (robotId && robotId !== view.detailRobot) openDetail(robotId);
  });
  canvas.addEventListener("mousemove", (event) => {
    const other = detailRobotAt(event);
    canvas.style.cursor = detailPickAt(event) || (other && other !== view.detailRobot) ? "pointer" : "";
  });
  $("dt-zoom-in").addEventListener("click", () => {
    detail.zoom = Math.max(0, detail.zoom - 1);
    drawDetailMap();
  });
  $("dt-zoom-out").addEventListener("click", () => {
    detail.zoom = Math.min(ZOOM_SPANS_M.length - 1, detail.zoom + 1);
    drawDetailMap();
  });
  window.addEventListener("resize", drawDetailMap);
}

function setupDetail() {
  setupHead();
  setupDetailMap();
  window.addEventListener("hashchange", applyRoute);
  // 스트림이 끊기면(백엔드 재시작 등) 다음 health 확인 때 다시 붙인다.
  $("camera-img").addEventListener("error", stopCamera);
  applyRoute();
}
