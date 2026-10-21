"""
FastAPI Server for OMX Teleoperation & LeRobot Imitation Learning Studio.
Provides REST API, MJPEG direct stream fallback, and LiveKit WebRTC token management.
"""

import os
import json
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import cv2
import numpy as np

from hardware.dynamixel_interface import DynamixelHardwareInterface
from recorder.lerobot_recorder import LeRobotDatasetRecorder
from server.livekit_bridge import LiveKitTeleopBridge

logger = logging.getLogger("omx_studio")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "omx_config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# Global Instances
hw = DynamixelHardwareInterface(
    device_name=CONFIG["serial"]["device_name"],
    baudrate=CONFIG["serial"]["baudrate"],
    mock=False  # Auto falls back to Mock if port absent
)

recorder = LeRobotDatasetRecorder(
    output_dir=os.path.expanduser("~/.cache/huggingface/lerobot/pinky_omx_tasks"),
    fps=30
)

bridge = LiveKitTeleopBridge(
    hardware_interface=hw,
    url=CONFIG["livekit"]["url"],
    api_key=CONFIG["livekit"]["api_key"],
    api_secret=CONFIG["livekit"]["api_secret"],
    room_name=CONFIG["livekit"]["room_name"]
)

# Camera Capture Handles
top_cap = None
wrist_cap = None
current_top_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
current_wrist_frame = np.zeros((480, 640, 3), dtype=np.uint8)
camera_task_running = True

