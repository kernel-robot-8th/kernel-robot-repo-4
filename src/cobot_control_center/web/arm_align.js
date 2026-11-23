// Copyright 2026 Pinky_Team4
// Licensed under the Apache License, Version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).
//
// 팔 상세화면 '정차 위치 맞추기' (위 카메라 칸의 '맞추기' 단추).
// 팔 모델은 지도 좌표가 아니라 위쪽 카메라 화면 속 자리로 학습됐다. 학습 때 화면(기준)을 지금 위쪽 영상에 겹쳐 보고,
// 고른 영역(접시·박스 자리)이 몇 픽셀 어긋났는지(dx·dy) 계속 보여 준다. 그 값이 0 근처가 되도록 핑키를 민다.
// 읽기만 한다: 팔·핑키에 아무것도 보내지 않는다.
//
// 기준 화면: /api/arms/<팔>/align/refs (목록), /api/arms/<팔>/align/refs/<이름> (이미지).
//   관제 PC 폴더(fleet_api_node.yaml align_refs_dir)에 omx_fleet/align_view.py --save-ref 로 뽑아 둔다.
// 지금 화면: /api/arms/<팔>/camera/top.jpg (백엔드가 중계 중인 마지막 장면 한 장). 위 카메라 <img> 가 MJPEG 을
//   보고 있어 중계가 붙어 있으므로, 여기서는 새 원본 연결을 열지 않고 마지막 장면만 가져온다.
// 계산은 브라우저에서 한다 (새 의존성 없음). align_view.py 는 phaseCorrelate 라 소수점 아래 값은 조금 다를 수 있다.
// 설명(label)은 textContent 로만 넣는다.

"use strict";

const ALIGN_TICK_MS = 200;        // 지금 장면을 가져와 다시 그리고 재는 간격 (약 5 Hz)
const ALIGN_GOOD_PX = 3;          // |dx|,|dy| 가 이 안이면 맞음 [px] (align_view draw_overlay 와 같은 값)
const ALIGN_MIN_SCORE = 0.6;      // 상관(NCC) 이보다 낮으면 '영역이 너무 다름' 으로 본다 (0~1)
const ALIGN_COARSE = 4;           // 크게 찾을 때 줄이는 배율
const ALIGN_COARSE_RANGE = 10;    // 줄인 화면에서 찾는 범위 [줄인 px] (= ±40 px)
const ALIGN_FINE_RANGE = 4;       // 원래 크기에서 다듬는 범위 [px]
const ALIGN_MIN_ROI = 16;         // 영역 한 변 최소 [px] (align_view clip_roi 와 같은 값)
const ALIGN_EDGE_LEVEL = 120;     // 기준 윤곽(Sobel 크기) 문턱
const ALIGN_MODES = { blend: "겹치기", edges: "기준 윤곽", diff: "차이" };

const armAlign = {
  on: false,
  armId: null,
  timer: null,
  busy: false,
  refName: "",
  ref: null,         // {canvas, gray, edges} 기준 화면 (캔버스 크기로 맞춘 것)
  liveGray: null,
  roi: null,         // {x, y, w, h} 캔버스 픽셀
  drag: null,
  lastShift: null,
};

// ---------- 순수 계산 (DOM 없음) ----------

// RGBA ImageData 값 → 흑백 Float32Array (BT.601, OpenCV COLOR_BGR2GRAY 와 같은 무게)
function alignGray(rgba, w, h) {
  const out = new Float32Array(w * h);
  for (let i = 0, p = 0; i < out.length; i += 1, p += 4) {
    out[i] = 0.299 * rgba[p] + 0.587 * rgba[p + 1] + 0.114 * rgba[p + 2];
  }
  return out;
}

// 흑백을 f 배 줄인다 (f x f 칸 평균). 남는 가장자리는 버린다.
function alignShrink(gray, w, h, f) {
  const sw = Math.floor(w / f);
  const sh = Math.floor(h / f);
  const out = new Float32Array(sw * sh);
  for (let y = 0; y < sh; y += 1) {
    for (let x = 0; x < sw; x += 1) {
      let sum = 0;
      for (let j = 0; j < f; j += 1) {
        const row = (y * f + j) * w + x * f;
        for (let i = 0; i < f; i += 1) sum += gray[row + i];
      }
      out[y * sw + x] = sum / (f * f);
    }
  }
  return { gray: out, w: sw, h: sh };
}

