// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 명령 버튼·정지·지점 고르기 오버레이.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const PICK_HIT_PX = 14;        // 지도에서 지점을 누른 것으로 볼 거리 [화면 px]

// ---------- 명령 ----------
// 화면은 요청만 한다. 검증·기록·발행은 작업 노드가 하고, 결과는 /ws/tasks 로 온다.
// 작업 노드는 cobot_fleet_control 의 fleet_control_node 다 (중앙 관제: 하트비트·세션·순번).
// 정지는 항상 누를 수 있다. 다른 명령은 연결돼 있고, 작업 중이 아니고, 작업 노드가 살아 있고,
// 상단 '작업 명령 켜기'로 켜져 있을 때만 (작업 노드는 bringup 에서 늘 켜져 있어 사람이 따로 켠다).
// 일반 정지는 그 로봇만 멈추고 잠그지 않는다 (구역 안이면 물러남, 주문 중이면 보류).
// 비상정지는 그 로봇만 제자리에 세우고 보류(정지 잠금)한다. 상단 전체 비상정지만 작업 명령을 모두 끈다.
// 잠긴 카드의 빨간 줄을 누르면 제어권 복구 띠가 뜬다 (release.js, release_control API).

const ACTIVE_TASK = new Set(["ACCEPTED", "SENT", "RUNNING"]);
const UNKNOWN_TASK = new Set(["UNKNOWN"]);
// 로봇이 이 상태면 관제 작업이 없어도 움직이는 중이다 (유휴 복귀 등). 순찰 노드의 상태 이름.
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
const OP_TEXT = { goto: "이동", zone: "구역", leave: "나가기", home: "홈", route: "경로" };
// 지점을 여러 개 순서대로 고르는 명령 (고른 순번을 붙이고 '지우기'를 보인다)
const MULTI_POINT = new Set(["goto", "route"]);
// fleet_control 보류 사유: 운영자 정지(STOP·ESTOP·PAUSE·MANUAL), 시나리오 중단(PAUSED·ESTOP·MANUAL),
// 상태·배터리 수신 만료(LINK_LOST), 고객 무응답으로 신발을 실은 채 복귀(CARGO_ONBOARD). 모르는 사유는 그대로 보인다.
const HOLD_TEXT = {
  RESET_PENDING: "잠금 해제 응답 대기", RESET_UNCONFIRMED: "잠금 해제 미확인", DISPATCH_FAILED: "명령 전달 실패",
  STOP: "정지", ESTOP: "비상정지", PAUSE: "일시정지", PAUSED: "일시정지", MANUAL: "수동",
  LINK_LOST: "통신 끊김", CARGO_ONBOARD: "신발 실려 있음",
};
const TASK_LIST_MAX = 50;   // 작업 목록에 보이는 최대 줄 수 (목록은 높이 고정, 스크롤)
const MSG_MS = 6000;

