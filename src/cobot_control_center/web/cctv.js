// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 현장영상: 상단 '현장영상' 버튼 → 창(dialog)에 천장 CCTV 를 띄운다.
// 영상은 백엔드 /api/cctv (MJPEG) 로만 받는다. 백엔드가 유선망 장치에서 받아 중계하므로
// 관제 웹이 열리는 곳이면 어디서든 보인다. 창을 닫으면 src 를 지워 연결을 끊는다
// (백엔드는 보는 사람이 없으면 원본 연결도 끊는다).

"use strict";

const CCTV_STATUS_MS = 2000;   // 창이 열려 있는 동안 /api/health 의 cctv 상태를 읽는 간격

const cctv = { timer: null, gotFrame: false };

function cctvShowEmpty(text) {
  $("cctv-img").hidden = true;
  const empty = $("cctv-empty");
  empty.hidden = false;
  empty.textContent = text;
}

function cctvStart() {
  const img = $("cctv-img");
  cctv.gotFrame = false;
  cctvShowEmpty("연결 중…");
  $("cctv-meta").textContent = "";
  // 같은 주소를 다시 열 때 브라우저가 예전 연결을 재사용하지 않게 매번 다른 쿼리를 붙인다.
  img.src = `/api/cctv?t=${Date.now()}`;
  cctvPollStatus();
  cctv.timer = setInterval(cctvPollStatus, CCTV_STATUS_MS);
}

function cctvStop() {
  const img = $("cctv-img");
  // src 를 지우면 브라우저가 MJPEG 연결을 닫는다.
  img.removeAttribute("src");
  img.hidden = true;
  if (cctv.timer) clearInterval(cctv.timer);
  cctv.timer = null;
}

async function cctvPollStatus() {
  let status = null;
  try {
    const res = await fetch("/api/health");
    if (res.ok) status = (await res.json()).cctv;
  } catch (err) {
    status = undefined;
  }
  const meta = $("cctv-meta");
  if (status === undefined) {
    meta.textContent = "백엔드 응답 없음";
    return;
  }
  if (status === null) {
    cctvShowEmpty("현장영상 주소가 설정되지 않음 (fleet_api_node.yaml 의 cctv_url)");
    meta.textContent = "";
    return;
  }
  const age = status.age_sec;
  if (status.connected && age !== null && age < 3) {
    meta.textContent = `연결됨 · ${age.toFixed(1)}초 전 장면`;
  } else if (status.error) {
    meta.textContent = `원본 끊김: ${status.error}`;
    if (!cctv.gotFrame) cctvShowEmpty(`영상 없음 (${status.url} 에 닿지 않음, 다시 시도 중)`);
  } else {
    meta.textContent = status.connected ? "연결됨 · 장면 기다리는 중" : "연결 중…";
  }
}

function setupCctv() {
  const dialog = $("cctv-dialog");
  const img = $("cctv-img");
  $("cctv-btn").addEventListener("click", () => {
    if (dialog.open) return;
    dialog.showModal();
    cctvStart();
  });
  $("cctv-close").addEventListener("click", () => dialog.close());
  // Esc·닫기 버튼·바깥 누름 모두 close 이벤트로 모아 연결을 끊는다.
  dialog.addEventListener("close", cctvStop);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  img.addEventListener("load", () => {
    cctv.gotFrame = true;
    img.hidden = false;
    $("cctv-empty").hidden = true;
  });
  img.addEventListener("error", () => {
    if (dialog.open) cctvShowEmpty("영상 없음 (백엔드 /api/cctv 오류)");
  });
}

setupCctv();
