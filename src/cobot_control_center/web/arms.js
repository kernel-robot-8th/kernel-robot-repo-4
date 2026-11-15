// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 로봇팔 패널: 팔 상태(/api/arms)를 보여 주고 켜기·끄기·정지를 보낸다 (/api/arms/{arm_id}/command).
// 명령은 로봇팔 명령 노드(arm_command_node)가 ArmCommand 로 바꿔 Station PC 팔 노드에 낸다.
// 켜기는 연결·토크, 끄기는 쉬는 자세에서 토크 끄기뿐이다 (팔을 움직이지 않음).
// 작업 시험(/api/arms/{arm_id}/work)은 개발용으로 팔 하나에 작업 한 건을 시킨다. 실제 팔이 움직이므로
// 상단 '작업 명령 켜기'(commands.js renderArmToggle)가 켜져 있어야 한다. 켜기·끄기·정지는 스위치와 상관없다.
// 화면 스크립트는 index.html 에 적은 순서로 읽힌다 (core.js 먼저, main.js 마지막).

"use strict";

const ARMS_POLL_MS = 1000;

// arm_command_utils.py 의 화면 상태 → 배지 글·색 묶음
const ARM_STATE = {
  STALE: { text: "미연결", level: "na", hint: "팔 노드 상태가 안 들어옴 (Station PC 노드·도메인 확인)" },
  OFF: { text: "꺼짐", level: "idle", hint: "토크 꺼짐. 고장이면 마지막 응답 사유를 보고 끄기(RESET)로 풀기" },
  READY: { text: "대기", level: "good", hint: "켜짐, 작업을 받을 수 있음" },
  BUSY: { text: "작업·연결 중", level: "active", hint: "연결 중이거나 작업 중이거나 끄는 중" },
  HOLD: { text: "정지", level: "warn", hint: "정지 유지 중. 정지 해제 또는 끄기" },
  SOFT_LATCH: { text: "소프트 정지", level: "bad", hint: "소프트 정지 래치. 끄기(RESET)로만 풀림" },
};

// 웹 명령 이름 → 버튼 글·확인 창 (정지 계열은 확인 창 없이 바로 보낸다)
const ARM_COMMAND = {
  start: {
    text: "켜기",
    confirm: (armId, domain) => `${armId} 를 켤까요? (도메인 ${domain})\n\n`
      + "실제 팔이면 연결하면서 토크가 잠깐 꺼졌다 켜집니다.\n"
      + "팔이 쉬는 자세에 있고, 팔 옆에 사람이 있을 때만 켜세요.",
  },
  reset: {
    text: "끄기",
    confirm: (armId, domain) => `${armId} 를 끌까요? (도메인 ${domain})\n\n`
      + "쉬는 자세일 때만 토크를 끕니다. 아니면 팔 노드가 거절합니다 (팔을 옮기지 않음).\n"
      + "고장(FAULT) 상태라면 이 명령으로 꺼짐으로 돌아갑니다.",
  },
  release_hold: {
    text: "정지 해제",
    confirm: (armId) => `${armId} 정지를 풀까요?\n\n팔이 바로 움직이지는 않습니다. 다음 작업 요청부터 받습니다.`,
  },
  hold: { text: "정지" },
  soft_latch: { text: "소프트 정지" },
};
const ARM_STOPS = new Set(["hold", "soft_latch"]);
// 작업 시험 (arm_command_utils.WORK_ACTIONS). 화면 글만 여기서 정한다.
const ARM_WORK_TEXT = { pick: "집기 (pick)", load: "싣기 (load)", unload: "내리기 (unload)",
  warehouse_store: "창고 보관 (warehouse_store)" };
const ARM_WORK_STATE = { RUNNING: "진행 중", SUCCEEDED: "성공", FAILED: "실패", NO_RESULT: "결과 없음" };
const HOLD_REASON_TEXT = { HOLD: "정지 유지", SOFT_LATCH: "소프트 정지" };
const ARM_RESULT_TEXT = {
  ACCEPTED: "수락", REJECTED_EPOCH: "세션 번호 거절", REJECTED_SEQ: "순번 거절",
  REJECTED_TTL: "기한 지남 (두 PC 시계 확인)", REJECTED_STATE: "지금 상태에서 안 됨",
  REJECTED_ROBOT_ID: "대상 아님", REJECTED_SIGNATURE: "서명 거절",
};

