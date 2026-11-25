// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 제어권 복구 (fleet_control 정지 잠금 해제).
// fleet 에서는 비상정지·주문 중 정지 뒤, 또는 움직이던 중 하트비트 끊김·관제 재시작 뒤 로봇이 잠긴다
// (놀던 로봇은 잠기지 않음, commands.js latchText).
// 카드의 빨간 '정지 잠금' 줄을 누르면 확인 창이 한 번 뜨고, 확인하면
// POST /api/robots/{id}/release_control 로 보낸다. 정지 상태 검사는 fleet 이 한다.
// 202는 접수이며 로봇 해제 응답 전에는 보류·UNKNOWN 표시를 유지한다.
// 누가 눌렀는지는 백엔드가 접속 IP 로 기록한다. 구역 안에서 잠긴 로봇도 복구한 뒤 '나가기'로 빼낸다.
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
    // 보류와 UNKNOWN 표시는 실제 로봇 확인 후 내려오는 상태로만 갱신한다.
    showMessage(robotId, ["복구 요청 접수 · 로봇 잠금 해제 응답 대기", hadUnknown ? "확인 후 결과 모름을 실패로 기록" : "",
      view.commandsArmed ? "" : "작업 명령은 꺼져 있음 (상단에서 켬)"].filter(Boolean).join(" · "), false);
  } else {
    showMessage(robotId, `복구 거절 (${result.status}): ${errorText(result)}`, true);
  }
}

// 구역 강제 해제: 로봇이 구역 토큰을 쥔 채 꺼지면 zone_manager 는 그 로봇의 이탈 통보 전까지
// 점유를 놓지 않고, 다시 켜진 로봇은 토큰을 잊어 '나가기'를 거절한다 (no zone held).
// 이때만 현장 확인 뒤 관제가 그 로봇 이름으로 이탈 통보를 낸다 (POST /api/zones/{zone}/release).
// 버튼은 (a) 로봇 연결 끊김, 또는 (b) 연결됐고 멈춰 있고 그 구역을 잡고 있지 않다고 보고할 때만 보인다.
// 살아 있고 아직 잡고 있다고 아는 로봇은 '나가기'로 뺀다. 최종 검사는 fleet_control 이 한다.
function zoneReleaseAllowed(zone, robotId) {
  if (view.readOnly || !view.controllerOnline) return false;
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  if (!robot) return false;
  if (!robot.online) return true;
  const extra = robot.extra || {};
  return extra.busy === false && "held_zone" in extra && extra.held_zone !== zone;
}

// 홈 초기위치 때 같이 풀 후보: 연결된 로봇이 다시 켜져 잊은 구역 (위 (b)). 끊긴 로봇은 넣지 않는다.
function forgottenZones(robotId) {
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  if (!robot || !robot.online || (robot.extra || {}).held_zone !== null) return [];
  return Object.entries(view.snapshot.zones || {})
    .filter(([zone, value]) => value === `occupied_by:${robotId}` && zoneReleaseAllowed(zone, robotId))
    .map(([zone]) => zone);
}

function zoneReleaseHint(robotId) {
  const robot = view.snapshot && view.snapshot.robots && view.snapshot.robots[robotId];
  return robot && robot.online ? `${robotId} 가 다시 켜져 구역 토큰을 잊음 · 현장 확인 후 해제`
    : `${robotId} 연결 끊김 · 현장 확인 후 해제`;
}

async function openZoneRelease(zone, robotId) {
  closeBars();
  const waiting = (view.snapshot && view.snapshot.queues && view.snapshot.queues[zone]) || [];
  if (!confirm([`구역 ${zone} 을 강제로 풀까요? (점유: ${robotId})`, zoneReleaseHint(robotId),
    `현장에서 ${robotId} 가 구역 ${zone} 밖에 있는지 확인했나요?`,
    waiting.length ? `풀면 대기 중인 ${waiting[0]} 이(가) 바로 들어옵니다.`
      : "풀면 다음에 요청한 로봇이 바로 들어옵니다."].join("\n"))) return;
  const result = await postJson(`/api/zones/${encodeURIComponent(zone)}/release`,
    { robot_id: robotId, client_request_id: newRequestId() });
  if (result.ok) {
    showMessage(robotId, `구역 ${zone} 강제 해제 요청 보냄 · zone_manager 상태가 바뀌면 비어 있음으로 보임`, false);
  } else {
    showMessage(robotId, `구역 ${zone} 강제 해제 거절 (${result.status}): ${errorText(result)}`, true);
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
      reason: `주문 ${order.order_id} 멈춤: ${recoverChoices(order)} 중 고르기`,
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
