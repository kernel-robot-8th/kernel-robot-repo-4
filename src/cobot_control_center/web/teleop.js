// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 상세 화면 직접 조종 (카메라 칸 아래 #teleop). 실제 로봇이 움직인다.
// [조종 시작]을 눌러야 WS /ws/teleop/<robot> 이 열리고, 그 뒤에만 ▲▼◀▶·키보드가 먹는다.
// 열려 있는 동안 100 ms 마다 {vx, wz} (-1~1 비율, 손 떼면 0) 를 보낸다. 실제 속도는 teleop_node 최대값.
// 보내기가 0.3초 끊기면 teleop_node 가 로봇을 세우고 세션을 끝낸다 (창 닫힘·네트워크 끊김 대비).
// 창이 포커스를 잃거나 다른 탭·화면으로 가면 바로 끝낸다 (키를 뗀 줄 모르고 계속 가지 않게).
// 막는 기준은 서버(teleop_utils.teleop_block_reason)와 같다: 정지·대기일 때만, 작업·경로·주문·정지 잠금이면 안 됨.

"use strict";

const TELEOP_SEND_MS = 100;

// 방향 → [vx, wz] 비율. 각속도 +는 왼쪽 회전 (REP-103).
const TELEOP_DIRS = { up: [1, 0], down: [-1, 0], left: [0, 1], right: [0, -1] };
const TELEOP_KEYS = {
  ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down",
  ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right",
};

const teleop = {
  ws: null,         // 열린 WebSocket (없으면 null)
  robotId: null,    // 조종 중(또는 여는 중)인 로봇
  started: false,   // 서버가 started 를 보냈는지
  timer: null,      // 100 ms 보내기 타이머
  held: new Set(),  // 누르고 있는 방향 (버튼·키보드)
  note: null,       // 마지막으로 끝난 이유 {robotId, text}
  limits: null,     // 서버가 알려 준 최대 속도 {max_linear, max_angular}
};

function isDriving(robotId) {
  return (view.teleop || []).includes(robotId);
}

// 이 화면에서 조종을 시작할 수 없는 이유 (되면 "").
function teleopBlockReason(robotId, robot) {
  if (!robot) return "등록되지 않은 로봇";
  const order = (view.orders || []).find((o) => o.robot_id === robotId);
  const latched = (robot.extra || {}).central_latched === true || view.holds[robotId];
  return linkBlockReason(robot)
    || (!view.teleopOnline ? "조종 노드 꺼짐 (teleop_node)" : "")
    || (!view.commandsArmed ? "상단 '작업 명령 켜기'를 누르세요" : "")
    || (latched ? "정지 잠금 (현장 확인 후 복구 먼저)" : "")
    || busyReason(robot, robotTask(robotId, new Set([...ACTIVE_TASK, ...UNKNOWN_TASK])),
      runningRoute(robotId))
    || (order ? `주문 진행 중 ${order.order_id}` : "")
    || (isDriving(robotId) && teleop.robotId !== robotId ? "다른 화면에서 조종 중" : "");
}

function teleopInput() {
  let vx = 0;
  let wz = 0;
  teleop.held.forEach((dir) => {
    const v = TELEOP_DIRS[dir];
    if (v) {
      vx += v[0];
      wz += v[1];
    }
  });
  return { vx: Math.max(-1, Math.min(1, vx)), wz: Math.max(-1, Math.min(1, wz)) };
}

function sendTeleop() {
  if (teleop.ws && teleop.ws.readyState === WebSocket.OPEN && teleop.started) {
    teleop.ws.send(JSON.stringify(teleopInput()));
  }
}

