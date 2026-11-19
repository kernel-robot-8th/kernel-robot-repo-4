// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 웨이포인트 기록 (상세 화면 조종 칸, 2026-11-18).
// [웨이포인트 기록 시작] → 기록 카드가 열린다. 로봇을 몰고 가서 [여기 추가 (R)] 를 누를 때마다
// 지금 위치가 관제 웨이포인트(W1, W2 …)로 저장되고 카드 목록과 오른쪽 확대 지도에 1→2→3 으로 쌓인다.
// [완료] 를 누르면 그 순서로 묶음 하나가 만들어진다 (경로 띠의 '묶음 불러오기'로 보낸다).
// [취소] 는 이번 기록에서 만든 점을 모두 지운다. 목록의 × 도 그 점을 지운다.
// 한 번에 한 로봇만 기록한다. 새로 고침해도 이어지게 기록 중 상태를 이 탭(sessionStorage)에 둔다.

"use strict";

const REC_KEY = "cobot_control_center.recording";
// 움직이는 중에 추가하면 먼저 세우고 이만큼 기다린 뒤 저장한다 [ms].
// 관제 상태(fleet_status)가 1초마다 오므로 멈춘 뒤 위치가 한 번은 들어오게 한다.
const REC_SETTLE_MS = 1200;

const rec = {
  robotId: null,   // 기록 중인 로봇 (없으면 null)
  name: "",        // 만들 묶음 이름
  points: [],      // 이번 기록에서 저장한 웨이포인트 이름 (순서대로)
  busy: false,     // 추가·완료·취소 처리 중
  msg: null,       // {text, bad} 카드 안 한 줄
};

function recording(robotId) {
  return rec.robotId !== null && rec.robotId === robotId;
}

function storeRecord() {
  try {
    if (rec.robotId === null) sessionStorage.removeItem(REC_KEY);
    else sessionStorage.setItem(REC_KEY, JSON.stringify(
      { robotId: rec.robotId, name: rec.name, points: rec.points }));
  } catch (err) {
    // 저장소를 못 쓰는 창이면 새로 고침 때 기록이 끊길 뿐이다.
  }
}

function restoreRecord() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(REC_KEY) || "null");
    if (saved && typeof saved.robotId === "string" && Array.isArray(saved.points)) {
      rec.robotId = saved.robotId;
      rec.name = String(saved.name || "");
      rec.points = saved.points.filter((p) => typeof p === "string");
    }
  } catch (err) {
    // 깨진 값은 버린다.
  }
}