const armsView = {
  data: null,         // /api/arms 응답
  ok: false,          // 마지막 /api/arms 를 받았는지
  cards: new Map(),   // arm_id → card element
  busy: new Set(),    // 응답을 기다리는 arm_id (정지 말고는 버튼을 잠근다)
  workActions: [],    // 스냅샷의 work_actions (선택 칸 채우기)
  msg: new Map(),     // arm_id → {text, bad, until}
};

function ensureArmCard(armId) {
  if (armsView.cards.has(armId)) return armsView.cards.get(armId);
  const card = $("arm-template").content.firstElementChild.cloneNode(true);
  card.querySelector(".name").textContent = armId;
  card.querySelectorAll("button[data-arm-cmd]").forEach((button) => {
    button.textContent = ARM_COMMAND[button.dataset.armCmd].text;
    button.addEventListener("click", () => sendArmCommand(armId, button.dataset.armCmd));
  });
  card.querySelector(".arm-work-btn").addEventListener("click",
    () => sendArmWork(armId, card.querySelector(".arm-work-action").value));
  $("arms").appendChild(card);
  armsView.cards.set(armId, card);
  return card;
}

function formatJoint(value) {
  return value === null || value === undefined ? "?" : value.toFixed(1);
}

// 퇴피 안전은 '쟀고 안전' 일 때만 녹색. 안 잰 것은 안전이 아니다 (ArmStatus.retract_safe_measured).
function retractText(status) {
  if (!status) return { text: "—", level: "na" };
  if (!status.retract_safe_measured) return { text: "미측정", level: "warn" };
  return status.retract_safe ? { text: "안전", level: "good" } : { text: "안전 아님", level: "bad" };
}

function ackText(ack) {
  if (!ack) return "";
  const what = ack.command ? `${ARM_COMMAND[ack.command] ? ARM_COMMAND[ack.command].text : ack.command} → ` : "";
  const result = ARM_RESULT_TEXT[ack.result] || ack.result;
  const stop = ack.stop_executed && !ack.accepted ? " (정지는 실행됨)" : "";
  const reason = ack.reason ? ` · ${ack.reason}` : "";
  return `마지막 응답 ${formatTime(ack.received_at)} ${what}${result}${stop}${reason}`;
}

function fillWorkActions(select) {
  if (select.options.length === armsView.workActions.length) return;
  const keep = select.value;
  select.replaceChildren(...armsView.workActions.map((action) => {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = ARM_WORK_TEXT[action] || action;
    return option;
  }));
  if (armsView.workActions.includes(keep)) select.value = keep;
}

function workText(work) {
  if (!work) return "";
  const what = ARM_WORK_TEXT[work.action] || work.action;
  const state = ARM_WORK_STATE[work.state] || work.state;
  if (work.state === "RUNNING") {
    return `작업 시험 ${what} ${state} · ${formatDuration(Date.now() / 1000 - work.sent_at)} 경과`;
  }
  const took = work.duration !== null && work.duration !== undefined ? ` · ${formatDuration(work.duration)}` : "";
  const retry = work.state === "FAILED" ? (work.retry_safe ? " · 팔 안 움직임" : " · 팔 자세 확인 필요") : "";
  const detail = work.detail ? ` · ${work.detail}` : "";
  return `작업 시험 ${formatTime(work.finished_at)} ${what} → ${state}${took}${retry}${detail}`;
}

function workBlockedReason(canCommand, allowed, running, waiting, meta) {
  if (!canCommand) return armsBlockedReason();
  if (!view.commandsArmed) return "작업 명령이 꺼져 있음 (화면 위 '작업 명령 켜기' 먼저)";
  if (running) return "앞 작업 시험이 진행 중";
  if (waiting) return "앞 명령의 응답을 기다리는 중";
  if (!allowed) return `대기 상태에서만 (지금 ${meta.text})`;
  return "실제 팔이 움직입니다. 주문 진행 중에는 쓰지 마세요";
}

