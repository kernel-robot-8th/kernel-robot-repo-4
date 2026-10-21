// OMX Teleoperation & LeRobot Studio Client Logic

let activeLeaseId = null;
let isDraggingSlider = false;
let isRecording = false;
let recordStartTime = 0;
let recordTimerInterval = null;
let isSwappedCameras = false;

// DOM Elements
const modeBadge = document.getElementById("modeBadge");
const leaseBadge = document.getElementById("leaseBadge");
const rttBadge = document.getElementById("rttBadge");
const mainVideo = document.getElementById("mainVideo");
const pipVideo = document.getElementById("pipVideo");
const mainLabel = document.getElementById("mainLabel");
const pipLabel = document.getElementById("pipLabel");

const taskSelect = document.getElementById("taskSelect");
const btnRecordStart = document.getElementById("btnRecordStart");
const btnRecordSave = document.getElementById("btnRecordSave");
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
  setInterval(fetchStatus, 100); // 10Hz status polling
  requestAnimationFrame(gamepadLoop); // 30~60Hz gamepad loop
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
        <button class="jog-btn" onclick="jogJoint(${idx}, -0.087)">-5°</button>
        <input type="range" id="jointSlider_${idx}" 
               min="${meta.min}" max="${meta.max}" step="${meta.isGripper ? '1' : '0.5'}" value="0">
        <button class="jog-btn" onclick="jogJoint(${idx}, 0.087)">+5°</button>
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
  // Preset buttons
  document.querySelectorAll("[data-preset]").forEach(btn => {
    btn.addEventListener("click", () => {
      const preset = btn.getAttribute("data-preset");
      fetch(`/api/arm/preset/${preset}`, { method: "POST" });
    });
  });

  // Torque Toggle
  const torqueBtn = document.getElementById("btnTorqueToggle");
  let torqueOn = true;
  torqueBtn.addEventListener("click", () => {
    torqueOn = !torqueOn;
    fetch("/api/arm/torque", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enable: torqueOn })
    }).then(() => {
      torqueBtn.innerText = torqueOn ? "TORQUE: ON" : "TORQUE: FREE (TEACH)";
      torqueBtn.className = torqueOn ? "badge badge-emerald" : "badge badge-amber";
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

  // Recorder buttons
  btnRecordStart.addEventListener("click", startRecording);
  btnRecordSave.addEventListener("click", saveRecording);
  btnRecordDiscard.addEventListener("click", discardRecording);

  // Keyboard Shortcuts
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;

    if (e.code === "Space") {
      e.preventDefault();
      if (!isRecording) startRecording();
    } else if (e.code === "Enter") {
      e.preventDefault();
      if (isRecording) saveRecording();
    } else if (e.code === "Backspace") {
      e.preventDefault();
      if (isRecording) discardRecording();
    }
  });
}

// -----------------------------------------------------------------------------
// Status & Telemetry
// -----------------------------------------------------------------------------
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    modeBadge.innerText = data.mock_mode ? "MOCK (SIM)" : "REAL HW";
    modeBadge.className = data.mock_mode ? "badge badge-amber" : "badge badge-cyan";

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
  fetch("/api/arm/jog", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ joint_index: idx, delta: deltaRad })
  });
}

// -----------------------------------------------------------------------------
// LeRobot Recording Actions
// -----------------------------------------------------------------------------
function startRecording() {
  const task = taskSelect.value;
  fetch("/api/record/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_name: task })
  }).then(res => res.json()).then(data => {
    if (data.success) {
      setRecordingUI(true);
    }
  });
}

function saveRecording() {
  fetch("/api/record/stop", { method: "POST" })
    .then(res => res.json())
    .then(data => {
      setRecordingUI(false);
      if (data.success) {
        recordStatusText.innerText = `Saved Ep #${data.episode_info.episode_index} (${data.episode_info.duration_sec}s)`;
        recordStatusText.className = "badge badge-emerald";
      }
    });
}

function discardRecording() {
  fetch("/api/record/discard", { method: "POST" })
    .then(() => {
      setRecordingUI(false);
      recordStatusText.innerText = "Discarded! Ready to retry";
      recordStatusText.className = "badge badge-amber";
    });
}

function setRecordingUI(active) {
  isRecording = active;
  if (active) {
    recordStartTime = Date.now();
    btnRecordStart.disabled = true;
    btnRecordSave.disabled = false;
    btnRecordDiscard.disabled = false;
    recordStatusText.innerText = "REC ● (30Hz Sync)";
    recordStatusText.className = "badge badge-rose";

    clearInterval(recordTimerInterval);
    recordTimerInterval = setInterval(() => {
      const elapsed = ((Date.now() - recordStartTime) / 1000).toFixed(1);
      recordTimerText.innerText = `${elapsed}s`;
    }, 100);
  } else {
    btnRecordStart.disabled = false;
    btnRecordSave.disabled = true;
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
    if (now - lastGamepadJogTime > 50) { // 20Hz jog
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

      // Buttons: R1 (5) = Start, L1 (4) = Save, B (1) = Discard
      if (gp.buttons[5] && gp.buttons[5].pressed && !isRecording) {
        startRecording();
      }
      if (gp.buttons[4] && gp.buttons[4].pressed && isRecording) {
        saveRecording();
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
