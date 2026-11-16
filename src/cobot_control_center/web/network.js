// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 네트워크 상태 화면 (주소 #/network).
// 전체 화면(.layout)을 숨기고: 헬스체크 카드 → 구조도(관제 PC 안 노드·브릿지 → 공유기 → Station PC·핑키)
//   → 자세히 → 핑 지연 그래프(최근 5분).
// 데이터는 /api/network 하나만 본다. 상단 바 '네트워크 상태보기' 버튼 옆 점은 화면 밖에서도 2초마다 갱신한다.
// 서버가 준 문자열(노드 이름 등)은 textContent 로만 넣는다.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).

"use strict";

const NET_ROUTE = "#/network";
const NET_POLL_MS = 2000;
const NET_CHART_SEC = 300;      // 그래프 가로 폭 [s] (fleet_api NetStore 기록 300개 = 1 Hz 로 5분)
const NET_CHART_MIN_MS = 120;   // 그래프 세로 최소 높이 [ms]
const SVG_NS = "http://www.w3.org/2000/svg";
// 백엔드 상태 이름 → 화면 점 이름 (core.js 의 good/warn/bad/na 와 같게)
const NET_DOT = { ok: "good", warn: "warn", bad: "bad", na: "na" };
const NET_TEXT = { ok: "정상", warn: "주의", bad: "끊김·이상", na: "모름·해당 없음" };
// 그래프 선 색: 로봇은 카드와 같은 --robot-N, 나머지는 고정
const NET_SERIES_COLOR = { router: "--idle", station: "--warn" };

const net = {
  open: false,
  data: null,       // 마지막 /api/network 응답 (실패하면 null)
  failed: false,    // 백엔드에 닿지 않음
  selected: "control",
  at: 0,
  checking: false,  // 자세히 확인 요청을 보내는 중
  requestedAt: 0,   // 마지막 자세히 확인 요청이 받아들여진 때 (Date.now)
};

const netDot = (state) => NET_DOT[state] || "na";

// ---------- 주소 ----------

function applyNetRoute() {
  const on = location.hash === NET_ROUTE;
  if (on === net.open) return;
  net.open = on;
  document.body.classList.toggle("network-mode", on);
  $("network-page").hidden = !on;
  if (on) {
    document.title = "네트워크 · 로봇 관제";
    window.scrollTo(0, 0);
    pollNetwork();
  } else {
    if (!view.detailRobot) document.title = "로봇 관제";
    // 숨어 있던 동안 잰 크기가 틀렸을 수 있어 전체 지도를 다시 잰다 (detail.js 와 같은 이유)
    layoutMap();
    drawMap();
  }
}

// ---------- 받기 ----------

async function pollNetwork() {
  try {
    const res = await fetch(`/api/network${net.open ? "?history=1" : ""}`);
    if (!res.ok) throw new Error(String(res.status));
    net.data = await res.json();
    net.failed = false;
  } catch (err) {
    net.data = null;
    net.failed = true;
  }
  net.at = Date.now();
  // 상단 경고 띠에 네트워크·PC 경고를 더한다 (어느 페이지에서든). 백엔드가 닿지 않으면 상단 점이 알려 준다.
  const alerts = net.data ? net.data.alerts || [] : [];
  if (JSON.stringify(alerts) !== JSON.stringify(view.netAlerts || [])) {
    view.netAlerts = alerts;
    renderAlertStrip();   // events.js: 핑키 경고·팔 알람과 함께 다시 그린다
  }
  renderNetButton();
  if (net.open) renderNetwork();
}

function renderNetButton() {
  const btn = $("net-btn");
  const state = net.failed ? "bad" : net.data ? net.data.overall : "na";
  btn.dataset.state = netDot(state);
  btn.title = net.failed ? "백엔드에 닿지 않음" : `네트워크 전체: ${NET_TEXT[state] || "모름"}`;
}

// ---------- 그리기 ----------

