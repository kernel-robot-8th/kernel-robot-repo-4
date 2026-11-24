// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 관제 웨이포인트·묶음 (주소 #/waypoints, 2026-11-18).
// 지점 원본은 관제(fleet_api 의 waypoint_utils, 관제 PC 파일)에 있다. 상세 화면 조종 칸의
// [웨이포인트 기록 시작](record.js)이 로봇의 지금 위치로 W1, W2 … 를 만들고, 이동·경로에서 P 처럼 고르면 관제가 좌표를 실어 보낸다
// (순찰 노드가 로봇 설정 파일 없이 그 좌표로 간다, goto 만). 구역은 구역 명령으로만 들어간다.
// 묶음은 지점 순서에 이름을 붙인 것이다. 경로 띠의 '묶음 불러오기'로 한 번에 채운다.
// 서버가 준 문자열(이름·메모)은 textContent 로만 넣는다.

"use strict";

const WP_ROUTE = "#/waypoints";
const WP_POLL_MS = 5000;
const SHOWN_GROUP_KEY = "cobot_control_center.shown_group";

const wp = {
  open: false,
  editing: null,   // 묶음 편집 중 {name, points[], note, original}
  checked: new Set(), // 내보내기로 고른 웨이포인트
};

// ---------- 받기 ----------

async function loadWaypoints() {
  let next;
  try {
    const res = await fetch("/api/waypoints");
    if (!res.ok) throw new Error(String(res.status));
    next = await res.json();
  } catch (err) {
    next = { waypoints: [], groups: [], failed: true };
  }
  // 바뀌었을 때만 다시 그린다 (5초마다 묻는다).
  if (JSON.stringify(next) === JSON.stringify(view.waypoints)) return;
  view.waypoints = next;
  if (wp.open) renderWaypointsPage();
  renderGroupSelect();
  renderMapGroupSelects();
  renderRecord();
  drawMap();
  drawDetailMap();
}

// 관제 웨이포인트 이름 → [x, y, yaw]
function waypointPoses() {
  const poses = new Map();
  for (const w of (view.waypoints && view.waypoints.waypoints) || []) poses.set(w.name, [w.x, w.y, w.yaw]);
  return poses;
}

async function wpRequest(method, url, body) {
  try {
    const res = await fetch(url, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: { detail: "백엔드에 닿지 않음" } };
  }
}

// ---------- 경로 띠: 묶음 불러오기 ----------

function renderGroupSelect() {
  const select = $("cmd-group");
  if (!select) return;
  const groups = (view.waypoints && view.waypoints.groups) || [];
  const current = select.value;
  select.replaceChildren(new Option(groups.length ? "묶음 불러오기…" : "묶음 없음", ""));
  for (const g of groups) select.append(new Option(`${g.name} (${g.points.length}곳)`, g.name));
  select.value = groups.some((g) => g.name === current) ? current : "";
  select.disabled = groups.length === 0;
}

// ---------- 지도: 묶음 보기 ----------

// 이름 → [x, y, yaw]: 로봇 설정 지점(일반·구역·출구·모든 로봇 홈) + 관제 웨이포인트
function allPointPoses() {
  const poses = new Map();
  const layers = view.layers || {};
  for (const [name, pose] of Object.entries(layers.points || {})) poses.set(name, pose);
  for (const zone of Object.values(layers.zones || {})) {
    for (const [name, pose] of Object.entries(zone.points || {})) poses.set(name, pose);
    if (zone.exit) poses.set(zone.exit.name, zone.exit.pose);
  }
  for (const home of Object.values(layers.homes || {})) poses.set(home.name, home.pose);
  for (const [name, pose] of waypointPoses()) poses.set(name, pose);
  return poses;
}

function shownGroup() {
  return ((view.waypoints && view.waypoints.groups) || []).find((g) => g.name === view.shownGroup) || null;
}

