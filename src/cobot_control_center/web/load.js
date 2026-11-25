// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 수동 상차 확인 띠.
// 팔 연동이 없거나 실패해 상차장에서 멈춘 주문은 사람이 싣고 화면에서 확인한다 (11/7 실물 시험).
// 백엔드 /api/health 의 orders 에서 load_waiting 인 주문이 있으면 그 로봇 카드 상태 줄이
// '상차 확인 대기'가 되고, 누르면 이 띠가 뜬다. 현장 확인 체크·운영자·메모를 받아
// POST /api/orders/{id}/confirm_loaded 로 보낸다. 검사(상차장 도착·정지·통신·구역·예약)는 fleet 이 하고,
// 통과하면 상차 구역 이탈부터 재개한다. savedOperator·saveOperator 는 release.js 의 것을 쓴다.
//
// 멈춘 주문 복구도 여기 둔다 (주문 화면 기능 모음). 빨간 줄을 누르면 멈춘 주문 막대가 떠서
// 보통 방식대로 한 곳에서 [다시](팔 단계)·[이어서 가기](이동 단계) / [사람이 처리함](하차·정리·반환) /
// [주문 취소] 를 고르고 POST /api/orders/{id}/recover 로 보낸다 (2026-11-23).
// 팔 PICK 실패처럼 멈춘 주문이 상차 확인 대기도 겹치면 카드 줄은 상차 확인 띠를 연다. 그 띠의
// [다시 / 주문 취소] 로 같은 멈춘 주문 막대에 갈 수 있다 (2026-11-21).
// TODO(시나리오): 멈춘 단계별 확인 항목, 취소 뒤 홈 복귀, 하차 완료 표시
//   (draft/safety_locks_review.md 8절).

"use strict";

const LOAD_NOTE = "현장에서 직접 상차함";
// confirm_loaded 의 evidence 확인 항목: 실제 적재 · 팔 퇴피 · 진입 통로 비움 (sku 는 주문 값을 그대로 보낸다)
const LOAD_EVIDENCE_KEYS = ["load_present", "arm_safe", "pickup_path_clear"];