function renderNetwork() {
  const d = net.data;
  $("net-updated").textContent = `갱신 ${formatTime(net.at / 1000)}`;
  const summary = $("net-summary");
  if (net.failed || !d) {
    summary.textContent = "백엔드에 닿지 않음 (fleet_api_node)";
    summary.dataset.state = "bad";
  } else {
    summary.textContent = `전체 ${NET_TEXT[d.overall]}`
      + (d.net_online ? "" : " · 측정 노드(net_status_node) 응답 없음 → 핑 칸 비어 있음")
      // ping 명령이 없는 환경(관제 도커 이미지)은 TCP 연결 시도로 잰다. 포트를 막은 장치는 응답 없음으로 보일 수 있다.
      + (d.net_online && d.probe === "tcp" ? ` · ping 대신 TCP ${d.probe_port} 연결로 잼` : "");
    summary.dataset.state = netDot(d.overall);
  }
  renderCheck(d);
  renderHealth(d);
  drawDiagram(d);
  renderNetInfo(d);
  drawNetChart(d);
}

function svgEl(tag, attrs, text) {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, String(v)));
  if (text !== undefined) el.textContent = text;
  return el;
}

function shorten(text, max) {
  const s = String(text ?? "");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

// 상자 하나: 제목 + 한 줄 설명 (+ 흐린 셋째 줄). 누르면 아래 '자세히'에 그 상자 내용.
function netBox(svg, id, x, y, w, h, title, sub, state, third) {
  const g = svgEl("g", { class: "nb", "data-state": netDot(state), "data-id": id,
                         tabindex: 0, role: "button" });
  if (net.selected === id) g.classList.add("sel");
  g.appendChild(svgEl("rect", { x, y, width: w, height: h, rx: 8 }));
  const lines = third ? [0.27, 0.53, 0.78] : [0.36, 0.7];
  g.appendChild(svgEl("text", { x: x + w / 2, y: y + h * lines[0], class: "nb-title" }, shorten(title, 22)));
  g.appendChild(svgEl("text", { x: x + w / 2, y: y + h * lines[1], class: "nb-sub" }, shorten(sub, 24)));
  if (third) g.appendChild(svgEl("text", { x: x + w / 2, y: y + h * lines[2], class: "nb-sub dim" }, third));
  g.appendChild(svgEl("title", {}, `${title}: ${sub}`));
  g.addEventListener("click", () => selectNet(id));
  g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") selectNet(id); });
  svg.appendChild(g);
}

function selectNet(id) {
  net.selected = id;
  renderNetwork();
}

function msText(ms) {
  return ms === null || ms === undefined ? "—" : `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
}

function drawDiagram(d) {
  const host = $("net-diagram");
  host.replaceChildren();
  const W = 900;
  const robots = d ? d.robots : [];
  const devices = d ? [d.station, ...robots] : [];
  const n = Math.max(devices.length, 1);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} 466`, class: "net-svg", role: "img",
                             "aria-label": "관제 네트워크 구조도" });

  // 관제 PC (바깥 상자)
  const local = (d && d.local) || {};
  const ctlState = !d ? "bad" : d.control_state;
  const ctl = svgEl("g", { class: "nb pc", "data-state": netDot(ctlState), "data-id": "control",
                           tabindex: 0, role: "button" });
  if (net.selected === "control") ctl.classList.add("sel");
  ctl.appendChild(svgEl("rect", { x: 20, y: 10, width: W - 40, height: 228, rx: 14 }));
  // 로봇망 = 공유기로 가는 경로의 연결. 관제 PC 는 Wi-Fi 와 유선이 함께 있을 수 있어 나머지 수도 적는다.
  const ifaces = (d && d.interfaces) || [];
  const robotIf = ifaces.find((i) => i.robot_net);
  ctl.appendChild(svgEl("text", { x: 36, y: 34, class: "pc-title" },
    `관제 PC · 도메인 ${local.domain_id ?? "?"} · ${local.rmw || "DDS ?"}`));
  ctl.appendChild(svgEl("text", { x: 36, y: 52, class: "nb-sub start" },
    [`로봇망 ${d && d.local_ip ? d.local_ip : "?"}`
       + (robotIf ? ` (${robotIf.kind_text} ${robotIf.name}${robotIf.wifi && robotIf.wifi.ssid ? ` ${robotIf.wifi.ssid}` : ""})`
         : d && String(d.local_ip || "").startsWith("127.") ? " (이 PC 안 시험)"
         : d && d.net_online ? " (연결 못 찾음)" : ""),
     ifaces.length ? `연결 ${ifaces.filter((i) => i.state === "ok").length}/${ifaces.length}` : "",
     local.nodes ? `노드 ${local.nodes.length}${local.unknown_nodes ? ` · 이름 안 보임 ${local.unknown_nodes}` : ""}` : ""]
      .filter(Boolean).join(" · ")));
  ctl.addEventListener("click", () => selectNet("control"));
  svg.appendChild(ctl);

  // 관제 PC 안 노드 (1줄) — 백엔드가 닿지 않으면 fleet_api 만 빨강, 나머지 모름
  const control = d ? d.control : [{ id: "fleet_api", label: "fleet_api", state: "bad", text: "응답 없음" }];
  const cw = 126;
  control.forEach((box, i) => {
    netBox(svg, box.id, 36 + i * (cw + 12), 66, cw, 56, box.label, box.text, box.state);
  });

  // 장치 줄 위치: Station PC + 로봇, 가운데 맞춤
  const bw = 190;
  const gap = 20;
  const start = (W - (n * bw + (n - 1) * gap)) / 2;
  const xs = devices.map((_, i) => start + i * (bw + gap));

  // 브릿지 (2줄): 해당 로봇 바로 위
  (d ? d.bridges : []).forEach((box) => {
    const i = devices.findIndex((dev) => dev.id === box.robot);
    if (i < 0) return;
    netBox(svg, box.id, xs[i], 150, bw, 56, box.label, box.text, box.state);
  });

  // 공유기
  const rx = 330;
  const rw = 240;
  const router = d ? d.router : { state: "na", text: "모름", label: "공유기" };
  const linkOf = (to) => (d ? d.links.find((l) => l.from === (to === "router" ? "control" : "router") && l.to === to) : null);
  const top = linkOf("router");
  svg.appendChild(svgEl("line", { x1: W / 2, y1: 238, x2: W / 2, y2: 270, class: "nl",
                                  "data-state": netDot(top ? top.state : "na") }));
  if (top && top.ms !== null) svg.appendChild(svgEl("text", { x: W / 2 + 8, y: 259, class: "nl-ms" }, msText(top.ms)));
  netBox(svg, "router", rx, 270, rw, 44,
         `${router.label}${router.ping && router.ping.host ? ` ${router.ping.host}` : ""}`, router.text, router.state);

  // 공유기 → 장치 선 (꺾은 선, 겹치지 않게 공유기 아래 칸을 나눠 쓴다)
  devices.forEach((dev, i) => {
    const link = linkOf(dev.id);
    const sx = rx + (rw * (i + 1)) / (n + 1);
    const dx = xs[i] + bw / 2;
    const midY = 330 + (Math.abs(i - (n - 1) / 2) < 1 ? 10 : 0);
    svg.appendChild(svgEl("path", { d: `M${sx} 314 L${sx} ${midY} L${dx} ${midY} L${dx} 370`,
                                    class: "nl", "data-state": netDot(link ? link.state : "na") }));
    if (link && link.ms !== null) svg.appendChild(svgEl("text", { x: dx + 8, y: 362, class: "nl-ms" }, msText(link.ms)));
  });

  // 장치 상자
  devices.forEach((dev, i) => {
    const addr = dev.ping && dev.ping.host ? ` ${dev.ping.host}` : "";
    netBox(svg, dev.id, xs[i], 370, bw, 84, `${dev.label}${addr}`, dev.text, dev.state,
      dev.kind === "station" ? "관제와 같은 도메인 · 브릿지 없음" : "브릿지 경유");
  });
  host.appendChild(svg);
}

