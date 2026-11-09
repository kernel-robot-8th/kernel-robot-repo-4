// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 제어권 복구 (fleet_control 정지 잠금 해제) 띠.
// fleet 에서는 정지·비상정지·하트비트 끊김·관제 재시작 뒤 로봇이 잠긴다 (commands.js latchText).
// 카드의 빨간 '정지 잠금' 줄을 누르면 이 띠가 뜨고, 현장 확인 4가지·운영자·메모를 받아
// POST /api/robots/{id}/release_control 로 보낸다. 검사(멈춤·구역 미점유·최근 상태·주문 없음)는 fleet 이 한다.
// fleet 은 지금 확인 4가지를 늘 요구한다. 띠가 카드 안에 들어가게 체크 하나로 묶어 네 항목을 함께 보낸다
// (항목 설명은 체크 줄의 마우스 설명). 규격이 바뀌어 시나리오 작업일 때만 요구하게 되면 여기서 나눈다.
// 서비스용 화면으로 옮겨 쓸 수 있게 이 파일에 모아 둔다 (barHost·postJson·showMessage 등은 commands.js).

"use strict";

const RELEASE_NOTE = "현장에서 정지 확인";
const OPERATOR_KEY = "cobot.operator"; // 운영자 이름을 이 브라우저에 기억한다
// release_control 의 evidence 항목: 멈춤 · 팔 안전 · 화물 확인 · 구역·자원 비움
const EVIDENCE_KEYS = ["base_stopped", "arms_safe", "cargo_reconciled", "resources_clear"];

function savedOperator() {
  try {
    return localStorage.getItem(OPERATOR_KEY) || "";
  } catch (err) {
    return "";
  }
}

function saveOperator(name) {
  try {
    localStorage.setItem(OPERATOR_KEY, name);
  } catch (err) {
    // 저장이 막혀 있어도 복구는 된다 (다음에 다시 적으면 된다).
  }
}

// 현장 확인 체크와 운영자 이름이 있어야 보낼 수 있다.
function updateReleaseButton() {
  const ready = $("release-confirm").checked && $("release-operator").value.trim() !== "";
  $("release-ok").disabled = !ready;
}

function openRelease(robotId) {
  const host = barHost(robotId);
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  if (!host || !robot) return;
  cancelPick();
  closeResolve();
  closeLoad();
  view.releasing = robotId;
  $("release-title").textContent = `${robotId} · 제어권 복구`;
  $("release-what").textContent = latchText(robotId, robot) || "";
  $("release-confirm").checked = false;
  $("release-operator").value = savedOperator();
  $("release-note").value = RELEASE_NOTE;
  updateReleaseButton();
  host.appendChild($("release-bar"));
  $("release-bar").hidden = false;
  if (view.detailRobot !== robotId) focusCard(robotId);
  $("release-confirm").focus();
}

function closeRelease() {
  view.releasing = null;
  $("release-bar").hidden = true;
}

async function sendRelease() {
  const robotId = view.releasing;
  if (!robotId || $("release-ok").disabled) return;
  const operator = $("release-operator").value.trim();
  const note = $("release-note").value.trim() || RELEASE_NOTE;
  const confirmed = $("release-confirm").checked;
  const evidence = Object.fromEntries(EVIDENCE_KEYS.map((key) => [key, confirmed]));
  saveOperator(operator);
  $("release-ok").disabled = true;
  const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/release_control`,
    { client_request_id: newRequestId(), operator, note, evidence });
  closeRelease();
  if (result.ok) {
    // 다음 /api/health 를 기다리지 않고 보류 표시를 바로 지운다.
    delete view.holds[robotId];
    showMessage(robotId, "복구함 · 작업 명령은 꺼져 있음 (상단에서 켬)", false);
  } else {
    showMessage(robotId, `복구 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

function setupRelease() {
  $("release-confirm").addEventListener("change", updateReleaseButton);
  $("release-operator").addEventListener("input", updateReleaseButton);
  $("release-ok").addEventListener("click", sendRelease);
  $("release-cancel").addEventListener("click", closeRelease);
  $("release-note").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendRelease();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && view.releasing) closeRelease();
  });
}

// 카드·상세 화면의 상태 줄을 눌렀을 때: 결과 모름 해제가 먼저, 다음 수동 상차 확인(load.js),
// 아니면 정지 잠금 복구.
function onCmdHeadClick(robotId) {
  if (!robotId) return;
  const unknown = robotTask(robotId, new Set(["UNKNOWN"]));
  if (unknown) {
    openResolve(unknown);
    return;
  }
  if (loadWaiting(robotId)) {
    openLoad(robotId);
    return;
  }
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  if (robot && latchText(robotId, robot)) openRelease(robotId);
}