function renderMapGroupSelects() {
  const groups = (view.waypoints && view.waypoints.groups) || [];
  // 지운 묶음을 고르고 있었으면 끈다 (목록을 받은 뒤에만, 못 받았으면 그대로 둔다)
  if (view.shownGroup && view.waypoints && !view.waypoints.failed
      && !groups.some((g) => g.name === view.shownGroup)) {
    setShownGroup("");
    return;
  }
  for (const id of ["map-group", "dt-map-group"]) {
    const select = $(id);
    if (!select) continue;
    select.replaceChildren(new Option(groups.length ? "묶음 보기: 없음" : "묶음 없음", ""));
    for (const g of groups) select.append(new Option(`묶음 보기: ${g.name} (${g.points.length}곳)`, g.name));
    select.value = view.shownGroup;
    select.disabled = groups.length === 0;
    select.title = "저장한 웨이포인트 묶음을 지도에 순번·점선으로 보인다 (#/waypoints 에서 만들고 고침)";
  }
  renderGroupRun();
}

// [묶음 실행] (상세 지도): 이 로봇의 경로 버튼과 같은 조건에서만 켠다.
function renderGroupRun() {
  const button = $("dt-group-run");
  if (!button) return;
  const robotId = view.detailRobot;
  const route = document.querySelector('#detail-cmds [data-cmd="route"]');
  const group = shownGroup();
  const why = !group ? "먼저 '묶음 보기'에서 묶음을 고르세요"
    : !route || route.disabled ? `경로를 보낼 수 없음: ${(route && route.title) || "명령 잠김"}`
      : "";
  button.disabled = robotId === null || Boolean(why);
  button.title = why || `'${group.name}' 순서로 ${robotId} 경로 띠를 채워 엽니다 · [보내기]를 눌러야 출발`;
}

// 묶음을 이 로봇 경로로: 경로 띠를 열고 묶음 순서로 채운다. 확인([보내기])은 운영자가 한다
// (실물 경고·갈 수 없는 지점 안내를 경로 띠가 그대로 보인다).
async function runGroup() {
  const robotId = view.detailRobot;
  const group = shownGroup();
  if (robotId === null || !group) return;
  const opened = choosePoints(robotId, "route");
  loadGroupIntoPick(group.name);
  const points = await opened;
  if (points === null) return;
  await sendRoute(robotId, points);
}

function setShownGroup(name) {
  view.shownGroup = name || "";
  try {
    localStorage.setItem(SHOWN_GROUP_KEY, view.shownGroup);
  } catch (err) {
    // 저장소를 못 쓰면 이번 창에서만 기억한다.
  }
  renderMapGroupSelects();
  drawMap();
  drawDetailMap();
}

