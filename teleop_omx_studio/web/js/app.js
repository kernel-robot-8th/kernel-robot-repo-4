// OMX Teleoperation & LeRobot Studio Client Logic

let activeLeaseId = null;
let isDraggingSlider = false;
let isRecording = false;
let isBroughtUp = false;
let recordStartTime = 0;
let recordTimerInterval = null;
let isSwappedCameras = false;

// DOM Elements
const modeBadge = document.getElementById("modeBadge");
const bringupStatusBadge = document.getElementById("bringupStatusBadge");
const bringupAlertBanner = document.getElementById("bringupAlertBanner");
const bringupBannerMsg = document.getElementById("bringupBannerMsg");
const btnBringUp = document.getElementById("btnBringUp");
const btnServerOff = document.getElementById("btnServerOff");

const savePathInput = document.getElementById("savePathInput");
const btnSavePathApply = document.getElementById("btnSavePathApply");
const savePathStatusText = document.getElementById("savePathStatusText");

const mainVideo = document.getElementById("mainVideo");
const pipVideo = document.getElementById("pipVideo");
const mainLabel = document.getElementById("mainLabel");
const pipLabel = document.getElementById("pipLabel");

const taskSelect = document.getElementById("taskSelect");
const btnRecordStart = document.getElementById("btnRecordStart");
const btnRecordSuccess = document.getElementById("btnRecordSuccess");
const btnRecordFail = document.getElementById("btnRecordFail");
const btnRecordDiscard = document.getElementById("btnRecordDiscard");

const recordStatusText = document.getElementById("recordStatusText");
const recordTimerText = document.getElementById("recordTimerText");
const episodeCounterText = document.getElementById("episodeCounterText");
const gamepadStatus = document.getElementById("gamepadStatus");

// Joint config: [name, minDeg, maxDeg]
const jointsMeta = [
  { name: "Joint 1 (Base)", min: -180, max: 180, isGripper: false },
  { name: "Joint 2 (Shoulder)", min: -100, max: 100, isGripper: false },
  { name: "Joint 3 (Elbow)", min: -95, max: 90, isGripper: false },
  { name: "Joint 4 (Wrist Pitch)", min: -105, max: 105, isGripper: false },
  { name: "Joint 5 (Wrist Roll)", min: -180, max: 180, isGripper: false },
  { name: "Gripper", min: 0, max: 50, isGripper: true } // mm
];

// Initialize UI
window.addEventListener("DOMContentLoaded", () => {
  setupJointSliders();
  setupEventListeners();
  setInterval(fetchStatus, 150); // ~7Hz status polling
  requestAnimationFrame(gamepadLoop); // Gamepad polling loop
});

function setupJointSliders() {
  const container = document.getElementById("jointsContainer");
  container.innerHTML = "";

  jointsMeta.forEach((meta, idx) => {
    const card = document.createElement("div");
    card.className = "joint-slider-card";

    const unit = meta.isGripper ? "mm" : "°";
    card.innerHTML = `
      <div class="joint-header">
        <span>${meta.name}</span>
        <span id="jointValText_${idx}">0.0${unit}</span>
      </div>
      <div class="joint-controls">
        <button class="jog-btn" id="jogBtn_m_${idx}" onclick="jogJoint(${idx}, -0.087)" disabled>-5°</button>
        <input type="range" id="jointSlider_${idx}" 
               min="${meta.min}" max="${meta.max}" step="${meta.isGripper ? '1' : '0.5'}" value="0" disabled>
        <button class="jog-btn" id="jogBtn_p_${idx}" onclick="jogJoint(${idx}, 0.087)" disabled>+5°</button>
      </div>
    `;
    container.appendChild(card);

    const slider = card.querySelector(`#jointSlider_${idx}`);
    slider.addEventListener("mousedown", () => isDraggingSlider = true);
    slider.addEventListener("mouseup", () => {
      isDraggingSlider = false;
      sendSliderTarget(idx, slider.value, meta.isGripper);
    });
    slider.addEventListener("input", () => {
      const val = parseFloat(slider.value);
      document.getElementById(`jointValText_${idx}`).innerText = `${val.toFixed(1)}${unit}`;
    });
  });
}