// ---------- 자세히 확인 ----------
// 평소 측정 노드는 5초마다 핑만 한다. 버튼을 누르면 10초 동안 1초마다 핑하고 상태 토픽 주기를 잰다.

function renderCheck(d) {
  const btn = $("net-check");
  const note = $("net-check-note");
  const detail = d && d.detail;
  const t = (d && d.thresholds) || {};
  if (!d || !d.net_online) {
    btn.disabled = true;
    btn.textContent = "자세히 확인";
    note.textContent = "측정 노드 응답 없음";
    return;
  }
  if (detail && detail.active) {
    btn.disabled = true;
    btn.textContent = `확인 중… ${Math.ceil(detail.remaining_sec)}초`;
    note.textContent = `${t.detail_period_sec ?? 1}초마다 핑 · 상태 토픽 주기 재는 중`;
    return;
  }
  // 요청 직후엔 측정 노드의 다음 발행(1초)까지 '확인 중'이 안 보이므로 잠깐 막아 두 번 눌리지 않게 한다.
  const waiting = net.checking || Date.now() - net.requestedAt < 3000;
  btn.disabled = waiting;
  btn.textContent = waiting ? "요청 중…" : `자세히 확인 (${(detail && detail.duration_sec) || 10}초)`;
  note.textContent = (detail && detail.started_at ? `마지막 자세히 확인 ${formatTime(detail.started_at)} · ` : "")
    + `평소 ${t.ping_period_sec ?? 5}초마다 핑`;
}

