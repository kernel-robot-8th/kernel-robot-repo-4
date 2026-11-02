// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 로봇 카드·위치 복사·위험구역 패널.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const BATTERY_LOW = 30;        // [%] 이하 주황
const BATTERY_CRITICAL = 15;   // [%] 이하 빨강

// 순찰 노드 state → 색 묶음
const STATE_GROUP = {
  MOVING: "active", STARTING: "active", RETURNING: "active",
  LEAVING_ZONE: "active", RETREATING: "active",
  QUEUEING: "warn", WAITING_ZONE: "warn", IDLE_WAIT: "warn", RETRY: "warn",
  ARRIVED: "good", HOLDING_ZONE: "good", DONE: "good",
  FAILED: "bad", STOPPED: "bad",
  IDLE: "idle",
};
// 카드 상태 배지에 쓰는 한글 이름. 원래 코드(MOVING 등)는 배지 옆에 작게 남겨 이벤트 로그와 맞춰 본다.
const STATE_TEXT = {
  MOVING: "이동 중", STARTING: "출발", RETURNING: "홈 복귀", LEAVING_ZONE: "구역 나가는 중",
  RETREATING: "출구로 후퇴", QUEUEING: "대기열", WAITING_ZONE: "구역 대기", IDLE_WAIT: "대기",
  RETRY: "재시도", ARRIVED: "도착", HOLDING_ZONE: "구역 점유", DONE: "완료",
  FAILED: "실패", STOPPED: "정지됨", IDLE: "유휴",
};

// ---------- 카드 ----------

function ensureCard(robotId, index) {
  if (view.cards.has(robotId)) return view.cards.get(robotId);
  const card = $("card-template").content.firstElementChild.cloneNode(true);
  card.style.setProperty("--robot-color", `var(${robotColorVar(index)})`);
  card.querySelector(".name").textContent = robotId;
  setupTeach(card);
  setupCommands(card, robotId);
  $("cards").appendChild(card);
  view.cards.set(robotId, card);
  return card;
}

function formatShortAge(sec) {
  if (sec === null || sec === undefined) return "—";
  if (sec < 10) return `${sec.toFixed(1)}s`;
  if (sec < 60) return `${Math.round(sec)}s`;
  return `${Math.floor(sec / 60)}m`;
}

function formatAge(sec) {
  if (sec === null || sec === undefined) return "-";
  if (sec < 1) return "방금";
  if (sec < 60) return `${Math.round(sec)}초 전`;
  return `${Math.floor(sec / 60)}분 전`;
}

function renderCard(robotId, robot, index) {
  const card = ensureCard(robotId, index);
  const status = robot.never_seen ? "never" : robot.online ? "online" : "offline";
  card.classList.toggle("offline", status !== "online");

  const badge = card.querySelector(".badge");
  badge.dataset.state = status;
  badge.textContent = { online: "연결", offline: "끊김", never: "미수신" }[status];

  const state = card.querySelector(".state");
  state.textContent = STATE_TEXT[robot.state] || robot.state || "상태 없음";
  card.querySelector(".state-code").textContent = STATE_TEXT[robot.state] ? robot.state : "";
  const group = STATE_GROUP[robot.state] || "idle";
  state.style.setProperty("--state-color", `var(--${group})`);

  const parts = [];
  if (robot.detail) parts.push(robot.detail);
  if (robot.waypoint !== null && robot.waypoint !== undefined && robot.waypoint >= 0) {
    parts.push(`#${robot.waypoint}`);
  }
  const detail = card.querySelector(".detail");
  detail.textContent = parts.join(" · ");
  detail.title = detail.textContent;

  // 이름 옆 배터리: 아이콘 안이 잔량만큼 차고, 아이콘·숫자 색이 함께 바뀐다.
  const battery = card.querySelector(".battery");
  const fill = card.querySelector(".battery-fill");
  const text = card.querySelector(".battery-text");
  const pct = robot.battery_percent;
  if (pct === null || pct === undefined) {
    fill.style.width = "0";
    text.textContent = "—";
    battery.dataset.level = "none";
  } else {
    const clamped = Math.max(0, Math.min(100, pct));
    fill.style.width = `${clamped}%`;
    battery.dataset.level = clamped <= BATTERY_CRITICAL ? "critical"
      : clamped <= BATTERY_LOW ? "low" : "ok";
    text.textContent = `${Math.round(clamped)}%`;
  }

  const meta = [];
  if (robot.pose) {
    const deg = (robot.pose.yaw * 180 / Math.PI).toFixed(0);
    meta.push(`(${robot.pose.x.toFixed(2)}, ${robot.pose.y.toFixed(2)}) m · ${deg}°`);
  }
  meta.push(`수신 ${formatAge(robot.last_seen_age)}`);
  card.querySelector(".meta").textContent = meta.join(" · ");
  // 토픽별 수신 시각 줄은 화면에서 잠시 뺐다 (index.html 주석 참고).
  // const ages = robot.topic_age || {};
  // card.querySelector(".topics").textContent =
  //   `위치 ${formatShortAge(ages.pose)} · 배터리 ${formatShortAge(ages.battery)} · 상태 ${formatShortAge(ages.status)}`;
  renderTeach(card, robotId, robot);
  renderCommands(card, robotId, robot);
}

