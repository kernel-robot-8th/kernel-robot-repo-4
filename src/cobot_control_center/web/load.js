// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 수동 상차 확인 띠.
// 팔 연동이 없거나 실패해 상차장에서 멈춘 주문은 사람이 싣고 화면에서 확인한다 (11/7 실물 시험).
// 백엔드 /api/health 의 orders 에서 load_confirmable 인 주문이 있으면 그 로봇 카드 상태 줄이
// '상차 확인 대기'가 되고, 누르면 이 띠가 뜬다. 현장 확인 체크·운영자·메모를 받아
// POST /api/orders/{id}/confirm_loaded 로 보낸다. 검사(상차장 도착·정지·통신·구역·예약)는 fleet 이 하고,
// 통과하면 상차 구역 이탈부터 재개한다. savedOperator·saveOperator 는 release.js 의 것을 쓴다.
//
// 멈춘 주문 복구도 여기 둔다 (주문 화면 기능 모음). 빨간 줄을 누르면 확인 창으로
// [이어서 가기](이동 단계만) / [주문 취소] 를 고르고 POST /api/orders/{id}/recover 로 보낸다.
// 보통 방식대로 확인 창 한 번 (2026-11-09 임시 일반형, 확인 항목은 fleet 에서도 선택).
// TODO(시나리오): 멈춘 단계별 확인 항목, 취소 뒤 홈 복귀, 하차 완료 표시
//   (draft/safety_locks_review.md 8절).

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
  closeBars();
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

// ---------- 멈춘 주문 복구 ----------

// 이 로봇의 멈춘 주문 (없으면 null). 화면 표시용이고 최종 판단은 fleet 이 한다.
function orderBlocked(robotId) {
  return view.orders.find((order) => order.robot_id === robotId && order.blocked) || null;
}

// 카드 상태 줄 글.
function orderBlockedText(order) {
  const why = HOLD_TEXT[order.state] || (order.state === "UNKNOWN" ? "결과 모름" : order.state);
  return `주문 ${order.order_id} 멈춤 (${why}) · 눌러서 ${order.resumable ? "이어서 가기/취소" : "취소"}`;
}

async function sendOrderRecover(order, decision) {
  const result = await postJson(`/api/orders/${encodeURIComponent(order.order_id)}/recover`,
    { client_request_id: newRequestId(), decision });
  if (result.ok) {
    view.orders = view.orders.filter((item) => item.order_id !== order.order_id || decision !== "fail");
    delete view.holds[order.robot_id];
    showMessage(order.robot_id, decision === "resume"
      ? `주문 ${order.order_id} 이어서 감` : `주문 ${order.order_id} 취소함 · 실은 상자는 꺼내고, 로봇은 제자리 (홈은 따로)`,
    false);
  } else {
    showMessage(order.robot_id, `주문 복구 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

function recoverOrder(robotId) {
  const order = orderBlocked(robotId);
  if (!order) return;
  closeBars();
  if (order.resumable && confirm([`주문 ${order.order_id} (${order.sku}) 이어서 갈까요?`,
    `${robotId} · ${order.stage}`,
    "현장에서 로봇·상자·주변을 확인했나요?",
    "취소를 누르면 주문 취소를 묻습니다."].join("\n"))) {
    sendOrderRecover(order, "resume");
    return;
  }
  if (confirm([`주문 ${order.order_id} (${order.sku}) 을 취소할까요?`, `${robotId} · ${order.stage}`,
    "실은 상자는 사람이 꺼냅니다. 로봇은 제자리에 둡니다 (홈은 따로 보내기)."].join("\n"))) {
    sendOrderRecover(order, "fail");
  }
}