async def camera_loop():
    """Background loop grabbing frames from cameras or generating synthetic test patterns"""
    global top_cap, wrist_cap, current_top_frame, current_wrist_frame, camera_task_running

    # Try opening actual webcams
    top_idx = CONFIG["cameras"]["top"]["device_index"]
    wrist_idx = CONFIG["cameras"]["wrist"]["device_index"]

    top_cap = cv2.VideoCapture(top_idx)
    wrist_cap = cv2.VideoCapture(wrist_idx)

    top_ok = top_cap.isOpened()
    wrist_ok = wrist_cap.isOpened()
    logger.info(f"Cameras opened: Top (device {top_idx})={top_ok}, Wrist (device {wrist_idx})={wrist_ok}")

    frame_count = 0
    while camera_task_running:
        frame_count += 1
        now_str = time.strftime("%H:%M:%S")

        # Top Cam Frame
        if top_ok:
            ret, frame = top_cap.read()
            if ret:
                current_top_frame = frame
        else:
            # Synthetic camera pattern
            img = np.zeros((720, 1280, 3), dtype=np.uint8)
            img[:] = (35, 30, 30)  # Dark background
            cv2.putText(img, f"TOP CAMERA (Device {top_idx}) - [SIMULATED]", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 220, 255), 2)
            cv2.putText(img, f"Time: {now_str} | Frame: {frame_count}", (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
            # Draw worktable grid
            cv2.rectangle(img, (240, 200), (1040, 650), (60, 60, 80), 2)
            cv2.putText(img, "WORK TABLE (Tray Area)", (260, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 160, 120), 1)
            current_top_frame = img

        # Wrist Cam Frame
        if wrist_ok:
            ret, frame = wrist_cap.read()
            if ret:
                current_wrist_frame = frame
        else:
            # Synthetic camera pattern
            img = np.zeros((480, 640, 3), dtype=np.uint8)
            img[:] = (25, 25, 35)  # Dark slate background
            cv2.putText(img, f"WRIST CAM (Eye-in-Hand) - [SIM]", (30, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 255, 100), 2)
            cv2.circle(img, (320, 240), 15, (0, 0, 255), 1)  # Crosshair
            cv2.line(img, (300, 240), (340, 240), (0, 0, 255), 1)
            cv2.line(img, (320, 220), (320, 260), (0, 0, 255), 1)
            current_wrist_frame = img

        # Record step if recording
        if recorder.recording:
            states = hw.sync_read_states()
            obs_state = states["positions"] + states["velocities"] + [states["currents"][-1]]
            target_action = [hw.goal_positions[jid] for jid in hw.joint_ids]
            recorder.record_step(obs_state, target_action, current_top_frame, current_wrist_frame)

        await asyncio.sleep(0.033)  # ~30 fps

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting OMX Teleop Studio Application...")
    cam_task = asyncio.create_task(camera_loop())
    bridge_task = asyncio.create_task(bridge.start())
    yield
    # Shutdown
    global camera_task_running
    camera_task_running = False
    await bridge.stop()
    hw.close()
    if top_cap:
        top_cap.release()
    if wrist_cap:
        wrist_cap.release()
    logger.info("OMX Teleop Studio shutdown complete.")

app = FastAPI(title="OMX Teleoperation & LeRobot Studio", lifespan=lifespan)

# ------------------------------------------------------------------------------
# REST API Models
# ------------------------------------------------------------------------------
class JogRequest(BaseModel):
    joint_index: int       # 0 ~ 5 (0: Base, 5: Gripper)
    delta: float           # in radians (or meters for gripper)

class TargetRequest(BaseModel):
    targets: List[float]   # 6 float values

class ParamsRequest(BaseModel):
    joint_id: int
    p_gain: Optional[int] = None
    i_gain: Optional[int] = None
    d_gain: Optional[int] = None
    profile_vel: Optional[int] = None
    profile_accel: Optional[int] = None
    gripper_current_limit: Optional[int] = None

class TorqueRequest(BaseModel):
    enable: bool
    joint_id: Optional[int] = None

class LeaseRequest(BaseModel):
    operator_id: str

class RecordStartRequest(BaseModel):
    task_name: str
    metadata: Optional[Dict[str, Any]] = None

# ------------------------------------------------------------------------------
# API Endpoints
# ------------------------------------------------------------------------------
@app.get("/api/status")
def get_status():
    states = hw.sync_read_states()
    return {
        "status": "online",
        "mock_mode": hw.mock,
        "positions": states["positions"],
        "velocities": states["velocities"],
        "currents": states["currents"],
        "temperatures": states["temperatures"],
        "voltages": states["voltages"],
        "torque_enabled": states["torque_enabled"],
        "goal_positions": [hw.goal_positions[jid] for jid in hw.joint_ids],
        "active_lease": {
            "lease_id": bridge.active_lease_id,
            "operator_id": bridge.lease_operator_id,
            "holding": bridge.is_holding
        },
        "recorder": {
            "recording": recorder.recording,
            "current_task": recorder.task_name,
            "steps": len(recorder.buffer_timestamps),
            "total_episodes": recorder.current_episode_index
        }
    }

@app.post("/api/arm/jog")
def jog_joint(req: JogRequest):
    if req.joint_index < 0 or req.joint_index >= len(hw.joint_ids):
        raise HTTPException(status_code=400, detail="Invalid joint index")

    jid = hw.joint_ids[req.joint_index]
    curr_goal = hw.goal_positions[jid]
    new_target = curr_goal + req.delta

    targets = [hw.goal_positions[j] for j in hw.joint_ids]
    targets[req.joint_index] = new_target
    hw.sync_write_goals(targets)
    return {"success": True, "goal": hw.goal_positions[jid]}

@app.post("/api/arm/target")
def set_target(req: TargetRequest):
    if len(req.targets) != 6:
        raise HTTPException(status_code=400, detail="Expected exactly 6 joint targets")
    hw.sync_write_goals(req.targets)
    return {"success": True, "goals": req.targets}

@app.post("/api/arm/preset/{preset_name}")
def apply_preset(preset_name: str):
    presets = CONFIG.get("presets", {})
    if preset_name not in presets:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_name}' not found")
    target = presets[preset_name]
    hw.sync_write_goals(target)
    return {"success": True, "preset": preset_name, "goals": target}

@app.post("/api/arm/params")
def update_params(req: ParamsRequest):
    jid = req.joint_id
    if req.p_gain is not None:
        hw.set_pid_gains(jid, req.p_gain, req.i_gain or 0, req.d_gain or 0)
    if req.profile_vel is not None and req.profile_accel is not None:
        hw.set_profile(jid, req.profile_vel, req.profile_accel)
    if req.gripper_current_limit is not None and jid == 6:
        hw.set_gripper_current_limit(req.gripper_current_limit)
    return {"success": True}

@app.post("/api/arm/torque")
def set_torque(req: TorqueRequest):
    hw.set_torque_enable(req.enable, req.joint_id)
    return {"success": True, "torque_enabled": req.enable}

@app.post("/api/lease/acquire")
def acquire_lease(req: LeaseRequest):
    res = bridge.acquire_lease(req.operator_id)
    return res

@app.post("/api/lease/release")
def release_lease(req: LeaseRequest):
    success = bridge.release_lease(req.operator_id, bridge.active_lease_id or "")
    return {"success": success}

@app.get("/api/livekit/token")
def get_livekit_token(identity: str = Query("operator_web")):
    try:
        jwt_token = bridge.generate_token(identity)
        return {
            "token": jwt_token,
            "url": bridge.url,
            "room": bridge.room_name
        }
    except Exception as e:
        return {"error": str(e), "message": "LiveKit API token generation failed"}

# ------------------------------------------------------------------------------
# LeRobot Recorder Endpoints
# ------------------------------------------------------------------------------
@app.post("/api/record/start")
def start_record(req: RecordStartRequest):
    recorder.start_episode(req.task_name, req.metadata)
    return {"success": True, "episode_index": recorder.current_episode_index, "task": req.task_name}

@app.post("/api/record/stop")
def stop_record():
    info = recorder.stop_and_save()
    if info is None:
        return {"success": False, "message": "Episode was too short or empty, discarded"}
    return {"success": True, "episode_info": info}

@app.post("/api/record/discard")
def discard_record():
    recorder.discard_episode()
    return {"success": True, "message": "Current recording buffer discarded"}

@app.get("/api/record/episodes")
def list_episodes():
    ep_file = os.path.join(recorder.output_dir, "meta", "episodes.jsonl")
    episodes = []
    if os.path.exists(ep_file):
        with open(ep_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    episodes.append(json.loads(line))
    return {
        "output_dir": recorder.output_dir,
        "total": len(episodes),
        "episodes": episodes
    }

# ------------------------------------------------------------------------------
# MJPEG Video Streaming Fallback (Works in any browser without WebRTC)
# ------------------------------------------------------------------------------
def generate_mjpeg(cam_type="top"):
    global current_top_frame, current_wrist_frame
    while True:
        frame = current_top_frame if cam_type == "top" else current_wrist_frame
        ret, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n\r\n")
        time.sleep(0.033)

@app.get("/video_feed/top")
def video_top():
    return StreamingResponse(generate_mjpeg("top"), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/video_feed/wrist")
def video_wrist():
    return StreamingResponse(generate_mjpeg("wrist"), media_type="multipart/x-mixed-replace; boundary=frame")

# ------------------------------------------------------------------------------
# Static Files & Frontend App Serving
# ------------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)