// 기준 영역 (평균을 뺀 값과 크기). 무늬가 없으면 null.
function alignTemplate(ref, w, roi) {
  const n = roi.w * roi.h;
  const values = new Float32Array(n);
  let mean = 0;
  for (let y = 0; y < roi.h; y += 1) {
    for (let x = 0; x < roi.w; x += 1) {
      const v = ref[(roi.y + y) * w + roi.x + x];
      values[y * roi.w + x] = v;
      mean += v;
    }
  }
  mean /= n;
  let norm = 0;
  for (let i = 0; i < n; i += 1) {
    values[i] -= mean;
    norm += values[i] * values[i];
  }
  return norm > 1e-6 ? { values, norm: Math.sqrt(norm) } : null;
}

// 기준 영역과, 지금 화면에서 (dx, dy) 옮긴 같은 크기 영역의 정규화 상관 (-1~1). 화면 밖이면 null.
function alignNcc(tpl, live, w, h, roi, dx, dy) {
  const x0 = roi.x + dx;
  const y0 = roi.y + dy;
  if (x0 < 0 || y0 < 0 || x0 + roi.w > w || y0 + roi.h > h) return null;
  let sum = 0;
  let sumSq = 0;
  let dot = 0;
  for (let y = 0; y < roi.h; y += 1) {
    const row = (y0 + y) * w + x0;
    const trow = y * roi.w;
    for (let x = 0; x < roi.w; x += 1) {
      const v = live[row + x];
      sum += v;
      sumSq += v * v;
      dot += tpl.values[trow + x] * v;   // 기준 평균이 0 이라 지금 화면 평균은 빼지 않아도 된다
    }
  }
  const n = roi.w * roi.h;
  const varLive = sumSq - (sum * sum) / n;
  if (varLive <= 1e-6) return null;
  return dot / (tpl.norm * Math.sqrt(varLive));
}

// 범위 안 정수 어긋남 중 상관이 가장 큰 것 {dx, dy, score, grid}. 하나도 못 재면 null.
function alignSearch(tpl, live, w, h, roi, cx, cy, range) {
  let best = null;
  const size = 2 * range + 1;
  const grid = new Array(size * size).fill(null);
  for (let j = -range; j <= range; j += 1) {
    for (let i = -range; i <= range; i += 1) {
      const score = alignNcc(tpl, live, w, h, roi, cx + i, cy + j);
      grid[(j + range) * size + (i + range)] = score;
      if (score !== null && (best === null || score > best.score)) {
        best = { dx: cx + i, dy: cy + j, score };
      }
    }
  }
  return best ? { ...best, grid, cx, cy, range } : null;
}

// 세 점 포물선의 꼭짓점 위치 (-0.5~0.5). 한쪽이 없으면 0.
function alignPeak(left, mid, right) {
  if (left === null || right === null) return 0;
  const denom = left - 2 * mid + right;
  if (Math.abs(denom) < 1e-9) return 0;
  return Math.max(-0.5, Math.min(0.5, 0.5 * (left - right) / denom));
}

/**
 * 영역 안에서 지금 화면이 기준보다 몇 픽셀 옮겨졌는지 {dx, dy, score} (align_view roi_shift 와 같은 부호).
 * dx > 0 이면 지금 화면의 물체가 기준보다 오른쪽, dy > 0 이면 아래에 있다. score 는 상관(0~1).
 * 1/ALIGN_COARSE 로 줄여 ±ALIGN_COARSE_RANGE 에서 크게 찾고, 원래 크기 ±ALIGN_FINE_RANGE 에서 다듬은 뒤
 * 포물선으로 소수점을 잡는다. 무늬가 없거나 너무 작으면 null.
 */
