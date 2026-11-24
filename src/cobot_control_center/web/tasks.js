// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 이동 작업 목록 (관제가 보낸 주행 기록: 개별 이동과 주문 안의 주행).
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

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


function formatDuration(sec) {
  if (!(sec >= 0)) return "";
  const s = Math.round(sec);
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분${s % 60 ? ` ${s % 60}초` : ""}`;
}

// goto:P3,P7 → "이동 P3→P7" (카드 버튼과 같은 말)
function taskCommandText(task) {
  const op = OP_TEXT[task.operation] || task.operation || "";
  const points = (task.points || []).join("→");
  return op ? `${op}${points ? ` ${points}` : ""}` : task.command;
}

const TASK_FINAL_TIMED = new Set(["SUCCEEDED", "FAILED", "STOPPED"]);

// 경로 구간 작업: 백엔드가 작업 ID 를 '<route_id>-<구간 번호>' 로 만든다 (route_utils). 아니면 null.
const ROUTE_TASK_ID = /^(route_[0-9a-f]+)-(\d+)$/;

function rememberRoutes(routes) {
  for (const route of routes) {
    if (route && route.route_id) view.routeTotals.set(route.route_id, route.legs.length);
  }
}

// 처음 열 때 최근 경로(끝난 것 포함)의 구간 수를 받아 둔다. 백엔드를 다시 켜면 잊으므로 그때는 'n' 만.
async function loadRoutes() {
  try {
    const res = await fetch("/api/routes");
    if (!res.ok) return;
    const data = await res.json();
    rememberRoutes([...Object.values(data.robots || {}), ...(data.recent || [])]);
    renderTasks();
  } catch (err) {
    // 읽기 전용 백엔드(503)·끊김: 꼬리표를 구간 번호만으로 단다
  }
}

// "경로 2/3" (구간 수를 모르면 "경로 2")
function taskRouteTag(task) {
  const match = ROUTE_TASK_ID.exec(task.task_id || "");
  if (!match) return "";
  const total = view.routeTotals.get(match[1]);
  return `경로 ${Number(match[2]) + 1}${total ? `/${total}` : ""}`;
}

function renderTasks() {
  // 상세 화면의 요약·타임라인도 작업 목록으로 그린다.
  renderDetail();
  const list = $("tasks");
  const filter = $("task-robot").value;
  const all = [...view.tasks.values()];
  // 결과 모름 → 진행 중 → 나머지(최신 먼저). 앞의 둘은 놓치지 않게 늘 위에 둔다.
  const rank = (t) => (t.state === "UNKNOWN" ? 0 : ACTIVE_TASK.has(t.state) ? 1 : 2);
  const tasks = all.filter((t) => !filter || t.robot_id === filter)
    .sort((a, b) => rank(a) - rank(b) || b.created_at - a.created_at);
  const unknown = all.filter((t) => t.state === "UNKNOWN").length;
  const running = all.filter((t) => ACTIVE_TASK.has(t.state)).length;
  const meta = $("tasks-meta");
  meta.textContent = [running ? `진행 ${running}` : "", unknown ? `결과 모름 ${unknown}` : ""]
    .filter(Boolean).join(" · ");
  meta.dataset.bad = unknown ? "1" : "";
  if (tasks.length === 0) {
    list.innerHTML = '<li class="muted">이동 작업 없음</li>';
    return;
  }
  list.replaceChildren(...tasks.slice(0, TASK_LIST_MAX).map((task) => {
    const el = $("task-template").content.firstElementChild.cloneNode(true);
    el.dataset.state = task.state;
    el.dataset.pin = rank(task) < 2 ? "1" : "";
    el.querySelector(".task-time").textContent = (task.created_at ? formatTime(task.created_at) : "");
    const robot = el.querySelector(".task-robot");
    robot.textContent = task.robot_id;
    const index = robotIndex(task.robot_id);
    if (index >= 0) robot.style.setProperty("--robot-color", `var(${robotColorVar(index)})`);
    el.querySelector(".task-command").textContent = taskCommandText(task);
    const routeTag = el.querySelector(".task-route");
    routeTag.textContent = taskRouteTag(task);
    routeTag.hidden = !routeTag.textContent;
    const state = el.querySelector(".task-state");
    state.textContent = TASK_TEXT[task.state] || task.state;
    state.style.setProperty("--state-color", `var(--${TASK_GROUP[task.state] || "idle"})`);
    // 끝난 작업은 걸린 시간, 실패·중단·거절·진행은 이유/현재 지점
    const took = TASK_FINAL_TIMED.has(task.state)
      ? formatDuration(task.updated_at - task.created_at) : "";
    const detail = task.state === "SUCCEEDED" ? took
      : [task.detail, took].filter(Boolean).join(" · ");
    el.querySelector(".task-detail").textContent = detail;
    el.title = `${task.task_id} · ${task.spec} · ${task.command} · 보냄 ${formatTime(task.created_at)}`
      + (task.detail ? `\n${task.detail}` : "");
    const resolve = el.querySelector(".resolve-btn");
    resolve.hidden = task.state !== "UNKNOWN";
    // 멈춘 주문이면 주문 복구, 보류 중이면 제어권 복구가 결과 모름까지 함께 정리한다 (release.js currentProblem)
    const problem = currentProblem(task.robot_id, true);
    const via = problem && (problem.kind === "order" || problem.kind === "release") ? problem : null;
    resolve.textContent = !via ? "현장 확인 후 해제"
      : via.kind === "order" ? "주문 복구" : "현장 확인 후 복구";
    resolve.addEventListener("click", () => (via ? via.open() : openResolve(task)));
    return el;
  }));
}

// ---------- 결과 모름 해제 ----------
// 작업 목록의 해제 버튼이나 카드의 빨간 '결과 모름' 줄을 누르면 확인 창이 한 번 뜬다
// 메모 입력은 선택이다. 로봇 해제 응답을 확인한 뒤 실패로 기록된다 (기록은 지우지 않는다).

async function openResolve(task) {
  if (!task) return;
  closeBars();
  if (!confirm([`${task.robot_id} 의 ${task.command} 결과를 모릅니다.`,
    "현장에서 로봇이 멈춰 있나요? 확인하면 실패로 기록하고 다시 명령을 보낼 수 있습니다."].join("\n"))) {
    return;
  }
  const result = await postJson(`/api/tasks/${encodeURIComponent(task.task_id)}/resolve`,
    { client_request_id: newRequestId(), result: "FAILED" });
  if (result.ok) {
    upsertTask(result.data);
    renderTasks();
    showMessage(task.robot_id, `해제 요청 접수: ${task.command} · 로봇 응답 확인 후 실패로 기록`, false);
  } else {
    showMessage(task.robot_id, `해제 실패 (${result.status}): ${errorText(result)}`, true);
  }
}
