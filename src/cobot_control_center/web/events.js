// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 경고 띠·이벤트 로그.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const EVENTS_MAX = 500;        // 화면에 들고 있을 이벤트 수 (백엔드 events_max 와 같게)

// ---------- 경고·이벤트 ----------

function robotIndex(robotId) {
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  return robots.indexOf(robotId);
}

function renderAlerts(alerts, fresh) {
  const box = $("alerts");
  // 관제 노드가 끊기면 마지막 경고가 남아 있어 헷갈리므로 숨긴다 (끊김은 상단 점이 알려 준다).
  const list = fresh ? alerts || [] : [];
  box.hidden = list.length === 0;
  box.replaceChildren();
  for (const alert of list) {
    const item = document.createElement("li");
    item.dataset.level = alert.level;
    if (alert.robot) {
      const who = document.createElement("strong");
      who.textContent = alert.robot;
      item.appendChild(who);
    }
    item.appendChild(document.createTextNode(alert.text));
    box.appendChild(item);
  }
}

async function loadEvents() {
  try {
    const res = await fetch(`/api/events?limit=${EVENTS_MAX}`);
    if (!res.ok) return;
    view.events = [];
    view.lastEventId = 0;
    addEvents(await res.json());
  } catch (err) {
    // 다음 연결 때 다시 읽는다.
  }
}

function addEvents(events) {
  let added = false;
  for (const event of events || []) {
    if (typeof event.id !== "number" || event.id <= view.lastEventId) continue;
    view.events.push(event);
    view.lastEventId = event.id;
    added = true;
  }
  if (view.events.length > EVENTS_MAX) view.events.splice(0, view.events.length - EVENTS_MAX);
  if (added) renderEvents();
}

// 이벤트·작업 목록의 로봇 고르기에 새로 보인 로봇을 넣는다.
function renderEventFilter() {
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  for (const select of [$("event-robot"), $("task-robot")]) {
    const have = new Set([...select.options].map((o) => o.value));
    for (const robotId of robots) {
      if (have.has(robotId)) continue;
      const option = document.createElement("option");
      option.value = robotId;
      option.textContent = robotId;
      select.appendChild(option);
    }
  }
}

function renderEvents() {
  const box = $("events");
  const filter = $("event-robot").value;
  const shown = view.events.filter((e) => !filter || e.robot === filter).slice().reverse();
  box.replaceChildren();
  if (shown.length === 0) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "이벤트 없음";
    box.appendChild(empty);
    return;
  }
  for (const event of shown) {
    const item = document.createElement("li");
    item.dataset.level = event.level;
    const time = document.createElement("time");
    time.textContent = formatTime(event.time);
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = event.robot || "구역";
    const index = event.robot ? robotIndex(event.robot) : -1;
    if (index >= 0) who.style.setProperty("--robot-color", `var(${robotColorVar(index)})`);
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = event.text;
    item.append(time, who, text);
    box.appendChild(item);
  }
}
