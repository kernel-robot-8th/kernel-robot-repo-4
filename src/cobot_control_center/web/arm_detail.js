// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 로봇팔 상세 화면 (주소 #/arm/<팔>, 예: #/arm/omx_1).
// 전체 화면(.layout)을 숨기고 한 팔 전용 배치(#arm-page)를 보인다:
//   머리줄(← 전체, 팔 이름, 자리·PC, 다른 팔로 가기) → 카메라 2대(위 top | 손목 wrist) → 상태 카드 | 그 팔 기록.
//   위 카메라 칸의 '맞추기' 는 학습 화면과 겹쳐 핑키 정차 위치를 맞춘다 (arm_align.js).
// 상태 카드는 전체 화면 팔 카드와 같은 템플릿·그리기 함수(arms.js makeArmCard·renderArmCard)를 쓴다.
// 켜기·끄기·정지도 같은 sendArmCommand 로 보낸다. 작업 시험 줄은 상세에서는 숨긴다 (전체 화면 카드에서).
//
// 영상은 백엔드 /api/arms/<팔>/camera/<역할> (MJPEG) 로만 받는다. 백엔드가 팔 실행기(omx_fleet cam_preview)의
// 미리보기를 받아 중계한다. 카메라는 실행기가 켜기~끄기 동안 열어 두므로 팔이 꺼져 있으면 영상도 없다.
// 화면을 떠나면 src 를 지워 연결을 끊는다 (백엔드는 보는 사람이 없으면 원본 연결도 끊는다, cctv.js 와 같은 방식).
// 팔이 보낸 문자열은 textContent 로만 넣는다.

"use strict";

const ARM_ROUTE_PREFIX = "#/arm/";
const ARM_CAM_ROLES = ["top", "wrist"];
const ARM_CAM_POLL_MS = 2000;     // /api/health 의 arm_cameras 를 읽는 간격
const ARM_CAM_STALE_SEC = 3;      // 마지막 장면이 이보다 오래되면 '멈춤' 으로 본다 [s]
const ARM_DETAIL_LOG_MAX = 100;   // 상세 화면 기록 칸에 보일 줄 수

const armDetail = {
  armId: null,     // 지금 보고 있는 팔 (없으면 null)
  card: null,      // 상세 화면 상태 카드 (팔이 바뀌면 새로 만든다: 버튼이 팔 이름을 붙잡고 있어서)
  timer: null,
  cams: null,      // /api/health 의 arm_cameras[팔] (undefined = 아직 모름, null = 주소 없음)
  got: {},         // 역할 → 장면을 한 번이라도 받았는지
};

function armDetailHref(armId) {
  return ARM_ROUTE_PREFIX + encodeURIComponent(armId);
}

function routeArm() {
  if (!location.hash.startsWith(ARM_ROUTE_PREFIX)) return null;
  const id = decodeURIComponent(location.hash.slice(ARM_ROUTE_PREFIX.length));
  return id || null;
}

// 주소가 바뀌면 팔 상세 화면을 켜고 끈다.
function applyArmRoute() {
  const armId = routeArm();
  if (armId === armDetail.armId) return;
  armAlignStop();   // 정차 위치 맞추기 (arm_align.js) 는 팔이 바뀌면 끈다
  armCamStop();
  if (armDetail.card) armDetail.card.remove();
  armDetail.card = null;
  armDetail.armId = armId;
  const on = armId !== null;
  document.body.classList.toggle("arm-mode", on);
  $("arm-page").hidden = !on;
  if (on) {
    window.scrollTo(0, 0);
    armDetail.card = makeArmCard(armId);
    $("ad-card").replaceChildren(armDetail.card);
    renderArmDetail();
    armCamStart();
  } else {
    if (!view.detailRobot) document.title = "로봇 관제";
    // 숨어 있던 동안 잰 크기가 틀렸을 수 있어 전체 지도를 다시 잰다 (detail.js 와 같은 이유)
    layoutMap();
    drawMap();
  }
}

// ---------- 상태 (arms.js pollArms 가 1 s 마다 부른다) ----------

function armDetailCanCommand() {
  const data = armsView.data;
  return armsView.ok && Boolean(data && data.controller_online) && !view.readOnly;
}

