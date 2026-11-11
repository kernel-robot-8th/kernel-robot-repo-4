// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 제어권 복구 (fleet_control 정지 잠금 해제).
// fleet 에서는 비상정지·주문 중 정지 뒤, 또는 움직이던 중 하트비트 끊김·관제 재시작 뒤 로봇이 잠긴다
// (놀던 로봇은 잠기지 않음, commands.js latchText).
// 카드의 빨간 '정지 잠금' 줄을 누르면 확인 창이 한 번 뜨고, 확인하면
// POST /api/robots/{id}/release_control 로 보낸다. 검사(보류·잠금 있음·주문 없음)는 fleet 이 한다.
// 주문 없는(그냥 주행하는) 로봇이라 보통 방식대로 확인 한 번이면 된다 (2026-11-09 임시 일반형).
// 누가 눌렀는지는 백엔드가 접속 IP 로 기록한다. 구역 안에서 잠긴 로봇도 복구한 뒤 '나가기'로 빼낸다.
// TODO(시나리오): 신발매장 시나리오가 정해지면 멈춘 단계별 확인 항목과 주문 복구 띠를 붙인다
//   (draft/safety_locks_review.md 8절).
// 서비스용 화면으로 옮겨 쓸 수 있게 이 파일에 모아 둔다 (postJson·showMessage 등은 commands.js).

"use strict";

const OPERATOR_KEY = "cobot.operator"; // 운영자 이름을 이 브라우저에 기억한다 (load.js 상차 확인이 씀)

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
    // 저장이 막혀 있어도 확인은 된다 (다음에 다시 적으면 된다).
  }
}

// 확인 창 문구. 결과 모름 작업이 함께 있으면 실패로 기록된다는 것도 알린다.
function releaseQuestion(robotId) {
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  const unknown = robotTask(robotId, UNKNOWN_TASK);
  return [`${robotId} 복구할까요?`, robot ? (latchText(robotId, robot) || "정지 잠금") : "",
    "현장에서 로봇이 멈춰 있고 주변이 안전한지 확인했나요?",
    unknown ? `결과 모름 작업 ${unknown.command} 은 실패로 기록합니다.` : "",
    "구역 안이면 복구한 뒤 '나가기'로 빼냅니다."].filter(Boolean).join("\n");
}

async function openRelease(robotId) {
  if (!robotId) return;
  closeBars();
  if (!confirm(releaseQuestion(robotId))) return;
  const hadUnknown = Boolean(robotTask(robotId, UNKNOWN_TASK));
  const result = await postJson(`/api/robots/${encodeURIComponent(robotId)}/release_control`,
    { client_request_id: newRequestId() });
  if (result.ok) {
    // 다음 /api/health 를 기다리지 않고 보류 표시를 바로 지운다.
    delete view.holds[robotId];
    showMessage(robotId, ["복구함", hadUnknown ? "결과 모름은 실패로 기록" : "",
      view.commandsArmed ? "" : "작업 명령은 꺼져 있음 (상단에서 켬)"].filter(Boolean).join(" · "), false);
  } else {
    showMessage(robotId, `복구 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

// 지금 이 로봇에서 사람이 풀어야 할 문제 하나 (없으면 null). 카드 줄 글(text)·명령 버튼을 막는
// 이유(reason)·눌렀을 때 여는 것(open)을 이 한 곳에서 정한다 (카드 줄·클릭·작업 목록 버튼이 함께 씀).
// 순서: 수동 상차 확인 → 멈춘 주문 → 보류 중 결과 모름(제어권 복구) → 결과 모름 해제 → 정지 잠금.
// 보류 중인 로봇은 복구(release_control) 하나로 결과 모름까지 푼다. 결과 모름 해제(resolve)보다 먼저인
// 것은 복구가 그 로봇의 UNKNOWN 작업도 실패로 기록하기 때문이다 (control_api._release_control).
// skipLoad: 상차 확인 대기는 명령 버튼을 막지 않으므로, 버튼 이유·작업 목록에서는 그다음 문제를 본다.
function currentProblem(robotId, skipLoad = false) {
  if (!robotId) return null;
  const load = skipLoad ? null : loadWaiting(robotId);
  if (load) {
    return { kind: "load", text: loadText(load, true), reason: "", open: () => openLoad(robotId) };
  }
  const order = orderBlocked(robotId);
  if (order) {
    return { kind: "order", text: orderBlockedText(order),
      reason: `주문 ${order.order_id} 멈춤: 이어서 가기 또는 취소 필요`,
      open: () => recoverOrder(robotId) };
  }
  const unknown = robotTask(robotId, UNKNOWN_TASK);
  if (unknown) {
    const held = Boolean(view.holds[robotId]);
    return { kind: held ? "release" : "unknown",
      text: held ? `결과 모름: ${unknown.command} · 정지 잠금 · 눌러서 현장 확인 후 복구`
        : `결과 모름: ${unknown.command} · 눌러서 현장 확인 후 해제`,
      reason: `결과 모름 작업 ${unknown.task_id}: 현장 확인 후 ${held ? "복구" : "해제"}`,
      open: held ? () => openRelease(robotId) : () => openResolve(unknown) };
  }
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  const latched = robot ? latchText(robotId, robot, true) : null;
  if (latched) {
    return { kind: "latch", text: latched, reason: latchText(robotId, robot),
      open: () => openRelease(robotId) };
  }
  return null;
}

// 카드·상세 화면의 상태 줄을 눌렀을 때: 지금 문제를 연다.
function onCmdHeadClick(robotId) {
  const problem = currentProblem(robotId);
  if (problem) problem.open();
}