const newRequestId = () => (crypto.randomUUID ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

// 이 로봇의 진행 중 경로 (/api/health 의 routes, 백엔드 route_utils). 없으면 null.
function runningRoute(robotId) {
  const route = view.routes && view.routes[robotId];
  return route && route.state === "RUNNING" ? route : null;
}

// 경로 진행 한 줄. 예: "경로 2/3 · zone:ZA1 · 진행"
function routeText(route) {
  const leg = route.legs[route.index];
  const total = route.legs.length;
  if (!leg) return `경로 ${total}/${total}`;
  return `경로 ${route.index + 1}/${total} · ${leg.operation}:${leg.points.join(",")}`
    + ` · ${TASK_TEXT[leg.state] || (leg.state === "WAITING" ? "보낼 차례" : leg.state)}`;
}

// 경로를 구간으로 미리 나눠 본다 (백엔드 route_utils.split_route 와 같은 규칙, 화면 미리보기용).
// 이어지는 일반 지점·홈은 goto 하나, 구역 지점은 하나씩 zone. 최종 판단은 백엔드가 한다.
function routeLegs(names) {
  const zonePoints = new Set(Object.values((view.layers && view.layers.zones) || {})
    .flatMap((zone) => Object.keys(zone.points || {})));
  const legs = [];
  for (const name of names) {
    const last = legs[legs.length - 1];
    if (zonePoints.has(name)) legs.push({ operation: "zone", points: [name] });
    else if (last && last.operation === "goto") last.points.push(name);
    else legs.push({ operation: "goto", points: [name] });
  }
  return legs;
}

// 경로 고르기 띠 가운데: 고른 지점을 화살표로 이은 칩 (× 로 그 지점만 빼기). 순서는 화살표로 보인다.
// 구간 미리보기는 띠 머리 마우스 글에만 둔다 (화면을 단순하게, 2026-11-18).
// 지점은 지도에서 고른다 (이름 버튼을 깔지 않는다: 40개 가까이 되어 고른 순서가 묻히므로).
function renderRouteChips(box, pick) {
  const names = pick.names();
  box.replaceChildren();
  if (names.length === 0) {
    const hint = document.createElement("p");
    hint.className = "route-hint";
    hint.textContent = "지도에서 차례로 누르세요";
    box.appendChild(hint);
    return;
  }
  const chips = document.createElement("div");
  chips.className = "route-chips";
  names.forEach((name, i) => {
    if (i > 0) {
      const arrow = document.createElement("span");
      arrow.className = "route-arrow";
      arrow.textContent = "→";
      chips.appendChild(arrow);
    }
    const chip = document.createElement("span");
    chip.className = "route-chip";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = `${name} 빼기`;
    remove.addEventListener("click", () => {
      pick.route.splice(i, 1);
      pick.update();
    });
    chip.append(document.createTextNode(name), remove);
    chips.appendChild(chip);
  });
  box.append(chips);
}

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
  card.querySelectorAll(".cmd-row button, .stop-row button, .pose-btn").forEach((button) => {
    button.addEventListener("click", () => onCommand(robotId, button.dataset.cmd));
  });
  // 빨간 줄을 누르면 결과 모름 해제, 아니면 정지 잠금 복구를 연다 (release.js).
  card.querySelector(".cmd-head").addEventListener("click", () => onCmdHeadClick(robotId));
}

// 지점 고르기·결과 모름 해제 띠를 붙일 자리. 상세 화면이면 상태줄 아래, 아니면 그 로봇 카드 위.
function barHost(robotId) {
  if (view.detailRobot === robotId) return $("detail-bar-host");
  const card = view.cards.get(robotId);
  return card ? card.querySelector(".card-body") : null;
}

// 정지 잠금: 로봇이 비상정지나 움직이던 중의 하트비트 단절·관제 재시작으로 잠겼거나(central_latched),
// fleet_control 이 보류 중(holds). 잠겨 있으면 이동 명령은 거절된다. 아니면 null.
// hint 가 참이면 푸는 방법을 붙인다 (카드 상태 줄), 거짓이면 상태만 (복구 띠 제목 옆).
function latchText(robotId, robot, hint = false) {
  const extra = robot.extra || {};
  const hold = view.holds[robotId];
  if (extra.central_latched !== true && !hold) return null;
  const parts = ["정지 잠금"];
  if (hold) parts[0] += ` (${HOLD_TEXT[hold] || hold})`;
  if (extra.held_zone) parts.push(`구역 ${extra.held_zone} 점유`);
  if (hint) parts.push("눌러서 현장 확인 후 복구");
  return parts.join(" · ");
}

// 이 로봇이 잡고 있는 구역 이름 목록. 구역 상태를 못 받았으면 null (모름).
function heldZones(robotId) {
  const zones = view.snapshot ? view.snapshot.zones || {} : {};
  if (Object.keys(zones).length === 0) return null;
  return Object.keys(zones).filter((name) => zones[name] === `occupied_by:${robotId}`);
}

// 명령을 막는 이유는 두 묶음이다. 일반 명령과 초기위치가 함께 쓴다 (누를 수 있으면 "").
// 연결: 읽기 전용 화면, 작업 노드 꺼짐, 로봇 연결 끊김
function linkBlockReason(robot) {
  return view.readOnly ? "개발 화면 (읽기 전용), 명령은 8080 에서"
    : !view.controllerOnline ? "작업 노드 꺼짐"
    : !robot.online ? "연결 끊김" : "";
}

// 움직이는 중: 관제 작업이 진행 중이거나, 작업이 없어도 로봇이 움직이는 상태 (유휴 복귀 등)
function busyReason(robot, active, route = null) {
  // 경로는 구간 사이에 관제 작업이 잠깐 없으므로 따로 본다 (그 사이에 다른 명령을 끼우지 않게).
  return route ? `경로 진행 중 ${route.route_id}`
    : active ? `작업 중 ${active.task_id}`
    : BUSY_ROBOT.has(robot.state) ? `로봇 작업 중 (${robot.state})` : "";
}