function renderArmDetail(canCommand = armDetailCanCommand()) {
  const armId = armDetail.armId;
  if (armId === null || !armDetail.card) return;
  // 다른 페이지(네트워크 등)가 닫히며 제목을 되돌릴 수 있어 그릴 때마다 맞춘다.
  document.title = `${armId} · 로봇팔 · 로봇 관제`;
  const arms = armList();
  const arm = arms.find((a) => a.arm_id === armId);
  // 팔 목록을 받았는데 그 팔이 없을 때만 '등록되지 않은 로봇팔' (받기 전·명령 노드 꺼짐이면 모름).
  const missing = arms.length > 0 && !arm;
  $("ad-missing").hidden = !missing;
  $("ad-videos").hidden = missing;
  $("ad-lower").hidden = missing;
  $("ad-name").textContent = armId;
  const site = $("ad-site");
  site.textContent = arm ? siteText(arm) : "";
  site.title = arm ? siteTitle(arm) : "";
  renderArmSwitch(arms, armId);
  if (arm) renderArmCard(arm, canCommand, armDetail.card);
  if (!armsView.ok) {
    armDetail.card.classList.add("offline");
    armDetail.card.querySelectorAll("button, select").forEach((b) => { b.disabled = true; });
  }
  $("ad-joints").textContent = arm ? jointsText(arm.status) : "로봇팔 명령 노드 상태 수신 대기";
  renderArmDetailLog(armId);
  renderArmCamMeta();
}

// 머리줄 오른쪽: 다른 팔로 바로 가는 링크 (ZA omx_1 · ZB omx_2 …)
function renderArmSwitch(arms, armId) {
  const nav = $("ad-switch");
  const key = arms.map((a) => `${a.arm_id}:${a.site ? a.site.station : ""}`).join(",") + `|${armId}`;
  if (nav.dataset.key === key) return;
  nav.dataset.key = key;
  nav.replaceChildren(...arms.map((a) => {
    const link = document.createElement("a");
    link.href = armDetailHref(a.arm_id);
    link.textContent = a.site && a.site.station ? `${a.site.station} ${a.arm_id}` : a.arm_id;
    if (a.arm_id === armId) link.setAttribute("aria-current", "page");
    return link;
  }));
}

function renderArmDetailLog(armId) {
  const box = $("ad-events");
  const shown = armsView.log.filter((e) => e.arm === armId).slice(-ARM_DETAIL_LOG_MAX).reverse();
  $("ad-log-count").textContent = shown.length ? `최근 ${shown.length}건` : "";
  const key = shown.length ? `${shown.length}:${shown[0].id}` : "0";
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  if (!shown.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "기록 없음 (백엔드를 다시 켜면 지워짐)";
    box.replaceChildren(empty);
    return;
  }
  box.replaceChildren(...shown.map((event) => {
    const item = document.createElement("li");
    item.dataset.level = event.level;
    item.dataset.source = "arm";
    const time = document.createElement("time");
    time.textContent = formatTime(event.time);
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = event.text;
    item.append(time, text);
    return item;
  }));
}

// ---------- 카메라 ----------

function armCamEl(role) {
  return document.querySelector(`.ad-cam[data-role="${role}"]`);
}

function armCamShowEmpty(role, text) {
  const wrap = armCamEl(role);
  const img = wrap.querySelector("img");
  const empty = wrap.querySelector(".camera-empty");
  // 한 번 받은 장면은 그대로 두고(멈춘 장면이라도 보이게) 글만 바꾼다. 받은 적이 없으면 글만 보인다.
  img.hidden = !armDetail.got[role];
  empty.hidden = Boolean(armDetail.got[role]);
  empty.textContent = text;
}

function armCamAttach(role) {
  const img = armCamEl(role).querySelector("img");
  if (img.getAttribute("src")) return;
  // 같은 주소를 다시 열 때 브라우저가 예전 연결을 재사용하지 않게 매번 다른 쿼리를 붙인다.
  img.src = `/api/arms/${encodeURIComponent(armDetail.armId)}/camera/${role}?t=${Date.now()}`;
}

function armCamStart() {
  armDetail.cams = undefined;
  ARM_CAM_ROLES.forEach((role) => {
    armDetail.got[role] = false;
    armCamShowEmpty(role, "연결 중…");
  });
  pollArmCams();
  armDetail.timer = setInterval(pollArmCams, ARM_CAM_POLL_MS);
}