function setupEventListeners() {
  // BringUp Button (Req 1 & 2)
  btnBringUp.addEventListener("click", () => {
    btnBringUp.disabled = true;
    btnBringUp.innerText = "⏳ BringUp 진행 중...";
    fetch("/api/bringup", { method: "POST" })
      .then(res => res.json())
      .then(data => {
        btnBringUp.innerText = "🚀 BringUp 완료";
        if (data.success) {
          updateBringUpState(true);
        } else {
          alert("BringUp 실패: " + (data.detail || data.message));
          btnBringUp.disabled = false;
          btnBringUp.innerText = "🚀 BringUp (시스템 활성화)";
        }
      })
      .catch(err => {
        alert("BringUp 통신 오류: " + err);
        btnBringUp.disabled = false;
        btnBringUp.innerText = "🚀 BringUp (시스템 활성화)";
      });
  });

  // Server OFF Button (Req 4: Kill Torque)
  btnServerOff.addEventListener("click", () => {
    if (!confirm("모터 토크를 해제하고 시스템을 Standby로 전환하시겠습니까?")) return;
    btnServerOff.disabled = true;
    fetch("/api/server_off", { method: "POST" })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          updateBringUpState(false);
        }
      })
      .catch(err => alert("Server OFF 통신 오류: " + err));
  });

  // Save Path Apply (Req 1)
  btnSavePathApply.addEventListener("click", () => {
    const path = savePathInput.value.trim();
    if (!path) return;
    fetch("/api/config/save_path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_dir: path })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          savePathStatusText.innerText = "경로 변경 성공";
          savePathStatusText.style.color = "var(--accent-emerald)";
        }
      });
  });

  // Preset buttons
  document.querySelectorAll("[data-preset]").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!isBroughtUp) {
        alert("먼저 [BringUp] 버튼을 눌러야 조작할 수 있습니다.");
        return;
      }
      const preset = btn.getAttribute("data-preset");
      fetch(`/api/arm/preset/${preset}`, { method: "POST" });
    });
  });

  // Camera PiP swap
  document.getElementById("pipContainer").addEventListener("click", () => {
    isSwappedCameras = !isSwappedCameras;
    if (isSwappedCameras) {
      mainVideo.src = "/video_feed/wrist";
      pipVideo.src = "/video_feed/top";
      mainLabel.innerText = "WRIST CAMERA (Eye-in-Hand)";
      pipLabel.innerText = "TOP CAMERA";
    } else {
      mainVideo.src = "/video_feed/top";
      pipVideo.src = "/video_feed/wrist";
      mainLabel.innerText = "TOP CAMERA (Work Table)";
      pipLabel.innerText = "WRIST CAM";
    }
  });

  // LeRobot Recorder buttons (Req 3: Success, Fail, Discard)
  btnRecordStart.addEventListener("click", startRecording);
  btnRecordSuccess.addEventListener("click", stopRecordingSuccess);
  btnRecordFail.addEventListener("click", stopRecordingFail);
  btnRecordDiscard.addEventListener("click", discardRecording);

  // Keyboard Shortcuts
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;

    if (e.code === "Space") {
      e.preventDefault();
      if (!isRecording && isBroughtUp) startRecording();
    } else if (e.code === "Enter") {
      e.preventDefault();
      if (isRecording) stopRecordingSuccess();
    } else if (e.code === "Backspace") {
      e.preventDefault();
      if (isRecording) discardRecording();
    }
  });
}