// 초기위치: 연결·멈춤만 본다. 작업 명령 켜기와 정지 잠금은 막지 않는다
// (로봇을 켜자마자, 또는 잠금 복구 중에 위치를 다시 잡는 단계라서). 최종 검사는 작업 노드가 한다.
function poseBlockReason(robotId, robot) {
  return linkBlockReason(robot)
    || (isDriving(robotId) ? "직접 조종 중" : "")
    || busyReason(robot, robotTask(robotId, ACTIVE_TASK), runningRoute(robotId));
}

// 초기위치 버튼 마우스 글 (버튼 data-pose 로 고른다)
const POSE_TITLE = {
  home: "로봇을 홈에 놓은 뒤 누름 · AMCL 위치를 홈으로 다시 잡음 (로봇은 움직이지 않음, 작업 명령 켜기 없이 가능)",
  manual: "확대 지도를 누르고 끌어 위치·방향 지정 · AMCL 위치를 그 자리로 다시 잡음 (로봇은 움직이지 않음)",
};

// 카드(.pose-row)와 상세 위치 칸이 함께 쓴다. 꺼지면 이유를, 켜지면 설명을 마우스 글로 보인다.
function renderPoseButton(button, robotId, robot) {
  const why = poseBlockReason(robotId, robot);
  button.disabled = Boolean(why);
  button.title = why || POSE_TITLE[button.dataset.pose] || "";
}

function renderCommands(card, robotId, robot) {
  const active = robotTask(robotId, ACTIVE_TASK);
  // 사람이 풀어야 할 문제 (release.js currentProblem). 상차 확인 대기는 버튼을 막지 않으므로 그다음 것을 본다.
  const problem = currentProblem(robotId);
  const blocker = problem && problem.kind === "load" ? currentProblem(robotId, true) : problem;
  // 잠금은 '작업 명령 켜기'보다 먼저 알린다 (보류된 로봇은 작업 명령이 켜져 있어도 복구해야 풀리므로 켜기만으로는 안 풀린다).
  const reason = linkBlockReason(robot)
    || (blocker ? blocker.reason : "")
    || (!view.commandsArmed ? "상단 '작업 명령 켜기'를 누르세요" : "")
    || (isDriving(robotId) ? "직접 조종 중 (상세 화면에서 조종 끝)" : "")
    || busyReason(robot, active, runningRoute(robotId));
  // 나가기는 보유 구역이 있을 때만 켠다. 구역 상태를 모르면 막지 않는다 (최종 판단은 작업 노드·로봇).
  // 구역을 잡고 있어도 이동·구역 명령은 켠다: 로봇이 먼저 구역을 나간다 (2026-11-09).
  const held = heldZones(robotId);
  const holding = Boolean(held && held.length);
  const only = {
    leave: held && !holding ? "보유 구역 없음" : "",
  };
  card.querySelectorAll(".cmd-row button").forEach((button) => {
    const why = reason || only[button.dataset.cmd] || "";
    button.disabled = Boolean(why);
    button.title = why;
    button.classList.toggle("picking", Boolean(view.pick && view.pick.robotId === robotId
      && view.pick.cmd === button.dataset.cmd));
  });
  card.querySelectorAll(".stop-row button").forEach((button) => {
    button.disabled = !view.controllerOnline || view.readOnly;
  });
  card.querySelectorAll(".pose-btn").forEach((button) => renderPoseButton(button, robotId, robot));
  // 아이콘 옆 한 줄: 명령을 보낼 수 있는지, 관제 작업이 있으면 그 내용 (마우스를 올리지 않아도 보이게).
  const why = card.querySelector(".cmd-reason");
  let text;
  let level;
  if (view.readOnly || !view.controllerOnline || !robot.online) {
    text = `명령 잠김: ${reason}`;
    level = "warn";
  } else if (problem) {
    text = problem.text;
    level = "bad";
  } else if (!view.commandsArmed) {
    text = `명령 잠김: ${reason}`;
    level = "warn";
  } else if (isDriving(robotId)) {
    text = "직접 조종 중 (상세 화면)";
    level = "busy";
  } else if (runningRoute(robotId)) {
    text = routeText(runningRoute(robotId));
    level = "busy";
  } else if (active) {
    text = `작업 중: ${active.command} · ${TASK_TEXT[active.state] || active.state}`
      + (active.detail ? ` · ${active.detail}` : "");
    level = "busy";
  } else if (reason) {
    text = `명령 잠김: ${reason}`;
    level = "warn";
  } else {
    text = holding ? `명령 가능 · ${held.join(", ")} 보유 중` : "명령 가능";
    level = "ok";
  }
  const task = robotTask(robotId, UNKNOWN_TASK) || active;
  const msg = view.cardMsg.get(robotId);
  if (msg && msg.until > Date.now()) {
    text = msg.text;
    level = msg.bad ? "bad" : "ok";
  } else if (msg) {
    view.cardMsg.delete(robotId);
  }
  why.textContent = text;
  why.title = task ? `${text} (${task.task_id})` : text;
  card.querySelector(".cmd-head").dataset.level = level;
}