async function startNetCheck() {
  net.checking = true;
  renderCheck(net.data);
  try {
    const res = await fetch("/api/network/check", { method: "POST" });
    if (res.ok) {
      net.requestedAt = Date.now();
    } else {
      const body = await res.json().catch(() => ({}));
      $("net-check-note").textContent = `요청 실패: ${body.detail || res.status}`;
    }
  } catch (err) {
    $("net-check-note").textContent = "요청 실패: 백엔드에 닿지 않음";
  }
  net.checking = false;
  pollNetwork();
}

// ---------- 헬스체크 (구조도 위) ----------
// 로봇·Station PC·관제 PC 마다 카드 하나, 점검 줄은 백엔드(net_status_utils.health_view)가 정한다.
// 로봇 판정은 fleet_status 경고와 같은 기준이라 상단 경고 띠와 말이 같다.

function renderHealth(d) {
  const counts = $("health-counts");
  const issues = $("health-issues");
  const cards = $("health-cards");
  const pcs = $("health-pcs");
  issues.replaceChildren();
  cards.replaceChildren();
  pcs.replaceChildren();
  if (!d || !d.health) {
    counts.textContent = "백엔드 응답 없음";
    return;
  }
  const h = d.health;
  const c = h.counts || {};
  counts.textContent = `점검 ${(c.ok || 0) + (c.warn || 0) + (c.bad || 0)}개: 정상 ${c.ok || 0} · 주의 ${c.warn || 0} · 이상 ${c.bad || 0}`
    + (c.na ? ` · 모름 ${c.na}` : "");
  // 지금 볼 것: 정상이 아닌 점검 (나쁜 것부터). 없으면 한 줄로 '이상 없음'.
  if (!h.issues.length) {
    const li = document.createElement("li");
    li.dataset.state = "good";
    li.textContent = "지금 이상 없음";
    issues.appendChild(li);
  }
  h.issues.forEach((issue) => {
    const li = document.createElement("li");
    li.dataset.state = netDot(issue.state);
    const who = document.createElement("strong");
    who.textContent = `${issue.label} · ${issue.name}`;
    li.append(who, document.createTextNode(` ${issue.value}`));
    // 팔 카드는 구조도의 Station PC 상자를 연다 (select)
    li.addEventListener("click", () => selectNet(issue.select || issue.card));
    issues.appendChild(li);
  });
  h.cards.forEach((card) => {
    const el = netCard(card.select || card.id, card.label, card.state,
      card.checks.map((check) => [check.name, check.value, check.state]));
    el.dataset.kind = card.kind;
    // PC(Station PC·관제 PC)는 장비 카드와 따로 아래 줄에 둔다
    (card.kind === "station" || card.kind === "control" ? pcs : cards).appendChild(el);
  });
}

