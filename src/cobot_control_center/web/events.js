// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 경고 띠·이벤트 로그. 핑키와 로봇팔을 함께 보여 준다 (보통 관제처럼 알람은 한 목록, 기록은 한 타임라인).
// 핑키: 경고는 스냅샷 alerts, 기록은 /api/events·스냅샷 events (필드 robot).
// 팔: 활성 알람은 /api/arms 의 arms[].alarms, 기록은 /api/arms/events (필드 arm, arms.js 가 armsView.log 에 받음).
// 두 기록은 번호 체계가 달라서 화면에서 시각 순으로 섞는다.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const EVENTS_MAX = 500;        // 화면에 들고 있을 이벤트 수 (백엔드 events_max 와 같게)

// ---------- 경고·이벤트 ----------

function robotIndex(robotId) {
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  return robots.indexOf(robotId);
}

// 핑키 경고를 받아 두고 경고 띠를 다시 그린다 (팔 알람은 arms.js 가 받을 때마다 renderAlertStrip 을 부름).
function renderAlerts(alerts, fresh) {
  // 관제 노드가 끊기면 마지막 경고가 남아 있어 헷갈리므로 숨긴다 (끊김은 상단 점이 알려 준다).
  view.alerts = fresh ? alerts || [] : [];
  renderAlertStrip();
}

// 팔 활성 알람 → 경고 띠 줄. 명령 노드가 끊기면(STALE) 숨긴다 (카드가 미연결로 보임).
function armAlertItems() {
  const data = armsView.data;
  if (!armsView.ok || !data || !data.controller_online) return [];
  const items = [];
  for (const arm of data.arms || []) {
    const where = arm.site && arm.site.station ? ` (${arm.site.station})` : "";
    for (const alarm of arm.alarms || []) {
      items.push({ who: `${arm.arm_id}${where}`, level: alarm.level, text: alarm.text, title: alarm.code });
    }
  }
  return items;
}

// 경고 띠 = 핑키 경고(fleet_status) + 팔 알람(arms.js) + 네트워크·PC 경고(network.js 가 /api/network 에서 받음).
// 네트워크·PC 경고는 관제 노드와 따로 와서 관제 노드가 끊겨도 남는다.
function renderAlertStrip() {
  const box = $("alerts");
  const list = [
    ...(view.alerts || []).map((a) => ({ who: a.robot, level: a.level, text: a.text, title: a.code })),
    ...armAlertItems(),
    ...(view.netAlerts || []).map((a) => ({ who: a.robot, level: a.level, text: a.text, title: a.code })),
  ];
  // 빨강이 위 (같은 수준이면 원래 순서: 핑키 먼저)
  list.sort((a, b) => (a.level === "bad" ? 0 : 1) - (b.level === "bad" ? 0 : 1));
  box.hidden = list.length === 0;
  box.replaceChildren();
  for (const alert of list) {
    const item = document.createElement("li");
    item.dataset.level = alert.level;
    if (alert.title) item.title = alert.title;
    if (alert.who) {
      const who = document.createElement("strong");
      who.textContent = alert.who;
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

// 이벤트 칸 '보기' 고르기 값: "" 전체, "@robots" 로봇 전체, "@arms" 팔 전체, "@zones" 구역,
// "robot:pinky1" 로봇 하나, "arm:omx_1" 팔 하나.
function addOption(parent, value, text) {
  parent.appendChild(makeOption(value, text));
}

// 로봇팔 명령 노드가 알려 준 팔 목록 (arms.js 가 1 s 마다 받음)
function armList() {
  return armsView.data ? armsView.data.arms || [] : [];
}

function optionGroup(select, label) {
  let group = [...select.querySelectorAll("optgroup")].find((g) => g.label === label);
  if (!group) {
    group = document.createElement("optgroup");
    group.label = label;
    select.appendChild(group);
  }
  return group;
}

// 이벤트 칸(로봇·팔)과 작업 목록(로봇만)의 고르기에 새로 보인 로봇·팔을 넣는다.
function renderEventFilter() {
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  const arms = armList();
  const events = $("event-robot");
  const have = new Set([...events.querySelectorAll("option")].map((o) => o.value));
  const robotGroup = optionGroup(events, "로봇");
  for (const robotId of robots) {
    if (!have.has(`robot:${robotId}`)) addOption(robotGroup, `robot:${robotId}`, robotId);
  }
  if (arms.length) {
    const armGroup = optionGroup(events, "로봇팔");
    for (const arm of arms) {
      const where = arm.site && arm.site.station ? ` (${arm.site.station})` : "";
      if (!have.has(`arm:${arm.arm_id}`)) addOption(armGroup, `arm:${arm.arm_id}`, `${arm.arm_id}${where}`);
    }
  }
  const tasks = $("task-robot");
  const haveTask = new Set([...tasks.options].map((o) => o.value));
  for (const robotId of robots) {
    if (!haveTask.has(robotId)) addOption(tasks, robotId, robotId);
  }
}

function eventMatches(event, filter) {
  if (!filter) return true;
  if (filter === "@robots") return Boolean(event.robot);
  if (filter === "@arms") return Boolean(event.arm);
  if (filter === "@zones") return !event.robot && !event.arm;
  if (filter.startsWith("robot:")) return event.robot === filter.slice(6);
  if (filter.startsWith("arm:")) return event.arm === filter.slice(4);
  return true;
}

function armStation(armId) {
  const arm = armList().find((a) => a.arm_id === armId);
  return arm && arm.site ? arm.site.station : "";
}

function renderEvents() {
  const box = $("events");
  const filter = $("event-robot").value;
  // 핑키·팔 기록을 시각 순으로 섞는다 (새것이 위). 같은 시각이면 들어온 순서를 지킨다.
  const shown = [...view.events, ...armsView.log]
    .filter((e) => eventMatches(e, filter))
    .map((e, i) => ({ e, i }))
    .sort((a, b) => (b.e.time - a.e.time) || (b.i - a.i))
    .slice(0, EVENTS_MAX)
    .map((x) => x.e);
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
    if (event.arm) {
      item.dataset.source = "arm";
      who.textContent = event.arm;
      const station = armStation(event.arm);
      if (station) {
        const where = document.createElement("small");
        where.className = "where";
        where.textContent = station;
        who.appendChild(where);
      }
    } else {
      who.textContent = event.robot || "구역";
    }
    const index = event.robot ? robotIndex(event.robot) : -1;
    if (index >= 0) who.style.setProperty("--robot-color", `var(${robotColorVar(index)})`);
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = event.text;
    item.append(time, who, text);
    box.appendChild(item);
  }
}