// 고른 묶음: 1 → 2 → 3 순번 원과 점선 (경로 고르기·기록과 헷갈리지 않게 따로 된 색 --group)
function drawGroup(ctx, info, scale) {
  const group = shownGroup();
  if (!group) return;
  const poses = allPointPoses();
  const path = group.points.map((name) => poses.get(name)).filter(Boolean)
    .map((pose) => toPixel(info, pose[0], pose[1]));
  if (!path.length) return;
  const color = css("--group");
  ctx.save();
  ctx.lineWidth = 2.5 / scale;
  ctx.strokeStyle = color;
  if (path.length > 1) {
    ctx.setLineDash([8 / scale, 5 / scale]);
    ctx.beginPath();
    path.forEach(([px, py], i) => (i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)));
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

// 경로 고르기 중 묶음을 고르면 그 순서로 채운다. 이 로봇이 갈 수 없는 지점(다른 로봇 홈 등)은 뺀다.
function loadGroupIntoPick(name) {
  const pick = view.pick;
  const group = ((view.waypoints && view.waypoints.groups) || []).find((g) => g.name === name);
  if (!pick || !group) return;
  const usable = group.points.filter((p) => pick.choices && pick.choices.has(p));
  const skipped = group.points.filter((p) => !usable.includes(p));
  pick.route.splice(0, pick.route.length, ...usable);
  pick.update();
  $("cmd-warn").textContent = skipped.length
    ? `${skipped.join("·")} 는 이 로봇이 갈 수 없는 지점이라 뺐어요` : $("cmd-warn").textContent;
  $("cmd-group").value = "";
}

// ---------- #/waypoints 화면 ----------

function applyWaypointRoute() {
  const on = location.hash === WP_ROUTE;
  if (on === wp.open) return;
  wp.open = on;
  document.body.classList.toggle("waypoints-mode", on);
  $("waypoints-page").hidden = !on;
  if (on) {
    document.title = "웨이포인트 · 로봇 관제";
    window.scrollTo(0, 0);
    // 받아 둔 목록을 바로 그린다 (loadWaypoints 는 목록이 바뀌었을 때만 다시 그린다).
    renderWaypointsPage();
    loadWaypoints();
  } else {
    wp.editing = null;
    if (!view.detailRobot) document.title = "로봇 관제";
    layoutMap();
    drawMap();
  }
}

function wpEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function wpButton(text, onClick, extra = {}) {
  const b = wpEl("button", extra.className || "", text);
  b.type = "button";
  if (extra.title) b.title = extra.title;
  b.disabled = Boolean(extra.disabled) || view.readOnly;
  b.addEventListener("click", onClick);
  return b;
}

function wpNote(text, bad) {
  const note = $("wp-note");
  note.textContent = text;
  note.dataset.level = bad ? "bad" : "ok";
}

function renderWaypointsPage() {
  const data = view.waypoints || { waypoints: [], groups: [] };
  $("wp-file").textContent = data.load_error ? data.load_error
    : data.failed ? "백엔드에 닿지 않음" : "";
  $("wp-add-ok").disabled = view.readOnly;
  renderWaypointTable(data.waypoints || []);
  renderGroups(data.groups || []);
  renderGroupEditor();
}

function renderWaypointTable(list) {
  const body = $("wp-rows");
  body.replaceChildren();
  $("wp-count").textContent = `${list.length}개`;
  $("wp-empty").hidden = list.length > 0;
  for (const w of list) {
    const row = wpEl("tr");
    const check = wpEl("input");
    check.type = "checkbox";
    check.checked = wp.checked.has(w.name);
    check.title = "내보내기에 넣기";
    check.addEventListener("change", () => {
      if (check.checked) wp.checked.add(w.name); else wp.checked.delete(w.name);
    });
    const name = wpEl("td", "wp-name");
    name.append(wpButton(w.name, () => renameWaypoint(w.name), { title: "이름 바꾸기" }));
    const when = w.captured_at ? formatTime(w.captured_at) : "";
    const warn = (w.warnings || []).length ? `주의: ${w.warnings.join(", ")}` : "";
    const cells = [
      wpEl("td", "num", w.x.toFixed(3)), wpEl("td", "num", w.y.toFixed(3)),
      wpEl("td", "num", `${toDeg(w.yaw)}°`), wpEl("td", "", w.robot_id || "값 입력"),
      wpEl("td", "num", when), wpEl("td", "wp-warn", warn),
    ];
    const note = wpEl("td", "wp-note-cell");
    note.append(wpButton(w.note || "메모", () => editNote(w), { className: "linkish" }));
    const actions = wpEl("td");
    actions.append(wpButton("지우기", () => deleteWaypoint(w.name), { className: "danger" }));
    const checkCell = wpEl("td");
    checkCell.append(check);
    row.append(checkCell, name, ...cells, note, actions);
    body.append(row);
  }
}

// 적은 좌표로 등록 (로봇은 움직이지 않는다). 화면은 도, 서버는 라디안.
async function addWaypointValues(event) {
  event.preventDefault();
  if (view.readOnly || $("wp-add-ok").disabled) return;
  const values = {};
  for (const [key, label] of [["x", "x"], ["y", "y"], ["yaw", "방향"]]) {
    const input = $(`wp-add-${key}`);
    const value = input.valueAsNumber;   // 빈 칸·숫자가 아니면 NaN
    if (!Number.isFinite(value)) {
      wpNote(`${label} 에 숫자를 적으세요`, true);
      input.focus();
      return;
    }
    values[key] = value;
  }
  if (Math.abs(values.yaw) > 360) {
    wpNote("방향은 -360 ~ 360 도", true);
    $("wp-add-yaw").focus();
    return;
  }
  $("wp-add-ok").disabled = true;
  const result = await wpRequest("POST", "/api/waypoints", {
    x: values.x, y: values.y, yaw: toRad(values.yaw),
    name: $("wp-add-name").value.trim() || null, note: $("wp-add-note").value.trim() || null,
  });
  $("wp-add-ok").disabled = view.readOnly;
  const d = result.data || {};
  if (!result.ok) {
    wpNote(`등록 안 됨: ${d.detail || result.status}`, true);
    return;
  }
  const warnings = d.warnings || [];
  wpNote(`${d.name} 등록 (${d.x.toFixed(3)}, ${d.y.toFixed(3)}, ${toDeg(d.yaw)}°)`
    + (warnings.length ? ` · 주의: ${warnings.join(", ")}` : " · 로봇 카드의 이동에서 고르세요"),
  warnings.length > 0);
  for (const key of ["name", "x", "y", "note"]) $(`wp-add-${key}`).value = "";
  loadWaypoints();
}

async function renameWaypoint(name) {
  const next = window.prompt(`${name} 의 새 이름 (대문자·숫자·_ 16자, 예: DOCK_1)`, name);
  if (!next || next.trim().toUpperCase() === name) return;
  const result = await wpRequest("PATCH", `/api/waypoints/${encodeURIComponent(name)}`, { name: next });
  wpNote(result.ok ? `${name} → ${result.data.name}` : `이름 안 바뀜: ${result.data.detail || result.status}`,
    !result.ok);
  if (result.ok && wp.checked.delete(name)) wp.checked.add(result.data.name);
  loadWaypoints();
}

async function editNote(w) {
  const next = window.prompt(`${w.name} 메모`, w.note || "");
  if (next === null) return;
  const result = await wpRequest("PATCH", `/api/waypoints/${encodeURIComponent(w.name)}`, { note: next });
  if (!result.ok) wpNote(`메모 저장 안 됨: ${result.data.detail || result.status}`, true);
  loadWaypoints();
}

async function deleteWaypoint(name) {
  if (!window.confirm(`${name} 을 지울까요? 이 이름을 쓰는 묶음에서도 빠집니다.`)) return;
  const result = await wpRequest("DELETE", `/api/waypoints/${encodeURIComponent(name)}`);
  if (result.ok) {
    const changed = result.data.groups_changed || [];
    wpNote(`${name} 지움${changed.length ? ` · 묶음에서 뺌: ${changed.join(", ")}` : ""}`, false);
    wp.checked.delete(name);
  } else {
    wpNote(`안 지워짐: ${result.data.detail || result.status}`, true);
  }
  loadWaypoints();
}

async function exportWaypoints() {
  const names = [...wp.checked].join(",");
  try {
    const res = await fetch(`/api/waypoints/export${names ? `?names=${encodeURIComponent(names)}` : ""}`);
    const text = await res.text();
    const box = $("wp-export");
    box.textContent = text;
    box.hidden = false;
    try {
      await navigator.clipboard.writeText(text);
      wpNote("내보내기 조각을 클립보드에 넣었어요 (로봇 설정 points: 아래에 붙임)", false);
    } catch (err) {
      wpNote("아래 조각을 선택해 복사하세요", false);
    }
  } catch (err) {
    wpNote("내보내기 실패: 백엔드에 닿지 않음", true);
  }
}

// ---------- 묶음 ----------

// 묶음에 넣을 수 있는 지점: 로봇 설정(일반·구역 지점·홈) + 관제 웨이포인트
function groupChoices() {
  const names = [];
  const layers = view.layers || {};
  names.push(...Object.keys(layers.points || {}));
  for (const zone of Object.values(layers.zones || {})) names.push(...Object.keys(zone.points || {}));
  for (const home of Object.values(layers.homes || {})) names.push(home.name);
  names.push(...waypointPoses().keys());
  return [...new Set(names)];
}

function renderGroups(groups) {
  const list = $("wp-groups");
  list.replaceChildren();
  $("wp-groups-empty").hidden = groups.length > 0;
  for (const g of groups) {
    const item = wpEl("li");
    const title = wpEl("strong", "", g.name);
    const path = wpEl("span", "wp-path", g.points.join(" → "));
    const note = wpEl("span", "muted", g.note || "");
    item.append(title, path, note,
      wpButton("고치기", () => startGroupEdit(g)),
      wpButton("지우기", () => deleteGroup(g.name), { className: "danger" }));
    list.append(item);
  }
}

function startGroupEdit(group = null) {
  wp.editing = group
    ? { name: group.name, points: [...group.points], note: group.note || "", original: group.name }
    : { name: "", points: [], note: "", original: null };
  renderGroupEditor();
}

function renderGroupEditor() {
  const box = $("wp-editor");
  const editing = wp.editing;
  box.hidden = !editing;
  if (!editing) return;
  $("wp-group-name").value = editing.name;
  $("wp-group-note").value = editing.note;
  const chips = $("wp-group-chips");
  chips.replaceChildren();
  if (!editing.points.length) chips.append(wpEl("span", "muted", "아래에서 지점을 순서대로 더하세요"));
  editing.points.forEach((name, i) => {
    if (i > 0) chips.append(wpEl("span", "route-arrow", "→"));
    const chip = wpEl("span", "route-chip");
    chip.append(document.createTextNode(name));
    chip.append(wpButton("‹", () => moveGroupPoint(i, -1), { title: "앞으로", disabled: i === 0 }));
    chip.append(wpButton("›", () => moveGroupPoint(i, 1),
      { title: "뒤로", disabled: i === editing.points.length - 1 }));
    chip.append(wpButton("×", () => { editing.points.splice(i, 1); renderGroupEditor(); },
      { title: `${name} 빼기` }));
    chips.append(chip);
  });
  const select = $("wp-group-add");
  select.replaceChildren(new Option("지점 더하기…", ""));
  const own = waypointPoses();
  for (const name of groupChoices()) select.append(new Option(own.has(name) ? `${name} (관제)` : name, name));
}

function moveGroupPoint(i, step) {
  const points = wp.editing.points;
  const j = i + step;
  if (j < 0 || j >= points.length) return;
  [points[i], points[j]] = [points[j], points[i]];
  renderGroupEditor();
}

async function saveGroup() {
  const editing = wp.editing;
  editing.name = $("wp-group-name").value.trim();
  editing.note = $("wp-group-note").value;
  if (!editing.name) {
    wpNote("묶음 이름을 적으세요", true);
    return;
  }
  const result = await wpRequest("PUT", `/api/waypoint_groups/${encodeURIComponent(editing.name)}`,
    { points: editing.points, note: editing.note });
  if (!result.ok) {
    wpNote(`묶음 저장 안 됨: ${result.data.detail || result.status}`, true);
    return;
  }
  // 이름을 바꿔 저장했으면 예전 이름은 지운다.
  if (editing.original && editing.original !== editing.name) {
    await wpRequest("DELETE", `/api/waypoint_groups/${encodeURIComponent(editing.original)}`);
  }
  wpNote(`묶음 '${editing.name}' 저장 (${editing.points.length}곳)`, false);
  wp.editing = null;
  loadWaypoints();
}

async function deleteGroup(name) {
  if (!window.confirm(`묶음 '${name}' 을 지울까요? (지점은 그대로 남아요)`)) return;
  const result = await wpRequest("DELETE", `/api/waypoint_groups/${encodeURIComponent(name)}`);
  wpNote(result.ok ? `묶음 '${name}' 지움` : `안 지워짐: ${result.data.detail || result.status}`, !result.ok);
  loadWaypoints();
}

function setupWaypoints() {
  $("wp-add").addEventListener("submit", addWaypointValues);
  $("wp-export-btn").addEventListener("click", exportWaypoints);
  $("wp-new-group").addEventListener("click", () => startGroupEdit());
  $("wp-group-save").addEventListener("click", saveGroup);
  $("wp-group-cancel").addEventListener("click", () => { wp.editing = null; renderGroupEditor(); });
  $("wp-group-add").addEventListener("change", (event) => {
    const name = event.target.value;
    if (name && wp.editing) {
      wp.editing.name = $("wp-group-name").value;
      wp.editing.note = $("wp-group-note").value;
      wp.editing.points.push(name);
      renderGroupEditor();
    }
  });
  $("cmd-group").addEventListener("change", (event) => loadGroupIntoPick(event.target.value));
  try {
    view.shownGroup = localStorage.getItem(SHOWN_GROUP_KEY) || "";
  } catch (err) {
    view.shownGroup = "";
  }
  for (const id of ["map-group", "dt-map-group"]) {
    $(id).addEventListener("change", (event) => setShownGroup(event.target.value));
  }
  $("dt-group-run").addEventListener("click", runGroup);
  window.addEventListener("hashchange", applyWaypointRoute);
  applyWaypointRoute();
  loadWaypoints();
  setInterval(loadWaypoints, WP_POLL_MS);
}