// ---------- 자세히 ----------

function addRow(dl, label, value, state) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value ?? "—";
  if (state) dd.dataset.level = state === "na" ? "none" : netDot(state);
  dl.append(dt, dd);
}

// 자세히 칸의 묶음 제목 (유선·무선 등). 두 칸을 다 쓴다.
function addHeading(dl, text) {
  const dt = document.createElement("dt");
  dt.className = "diag-heading";
  dt.textContent = text;
  dl.appendChild(dt);
}

function pingText(ping) {
  if (!ping) return "측정 없음";
  if (!ping.samples) return `${ping.host || ""} 아직 안 잼`;
  return `${ping.host || ""} · 마지막 ${msText(ping.last_ms)} · 평균 ${msText(ping.avg_ms)}`
    + ` · 최대 ${msText(ping.max_ms)} · 손실 ${ping.loss_pct}% (${ping.samples}번)`;
}

// 토픽 수신 주기는 자세히 확인 때만 잰다. 끝난 뒤에는 그때 결과를 시각과 함께 보인다.
function rateText(rate) {
  if (!rate) return "자세히 확인 때 잼";
  const when = rate.checked_at ? ` (${formatTime(rate.checked_at)} 확인)` : "";
  if (rate.age === null) return `${rate.topic} 받지 못함${when}`;
  return `${rate.topic} · ${rate.hz} Hz${rate.checked_at ? "" : ` · ${rate.age} 초 전`}${when}`;
}

function findNetBox(d, id) {
  if (!d) return null;
  return [...d.control, ...d.bridges, d.router, d.station, ...d.robots].find((b) => b.id === id) || null;
}

