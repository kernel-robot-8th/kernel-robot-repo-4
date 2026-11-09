// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 전체 그리기·상태 확인·시작.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).
// 파일끼리 함수·상수를 전역 이름으로 함께 쓴다 (빌드 단계 없이 브라우저가 바로 읽게).

"use strict";

// ---------- 전체 ----------

function render() {
  const snap = view.snapshot;
  if (!snap) return;
  setLink("link-source", snap.source_online);
  renderMode(snap.infra);
  renderInfra(snap.infra, snap.source_online);
  $("updated").textContent = `갱신 ${formatTime(view.receivedAt / 1000)}`;
  Object.entries(snap.robots || {}).forEach(([robotId, robot], index) => {
    renderCard(robotId, robot, index);
  });
  renderZones(snap.zones, snap.queues);
  renderAlerts(snap.alerts, snap.source_online);
  renderEventFilter();
  renderRawPanel();
  renderDetail();
  // 첫 상태가 오면 상단 바(브릿지 점 등)가 채워져 높이가 바뀔 수 있어 한 번 다시 잰다.
  if (!view.laidOut) {
    view.laidOut = true;
    layoutMap();
  }
  drawMap();
}

// 관제 노드가 멈추면 새 스냅샷이 오지 않아 마지막 값이 남는다. 그래서 상태는 따로 물어본다.
async function pollHealth() {
  try {
    const res = await fetch("/api/health");
    const health = res.ok ? await res.json() : {};
    view.healthDomain = health.domain_id ?? null;
    setLink("link-source", Boolean(health.source_online));
    const armed = Boolean(health.commands_armed);
    const readOnly = Boolean(health.read_only);
    if (view.controllerOnline !== Boolean(health.controller_online)
        || view.commandsArmed !== armed || view.readOnly !== readOnly) {
      view.controllerOnline = Boolean(health.controller_online);
      view.commandsArmed = armed;
      view.readOnly = readOnly;
      if (!armed) cancelPick();
      render();
    }
    renderArmToggle();
    setLink("link-tasks", view.controllerOnline);
    $("stop-all").disabled = !view.controllerOnline || view.readOnly;
    view.rawEnabled = Boolean(health.raw_cmd_enabled) && !view.readOnly;
    renderRawPanel();
    view.cameras = health.cameras || {};
    view.spec = health.spec ?? null;
    const holds = health.holds || {};
    const orders = health.orders || [];
    if (JSON.stringify(view.holds) !== JSON.stringify(holds)
        || JSON.stringify(view.orders) !== JSON.stringify(orders)) {
      view.holds = holds;
      view.orders = orders;
      render();
    }
    updateCamera();
    const infra = view.snapshot ? view.snapshot.infra : null;
    if (!infra) renderMode(null);
    renderInfra(infra, Boolean(health.source_online));
    if (!health.source_online) renderAlerts(null, false);
  } catch (err) {
    // 백엔드가 꺼지면 마지막 스냅샷이 남으므로, 카드 명령 버튼이 켜진 채로 남지 않게 다시 그린다.
    if (view.controllerOnline || view.commandsArmed) {
      view.controllerOnline = false;
      view.commandsArmed = false;
      render();
    }
    renderArmToggle();
    setLink("link-source", false);
    renderAlerts(null, false);
    setLink("link-tasks", false);
    $("stop-all").disabled = true;
    view.rawEnabled = false;
    renderRawPanel();
    view.holds = {};
    view.orders = [];
    view.cameras = {};
    updateCamera();
    renderInfra(view.snapshot ? view.snapshot.infra : null, false);
  }
}

window.addEventListener("resize", () => {
  layoutMap();
  drawMap();
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawMap);
$("event-robot").addEventListener("change", renderEvents);
$("task-robot").addEventListener("change", renderTasks);
setupToggle("show-layers", SHOW_LAYERS_KEY, "showLayers", "off");
setupToggle("show-points", SHOW_POINTS_KEY, "showPoints", "points-off");
setupPick();
setupRaw();
setupResolve();
setupRelease();
setupLoad();
setupDetail();
loadMap();
loadLayers();
connect();
connectTasks();
pollHealth();
setInterval(pollHealth, HEALTH_POLL_MS);
