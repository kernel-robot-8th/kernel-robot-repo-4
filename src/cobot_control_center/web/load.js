// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 수동 상차 확인 띠.
// 팔 연동이 없거나 실패해 상차장에서 멈춘 주문은 사람이 싣고 화면에서 확인한다 (11/7 실물 시험).
// 백엔드 /api/health 의 orders 에서 load_confirmable 인 주문이 있으면 그 로봇 카드 상태 줄이
// '상차 확인 대기'가 되고, 누르면 이 띠가 뜬다. 현장 확인 체크·운영자·메모를 받아
// POST /api/orders/{id}/confirm_loaded 로 보낸다. 검사(상차장 도착·정지·통신·구역·예약)는 fleet 이 하고,
// 통과하면 상차 구역 이탈부터 재개한다. savedOperator·saveOperator 는 release.js 의 것을 쓴다.

"use strict";

const LOAD_NOTE = "현장에서 직접 상차함";
// confirm_loaded 의 evidence 확인 항목: 실제 적재 · 팔 퇴피 · 진입 통로 비움 (sku 는 주문 값을 그대로 보낸다)
const LOAD_EVIDENCE_KEYS = ["load_present", "arm_safe", "pickup_path_clear"];

// 이 로봇이 상차 확인을 기다리는 주문 (없으면 null). 화면 표시용이고 최종 판단은 fleet 이 한다.
function loadWaiting(robotId) {
  return view.orders.find((order) => order.robot_id === robotId && order.load_confirmable) || null;
}

// 카드 상태 줄 글. 띠 제목 옆에는 hint 없이 쓴다.
function loadText(order, hint = false) {
  const text = `상차 확인 대기 · 주문 ${order.order_id} (${order.sku})`;
  return hint ? `${text} · 눌러서 현장 확인` : text;
}

function updateLoadButton() {
  const ready = $("load-confirm").checked && $("load-operator").value.trim() !== "";
  $("load-ok").disabled = !ready;
}

function openLoad(robotId) {
  const host = barHost(robotId);
  const order = loadWaiting(robotId);
  if (!host || !order) return;
  cancelPick();
  closeResolve();
  closeRelease();
  view.loading = { robotId, orderId: order.order_id, sku: order.sku };
  $("load-title").textContent = `${robotId} · 수동 상차 확인`;
  $("load-what").textContent = loadText(order);
  $("load-confirm").checked = false;
  $("load-operator").value = savedOperator();
  $("load-note").value = LOAD_NOTE;
  updateLoadButton();
  host.appendChild($("load-bar"));
  $("load-bar").hidden = false;
  if (view.detailRobot !== robotId) focusCard(robotId);
  $("load-confirm").focus();
}

function closeLoad() {
  view.loading = null;
  $("load-bar").hidden = true;
}

async function sendLoad() {
  const loading = view.loading;
  if (!loading || $("load-ok").disabled) return;
  const operator = $("load-operator").value.trim();
  const note = $("load-note").value.trim() || LOAD_NOTE;
  const confirmed = $("load-confirm").checked;
  const evidence = Object.fromEntries(LOAD_EVIDENCE_KEYS.map((key) => [key, confirmed]));
  evidence.sku = loading.sku;
  saveOperator(operator);
  $("load-ok").disabled = true;
  const result = await postJson(`/api/orders/${encodeURIComponent(loading.orderId)}/confirm_loaded`,
    { client_request_id: newRequestId(), operator, note, evidence });
  closeLoad();
  if (result.ok) {
    // 다음 /api/health 를 기다리지 않고 대기 표시를 바로 지운다.
    view.orders = view.orders.map((order) => (order.order_id === loading.orderId
      ? { ...order, load_confirmable: false, load_confirmed: true } : order));
    showMessage(loading.robotId, `상차 확인함 · 주문 ${loading.orderId} 구역 이탈부터 재개`, false);
  } else {
    showMessage(loading.robotId, `상차 확인 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

function setupLoad() {
  $("load-confirm").addEventListener("change", updateLoadButton);
  $("load-operator").addEventListener("input", updateLoadButton);
  $("load-ok").addEventListener("click", sendLoad);
  $("load-cancel").addEventListener("click", closeLoad);
  $("load-note").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendLoad();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view.loading) closeLoad();
  });
}