function updateBringUpState(broughtUp) {
  isBroughtUp = broughtUp;

  if (broughtUp) {
    bringupStatusBadge.innerText = "READY (BRINGUP OK)";
    bringupStatusBadge.className = "badge badge-emerald";

    bringupAlertBanner.className = "bringup-alert-banner active-ok";
    bringupBannerMsg.innerText = "모터 전원 인가 완료 (Init 자세 안착): 정상 조작 및 LeRobot 녹화가 가능합니다.";

    btnBringUp.disabled = true;
    btnBringUp.innerText = "🚀 BringUp 완료";
    btnServerOff.disabled = false;

    // Enable presets
    document.querySelectorAll("[data-preset]").forEach(b => b.disabled = false);

    // Enable sliders & jog buttons
    jointsMeta.forEach((_, idx) => {
      const slider = document.getElementById(`jointSlider_${idx}`);
      const btnM = document.getElementById(`jogBtn_m_${idx}`);
      const btnP = document.getElementById(`jogBtn_p_${idx}`);
      if (slider) slider.disabled = false;
      if (btnM) btnM.disabled = false;
      if (btnP) btnP.disabled = false;
    });

    if (!isRecording) {
      btnRecordStart.disabled = false;
      recordStatusText.innerText = "IDLE (READY)";
      recordStatusText.className = "badge badge-cyan";
    }
  } else {
    bringupStatusBadge.innerText = "STANDBY (LOCKED)";
    bringupStatusBadge.className = "badge badge-amber";

    bringupAlertBanner.className = "bringup-alert-banner";
    bringupBannerMsg.innerText = "시스템이 대기 상태입니다. 상단 [🚀 BringUp] 버튼을 눌러 모터 전원 및 초기 자세를 인가하세요.";

    btnBringUp.disabled = false;
    btnBringUp.innerText = "🚀 BringUp (시스템 활성화)";
    btnServerOff.disabled = true;

    // Disable presets
    document.querySelectorAll("[data-preset]").forEach(b => b.disabled = true);

    // Disable sliders & jog buttons
    jointsMeta.forEach((_, idx) => {
      const slider = document.getElementById(`jointSlider_${idx}`);
      const btnM = document.getElementById(`jogBtn_m_${idx}`);
      const btnP = document.getElementById(`jogBtn_p_${idx}`);
      if (slider) slider.disabled = true;
      if (btnM) btnM.disabled = true;
      if (btnP) btnP.disabled = true;
    });

    btnRecordStart.disabled = true;
    btnRecordSuccess.disabled = true;
    btnRecordFail.disabled = true;
    btnRecordDiscard.disabled = true;
    recordStatusText.innerText = "STANDBY";
    recordStatusText.className = "badge badge-amber";
  }
}

// -----------------------------------------------------------------------------
// Status & Telemetry
// -----------------------------------------------------------------------------
let isFirstStatus = true;

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    modeBadge.innerText = data.mock_mode ? "MOCK (SIM)" : "REAL HW";
    modeBadge.className = data.mock_mode ? "badge badge-amber" : "badge badge-cyan";

    // Sync BringUp state with server
    if (data.is_brought_up !== isBroughtUp) {
      updateBringUpState(data.is_brought_up);
    }

    // Populate save path on first load
    if (isFirstStatus && data.save_path) {
      savePathInput.value = data.save_path;
      isFirstStatus = false;
    }

    if (!isDraggingSlider && data.positions) {
      data.positions.forEach((rad, idx) => {
        const meta = jointsMeta[idx];
        const val = meta.isGripper ? (rad * 1000.0) : (rad * 180.0 / Math.PI);
        const slider = document.getElementById(`jointSlider_${idx}`);
        const text = document.getElementById(`jointValText_${idx}`);
        if (slider && text) {
          slider.value = val;
          text.innerText = `${val.toFixed(1)}${meta.isGripper ? 'mm' : '°'}`;
        }
      });
    }

    // Telemetry Diagnostics
    if (data.temperatures) {
      const avgTemp = (data.temperatures.reduce((a, b) => a + b, 0) / data.temperatures.length).toFixed(1);
      document.getElementById("hudTemp").innerText = `${avgTemp}°C`;
    }
    if (data.voltages) {
      document.getElementById("hudVolt").innerText = `${data.voltages[0].toFixed(1)}V`;
    }
    if (data.currents) {
      const maxCurr = Math.max(...data.currents.map(Math.abs)).toFixed(0);
      document.getElementById("hudCurrent").innerText = `${maxCurr} mA`;
    }

    // Recorder sync
    if (data.recorder) {
      episodeCounterText.innerText = `${data.recorder.total_episodes} Saved`;
      if (data.recorder.recording && !isRecording) {
        setRecordingUI(true);
      } else if (!data.recorder.recording && isRecording) {
        setRecordingUI(false);
      }
    }

  } catch (err) {
    console.error("Status fetch error", err);
  }
}

function sendSliderTarget(jointIdx, val, isGripper) {
  if (!isBroughtUp) return;
  const targetVal = isGripper ? (val / 1000.0) : (val * Math.PI / 180.0);
  fetch("/api/arm/jog", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      joint_index: jointIdx,
      delta: targetVal - parseFloat(document.getElementById(`jointSlider_${jointIdx}`).dataset.prev || 0)
    })
  });
}

function jogJoint(idx, deltaRad) {
  if (!isBroughtUp) return;
  fetch("/api/arm/jog", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ joint_index: idx, delta: deltaRad })
  });
}

// -----------------------------------------------------------------------------
// LeRobot Recording Actions (Req 3)
// -----------------------------------------------------------------------------
function startRecording() {
  if (!isBroughtUp) {
    alert("BringUp 버튼을 먼저 눌러야 녹화할 수 있습니다.");
    return;
  }
  const task = taskSelect.value;
  fetch("/api/record/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_name: task })
  }).then(res => res.json()).then(data => {
    if (data.success) {
      setRecordingUI(true);
    } else {
      alert("녹화 시작 실패: " + data.detail);
    }
  });
}

