// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 초기위치 (상세 화면). 위치 칸의 [홈]·[좌표 지정] 버튼과 좌표 지정 띠(#pose-bar),
// 확대 지도 누르고 끌기 (RViz 2D Pose Estimate 와 같음). 로봇은 움직이지 않는다.
// 기대는 것: detail.js 의 detail 상태(posePick·poseBtns)·detailMapPoint·drawDetailMap,
// commands.js 의 sendInitialPose·renderPoseButton·closeBars, map.js 의 toPixel·toWorld·insideMap.
// 카드의 [초기위치](홈)는 commands.js onCommand 가 맡는다.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

// 위치 칸의 [홈] [좌표 지정] 버튼. 칸은 매번 새로 그리므로 버튼은 한 번 만들어 detail.poseBtns 에 두고
// renderStats 가 옮겨 붙인다 (클릭 연결이 사라지지 않게).
function createPoseButtons() {
  const button = (text, kind, onClick) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "pose-btn";
    el.dataset.pose = kind;   // 마우스 글 종류 (commands.js POSE_TITLE)
    el.textContent = text;
    el.addEventListener("click", () => {
      if (view.detailRobot) onClick(view.detailRobot);
    });
    return el;
  };
  return [
    button("홈", "home", (robotId) => onCommand(robotId, "initial_pose")),
    button("좌표 지정", "manual", openPosePick),
  ];
}

// ---------- 초기위치 좌표 지정 ----------
// 확대 지도를 누른 곳이 위치, 누른 채 끈 방향이 로봇 방향 (RViz 2D Pose Estimate 와 같다).
// 띠(#pose-bar)의 숫자를 직접 고쳐도 된다. 보내기는 commands.js sendInitialPose (확인 창 한 번 더).

const POSE_DRAG_MIN_PX = 6;   // 이만큼 [화면 px] 끌어야 방향으로 본다 (그냥 클릭은 방향 유지)

function openPosePick(robotId) {
  closeBars();
  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  const robot = robots[robotId];
  const home = view.layers && view.layers.homes && view.layers.homes[robotId];
  // 처음 값: 지금 추정 위치, 없으면 홈, 그것도 없으면 지도 원점
  const start = robot && robot.pose ? [robot.pose.x, robot.pose.y, robot.pose.yaw]
    : home ? home.pose.map(Number) : [0, 0, 0];
  detail.posePick = { robotId, x: start[0], y: start[1], yaw: start[2] || 0, drag: null };
  $("pose-title").textContent = `${robotId} · 초기위치 좌표`;
  $("detail-bar-host").appendChild($("pose-bar"));
  $("pose-bar").hidden = false;
  syncPoseInputs();
  updatePosePick();
}

function closePosePick() {
  if (!detail.posePick) return;
  detail.posePick = null;
  $("pose-bar").hidden = true;
  drawDetailMap();
}

// 상태 → 입력칸 (지도를 눌렀을 때)
function syncPoseInputs() {
  const p = detail.posePick;
  $("pose-x").value = p.x.toFixed(2);
  $("pose-y").value = p.y.toFixed(2);
  $("pose-yaw").value = String(toDeg(p.yaw));
}

// 입력칸 → 상태 (숫자를 고쳤을 때)
function readPoseInputs() {
  const p = detail.posePick;
  if (!p) return;
  p.x = parseFloat($("pose-x").value);
  p.y = parseFloat($("pose-y").value);
  p.yaw = toRad(parseFloat($("pose-yaw").value));
  updatePosePick();
}

// 보낼 수 있는지 검사해 경고·보내기 버튼을 맞추고 지도를 다시 그린다.
function updatePosePick() {
  const p = detail.posePick;
  if (!p) return;
  const numbers = [p.x, p.y, p.yaw].every(Number.isFinite);
  const why = !numbers ? "x, y, 방향을 숫자로 적으세요"
    : view.map && !insideMap(view.map.info, p.x, p.y) ? "지도 밖 좌표입니다"
    : "";
  const real = view.snapshot && view.snapshot.infra && view.snapshot.infra.mode === "real";
  $("pose-warn").textContent = why ? `⚠ ${why}`
    : real ? "⚠ 실물 로봇: 로봇이 정말 그 자리·방향에 있을 때만 보내세요." : "";
  $("pose-ok").disabled = Boolean(why);
  drawDetailMap();
}

async function sendPosePick() {
  const p = detail.posePick;
  if (!p || $("pose-ok").disabled) return;
  // 방향은 -180°~180° 로 맞춰 보낸다 (AMCL 은 어느 쪽이든 같지만 기록을 읽기 쉽게)
  const yaw = Math.atan2(Math.sin(p.yaw), Math.cos(p.yaw));
  if (await sendInitialPose(p.robotId, { x: p.x, y: p.y, yaw })) closePosePick();
}

// 화살표 미리보기: 로봇 크기 원 + 방향 화살표 (점선 테두리로 '아직 안 보냄'을 보인다)
function drawPosePick(ctx, info, scale) {
  const p = detail.posePick;
  if (![p.x, p.y, p.yaw].every(Number.isFinite)) return;
  const [px, py] = toPixel(info, p.x, p.y);
  const r = Math.max(ROBOT_RADIUS_M / info.resolution, 6 / scale);
  ctx.save();
  ctx.translate(px, py);
  ctx.strokeStyle = css("--active");
  ctx.fillStyle = css("--active");
  ctx.lineWidth = 2 / scale;
  ctx.setLineDash([4 / scale, 3 / scale]);
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.rotate(-p.yaw);   // 지도 y 는 위가 +, canvas y 는 아래가 +
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(r * 2.6, 0);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(r * 3.2, 0);
  ctx.lineTo(r * 2.3, -r * 0.6);
  ctx.lineTo(r * 2.3, r * 0.6);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function setupPosePick() {
  const canvas = $("dt-map");
  const active = () => detail.posePick && detail.posePick.robotId === view.detailRobot;
  canvas.addEventListener("pointerdown", (event) => {
    if (!active() || !view.map) return;
    const point = detailMapPoint(event);
    if (!point) return;
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    const [x, y] = toWorld(view.map.info, point[0], point[1]);
    Object.assign(detail.posePick, { x, y, drag: point });
    syncPoseInputs();
    updatePosePick();
  });
  canvas.addEventListener("pointermove", (event) => {
    const p = detail.posePick;
    if (!active() || !p.drag) return;
    const point = detailMapPoint(event);
    const dx = point[0] - p.drag[0];
    const dy = point[1] - p.drag[1];
    if (Math.hypot(dx, dy) * detail.xf.scale < POSE_DRAG_MIN_PX) return;
    p.yaw = Math.atan2(-dy, dx);   // canvas y 는 아래가 + 라서 뒤집는다
    syncPoseInputs();
    updatePosePick();
  });
  const release = () => {
    if (detail.posePick) detail.posePick.drag = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  for (const id of ["pose-x", "pose-y", "pose-yaw"]) $(id).addEventListener("input", readPoseInputs);
  $("pose-ok").addEventListener("click", sendPosePick);
  $("pose-cancel").addEventListener("click", closePosePick);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && detail.posePick) closePosePick();
  });
}