// 명령 결과는 누른 로봇 카드의 상태 줄에 MSG_MS 동안 보인다 (누른 곳에서 바로 보이게).
function showMessage(robotId, text, bad) {
  view.cardMsg.set(robotId, { text, bad, until: Date.now() + MSG_MS });
  render();
  setTimeout(render, MSG_MS + 50);
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

function sendStop(robotId, emergency) {
  return postJson(`/api/robots/${encodeURIComponent(robotId)}/stop`,
    { client_request_id: newRequestId(), emergency });
}

// 상단 '작업 명령 켜기/끄기' 버튼. 버튼 글은 누르면 할 일이고, 켜진 동안은 주황이다.
// 켜는 쪽만 확인 창을 띄운다 (끄는 것은 늘 안전한 쪽이라 바로).
function renderArmToggle() {
  const button = $("arm-toggle");
  button.disabled = !view.controllerOnline || view.readOnly;
  button.dataset.armed = String(view.commandsArmed);
  button.textContent = view.commandsArmed ? "작업 명령 끄기" : "작업 명령 켜기";
  button.title = view.readOnly ? "개발 화면 (읽기 전용): 실물 관제 화면(8080)에서 켜고 끈다"
    : view.commandsArmed
    ? "작업 명령 켜짐: 개별 이동(이동·구역·나가기·홈)을 보낼 수 있음. 누르면 끈다"
    : "작업 명령 꺼짐: 개별 이동(이동·구역·나가기·홈)이 막혀 있음. 누르면 켠다 (정지·비상정지는 꺼져 있어도 됨)";
}

async function toggleArm() {
  const armed = !view.commandsArmed;
  if (armed) {
    const domain = view.healthDomain ?? "?";
    const real = view.snapshot && view.snapshot.infra && view.snapshot.infra.mode === "real";
    const what = real ? "실물 로봇이 움직입니다" : "로봇에 명령이 나갑니다";
    if (!confirm(`${what} (도메인 ${domain}).\n작업 명령(개별 이동: 이동·구역·나가기·홈)을 켤까요?`)) return;
  } else {
    cancelPick();
  }
  const result = await postJson("/api/commands/arm", { client_request_id: newRequestId(), armed });
  if (!result.ok) {
    alert(`작업 명령 ${armed ? "켜기" : "끄기"} 실패 (${result.status}): ${errorText(result)}`);
    return;
  }
  // 다음 /api/health 를 기다리지 않고 바로 반영한다.
  view.commandsArmed = Boolean(result.data.armed);
  renderArmToggle();
  renderRawPanel();
  render();
}

// 전체 비상정지: 모든 로봇을 그 자리에 세우고 로봇팔을 모두 잠근다. 확인 창 없이 한꺼번에 보낸다.
async function stopAll() {
  // 백엔드가 팔 전부에 비상정지(soft_latch)를 먼저 내고, fleet_control 이 로봇 지정 없는 estop 으로 전 로봇을 세운다.
  const robots = Object.keys((view.snapshot && view.snapshot.robots) || {});
  cancelPick();
  const r = await postJson("/api/commands/estop", { client_request_id: newRequestId() });
  const arms = (r.data && r.data.arms) || null;
  const armText = !arms ? "" : arms.detail ? ` · 팔: ${arms.detail}` : ` · 팔 ${arms.latched.length}대 잠금`;
  const text = (r.ok ? "전체 비상정지(estop) 보냄" : `전체 비상정지 실패 (${r.status}): ${errorText(r)}`) + armText;
  if (robots.length === 0) alert(text);
  robots.forEach((robotId) => showMessage(robotId, text, !r.ok));
}

async function onCommand(robotId, cmd) {
  if (cmd === "stop" || cmd === "emergency_stop") {
    // 정지는 확인 창 없이 바로 보낸다 (늦으면 안 되는 명령). 그 로봇 지점 고르기는 접는다.
    if (view.pick && view.pick.robotId === robotId) cancelPick();
    const result = await sendStop(robotId, cmd === "emergency_stop");
    if (result.ok) {
      showMessage(robotId, `${cmd === "stop" ? "정지" : "비상정지"} 보냄`
        + (result.data.warning ? ` · ${result.data.warning}` : ""), false);
    } else {
      showMessage(robotId, `정지 실패 (${result.status}): ${errorText(result)}`, true);
    }
    return;
  }
  if (cmd === "initial_pose") {
    await sendInitialPose(robotId);
    return;
  }
  const points = await choosePoints(robotId, cmd);
  if (points === null) return;
  if (cmd === "route") {
    await sendRoute(robotId, points);
    return;
  }
  const result = await postJson("/api/tasks", {
    client_request_id: newRequestId(), robot_id: robotId, operation: cmd, points,
  });
  if (result.data && result.data.task_id) upsertTask(result.data);
  if (result.data && result.data.task) upsertTask(result.data.task);
  if (result.ok) {
    showMessage(robotId, `보냄: ${result.data.command} (${result.data.task_id})`, false);
  } else {
    showMessage(robotId, `${OP_TEXT[cmd]} 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

// 경로: 백엔드가 구간(이어지는 일반 지점은 이동 하나, 구역 지점은 하나씩)으로 나눠 차례로 보낸다.
// 첫 구간은 바로 보내고 결과를 돌려준다. 진행은 /api/health 의 routes 로 본다.
async function sendRoute(robotId, points) {
  const result = await postJson("/api/routes", {
    client_request_id: newRequestId(), robot_id: robotId, points,
  });
  const route = result.ok ? result.data : result.data && result.data.route;
  if (route) {
    view.routes = { ...view.routes, [robotId]: route };
  }
  if (result.ok) {
    const legs = route.legs.map((leg) => `${leg.operation}:${leg.points.join(",")}`).join(" → ");
    showMessage(robotId, `경로 보냄 (${route.legs.length}구간): ${legs}`, false);
  } else {
    showMessage(robotId, `경로 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

// 초기위치: 로봇이 그 자리에 있는지 묻고, 작업 노드가 AMCL 위치를 다시 잡게 한다.
// pose 가 없으면 홈: 화면의 홈 좌표는 확인 창에 보여 주기만 하고, 실제 좌표는 작업 노드가 순찰 설정에서 읽는다.
// pose {x, y, yaw[rad]} 가 있으면 지도에서 찍은 좌표 (detail.js 좌표 지정). 보냈으면 true.
async function sendInitialPose(robotId, pose = null) {
  let where;
  if (pose) {
    where = `(x ${pose.x.toFixed(2)}, y ${pose.y.toFixed(2)}, ${toDeg(pose.yaw)}°)`;
  } else {
    const home = view.layers && view.layers.homes && view.layers.homes[robotId];
    where = home
      ? `홈 ${home.name} (x ${Number(home.pose[0]).toFixed(2)}, y ${Number(home.pose[1]).toFixed(2)}, `
        + `${toDeg(Number(home.pose[2]) || 0)}°)`
      : "홈";
  }
  const zones = pose ? [] : forgottenZones(robotId);
  if (!confirm(`${robotId} 로봇이 ${where} 에 있나요?\n`
      + "AMCL 위치를 그 자리로 다시 잡습니다. 로봇은 움직이지 않습니다."
      + (zones.length ? `\n\n다시 켜져 잊은 구역 ${zones.join(", ")} 점유도 풉니다.\n`
        + `현장에서 구역 ${zones.join(", ")} 이(가) 비어 있는지 확인했나요? `
        + "풀면 대기 중인 로봇이 바로 들어올 수 있습니다." : ""))) return false;
  const body = { client_request_id: newRequestId() };
  if (pose) body.pose = pose;
  if (zones.length) body.release_zones = zones;
  const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/initial_pose`, body);
  if (result.ok) {
    const d = result.data;
    showMessage(robotId, `초기위치 보냄: ${d.point} (${Number(d.x).toFixed(2)}, `
      + `${Number(d.y).toFixed(2)}) · 지도에서 로봇 위치를 확인하세요`
      + ((d.zones_pending || []).length ? ` · 구역 ${d.zones_pending.join(", ")} 해제 확인 중` : "")
      + Object.entries(d.zones_skipped || {})
        .map(([zone, reason]) => ` · 구역 ${zone} 유지 (${reason}, 강제 해제 사용)`).join(""), false);
    return true;
  }
  showMessage(robotId, `초기위치 거절 (${result.status}): ${errorText(result)}`, true);
  return false;
}

// 고를 수 있는 지점: 이름 → [x, y, yaw]. 지점 목록(/api/map/layers)이 없으면 null.
function pointChoices(robotId, cmd) {
  const layers = view.layers;
  if (!layers) return null;
  const choices = new Map();
  if (cmd === "goto") {
    for (const [name, pose] of Object.entries(layers.points || {})) choices.set(name, pose);
    const home = layers.homes && layers.homes[robotId];
    if (home) choices.set(home.name, home.pose);
    // 관제 웨이포인트: 관제가 좌표를 실어 보낸다 (goto·경로만, waypoints.js)
    for (const [name, pose] of waypointPoses()) choices.set(name, pose);
  } else if (cmd === "zone") {
    for (const zone of Object.values(layers.zones || {})) {
      for (const [name, pose] of Object.entries(zone.points || {})) choices.set(name, pose);
    }
  } else if (cmd === "route") {
    // 경로는 이동·구역 지점을 모두 고를 수 있다 (구역 출구는 빼고, 순찰 노드가 알아서 지난다).
    for (const [name, pose] of pointChoices(robotId, "goto")) choices.set(name, pose);
    for (const [name, pose] of pointChoices(robotId, "zone")) choices.set(name, pose);
  }
  return choices;
}

// 지점 고르기 + 확인. 누른 로봇 카드 안의 막대에서 하고, 지점은 지도를 누르거나 이름 버튼으로 고른다.
// 창(dialog)을 쓰지 않는 것은 고르는 동안 지도를 보고 눌러야 하기 때문이다.
// 고른 지점 목록을 돌려주고, 취소하면 null.
function choosePoints(robotId, cmd) {
  closeBars();
  const needsPoints = cmd === "goto" || cmd === "zone" || cmd === "route";
  const choices = needsPoints ? pointChoices(robotId, cmd) : null;
  const box = $("cmd-pick");
  const pick = { robotId, cmd, choices, route: [], input: null };
  // 경로는 이름 버튼 대신 고른 순서 칩을 보인다 (지점 목록이 없으면 직접 적는 칸).
  const chipMode = cmd === "route" && choices !== null;
  pick.names = () => (pick.input
    ? pick.input.value.toUpperCase().split(/[\s,]+/).filter(Boolean) : pick.route);
  pick.update = () => {
    const names = pick.names();
    const route = $("cmd-route");
    // 경로는 칩이 순서를 보이므로 머리에는 개수와 구간 수만 (구간 내용은 마우스 글·칩 아래 줄).
    route.textContent = chipMode
      ? (names.length ? `${names.length}곳` : "지점 선택")
      : MULTI_POINT.has(cmd) ? (names.length ? names.join(" → ") : "지점 선택")
      : cmd === "zone" ? (names[0] || "구역 지점 선택")
      : cmd === "home" ? "홈으로 복귀" : "구역 출구로 나가기";
    route.title = chipMode && names.length ? routeLegs(names)
      .map((leg) => `${OP_TEXT[leg.operation]} ${leg.points.join(",")}`).join(" → ") : route.textContent;
    route.dataset.empty = needsPoints && names.length === 0 ? "1" : "";
    if (chipMode) renderRouteChips(box, pick);
    // 고른 지점 버튼은 채우고, 이동은 순번을 붙인다.
    if (!chipMode) box.querySelectorAll("button").forEach((button) => {
      // 경로는 같은 지점을 두 번 고를 수 있으므로 순번을 모두 적는다 (예: 1·3).
      const orders = names.map((name, i) => (name === button.textContent ? i + 1 : 0)).filter(Boolean);
      button.classList.toggle("chosen", orders.length > 0);
      button.dataset.order = orders.length && MULTI_POINT.has(cmd) ? orders.join("·") : "";
    });
    $("cmd-ok").disabled = needsPoints && names.length === 0;
    drawMap();
    drawDetailMap();
  };
  pick.add = (name) => {
    if (cmd === "zone") pick.route.length = 0;
    pick.route.push(name);
    pick.update();
  };

  // 막대가 카드 머리(로봇 이름)를 덮으므로 제목에 로봇 이름을 다시 쓴다.
  $("cmd-title").textContent = `${robotId} · ${OP_TEXT[cmd]}`;
  box.replaceChildren();
  $("cmd-clear").hidden = !MULTI_POINT.has(cmd);
  $("cmd-undo").hidden = !chipMode;
  box.classList.toggle("route-mode", chipMode);
  $("cmd-group").hidden = !chipMode;
  renderGroupSelect();
  $("cmd-warn").textContent = view.snapshot && view.snapshot.infra
    && view.snapshot.infra.mode === "real" ? "⚠ 실물 로봇이 움직입니다. 주변을 확인하세요." : "";
  if (needsPoints && choices === null) {
    // 지점 목록이 없으면 직접 적는다. 로봇·작업 노드가 다시 검사한다.
    pick.input = document.createElement("input");
    pick.input.placeholder = cmd === "goto" ? "P1, P2" : cmd === "route" ? "P1, ZA1, P3" : "ZA";
    pick.input.addEventListener("input", pick.update);
    box.appendChild(pick.input);
  } else if (needsPoints && !chipMode) {
    for (const name of choices.keys()) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = name;
      button.addEventListener("click", () => pick.add(name));
      box.appendChild(button);
    }
  }

  view.pick = pick;
  barHost(robotId).appendChild($("pick-bar"));
  $("pick-bar").hidden = false;
  $("map").classList.toggle("picking", Boolean(choices));
  render();
  pick.update();
  if (pick.input) pick.input.focus();
  return new Promise((resolve) => { pick.resolve = resolve; });
}

function finishPick(ok) {
  const pick = view.pick;
  if (!pick) return;
  view.pick = null;
  $("pick-bar").hidden = true;
  $("map").classList.remove("picking");
  pick.resolve(ok ? pick.names() : null);
  render();
  drawMap();
}

function cancelPick() {
  finishPick(false);
}

// 상태줄 아래·카드 위 띠(지점 고르기·상차 확인·좌표 지정)를 모두 접는다. 새 띠·확인 창을 열기 전에 부른다.
// 상세 화면에서는 셋이 같은 자리(#detail-bar-host)를 써서 하나라도 빠지면 띠가 겹친다.
function closeBars() {
  cancelPick();
  closeLoad();
  closeRecover();
  closePosePick();
}

// 지도에서 누른 곳에 가장 가까운 고를 수 있는 지점 (PICK_HIT_PX 안). 없으면 null.
function pickAt(event) {
  const pick = view.pick;
  if (!pick || !pick.choices || !view.map || !view.mapScale) return null;
  const rect = $("map").getBoundingClientRect();
  const x = (event.clientX - rect.left) / view.mapScale;
  const y = (event.clientY - rect.top) / view.mapScale;
  return nearestChoice(pick.choices, x, y, PICK_HIT_PX / view.mapScale);
}

function setupPick() {
  const canvas = $("map");
  // 지점을 고르는 중이면 지점을, 아니면(또는 지점이 아니면) 로봇을 누른 것으로 본다.
  canvas.addEventListener("click", (event) => {
    const name = pickAt(event);
    if (name) {
      view.pick.add(name);
      return;
    }
    const robotId = robotAt(event);
    if (robotId) focusCard(robotId);
  });
  canvas.addEventListener("mousemove", (event) => {
    canvas.style.cursor = pickAt(event) || robotAt(event) ? "pointer" : "";
  });
  $("cmd-ok").addEventListener("click", () => finishPick(true));
  $("cmd-cancel").addEventListener("click", cancelPick);
  $("cmd-undo").addEventListener("click", () => {
    if (!view.pick) return;
    view.pick.route.pop();
    view.pick.update();
  });
  $("cmd-clear").addEventListener("click", () => {
    if (!view.pick) return;
    view.pick.route.length = 0;
    view.pick.update();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view.pick) cancelPick();
  });
  $("stop-all").addEventListener("click", stopAll);
  $("arm-toggle").addEventListener("click", toggleArm);
}
