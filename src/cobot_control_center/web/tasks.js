// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 작업 목록 (관제가 보낸 명령 기록).
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
    list.innerHTML = '<li class="muted">작업 없음</li>';
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
    resolve.addEventListener("click", () => openResolve(task));
    return el;
  }));
}

// ---------- 결과 모름 해제 ----------
// 작업 목록의 해제 버튼이나 카드의 빨간 '결과 모름' 줄을 누르면 그 로봇 카드 위에 확인 막대를 띄운다.
// 현장 확인 내용을 적어 해제하면 실패로 기록된다 (기록은 지우지 않는다).

const RESOLVE_NOTE = "현장에서 정지 확인";

function openResolve(task) {
  const host = barHost(task.robot_id);
  if (!host) return;
  cancelPick();
  closeRelease();
  closeLoad();
  view.resolving = task;
  $("resolve-title").textContent = `${task.robot_id} · 결과 모름 해제`;
  $("resolve-what").textContent = task.command;
  $("resolve-what").title = `${task.command} (${task.task_id})`;
  $("resolve-note").value = RESOLVE_NOTE;
  host.appendChild($("resolve-bar"));
  $("resolve-bar").hidden = false;
  if (view.detailRobot !== task.robot_id) focusCard(task.robot_id);
  $("resolve-note").select();
}

function closeResolve() {
  view.resolving = null;
  $("resolve-bar").hidden = true;
}

async function resolveTask() {
  const task = view.resolving;
  if (!task) return;
  const note = $("resolve-note").value.trim() || RESOLVE_NOTE;
  $("resolve-ok").disabled = true;
  const result = await postJson(`/api/tasks/${encodeURIComponent(task.task_id)}/resolve`,
    { client_request_id: newRequestId(), result: "FAILED", note });
  $("resolve-ok").disabled = false;
  closeResolve();
  if (result.ok) {
    upsertTask(result.data);
    renderTasks();
    showMessage(task.robot_id, `해제함: ${task.command} (실패로 기록)`, false);
  } else {
    showMessage(task.robot_id, `해제 실패 (${result.status}): ${errorText(result)}`, true);
  }
}

function setupResolve() {
  $("resolve-ok").addEventListener("click", resolveTask);
  $("resolve-cancel").addEventListener("click", closeResolve);
  $("resolve-note").addEventListener("keydown", (event) => {
    if (event.key === "Enter") resolveTask();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view.resolving) closeResolve();
  });
}