// 이 로봇이 상차 확인을 기다리는 주문 (없으면 null). 화면 표시용이고 최종 판단은 fleet 이 한다.
function loadWaiting(robotId) {
  return view.orders.find((order) => order.robot_id === robotId && order.load_waiting) || null;
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
  // 진행 중(정상 상차 대기) 주문은 fleet 도 취소를 거절하므로 멈춘 주문일 때만 보인다.
  $("load-abort").hidden = !order.blocked;
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
      ? { ...order, load_confirmable: false, load_waiting: false, load_confirmed: true } : order));
    showMessage(loading.robotId, `상차 확인함 · 주문 ${loading.orderId} 구역 이탈부터 재개`, false);
  } else {
    showMessage(loading.robotId, `상차 확인 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

// 상차 확인 띠의 [다시 / 주문 취소]: 띠를 닫고 멈춘 주문 막대(recoverOrder)로 넘긴다.
function abortLoad() {
  const loading = view.loading;
  if (!loading) return;
  closeLoad();
  recoverOrder(loading.robotId);
}

function setupLoad() {
  $("load-confirm").addEventListener("change", updateLoadButton);
  $("load-operator").addEventListener("input", updateLoadButton);
  $("load-ok").addEventListener("click", sendLoad);
  $("load-cancel").addEventListener("click", closeLoad);
  $("load-abort").addEventListener("click", abortLoad);
  $("load-note").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendLoad();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view.loading) closeLoad();
  });
}

// ---------- 멈춘 주문 복구 ----------

const RECOVER_NOTE = "화면에서 현장 확인 후 복구";
// 팔 단계별 다시 할 때 시작 단계 (fleet scenario_contracts.RETRY_FROM 과 같음, 안내 글에만 씀)
const RETRY_FROM = { LOAD: "PICK", UNLOAD: "PICK_DROPOFF" };

// 이 로봇의 멈춘 주문 (없으면 null). 화면 표시용이고 최종 판단은 fleet 이 한다.
function orderBlocked(robotId) {
  return view.orders.find((order) => order.robot_id === robotId && order.blocked) || null;
}

// 고를 수 있는 것: 이어서 가기(이동) 또는 다시(팔), 사람이 처리함(하차·정리·반환), 취소(늘).
function recoverChoices(order) {
  const again = order.resumable ? "이어서 가기" : order.retryable ? "다시" : "";
  return [again, order.hand_done ? "사람이 처리함" : "", "취소"].filter(Boolean).join("/");
}

// 카드 상태 줄 글.
function orderBlockedText(order) {
  const why = HOLD_TEXT[order.state] || (order.state === "UNKNOWN" ? "결과 모름" : order.state);
  return `주문 ${order.order_id} 멈춤 (${why}) · 눌러서 ${recoverChoices(order)}`;
}

async function sendOrderRecover(order, decision, evidence) {
  const operator = view.recovering ? $("recover-operator").value.trim() : "";
  const note = view.recovering ? ($("recover-note").value.trim() || RECOVER_NOTE) : "";
  if (operator) saveOperator(operator);
  closeRecover();
  const result = await postJson(`/api/orders/${encodeURIComponent(order.order_id)}/recover`,
    { client_request_id: newRequestId(), decision, evidence, operator: operator || null,
      note: note || null });
  if (result.ok) {
    view.orders = view.orders.filter((item) => item.order_id !== order.order_id || decision !== "fail");
    const what = { resume: "재개", done: "사람 처리 기록 · 다음 단계로" }[decision];
    showMessage(order.robot_id, what
      ? `주문 ${order.order_id} ${what} 요청 접수 · 로봇 응답 대기`
      : `주문 ${order.order_id} 취소함 · 로봇 잠금 해제 응답 대기`,
    false);
  } else {
    showMessage(order.robot_id, `주문 복구 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

function updateRecoverButtons() {
  const ready = $("recover-confirm").checked;
  $("recover-again").disabled = !ready;
  $("recover-done").disabled = !ready;
}

// 멈춘 주문 막대를 연다. 카드 줄·상차 확인 띠의 [다시 / 주문 취소] 에서 온다.
function recoverOrder(robotId) {
  const order = orderBlocked(robotId);
  const host = barHost(robotId);
  if (!order || !host) return;
  closeBars();
  view.recovering = { robotId, orderId: order.order_id };
  const why = HOLD_TEXT[order.state] || (order.state === "UNKNOWN" ? "결과 모름" : order.state);
  $("recover-title").textContent = `${robotId} · 주문 ${order.order_id} (${order.sku}) 멈춤`;
  $("recover-what").textContent = `${order.stage} · ${why}${order.detail ? ` · ${order.detail}` : ""}`;
  $("recover-what").title = $("recover-what").textContent; // 긴 실패 이유는 마우스를 올려 전체를 본다
  $("recover-confirm").checked = false;
  $("recover-operator").value = savedOperator();
  $("recover-note").value = RECOVER_NOTE;
  $("recover-again").hidden = !(order.resumable || order.retryable);
  $("recover-again").textContent = order.resumable ? "이어서 가기" : "다시";
  $("recover-done").hidden = !order.hand_done;
  updateRecoverButtons();
  host.appendChild($("recover-bar"));
  $("recover-bar").hidden = false;
  if (view.detailRobot !== robotId) focusCard(robotId);
  $("recover-confirm").focus();
}

function closeRecover() {
  view.recovering = null;
  $("recover-bar").hidden = true;
}

function recoveringOrder() {
  const recovering = view.recovering;
  return recovering && view.orders.find((order) => order.order_id === recovering.orderId);
}

// [다시]/[이어서 가기]. 팔 단계는 물건을 처음 자리에 돌려놓았는지 한 번 더 묻는다 (item_ready).
function recoverAgain() {
  const order = recoveringOrder();
  if (!order || $("recover-again").disabled) return;
  if (order.resumable) {
    sendOrderRecover(order, "resume");
    return;
  }
  const from = RETRY_FROM[order.stage] || order.stage;
  if (!confirm([`${order.robot_id} · ${order.stage} 를 ${from} 부터 다시 할까요?`,
    "물건을 이 작업 시작 전 자리(선반·적재함)에 돌려놓았나요?",
    "확인을 누르면 팔이 처음부터 다시 움직입니다."].join("\n"))) return;
  sendOrderRecover(order, "resume", { arms_safe: true, item_ready: true });
}

// [사람이 처리함]: 하차·정리·선반 반환을 사람이 대신 했을 때. 하차는 다음 비전 확인을 그대로 거친다.
function recoverDone() {
  const order = recoveringOrder();
  if (!order || $("recover-done").disabled) return;
  if (!confirm([`${order.robot_id} · ${order.stage} 를 사람이 처리했나요?`,
    "물건을 놓을 자리에 놓았나요? 이 단계를 완료로 적고 다음 단계로 갑니다."].join("\n"))) return;
  sendOrderRecover(order, "done", { arms_safe: true, item_placed: true });
}

// [주문 취소]: 예약을 풀기 전 현장 정리 3가지를 하나씩 묻는다.
function recoverCancel() {
  const order = recoveringOrder();
  if (!order) return;
  if (!confirm([`주문 ${order.order_id} (${order.sku}) 을 취소할까요?`, `${order.robot_id} · ${order.stage}`,
    "예약을 풀기 전에 현장 정리가 끝나 있어야 합니다. 다음 세 항목을 각각 확인합니다."].join("\n"))) return;
  const evidence = {};
  for (const [key, question] of [
    ["arms_safe", "로봇팔이 멈추고 안전한 위치로 퇴피했나요?"],
    ["cargo_reconciled", "화물을 꺼내거나 인계해 주문의 화물 정리를 마쳤나요?"],
    ["resources_clear", "예약된 작업장과 통로에서 로봇·화물이 이탈해 다른 작업이 사용해도 안전한가요?"],
  ]) {
    if (!confirm(question)) return;
    evidence[key] = true;
  }
  sendOrderRecover(order, "fail", evidence);
}

function setupRecover() {
  $("recover-confirm").addEventListener("change", updateRecoverButtons);
  $("recover-close").addEventListener("click", closeRecover);
  $("recover-again").addEventListener("click", recoverAgain);
  $("recover-done").addEventListener("click", recoverDone);
  $("recover-cancel").addEventListener("click", recoverCancel);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view.recovering) closeRecover();
  });
}