function renderNetInfo(d) {
  const dl = $("net-info");
  dl.replaceChildren();
  const title = $("net-info-title");
  if (!d) {
    title.textContent = "자세히";
    addRow(dl, "백엔드", "응답 없음. fleet_api_node 가 켜져 있는지 확인", "bad");
    return;
  }
  if (net.selected === "control") {
    const l = d.local || {};
    title.textContent = "관제 PC";
    addRow(dl, "DDS (RMW)", l.rmw ? `${l.rmw} (이 PC 에서 직접 확인)` : "모름");
    addRow(dl, "RMW_IMPLEMENTATION", l.rmw_env || "설정 없음 (ROS 기본값)");
    addRow(dl, "도메인", l.domain_id ?? "?");
    addRow(dl, "CYCLONEDDS_URI", l.cyclonedds_uri || "설정 없음");
    addRow(dl, "발견 범위", l.discovery_range || "설정 없음 (기본 SUBNET)");
    if (l.static_peers) addRow(dl, "ROS_STATIC_PEERS", l.static_peers);
    addRow(dl, "로봇망 주소", d.local_ip ? `${d.local_ip} (공유기로 가는 연결)` : "모름 (측정 노드 필요)");
    // 연결: 보통 네트워크 설정 화면처럼 유선 → 무선 → VPN·기타 로 묶고, 용도는 [로봇망] [기본 경로] 배지.
    const ifaces = d.interfaces || [];
    if (!ifaces.length) addRow(dl, "연결", d.net_online ? "없음" : "모름 (측정 노드 필요)");
    ["ethernet", "wifi", "vpn", "other"].forEach((kind) => {
      const group = ifaces.filter((i) => (i.kind || "other") === kind);
      if (!group.length) return;
      addHeading(dl, group[0].kind_text);
      group.forEach((i) => {
        const badges = (i.badges || []).map((b) => `[${b}]`).join(" ");
        addRow(dl, i.name, `${i.summary}${badges ? ` ${badges}` : ""}`,
          i.robot_net ? i.state : (i.state === "ok" ? "ok" : "na"));
        const more = [i.gateway ? `게이트웨이 ${i.gateway}` : "", i.mac ? `MAC ${i.mac}` : "",
          i.carrier_changes ? `링크 끊겼다 붙음 ${i.carrier_changes}번` : ""].filter(Boolean).join(" · ");
        if (more) addRow(dl, "", more);
        const same = i.wifi && i.wifi.same_channel;
        if (same && same.length) {
          addRow(dl, "", `같은 채널 AP ${same.length}개: ${same.join(", ")} (겹치면 느려질 수 있음)`, "na");
        }
      });
    });
    addRow(dl, `도메인 ${l.domain_id ?? "?"} 노드`, l.nodes ? `${l.nodes.length}개: ${l.nodes.join(", ")}` : "모름");
    if (l.unknown_nodes) {
      addRow(dl, "이름 안 보이는 노드", `${l.unknown_nodes}개 · 발행은 보이는데 이름 정보가 안 옴 → DDS 구현이 다를 수 있음 (Cyclone ↔ Fast DDS)`, "warn");
    }
    return;
  }
  const box = findNetBox(d, net.selected);
  if (!box) {
    net.selected = "control";
    renderNetInfo(d);
    return;
  }
  title.textContent = box.label;
  addRow(dl, "상태", `${NET_TEXT[box.state]} · ${box.text}`, box.state);
  if (box.note) addRow(dl, "설명", box.note);
  if (box.node) addRow(dl, "노드 이름", box.node);
  if (box.dds) addRow(dl, "DDS", `${box.dds} (원격 DDS 종류는 ROS 로 확인할 수 없음)`);
  if ("ping" in box) {
    addRow(dl, "핑", pingText(box.ping), box.ping ? box.ping.state : "na");
    // MAC 은 관제 PC 의 ARP 표 값 (핑을 보내므로 따로 패킷을 보내지 않는다)
    if (box.ping && box.ping.host) {
      addRow(dl, "MAC", box.ping.mac ? `${box.ping.mac}${box.ping.mac_fresh ? "" : " (예전 값)"}` : "모름 (핑 응답 뒤 채워짐)");
    }
  }
  if (box.nodes) {
    addRow(dl, "보이는 노드", box.nodes.length ? `${box.nodes.length}개: ${box.nodes.join(", ")}` : "없음",
      box.nodes.length ? "ok" : "na");
  }
  if (box.rate !== undefined) addRow(dl, "상태 토픽", rateText(box.rate), box.rate ? box.rate.state : "na");
  if (box.topic_age) {
    const age = Object.entries(box.topic_age).map(([k, v]) => `${k} ${v === null ? "—" : `${v}초`}`).join(" · ");
    addRow(dl, "마지막 수신 (fleet_status)", age || "—");
  }
  (box.arms || []).forEach((arm) => {
    const rate = box.rates ? box.rates[arm.arm_id] : null;
    addRow(dl, arm.arm_id, `${arm.state || "?"} · ${rateText(rate)}`, arm.online ? (rate ? rate.state : "ok") : "bad");
  });
}

// ---------- 카드 ----------

function netCard(id, title, state, rows) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "net-card";
  card.dataset.state = netDot(state);
  if (net.selected === id) card.classList.add("sel");
  const head = document.createElement("div");
  head.className = "net-card-head";
  const name = document.createElement("strong");
  name.textContent = title;
  const badge = document.createElement("span");
  badge.className = "net-badge";
  badge.textContent = NET_TEXT[state] || "모름";
  head.append(name, badge);
  const dl = document.createElement("dl");
  dl.className = "diag";
  rows.forEach(([label, value, s]) => addRow(dl, label, value, s));
  card.append(head, dl);
  card.addEventListener("click", () => selectNet(id));
  return card;
}