function alignShift(refGray, liveGray, w, h, roi) {
  if (!roi || roi.w < ALIGN_MIN_ROI || roi.h < ALIGN_MIN_ROI) return null;
  const f = ALIGN_COARSE;
  const sRef = alignShrink(refGray, w, h, f);
  const sLive = alignShrink(liveGray, w, h, f);
  const sRoi = { x: Math.floor(roi.x / f), y: Math.floor(roi.y / f),
    w: Math.max(4, Math.floor(roi.w / f)), h: Math.max(4, Math.floor(roi.h / f)) };
  const sTpl = alignTemplate(sRef.gray, sRef.w, sRoi);
  if (!sTpl) return null;
  const coarse = alignSearch(sTpl, sLive.gray, sLive.w, sLive.h, sRoi, 0, 0, ALIGN_COARSE_RANGE);
  if (!coarse) return null;
  const tpl = alignTemplate(refGray, w, roi);
  if (!tpl) return null;
  const fine = alignSearch(tpl, liveGray, w, h, roi, coarse.dx * f, coarse.dy * f, ALIGN_FINE_RANGE);
  if (!fine) return null;
  const size = 2 * fine.range + 1;
  const at = (i, j) => {
    const gi = fine.dx - fine.cx + fine.range + i;
    const gj = fine.dy - fine.cy + fine.range + j;
    if (gi < 0 || gj < 0 || gi >= size || gj >= size) return null;
    return fine.grid[gj * size + gi];
  };
  return {
    dx: fine.dx + alignPeak(at(-1, 0), fine.score, at(1, 0)),
    dy: fine.dy + alignPeak(at(0, -1), fine.score, at(0, 1)),
    score: Math.max(0, fine.score),
  };
}

// 기준 윤곽: Sobel 크기가 문턱을 넘는 곳을 초록 점으로 칠한 RGBA (나머지는 투명)
function alignEdges(gray, w, h, level = ALIGN_EDGE_LEVEL) {
  const out = new Uint8ClampedArray(w * h * 4);
  for (let y = 1; y < h - 1; y += 1) {
    for (let x = 1; x < w - 1; x += 1) {
      const i = y * w + x;
      const gx = gray[i - w + 1] + 2 * gray[i + 1] + gray[i + w + 1]
        - gray[i - w - 1] - 2 * gray[i - 1] - gray[i + w - 1];
      const gy = gray[i + w - 1] + 2 * gray[i + w] + gray[i + w + 1]
        - gray[i - w - 1] - 2 * gray[i - w] - gray[i - w + 1];
      if (Math.hypot(gx, gy) > level) {
        out[i * 4 + 1] = 255;
        out[i * 4 + 3] = 255;
      }
    }
  }
  return out;
}

// 마우스로 끈 두 점 → 화면 안으로 자른 영역. 너무 작으면 null.
function alignClipRoi(x0, y0, x1, y1, w, h) {
  const left = Math.max(0, Math.round(Math.min(x0, x1)));
  const top = Math.max(0, Math.round(Math.min(y0, y1)));
  const right = Math.min(w, Math.round(Math.max(x0, x1)));
  const bottom = Math.min(h, Math.round(Math.max(y0, y1)));
  if (right - left < ALIGN_MIN_ROI || bottom - top < ALIGN_MIN_ROI) return null;
  return { x: left, y: top, w: right - left, h: bottom - top };
}

// dx·dy → 사람이 읽는 안내 ("물체가 기준보다 오른쪽 5 px")
function alignAdvice(shift) {
  const parts = [];
  const side = (value, plus, minus) => {
    if (Math.abs(value) <= ALIGN_GOOD_PX) return;
    parts.push(`${value > 0 ? plus : minus} ${Math.abs(value).toFixed(0)} px`);
  };
  side(shift.dx, "오른쪽", "왼쪽");
  side(shift.dy, "아래", "위");
  return parts.length ? `화면에서 물체가 기준보다 ${parts.join(", ")}` : "기준과 맞음";
}

// ---------- 화면 ----------

function alignEl(id) {
  return document.getElementById(id);
}

function alignCanvas() {
  return alignEl("ad-align-canvas");
}

function alignStatus(text, level = "") {
  const el = alignEl("ad-align-status");
  el.textContent = text;
  el.dataset.level = level;
}

// 이미지(또는 ImageBitmap)를 캔버스 크기로 그려 픽셀을 읽는다.
function alignPixels(source, w, h) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(source, 0, 0, w, h);
  return { canvas, data: ctx.getImageData(0, 0, w, h).data };
}

async function alignFetchImage(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (err) { /* 본문 없음 */ }
    throw new Error(detail);
  }
  return createImageBitmap(await res.blob());
}