function armCamStop() {
  if (armDetail.timer) clearInterval(armDetail.timer);
  armDetail.timer = null;
  ARM_CAM_ROLES.forEach((role) => {
    const img = armCamEl(role).querySelector("img");
    // src 를 지우면 브라우저가 MJPEG 연결을 닫는다.
    img.removeAttribute("src");
    img.hidden = true;
    armDetail.got[role] = false;
  });
}

async function pollArmCams() {
  const armId = armDetail.armId;
  if (armId === null) return;
  let cams;
  try {
    const res = await fetch("/api/health");
    cams = res.ok ? ((await res.json()).arm_cameras || {})[armId] || null : undefined;
  } catch (err) {
    cams = undefined;
  }
  if (armId !== armDetail.armId) return;   // 기다리는 사이 다른 팔로 옮김
  armDetail.cams = cams;
  // 주소가 있는 역할만 연결한다 (없으면 404 라 붙지 않는다).
  if (cams) ARM_CAM_ROLES.forEach((role) => { if (cams[role]) armCamAttach(role); });
  renderArmCamMeta();
}

// 영상 칸 위 글: 연결 상태 (/api/health arm_cameras) + 팔 상태로 '왜 영상이 없는지'
function armCamStatus(role) {
  const cams = armDetail.cams;
  if (cams === undefined) return { meta: "백엔드 응답 확인 중", empty: "연결 중…" };
  if (cams === null || !cams[role]) {
    return { meta: "", empty: "이 팔 카메라 주소가 설정되지 않음 (config/site_arms.yaml 의 video)" };
  }
  const status = cams[role];
  const age = status.age_sec;
  if (status.connected && age !== null && age !== undefined && age < ARM_CAM_STALE_SEC) {
    return { meta: `연결됨 · ${age.toFixed(1)}초 전 장면`, empty: null };
  }
  const arm = armList().find((a) => a.arm_id === armDetail.armId);
  const off = arm && (arm.state === "OFF" || arm.state === "STALE" || arm.state === "FAULT");
  if (status.connected) {
    const stale = age !== null && age !== undefined ? `${age.toFixed(0)}초 전 장면에서 멈춤` : "장면 기다리는 중";
    return { meta: `연결됨 · ${stale}`, empty: "장면 기다리는 중…" };
  }
  if (off) {
    const state = (ARM_STATE[arm.state] || ARM_STATE.STALE).text;
    return { meta: `팔 ${state}`, empty: `팔이 ${state} 상태라 영상 없음 (카메라는 팔을 켜면 실행기가 엽니다)` };
  }
  const why = status.error ? `원본 끊김: ${status.error}` : "연결 중…";
  return { meta: why, empty: `영상 없음 (${status.url} 에 닿지 않음, 다시 시도 중)\n팔 실행기 fleet_arms.yaml 의 preview 설정 확인` };
}

function renderArmCamMeta() {
  if (armDetail.armId === null) return;
  ARM_CAM_ROLES.forEach((role) => {
    const { meta, empty } = armCamStatus(role);
    const metaEl = document.querySelector(`.ad-cam-meta[data-role="${role}"]`);
    metaEl.textContent = meta;
    if (empty === null) {
      const wrap = armCamEl(role);
      wrap.querySelector("img").hidden = !armDetail.got[role];
      wrap.querySelector(".camera-empty").hidden = Boolean(armDetail.got[role]);
    } else {
      armCamShowEmpty(role, empty);
    }
  });
}

function setupArmDetail() {
  ARM_CAM_ROLES.forEach((role) => {
    const img = armCamEl(role).querySelector("img");
    img.addEventListener("load", () => {
      armDetail.got[role] = true;
      img.hidden = false;
      armCamEl(role).querySelector(".camera-empty").hidden = true;
    });
    img.addEventListener("error", () => {
      // 스트림이 끊기면(백엔드 재시작·404) src 를 비워 두고, 다음 확인 때 다시 붙인다.
      if (armDetail.armId === null) return;
      img.removeAttribute("src");
      armCamShowEmpty(role, "영상 끊김, 다시 연결 중…");
    });
  });
  setupArmAlign();
  window.addEventListener("hashchange", applyArmRoute);
  applyArmRoute();
}