// ---------- 그래프 ----------

function netSeries(d) {
  if (!d) return [];
  const list = [{ key: "router", label: "공유기", color: css(NET_SERIES_COLOR.router) },
    { key: "station", label: "Station PC", color: css(NET_SERIES_COLOR.station) }];
  d.robots.forEach((r, i) => list.push({ key: r.id, label: r.label, color: css(robotColorVar(i)) }));
  return list;
}

function drawNetChart(d) {
  const canvas = $("net-chart");
  const legend = $("net-legend");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);
  legend.replaceChildren();
  const history = (d && d.history) || {};
  const series = netSeries(d).filter((s) => (history[s.key] || []).length);
  const pad = { l: 44, r: 10, t: 8, b: 20 };
  const warnMs = d && d.thresholds ? d.thresholds.ping_warn_ms : null;
  let end = 0;
  let maxMs = NET_CHART_MIN_MS;
  series.forEach((s) => history[s.key].forEach(([t, ms]) => {
    end = Math.max(end, t);
    if (ms !== null) maxMs = Math.max(maxMs, ms);
  }));
  maxMs = Math.ceil(maxMs * 1.1);
  const x = (t) => pad.l + ((t - (end - NET_CHART_SEC)) / NET_CHART_SEC) * (w - pad.l - pad.r);
  const y = (ms) => pad.t + (1 - ms / maxMs) * (h - pad.t - pad.b);

  // 축·눈금
  ctx.font = "11px system-ui, sans-serif";
  ctx.fillStyle = css("--muted");
  ctx.strokeStyle = css("--border");
  ctx.lineWidth = 1;
  [0, 0.5, 1].forEach((f) => {
    const ms = Math.round(maxMs * f);
    ctx.beginPath();
    ctx.moveTo(pad.l, y(ms));
    ctx.lineTo(w - pad.r, y(ms));
    ctx.stroke();
    ctx.fillText(`${ms} ms`, 4, y(ms) + 4);
  });
  ctx.fillText("5분 전", pad.l, h - 5);
  ctx.fillText("지금", w - pad.r - 24, h - 5);
  if (!series.length) {
    ctx.fillText(d && !d.net_online ? "측정 노드(net_status_node) 응답 없음" : "기록 없음", pad.l + 8, pad.t + 16);
    return;
  }
  if (warnMs) {
    ctx.strokeStyle = css("--warn");
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.l, y(warnMs));
    ctx.lineTo(w - pad.r, y(warnMs));
    ctx.stroke();
    ctx.setLineDash([]);
  }
  series.forEach((s) => {
    // 실패(null)에서 선을 끊고 아래쪽에 빨간 눈금을 둔다
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let drawing = false;
    history[s.key].forEach(([t, ms]) => {
      if (t < end - NET_CHART_SEC) return;
      if (ms === null) {
        drawing = false;
        return;
      }
      if (drawing) ctx.lineTo(x(t), y(ms));
      else ctx.moveTo(x(t), y(ms));
      drawing = true;
    });
    ctx.stroke();
    ctx.fillStyle = css("--bad");
    history[s.key].forEach(([t, ms]) => {
      if (ms === null && t >= end - NET_CHART_SEC) ctx.fillRect(x(t) - 1, h - pad.b - 6, 2, 6);
    });
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.background = s.color;
    item.append(swatch, document.createTextNode(s.label));
    legend.appendChild(item);
  });
  if (warnMs) {
    const note = document.createElement("span");
    note.className = "muted";
    note.textContent = `점선 = 주의 기준 ${warnMs} ms · 빨간 눈금 = 응답 없음`;
    legend.appendChild(note);
  }
}

function setupNetwork() {
  window.addEventListener("hashchange", applyNetRoute);
  $("net-check").addEventListener("click", startNetCheck);
  window.addEventListener("resize", () => { if (net.open) drawNetChart(net.data); });
  applyNetRoute();
  pollNetwork();
  setInterval(pollNetwork, NET_POLL_MS);
}