async function alignLoadRefs() {
  const select = alignEl("ad-align-ref");
  const armId = armAlign.armId;
  select.replaceChildren();
  armAlign.ref = null;
  armAlign.refName = "";
  let refs = [];
  try {
    const res = await fetch(`/api/arms/${encodeURIComponent(armId)}/align/refs`);
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    refs = body.refs || [];
  } catch (err) {
    if (armId === armAlign.armId) alignStatus(`기준 목록을 못 읽음: ${err.message}`, "bad");
    return;
  }
  if (armId !== armAlign.armId) return;
  if (!refs.length) {
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "기준 화면 없음";
    select.append(none);
    alignStatus(`기준 화면이 없음: 관제 PC align_refs_dir/${armId}/ 에 align_view.py --save-ref 로 넣기`, "bad");
    return;
  }
  select.append(...refs.map((ref) => {
    const option = document.createElement("option");
    option.value = ref.name;
    option.textContent = ref.label === ref.name ? ref.name : `${ref.name} · ${ref.label}`;
    return option;
  }));
  await alignPickRef(refs[0].name);
}

async function alignPickRef(name) {
  const armId = armAlign.armId;
  const canvas = alignCanvas();
  armAlign.refName = name;
  armAlign.ref = null;
  armAlign.lastShift = null;
  if (!name) return;
  try {
    const bitmap = await alignFetchImage(
      `/api/arms/${encodeURIComponent(armId)}/align/refs/${encodeURIComponent(name)}`);
    if (armId !== armAlign.armId || name !== armAlign.refName) return;
    const { width: w, height: h } = canvas;
    const pixels = alignPixels(bitmap, w, h);
    const gray = alignGray(pixels.data, w, h);
    const edgeCanvas = document.createElement("canvas");
    edgeCanvas.width = w;
    edgeCanvas.height = h;
    edgeCanvas.getContext("2d").putImageData(new ImageData(alignEdges(gray, w, h), w, h), 0, 0);
    armAlign.ref = { canvas: pixels.canvas, gray, edges: edgeCanvas };
    alignStatus(armAlign.roi ? "" : "영상에서 핑키·접시 자리를 마우스로 끌어 영역을 고르세요");
  } catch (err) {
    if (armId === armAlign.armId) alignStatus(`기준 화면을 못 읽음: ${err.message}`, "bad");
  }
}

function alignDraw(live) {
  const canvas = alignCanvas();
  const ctx = canvas.getContext("2d");
  const { width: w, height: h } = canvas;
  const mode = alignEl("ad-align-mode").value;
  const alpha = Number(alignEl("ad-align-alpha").value) / 100;
  ctx.save();
  ctx.clearRect(0, 0, w, h);
  if (live) ctx.drawImage(live, 0, 0, w, h);
  if (armAlign.ref) {
    if (mode === "diff") {
      ctx.globalCompositeOperation = "difference";
      ctx.drawImage(armAlign.ref.canvas, 0, 0);
    } else if (mode === "edges") {
      ctx.drawImage(armAlign.ref.edges, 0, 0);
    } else {
      ctx.globalAlpha = live ? alpha : 1;
      ctx.drawImage(armAlign.ref.canvas, 0, 0);
    }
  }
  ctx.restore();
  const roi = armAlign.drag ? armAlign.drag.roi : armAlign.roi;
  if (roi) {
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#ffc400";
    ctx.strokeRect(roi.x + 1, roi.y + 1, roi.w - 2, roi.h - 2);
  }
}

function alignShowShift(shift) {
  const out = alignEl("ad-align-shift");
  if (!armAlign.roi) {
    out.textContent = "";
    out.dataset.level = "";
    return;
  }
  if (!shift) {
    out.textContent = "영역에 무늬가 없거나 기준과 너무 달라 못 잼 (영역을 다시 고르기)";
    out.dataset.level = "bad";
    return;
  }
  const good = Math.abs(shift.dx) <= ALIGN_GOOD_PX && Math.abs(shift.dy) <= ALIGN_GOOD_PX
    && shift.score >= ALIGN_MIN_SCORE;
  const sign = (v) => (v >= 0 ? "+" : "") + v.toFixed(1);
  const lowScore = shift.score < ALIGN_MIN_SCORE ? " · 상관이 낮음 (영역이 기준과 많이 다름)" : "";
  out.textContent = `dx ${sign(shift.dx)} px · dy ${sign(shift.dy)} px · 상관 ${shift.score.toFixed(2)}`
    + ` → ${alignAdvice(shift)}${lowScore}`;
  out.dataset.level = good ? "good" : "bad";
}