// ---------- 위치 복사 (웨이포인트 티칭) ----------
// 로봇을 사람이 세운 뒤 버튼을 누르면 지금 위치를 [x, y, yaw] 로 클립보드에 넣는다
// (pinkyN.yaml points 의 값 형식). 서버에 저장하거나 로봇에 보내지 않는다.

const COPIED_MS = 2000; // '복사됨' 표시 시간 [ms]

function teachLine(robot) {
  const p = robot.pose;
  return `[${p.x.toFixed(3)}, ${p.y.toFixed(3)}, ${p.yaw.toFixed(2)}]`;
}

function setupTeach(card) {
  card.querySelector(".teach-btn").addEventListener("click", () => copyTeach(card));
}

const TEACH_TITLE = "지금 위치 [x, y, yaw] 를 클립보드에 넣는다 (파일은 고치지 않음)";

// 경고(이동 중·불확실성 큼 등)는 화면에 띄우지 않고 버튼에 마우스를 올리면 보인다. 복사는 막지 않는다.
function renderTeach(card, robotId, robot) {
  const warnings = (robot.teach && robot.teach.warnings) || [];
  const button = card.querySelector(".teach-btn");
  button.title = warnings.length ? `${TEACH_TITLE}\n주의: ${warnings.join(", ")}` : TEACH_TITLE;
  button.disabled = !robot.pose;
}

async function copyTeach(card) {
  const robotId = card.querySelector(".name").textContent;
  const robot = view.snapshot && view.snapshot.robots ? view.snapshot.robots[robotId] : null;
  if (!robot || !robot.pose) return;
  const text = teachLine(robot);
  const button = card.querySelector(".teach-btn");
  const line = card.querySelector(".teach-line");
  try {
    await navigator.clipboard.writeText(text);
    line.hidden = true;
    button.textContent = "복사됨 ✓";
    setTimeout(() => { button.textContent = "위치 복사"; }, COPIED_MS);
  } catch (err) {
    // 클립보드를 못 쓰는 환경(http://localhost 가 아닌 주소 등): 줄을 보여 주고 선택해 둔다.
    line.textContent = text;
    line.hidden = false;
    const range = document.createRange();
    range.selectNodeContents(line);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    button.textContent = "Ctrl+C 로 복사";
    setTimeout(() => { button.textContent = "위치 복사"; }, COPIED_MS);
  }
}

// ---------- 구역 ----------

function renderZones(zones) {
  const box = $("zones");
  const names = Object.keys(zones || {}).sort();
  if (names.length === 0) return;
  box.replaceChildren();
  for (const name of names) {
    const value = zones[name];
    const el = document.createElement("div");
    el.className = "zone";
    const title = document.createElement("strong");
    title.textContent = name;
    const label = document.createElement("span");
    if (value.startsWith("occupied_by:")) {
      el.classList.add("occupied");
      label.textContent = value.slice("occupied_by:".length);
    } else {
      label.textContent = value === "free" ? "비어 있음" : value;
    }
    el.append(title, label);
    box.appendChild(el);
  }
}