function renderArmCard(arm, canCommand) {
  const card = ensureArmCard(arm.arm_id);
  const meta = ARM_STATE[arm.state] || ARM_STATE.STALE;
  const status = arm.status;
  card.dataset.level = meta.level;
  card.classList.toggle("offline", arm.state === "STALE");
  card.querySelector(".alias").textContent = arm.alias && arm.alias !== arm.arm_id
    ? `시나리오 ${arm.alias}` : "";
  const badge = card.querySelector(".arm-state");
  badge.dataset.level = meta.level;
  badge.textContent = meta.text;
  badge.title = meta.hint;

  const torque = card.querySelector(".arm-torque");
  torque.textContent = !status ? "—" : status.torque_enabled ? "켜짐" : "꺼짐";
  torque.dataset.level = !status ? "na" : status.torque_enabled ? "active" : "idle";
  const retract = retractText(status);
  const retractEl = card.querySelector(".arm-retract");
  retractEl.textContent = retract.text;
  retractEl.dataset.level = retract.level;
  const hold = card.querySelector(".arm-hold");
  hold.textContent = status && status.hold_active
    ? (HOLD_REASON_TEXT[status.hold_reason] || status.hold_reason || "정지") : "없음";
  hold.dataset.level = status && status.hold_active ? "warn" : "na";
  card.querySelector(".arm-session").textContent = `${arm.epoch} · ${arm.seq}`;

  // 관절 값: lerobot 단위(-100..100)는 명세 열거에 없어 joint_unit 이 비어 온다 → '단위 모름'
  const joints = card.querySelector(".arm-joints");
  if (status && status.joint_names && status.joint_names.length) {
    const values = status.joint_names.map((name, i) => `${name} ${formatJoint(status.joint_positions[i])}`);
    if (status.gripper_position !== null) values.push(`gripper ${formatJoint(status.gripper_position)}`);
    joints.textContent = values.join(" · ");
    joints.title = `단위 ${status.joint_unit || "모름 (lerobot -100..100)"} · 측정 ${formatTime(status.stamp)}`
      + " (작업 중에는 관절 값이 갱신되지 않음)";
  } else {
    joints.textContent = "관절 값 없음";
    joints.title = "";
  }
  card.querySelector(".arm-ack").textContent = ackText(arm.last_ack);
  card.querySelector(".arm-ack").dataset.bad = String(Boolean(arm.last_ack && !arm.last_ack.accepted));
  const workEl = card.querySelector(".arm-work");
  workEl.textContent = workText(arm.work);
  workEl.dataset.state = arm.work ? arm.work.state : "";
  workEl.title = arm.work ? `request ${arm.work.request_id} · seq ${arm.work.seq}` : "";

  const msg = armsView.msg.get(arm.arm_id);
  const msgEl = card.querySelector(".arm-msg");
  const showMsg = msg && msg.until > Date.now();
  msgEl.textContent = showMsg ? msg.text : "";
  msgEl.dataset.bad = String(Boolean(showMsg && msg.bad));

  const allowed = new Set(arm.allowed || []);
  const waiting = armsView.busy.has(arm.arm_id) || arm.pending > 0;
  card.querySelectorAll("button[data-arm-cmd]").forEach((button) => {
    const cmd = button.dataset.armCmd;
    // 정지는 응답을 기다리는 중에도 누를 수 있어야 한다.
    button.disabled = !canCommand || !allowed.has(cmd) || (waiting && !ARM_STOPS.has(cmd));
    button.title = !canCommand ? armsBlockedReason()
      : !allowed.has(cmd) ? `지금 상태(${meta.text})에서는 쓰지 않음`
      : waiting && !ARM_STOPS.has(cmd) ? "앞 명령의 응답을 기다리는 중" : "";
  });

  // 작업 시험: 스위치 켜짐 + 대기(서버가 allowed 에 work 를 넣음) + 앞 작업·명령 없음
  const select = card.querySelector(".arm-work-action");
  fillWorkActions(select);
  const running = Boolean(arm.work && arm.work.state === "RUNNING");
  const workOk = canCommand && view.commandsArmed && allowed.has("work") && !running && !waiting;
  const workBtn = card.querySelector(".arm-work-btn");
  workBtn.disabled = !workOk || !select.value;
  select.disabled = !workOk;
  workBtn.title = workBlockedReason(canCommand, allowed.has("work"), running, waiting, meta);
}