async function alignTick() {
  if (!armAlign.on || armAlign.busy) return;
  armAlign.busy = true;
  const armId = armAlign.armId;
  try {
    let live = null;
    try {
      live = await alignFetchImage(`/api/arms/${encodeURIComponent(armId)}/camera/top.jpg`);
    } catch (err) {
      if (armId === armAlign.armId) alignStatus(`지금 위 카메라 장면이 없음 (${err.message}). 기준 화면만 보임`, "bad");
    }
    if (!armAlign.on || armId !== armAlign.armId) return;
    alignDraw(live);
    if (live && armAlign.ref) {
      const { width: w, height: h } = alignCanvas();
      armAlign.liveGray = alignGray(alignPixels(live, w, h).data, w, h);
      // 장면·기준이 다 있으면 지난 오류 글을, 영역이 있으면 '영역을 고르세요' 안내를 지운다.
      if (armAlign.roi || alignEl("ad-align-status").dataset.level === "bad") alignStatus("");
      armAlign.lastShift = armAlign.roi
        ? alignShift(armAlign.ref.gray, armAlign.liveGray, w, h, armAlign.roi) : null;
      alignShowShift(armAlign.lastShift);
    }
  } finally {
    armAlign.busy = false;
  }
}

function alignCanvasPoint(event) {
  const canvas = alignCanvas();
  const rect = canvas.getBoundingClientRect();
  return {
    x: (event.clientX - rect.left) * canvas.width / rect.width,
    y: (event.clientY - rect.top) * canvas.height / rect.height,
  };
}

function alignSetupPointer() {
  const canvas = alignCanvas();
  canvas.addEventListener("pointerdown", (event) => {
    if (!armAlign.on) return;
    const p = alignCanvasPoint(event);
    armAlign.drag = { x: p.x, y: p.y, roi: null };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!armAlign.drag) return;
    const p = alignCanvasPoint(event);
    armAlign.drag.roi = alignClipRoi(armAlign.drag.x, armAlign.drag.y, p.x, p.y,
      canvas.width, canvas.height);
  });
  const finish = () => {
    if (!armAlign.drag) return;
    if (armAlign.drag.roi) {
      armAlign.roi = armAlign.drag.roi;
      alignStatus("");
    }
    armAlign.drag = null;
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

// 팔 상세화면(arm_detail.js)이 팔을 바꾸거나 떠날 때 부른다.
function armAlignStop() {
  if (armAlign.timer) clearInterval(armAlign.timer);
  armAlign.timer = null;
  armAlign.on = false;
  armAlign.armId = null;
  armAlign.ref = null;
  armAlign.roi = null;
  armAlign.drag = null;
  armAlign.lastShift = null;
  const panel = alignEl("ad-align");
  if (!panel) return;
  panel.hidden = true;
  alignEl("ad-align-toggle").setAttribute("aria-pressed", "false");
  const canvas = alignCanvas();
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  alignEl("ad-align-shift").textContent = "";
}

function armAlignStart(armId) {
  armAlignStop();
  armAlign.on = true;
  armAlign.armId = armId;
  alignEl("ad-align").hidden = false;
  alignEl("ad-align-toggle").setAttribute("aria-pressed", "true");
  alignStatus("기준 화면 읽는 중…");
  alignLoadRefs();
  alignTick();
  armAlign.timer = setInterval(alignTick, ALIGN_TICK_MS);
}

function setupArmAlign() {
  const mode = alignEl("ad-align-mode");
  mode.replaceChildren(...Object.entries(ALIGN_MODES).map(([value, text]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    return option;
  }));
  alignEl("ad-align-toggle").addEventListener("click", () => {
    if (armAlign.on) armAlignStop();
    else if (armDetail.armId !== null) armAlignStart(armDetail.armId);
  });
  alignEl("ad-align-ref").addEventListener("change", (event) => alignPickRef(event.target.value));
  alignEl("ad-align-clear").addEventListener("click", () => {
    armAlign.roi = null;
    alignShowShift(null);
    alignStatus("영상에서 핑키·접시 자리를 마우스로 끌어 영역을 고르세요");
  });
  alignSetupPointer();
}