function startTeleop() {
  const robotId = view.detailRobot;
  if (robotId === null || teleop.ws) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/teleop/${encodeURIComponent(robotId)}`);
  teleop.ws = ws;
  teleop.robotId = robotId;
  teleop.started = false;
  teleop.note = null;
  teleop.held.clear();
  ws.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    if (msg.type === "started") {
      teleop.started = true;
      teleop.limits = msg.limits || null;
      teleop.timer = setInterval(sendTeleop, TELEOP_SEND_MS);
      sendTeleop();
      // [조종 시작]에 포커스가 남으면 Space·Enter 가 그 버튼(조종 끝)을 눌러 버린다.
      if (document.activeElement) document.activeElement.blur();
    } else if (msg.type === "refused" || msg.type === "ended") {
      teleop.note = { robotId, text: `${msg.type === "refused" ? "시작 안 됨" : "조종 끝남"}: ${msg.detail}` };
    }
    renderTeleop();
  };
  ws.onclose = () => {
    if (teleop.ws !== ws) return;
    if (teleop.started && !teleop.note) teleop.note = { robotId, text: "조종 끝남: 연결 끊김" };
    cleanupTeleop();
  };
  renderTeleop();
}

// 화면 쪽 정리. 서버는 연결이 닫히면 stop 을 보내고, teleop_node 가 0 속도를 낸다.
function cleanupTeleop() {
  clearInterval(teleop.timer);
  teleop.timer = null;
  teleop.ws = null;
  teleop.started = false;
  teleop.held.clear();
  renderTeleop();
}

function stopTeleop(text) {
  if (!teleop.ws) return;
  const ws = teleop.ws;
  if (text) teleop.note = { robotId: teleop.robotId, text };
  // 닫기 전에 0 을 한 번 보낸다 (서버가 stop 을 보내기 전 사이에도 멈춰 있게).
  teleop.held.clear();
  sendTeleop();
  cleanupTeleop();
  ws.close();
}

function renderTeleop() {
  const box = $("teleop");
  if (!box) return;
  const robotId = view.detailRobot;
  const robots = view.snapshot ? view.snapshot.robots || {} : {};
  const robot = robotId === null ? null : robots[robotId];
  const mine = teleop.ws !== null && teleop.robotId === robotId;
  const driving = mine && teleop.started;
  const why = mine ? "" : teleopBlockReason(robotId, robot);
  const toggle = $("teleop-toggle");
  toggle.textContent = mine ? "조종 끝" : "조종 시작";
  toggle.disabled = !mine && Boolean(why);
  toggle.title = mine ? "조종을 끝내고 로봇을 세움 (Esc)" : why || "이 로봇을 직접 조종 (실제 로봇이 움직임)";
  toggle.classList.toggle("on", mine);
  box.dataset.state = driving ? "driving" : mine ? "opening" : why ? "blocked" : "ready";
  box.querySelectorAll(".teleop-pad button").forEach((button) => {
    button.disabled = !driving;
    button.classList.toggle("held", teleop.held.has(button.dataset.dir));
  });
  const status = $("teleop-status");
  const note = teleop.note && teleop.note.robotId === robotId ? teleop.note.text : "";
  if (driving) {
    const { vx, wz } = teleopInput();
    status.textContent = vx || wz ? `조종 중 · 움직이는 중` : "조종 중 · 멈춤 (누르고 있는 동안만 움직임)";
  } else if (mine) {
    status.textContent = "연결 중…";
  } else {
    status.textContent = note || (why ? `조종 불가: ${why}` : "조종 가능 · 실제 로봇이 움직입니다");
  }
  status.dataset.level = driving ? "busy" : note ? "bad" : why ? "warn" : "ok";
  renderRecord();
  const limits = teleop.limits || view.teleopLimits;
  $("teleop-limit").textContent = limits && limits.max_linear
    ? `최대 ${limits.max_linear} m/s · ${limits.max_angular} rad/s` : "";
}

function pressDir(dir, on) {
  if (!teleop.started) return;
  if (dir === "stop") {
    teleop.held.clear();
  } else if (on) {
    teleop.held.add(dir);
  } else {
    teleop.held.delete(dir);
  }
  // 누르는 순간 바로 보낸다 (다음 100 ms 를 기다리지 않게).
  sendTeleop();
  renderTeleop();
}

function typingTarget(target) {
  return target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
}

function setupTeleop() {
  $("teleop-toggle").addEventListener("click", () => {
    if (teleop.ws) stopTeleop("조종 끝남: 운영자 끝냄");
    else startTeleop();
  });
  $("teleop-pad").querySelectorAll("button").forEach((button) => {
    const dir = button.dataset.dir;
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      pressDir(dir, true);
    });
    ["pointerup", "pointercancel", "lostpointercapture"].forEach((name) => {
      button.addEventListener(name, () => pressDir(dir, false));
    });
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  });
  window.addEventListener("keydown", (event) => {
    if (typingTarget(event.target)) return;
    // 웨이포인트 기록 중이면 R 로 지금 자리를 추가 (조종하지 않을 때도, record.js)
    if (event.code === "KeyR" && recording(view.detailRobot)) {
      event.preventDefault();
      if (!event.repeat) addRecordPoint();
      return;
    }
    if (!teleop.started) return;
    if (event.code === "Escape") {
      stopTeleop("조종 끝남: 운영자 끝냄 (Esc)");
      event.preventDefault();
      return;
    }
    const dir = event.code === "Space" ? "stop" : TELEOP_KEYS[event.code];
    if (!dir) return;
    event.preventDefault(); // 방향키·스페이스로 화면이 스크롤되지 않게
    if (!event.repeat) pressDir(dir, true);
  });
  window.addEventListener("keyup", (event) => {
    const dir = TELEOP_KEYS[event.code];
    if (dir && teleop.started) pressDir(dir, false);
  });
  // 키를 누른 채 창을 떠나면 keyup 이 오지 않는다. 그래서 포커스를 잃으면 조종을 끝낸다.
  window.addEventListener("blur", () => stopTeleop("조종 끝남: 창이 포커스를 잃음"));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopTeleop("조종 끝남: 화면이 가려짐");
  });
  window.addEventListener("hashchange", () => {
    if (teleop.ws && routeRobot() !== teleop.robotId) stopTeleop("조종 끝남: 화면을 떠남");
  });
  window.addEventListener("pagehide", () => stopTeleop());
  renderTeleop();
}
