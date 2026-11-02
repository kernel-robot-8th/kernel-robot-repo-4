// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 공통: 상수·화면 상태(view)·연결·기반 노드 표시.
// 관제 화면은 /ws/fleet 스냅샷으로 카드·구역·지도를 그린다.
// 명령은 /api/tasks·/api/robots/{id}/stop 으로만 보내고, 작업 상태는 /ws/tasks 로 받는다.
// 로봇이 보낸 문자열(detail 등)은 textContent 로만 넣는다 (HTML 로 해석하지 않는다).
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

const RECONNECT_MS = 2000;
const HEALTH_POLL_MS = 2000;


const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = (id) => document.getElementById(id);

// 기반 노드 판정(fleet_status 의 infra) → 점 색과 설명
const INFRA_STATE = {
  ok: { dot: "good", text: "정상" },
  missing: { dot: "bad", text: "없음" },
  duplicate: { dot: "bad", text: "중복" },
  unknown: { dot: "warn", text: "확인 불가 (DDS 가 달라 이름이 안 보임)" },
  "n/a": { dot: "na", text: "해당 없음 (실물 도메인 아님)" },
};
const MODE_TEXT = { real: "실물", mock: "가짜 핑키", test: "시험" };

const view = {
  snapshot: null,
  receivedAt: 0,
  healthDomain: null, // /api/health 의 domain_id (fleet_status 를 받기 전에도 보이게)
  map: null,        // {info, canvas}
  layers: null,     // /api/map/layers (구역 지점·출구·대기 슬롯·홈)
  showLayers: true, // 지도 구역 표시 켜기/끄기 (브라우저에 기억)
  showPoints: true, // 지도 일반 웨이포인트(P) 표시 켜기/끄기 (브라우저에 기억)
  cards: new Map(), // robot_id → card element
  events: [],       // 이벤트 로그 (오래된 것부터, id 오름차순)
  lastEventId: 0,
  tasks: new Map(), // task_id → 작업 (/ws/tasks)
  taskManagerOnline: false,
  rawEnabled: false, // 개발용 수동 명령 칸을 보일지 (/api/health)
  pick: null,       // 명령 지점 고르는 중 {robotId, cmd, choices, route, ...}
  mapScale: 0,      // 지도 1 px 의 화면 크기 (layoutMap 이 정함)
  laidOut: false,   // 첫 상태를 받은 뒤 한 번 다시 쟀는지
};

function robotColorVar(index) {
  return `--robot-${(index % 3) + 1}`;
}

// ---------- 연결 ----------

function setLink(id, ok) {
  $(id).dataset.state = ok ? "good" : "bad";
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/fleet`);
  // 다시 붙으면 이벤트를 처음부터 다시 받는다 (백엔드가 다시 켜졌으면 id 가 1 부터 다시 시작).
  ws.onopen = () => {
    setLink("link-ws", true);
    loadEvents();
  };
  ws.onmessage = (event) => {
    view.snapshot = JSON.parse(event.data);
    view.receivedAt = Date.now();
    addEvents(view.snapshot.events);
    render();
  };
  ws.onclose = () => {
    setLink("link-ws", false);
    setTimeout(connect, RECONNECT_MS);
  };
  ws.onerror = () => ws.close();
}

// ---------- 도메인·기반 노드 ----------

function renderMode(infra) {
  const el = $("mode");
  const domain = infra ? infra.domain_id : view.healthDomain;
  const mode = infra ? infra.mode : "unknown";
  el.dataset.mode = mode;
  el.textContent = domain === null || domain === undefined ? "도메인 ?"
    : MODE_TEXT[mode] ? `도메인 ${domain} · ${MODE_TEXT[mode]}` : `도메인 ${domain}`;
  el.title = mode === "real" ? "실물 관제 도메인입니다"
    : mode === "unknown" ? "관제 노드 정보를 기다리는 중"
    : `실물 관제 도메인(${infra.control_domain_id})이 아닙니다`;
}

// 관제 노드가 끊기면 마지막 판정이 낡았으므로 회색으로 둔다.
function renderInfra(infra, fresh) {
  const zone = $("link-zone");
  const zoneState = infra && fresh ? infra.zone_manager.state : "n/a";
  zone.dataset.state = INFRA_STATE[zoneState].dot;
  zone.querySelector(".label").textContent = zoneState === "duplicate"
    ? `zone_manager 중복 ${infra.zone_manager.count}` : "zone_manager";
  zone.title = fresh ? `zone_manager: ${INFRA_STATE[zoneState].text}` : "관제 노드 끊김";

  const box = $("link-bridges");
  box.querySelectorAll(".dot").forEach((dot) => dot.remove());
  Object.entries((infra && infra.bridges) || {}).forEach(([robotId, bridge], index) => {
    const state = fresh ? bridge.state : "n/a";
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.dataset.state = INFRA_STATE[state].dot;
    dot.appendChild(document.createElement("i"));
    dot.appendChild(document.createTextNode(String(index + 1)));
    dot.title = fresh
      ? `${robotId} (${bridge.node}): ${INFRA_STATE[state].text}${bridge.count > 1 ? ` ${bridge.count}개` : ""}`
      : "관제 노드 끊김";
    box.appendChild(dot);
  });
}
