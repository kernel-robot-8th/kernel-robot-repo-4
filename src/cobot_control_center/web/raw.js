// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 개발용 수동 명령 패널: 적은 문자열을 /pinkyN/patrol_cmd 에 그대로 한 번 보낸다.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const RAW_LOG_MAX = 8;   // 패널에 남기는 최근 수동 명령 수

// ---------- 수동 명령 ----------
// task_manager_node 의 allow_raw_cmd 가 켜져 있을 때만 보인다 (/api/health 의 raw_cmd_enabled).
// 보낸 명령은 작업 목록에 남지 않고 작업 노드의 사건 기록에만 남는다. 그래서 이 화면에서 보낸 것을 아래에 보여 준다.

function renderRawPanel() {
  $("raw-panel").hidden = !view.rawEnabled;
  if (!view.rawEnabled) return;
  const select = $("raw-robot");
  const robots = view.snapshot ? Object.keys(view.snapshot.robots || {}) : [];
  const have = new Set([...select.options].map((o) => o.value));
  for (const robotId of robots) {
    if (have.has(robotId)) continue;
    const option = document.createElement("option");
    option.value = robotId;
    option.textContent = robotId;
    select.appendChild(option);
  }
}

// 로그 한 줄. parts 는 [글, 꾸밈 class] 목록이다 (textContent 로만 넣는다).
// 보낸 줄은 토픽 이름(/pinkyN/...)이 어느 로봇인지 알려 주므로 로봇 칸을 따로 두지 않는다.
function addRawLog(parts, bad, title) {
  const item = document.createElement("li");
  item.dataset.bad = bad ? "1" : "";
  if (title) item.title = title;
  const time = document.createElement("time");
  time.textContent = formatTime();
  item.appendChild(time);
  for (const [text, cls] of parts) {
    const el = document.createElement(cls === "text" ? "span" : "code");
    el.className = `raw-${cls}`;
    el.textContent = text;
    item.appendChild(el);
  }
  const log = $("raw-log");
  log.prepend(item);
  while (log.children.length > RAW_LOG_MAX) log.lastElementChild.remove();
}

// 실제로 나간 메시지 그대로: 토픽 · 타입 · {data: "..."} (값은 작업 노드가 돌려준 것).
// 예전 작업 노드는 topic·msg_type 을 돌려주지 않으므로 같은 규칙(v1 patrol_cmd)으로 채운다.
function logRawSent(sent, robotId, command) {
  const topic = sent.topic || `/${robotId}/patrol_cmd`;
  const type = sent.msg_type || "std_msgs/msg/String";
  const data = `{data: ${JSON.stringify(sent.command || command)}}`;
  addRawLog([[topic, "topic"], [type, "type"], [data, "data"]], false,
    `같은 메시지를 터미널에서:\nros2 topic pub --once -w 1 ${topic} ${type} '${data}'`);
}

function logRawFailed(robotId, command, why) {
  addRawLog([[`안 보냄 · ${robotId} · ${JSON.stringify(command)} · ${why}`, "text"]], true);
}

async function sendRaw(event) {
  event.preventDefault();
  const robotId = $("raw-robot").value;
  const command = $("raw-cmd").value.trim();
  if (!robotId || !command) return;
  // 실물 도메인이면 로봇 이름을 직접 쳐야 보낸다 (다른 로봇을 고른 채 보내지 않게).
  if (view.snapshot && view.snapshot.infra && view.snapshot.infra.mode === "real") {
    const typed = prompt(`실물 로봇이 움직입니다.\n${robotId} 에 "${command}" 를 보내려면 로봇 이름을 입력하세요.`);
    if (typed === null || typed.trim() !== robotId) {
      logRawFailed(robotId, command, "취소 (이름이 다름)");
      return;
    }
  }
  $("raw-send").disabled = true;
  const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/raw_cmd`,
    { client_request_id: newRequestId(), command });
  $("raw-send").disabled = false;
  if (result.ok) {
    logRawSent(result.data || {}, robotId, command);
    $("raw-cmd").select();
  } else {
    logRawFailed(robotId, command, `${result.status} ${errorText(result)}`);
  }
}

function setupRaw() {
  $("raw-form").addEventListener("submit", sendRaw);
}