function armsBlockedReason() {
  if (view.readOnly) return "개발 화면 (읽기 전용): 실물 관제 화면(8080)에서";
  if (!armsView.ok) return "백엔드에 연결하지 못함";
  return "로봇팔 명령 노드(arm_command_node) 응답 없음";
}

function renderArms() {
  const data = armsView.data;
  const online = armsView.ok && Boolean(data && data.controller_online);
  const canCommand = online && !view.readOnly;
  const head = $("arms-meta");
  head.textContent = online ? "" : armsView.ok ? "명령 노드 꺼짐" : "백엔드 연결 안 됨";
  head.title = online ? "" : armsBlockedReason();
  const arms = (data && data.arms) || [];
  armsView.workActions = (data && data.work_actions) || [];
  const empty = $("arms-empty");
  empty.hidden = arms.length > 0;
  empty.textContent = armsView.ok ? "로봇팔 명령 노드(arm_command_node) 상태 수신 대기" : "백엔드 연결 안 됨";
  arms.forEach((arm) => renderArmCard(arm, canCommand));
  // 백엔드가 끊기면 마지막 카드는 남기되 버튼은 모두 잠근다.
  if (!armsView.ok) {
    armsView.cards.forEach((card) => {
      card.classList.add("offline");
      card.querySelectorAll("button, select").forEach((b) => { b.disabled = true; });
    });
  }
}

function showArmMessage(armId, text, bad) {
  armsView.msg.set(armId, { text, bad, until: Date.now() + MSG_MS });
  renderArms();
  setTimeout(renderArms, MSG_MS + 50);
}

async function sendArmCommand(armId, cmd) {
  const spec = ARM_COMMAND[cmd];
  if (spec.confirm && !confirm(spec.confirm(armId, view.healthDomain ?? "?"))) return;
  armsView.busy.add(armId);
  showArmMessage(armId, `${spec.text} 보냄, 팔 응답 기다리는 중…`, false);
  const result = await postJson(`/api/arms/${encodeURIComponent(armId)}/command`,
    { client_request_id: newRequestId(), command: cmd });
  armsView.busy.delete(armId);
  if (result.ok) {
    const late = result.data.accepted ? "" : " (정지는 실행됨)";
    showArmMessage(armId, `${spec.text} 수락${late}`, false);
  } else {
    const data = result.data || {};
    const why = data.reason || errorText(result);
    const kind = data.result ? ARM_RESULT_TEXT[data.result] || data.result : "";
    showArmMessage(armId, `${spec.text} 거절 (${result.status}${kind ? ` ${kind}` : ""}): ${why}`, true);
  }
  pollArms();
}

async function sendArmWork(armId, action) {
  const what = ARM_WORK_TEXT[action] || action;
  const question = `${armId} 에 작업 시험 '${what}' 을 시킬까요? (도메인 ${view.healthDomain ?? "?"})\n\n`
    + "실제 팔이 움직입니다. 팔 옆에 사람이 있고 작업 자리에 물건이 놓여 있을 때만 하세요.\n"
    + "주문이 진행 중이면 쓰지 마세요 (주문 작업과 같은 팔에서 부딪힙니다).";
  if (!action || !confirm(question)) return;
  armsView.busy.add(armId);
  showArmMessage(armId, `작업 시험 ${what} 보내는 중…`, false);
  const result = await postJson(`/api/arms/${encodeURIComponent(armId)}/work`,
    { client_request_id: newRequestId(), action });
  armsView.busy.delete(armId);
  if (result.ok) {
    showArmMessage(armId, `작업 시험 ${what} 보냄. 결과는 카드의 작업 시험 줄에 나옵니다`, false);
  } else {
    showArmMessage(armId, `작업 시험 ${what} 못 보냄 (${result.status}): ${errorText(result)}`, true);
  }
  pollArms();
}

async function pollArms() {
  try {
    const res = await fetch("/api/arms");
    if (!res.ok) throw new Error(String(res.status));
    armsView.data = await res.json();
    armsView.ok = true;
  } catch (err) {
    armsView.ok = false;
  }
  renderArms();
}

function setupArms() {
  pollArms();
  setInterval(pollArms, ARMS_POLL_MS);
}