function stopRecordingSuccess() {
  fetch("/api/record/stop_success", { method: "POST" })
    .then(res => res.json())
    .then(data => {
      setRecordingUI(false);
      if (data.success) {
        recordStatusText.innerText = `✅ Ep #${data.episode_info.episode_index} 성공 저장 (${data.episode_info.duration_sec}s)`;
        recordStatusText.className = "badge badge-emerald";
      } else {
        recordStatusText.innerText = data.message || "저장 실패";
      }
    });
}

function stopRecordingFail() {
  fetch("/api/record/stop_fail", { method: "POST" })
    .then(res => res.json())
    .then(data => {
      setRecordingUI(false);
      if (data.success) {
        recordStatusText.innerText = `❌ Ep #${data.episode_info.episode_index} 실패 데이터 저장 (${data.episode_info.duration_sec}s)`;
        recordStatusText.className = "badge badge-rose";
      } else {
        recordStatusText.innerText = data.message || "저장 실패";
      }
    });
}

function discardRecording() {
  fetch("/api/record/discard", { method: "POST" })
    .then(() => {
      setRecordingUI(false);
      recordStatusText.innerText = "🗑️ 폐기됨 (디스크 저장 없음)";
      recordStatusText.className = "badge badge-amber";
    });
}

function setRecordingUI(active) {
  isRecording = active;
  if (active) {
    recordStartTime = Date.now();
    btnRecordStart.disabled = true;
    btnRecordSuccess.disabled = false;
    btnRecordFail.disabled = false;
    btnRecordDiscard.disabled = false;
    recordStatusText.innerText = "REC ● (30Hz Sync)";
    recordStatusText.className = "badge badge-rose";

    clearInterval(recordTimerInterval);
    recordTimerInterval = setInterval(() => {
      const elapsed = ((Date.now() - recordStartTime) / 1000).toFixed(1);
      recordTimerText.innerText = `${elapsed}s`;
    }, 100);
  } else {
    btnRecordStart.disabled = !isBroughtUp;
    btnRecordSuccess.disabled = true;
    btnRecordFail.disabled = true;
    btnRecordDiscard.disabled = true;
    clearInterval(recordTimerInterval);
    recordTimerText.innerText = "0.0s";
  }
}

// -----------------------------------------------------------------------------
// HTML5 Gamepad API Loop
// -----------------------------------------------------------------------------
let lastGamepadJogTime = 0;

function gamepadLoop() {
  const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
  const gp = gamepads[0];

  if (gp && gp.connected) {
    gamepadStatus.innerText = `Gamepad: ${gp.id.substring(0, 20)}...`;
    gamepadStatus.className = "badge badge-emerald";

    const now = Date.now();
    if (isBroughtUp && now - lastGamepadJogTime > 50) { // 20Hz jog
      lastGamepadJogTime = now;

      const deadzone = 0.15;
      const lx = Math.abs(gp.axes[0]) > deadzone ? gp.axes[0] : 0;
      const ly = Math.abs(gp.axes[1]) > deadzone ? gp.axes[1] : 0;
      const rx = Math.abs(gp.axes[2]) > deadzone ? gp.axes[2] : 0;
      const ry = Math.abs(gp.axes[3]) > deadzone ? gp.axes[3] : 0;

      if (lx !== 0) jogJoint(0, lx * -0.05);  // Base
      if (ly !== 0) jogJoint(1, ly * -0.04);  // Shoulder
      if (ry !== 0) jogJoint(2, ry * -0.04);  // Elbow
      if (rx !== 0) jogJoint(3, rx * 0.04);   // Wrist pitch

      // Buttons: R1 (5) = Start, L1 (4) = Success, B (1) = Discard
      if (gp.buttons[5] && gp.buttons[5].pressed && !isRecording) {
        startRecording();
      }
      if (gp.buttons[4] && gp.buttons[4].pressed && isRecording) {
        stopRecordingSuccess();
      }
      if (gp.buttons[1] && gp.buttons[1].pressed && isRecording) {
        discardRecording();
      }
    }
  } else {
    gamepadStatus.innerText = "Gamepad: Disconnected (Use Keyboard/Sliders)";
    gamepadStatus.className = "badge badge-amber";
  }

  requestAnimationFrame(gamepadLoop);
}