function defaultGroupName(robotId) {
  const d = new Date();
  const two = (n) => String(n).padStart(2, "0");
  return `${robotId} ${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

function recMsg(text, bad = false) {
  rec.msg = { text, bad };
  renderRecord();
}

function startRecord() {
  const robotId = view.detailRobot;
  if (robotId === null) return;
  if (rec.robotId !== null && rec.robotId !== robotId) {
    recMsg(`${rec.robotId} 기록이 진행 중이에요. 그 로봇 화면에서 완료하거나 취소하세요.`, true);
    return;
  }
  rec.robotId = robotId;
  rec.name = defaultGroupName(robotId);
  rec.points = [];
  rec.msg = { text: "로봇을 옮기고 [여기 추가] 를 누르세요", bad: false };
  storeRecord();
  renderRecord();
  drawDetailMap();
}

// 움직이는 중이면 먼저 세우고 위치가 들어올 때까지 기다린 뒤 저장한다. 조종 세션은 그대로 둔다.
async function addRecordPoint() {
  const robotId = view.detailRobot;
  if (!recording(robotId) || rec.busy) return;
  rec.busy = true;
  recMsg("저장 중…");
  if (teleop.started && teleop.robotId === robotId) {
    const { vx, wz } = teleopInput();
    if (vx || wz) {
      teleop.held.clear();
      sendTeleop();
      renderTeleop();
      await new Promise((resolve) => { setTimeout(resolve, REC_SETTLE_MS); });
    }
  }
  const result = await wpRequest("POST", "/api/waypoints", { robot_id: robotId });
  rec.busy = false;
  const d = result.data || {};
  if (result.ok) {
    // 목록을 먼저 새로 받아야 한다 (안 그러면 pruneRecord 가 아직 모르는 새 점을 빼 버린다).
    await loadWaypoints();
    rec.points.push(d.name);
    storeRecord();
    const warn = (d.warnings || []).length ? ` · 주의: ${d.warnings.join(", ")}` : "";
    recMsg(`${rec.points.length}. ${d.name} 추가 (${d.x.toFixed(2)}, ${d.y.toFixed(2)})${warn}`,
      Boolean(warn));
  } else {
    recMsg(`추가 안 됨: ${d.detail || result.status}`, true);
  }
  drawDetailMap();
}

async function removeRecordPoint(i) {
  const name = rec.points[i];
  if (!name || rec.busy) return;
  rec.busy = true;
  const result = await wpRequest("DELETE", `/api/waypoints/${encodeURIComponent(name)}`);
  rec.busy = false;
  // 이미 지워졌으면(404) 목록에서만 뺀다.
  if (result.ok || result.status === 404) {
    rec.points.splice(i, 1);
    storeRecord();
    recMsg(`${name} 뺐어요`);
    await loadWaypoints();
  } else {
    recMsg(`${name} 을 못 지웠어요: ${result.data.detail || result.status}`, true);
  }
  drawDetailMap();
}

function clearRecord() {
  rec.robotId = null;
  rec.name = "";
  rec.points = [];
  rec.busy = false;
  storeRecord();
}

async function finishRecord() {
  if (rec.busy || rec.robotId === null) return;
  const name = $("rec-name").value.trim();
  rec.name = name;
  if (!name) {
    recMsg("묶음 이름을 적으세요", true);
    return;
  }
  if (!rec.points.length) {
    recMsg("추가한 지점이 없어요", true);
    return;
  }
  const exists = ((view.waypoints && view.waypoints.groups) || []).some((g) => g.name === name);
  if (exists && !window.confirm(`묶음 '${name}' 이 이미 있어요. 이번 기록으로 바꿀까요?`)) return;
  rec.busy = true;
  const result = await wpRequest("PUT", `/api/waypoint_groups/${encodeURIComponent(name)}`,
    { points: rec.points, note: `${rec.robotId} 기록` });
  rec.busy = false;
  if (!result.ok) {
    recMsg(`묶음 저장 안 됨: ${result.data.detail || result.status}`, true);
    return;
  }
  const robotId = rec.robotId;
  const count = rec.points.length;
  clearRecord();
  rec.msg = { text: `묶음 '${name}' 저장 (${count}곳) · 경로 → 묶음 불러오기로 보냄`, bad: false };
  showMessage(robotId, `묶음 '${name}' 저장 (${count}곳)`, false);
  await loadWaypoints();
  renderRecord();
  drawDetailMap();
}

async function cancelRecord() {
  if (rec.busy || rec.robotId === null) return;
  const names = [...rec.points];
  if (names.length && !window.confirm(
    `기록을 취소하고 이번에 추가한 ${names.length}개 지점(${names.join(", ")})도 지울까요?`)) return;
  rec.busy = true;
  const failed = [];
  for (const name of names) {
    const result = await wpRequest("DELETE", `/api/waypoints/${encodeURIComponent(name)}`);
    if (!result.ok && result.status !== 404) failed.push(name);
  }
  clearRecord();
  rec.msg = failed.length ? { text: `기록 취소 · 못 지운 지점: ${failed.join(", ")}`, bad: true }
    : { text: "기록 취소", bad: false };
  await loadWaypoints();
  renderRecord();
  drawDetailMap();
}

// 웨이포인트 화면 등에서 지운 점은 목록에서도 뺀다 (완료 때 '모르는 지점'으로 막히지 않게).
function pruneRecord() {
  if (rec.robotId === null || !view.waypoints || view.waypoints.failed) return;
  const known = waypointPoses();
  const kept = rec.points.filter((p) => known.has(p));
  if (kept.length !== rec.points.length) {
    rec.points = kept;
    storeRecord();
  }
}

function renderRecord() {
  const box = $("teleop");
  if (!box) return;
  const robotId = view.detailRobot;
  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  const robot = robotId === null ? null : robots[robotId];
  const on = recording(robotId);
  pruneRecord();
  box.dataset.recording = on ? "1" : "";
  const start = $("rec-start");
  start.hidden = on;
  start.disabled = view.readOnly || robotId === null;
  start.title = view.readOnly ? "개발 화면 (읽기 전용)"
    : rec.robotId !== null && !on ? `${rec.robotId} 기록 중`
      : "로봇을 몰고 다니며 지점을 차례로 저장하고, 완료하면 묶음 하나로 만든다";
  $("rec-card").hidden = !on;
  const msg = $("rec-msg");
  const note = rec.msg && (on || rec.robotId === null) ? rec.msg : null;
  msg.textContent = note ? note.text : "";
  msg.dataset.level = note && note.bad ? "bad" : "ok";
  if (!on) return;
  const name = $("rec-name");
  if (document.activeElement !== name) name.value = rec.name;
  $("rec-count").textContent = `${rec.points.length}곳`;
  const add = $("rec-add");
  add.disabled = rec.busy || !robot || !robot.pose || !robot.online;
  add.textContent = rec.busy ? "저장 중…" : "여기 추가 (R)";
  const warnings = (robot && robot.teach && robot.teach.warnings) || [];
  add.title = "지금 위치를 다음 번호로 추가 (R) · 움직이는 중이면 먼저 세운 뒤 저장 · 조종은 이어짐"
    + (warnings.length ? `\n주의: ${warnings.join(", ")}` : "");
  $("rec-done").disabled = rec.busy || rec.points.length === 0;
  $("rec-cancel").disabled = rec.busy;
  const poses = waypointPoses();
  const list = $("rec-list");
  list.replaceChildren();
  rec.points.forEach((pointName, i) => {
    const item = document.createElement("li");
    const label = document.createElement("span");
    const pose = poses.get(pointName);
    // 번호는 지도 순번과 같다 (li 가 flex 라 목록 기본 번호가 안 보여 직접 붙인다)
    label.textContent = `${i + 1}. ${pointName}`
      + (pose ? ` (${pose[0].toFixed(2)}, ${pose[1].toFixed(2)})` : "");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = `${pointName} 빼고 지우기`;
    remove.disabled = rec.busy;
    remove.addEventListener("click", () => removeRecordPoint(i));
    item.append(label, remove);
    list.append(item);
  });
  if (!rec.points.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "아직 없음";
    list.append(empty);
  }
}

// 확대 지도: 이번 기록의 점을 1 → 2 → 3 순번과 점선으로 (drawDetailMap 이 부른다).
function drawRecord(ctx, info, scale, robotId) {
  if (!recording(robotId) || !rec.points.length) return;
  const poses = waypointPoses();
  const path = rec.points.map((name) => poses.get(name)).filter(Boolean)
    .map((pose) => toPixel(info, pose[0], pose[1]));
  const color = css("--warn");
  ctx.save();
  ctx.lineWidth = 2 / scale;
  ctx.strokeStyle = color;
  if (path.length > 1) {
    ctx.setLineDash([6 / scale, 4 / scale]);
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

function setupRecord() {
  restoreRecord();
  $("rec-start").addEventListener("click", startRecord);
  $("rec-add").addEventListener("click", addRecordPoint);
  $("rec-done").addEventListener("click", finishRecord);
  $("rec-cancel").addEventListener("click", cancelRecord);
  $("rec-name").addEventListener("input", (event) => {
    rec.name = event.target.value;
    storeRecord();
  });
  renderRecord();
}
