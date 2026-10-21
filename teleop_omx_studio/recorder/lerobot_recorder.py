"""
HuggingFace LeRobot Standard Dataset Recorder.
Synchronizes 30Hz joint observations, operator actions, and dual camera streams into Parquet & MP4 video.
Compatible with LeRobot ACT training: `python lerobot/scripts/train.py --policy.type=act`
"""

import os
import json
import time
import logging
from typing import Dict, List, Optional, Any
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import cv2

logger = logging.getLogger(__name__)

class LeRobotDatasetRecorder:
    def __init__(
        self,
        output_dir: str = "~/.cache/huggingface/lerobot/pinky_omx_tasks",
        fps: int = 30,
        task_name: str = "task_load_s1"
    ):
        self.output_dir = os.path.expanduser(output_dir)
        self.fps = fps
        self.task_name = task_name

        self.recording = False
        self.current_episode_index = 0
        self.start_time = 0.0

        # Memory buffers for the currently active episode
        self.buffer_timestamps: List[float] = []
        self.buffer_indices: List[int] = []
        self.buffer_states: List[List[float]] = []
        self.buffer_actions: List[List[float]] = []
        self.buffer_dones: List[bool] = []
        self.buffer_top_frames: List[np.ndarray] = []
        self.buffer_wrist_frames: List[np.ndarray] = []

        self.last_saved_episode_info: Optional[Dict[str, Any]] = None

        self._init_storage()

    def _init_storage(self):
        """Creates standard LeRobot directory structure and info.json if not present"""
        os.makedirs(os.path.join(self.output_dir, "data", "chunk-000"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "videos", "observation.images.top", "chunk-000"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "videos", "observation.images.wrist", "chunk-000"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "meta"), exist_ok=True)

        episodes_jsonl = os.path.join(self.output_dir, "meta", "episodes.jsonl")
        if os.path.exists(episodes_jsonl):
            with open(episodes_jsonl, "r", encoding="utf-8") as f:
                lines = f.readlines()
                self.current_episode_index = len(lines)
        else:
            self.current_episode_index = 0

        self._ensure_info_json()

    def _ensure_info_json(self):
        info_path = os.path.join(self.output_dir, "meta", "info.json")
        info = {
            "codebase_version": "v2.0",
            "robot_type": "openmanipulator_f",
            "fps": self.fps,
            "total_episodes": self.current_episode_index,
            "features": {
                "observation.state": {
                    "dtype": "float32",
                    "shape": [12],
                    "names": [
                        "joint_base_pos", "joint_shoulder_pos", "joint_elbow_pos",
                        "joint_wrist_pitch_pos", "joint_wrist_roll_pos", "gripper_pos",
                        "joint_base_vel", "joint_shoulder_vel", "joint_elbow_vel",
                        "joint_wrist_pitch_vel", "joint_wrist_roll_vel", "gripper_current"
                    ]
                },
                "action": {
                    "dtype": "float32",
                    "shape": [6],
                    "names": [
                        "joint_base_cmd", "joint_shoulder_cmd", "joint_elbow_cmd",
                        "joint_wrist_pitch_cmd", "joint_wrist_roll_cmd", "gripper_cmd"
                    ]
                },
                "observation.images.top": {
                    "dtype": "video",
                    "shape": [720, 1280, 3],
                    "names": ["height", "width", "channel"]
                },
                "observation.images.wrist": {
                    "dtype": "video",
                    "shape": [480, 640, 3],
                    "names": ["height", "width", "channel"]
                }
            }
        }
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)

    # --------------------------------------------------------------------------
    # Recording Control API
    # --------------------------------------------------------------------------
    def start_episode(self, task_name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Starts a new recording session buffer"""
        self.buffer_timestamps.clear()
        self.buffer_indices.clear()
        self.buffer_states.clear()
        self.buffer_actions.clear()
        self.buffer_dones.clear()
        self.buffer_top_frames.clear()
        self.buffer_wrist_frames.clear()

        if task_name:
            self.task_name = task_name

        self.current_metadata = metadata or {}
        self.start_time = time.time()
        self.recording = True
        logger.info(f"Started recording episode #{self.current_episode_index} for task '{self.task_name}'")

    def record_step(
        self,
        observation_state: List[float],
        action: List[float],
        top_frame: Optional[np.ndarray] = None,
        wrist_frame: Optional[np.ndarray] = None
    ):
        """Records one synchronous timestep step (called at 30Hz)"""
        if not self.recording:
            return

        now = time.time() - self.start_time
        idx = len(self.buffer_timestamps)

        self.buffer_timestamps.append(now)
        self.buffer_indices.append(idx)
        self.buffer_states.append([float(x) for x in observation_state])
        self.buffer_actions.append([float(x) for x in action])
        self.buffer_dones.append(False)

        # Store video frames (make copy to ensure thread safety)
        if top_frame is not None:
            self.buffer_top_frames.append(top_frame.copy())
        if wrist_frame is not None:
            self.buffer_wrist_frames.append(wrist_frame.copy())

    def stop_and_save(self) -> Optional[Dict[str, Any]]:
        """
        Finalizes recording buffer, writes Parquet table & MP4 videos,
        appends to episodes.jsonl, and returns summary metadata.
        """
        if not self.recording:
            logger.warning("stop_and_save called but not recording.")
            return None

        self.recording = False
        num_steps = len(self.buffer_timestamps)

        if num_steps < 5:
            logger.warning(f"Episode #{self.current_episode_index} too short ({num_steps} steps), discarding.")
            self.discard_episode()
            return None

        # Mark last step done = True
        self.buffer_dones[-1] = True

        ep_id = self.current_episode_index
        ep_name = f"episode_{ep_id:06d}"

        # 1. Save Parquet
        parquet_path = os.path.join(self.output_dir, "data", "chunk-000", f"{ep_name}.parquet")
        table = pa.Table.from_arrays(
            [
                pa.array(self.buffer_timestamps, type=pa.float64()),
                pa.array(self.buffer_indices, type=pa.int64()),
                pa.array(self.buffer_states, type=pa.list_(pa.float32(), 12)),
                pa.array(self.buffer_actions, type=pa.list_(pa.float32(), 6)),
                pa.array(self.buffer_dones, type=pa.bool_()),
                pa.array([ep_id] * num_steps, type=pa.int64()),
            ],
            names=["timestamp", "index", "observation.state", "action", "next.done", "episode_index"]
        )
        pq.write_table(table, parquet_path, compression="snappy")

        # 2. Save MP4 Videos
        top_video_path = os.path.join(
            self.output_dir, "videos", "observation.images.top", "chunk-000", f"{ep_name}.mp4"
        )
        wrist_video_path = os.path.join(
            self.output_dir, "videos", "observation.images.wrist", "chunk-000", f"{ep_name}.mp4"
        )

        self._encode_video(self.buffer_top_frames, top_video_path, default_w=1280, default_h=720)
        self._encode_video(self.buffer_wrist_frames, wrist_video_path, default_w=640, default_h=480)

        # 3. Update episodes.jsonl
        ep_meta = {
            "episode_index": ep_id,
            "task": self.task_name,
            "length": num_steps,
            "duration_sec": round(self.buffer_timestamps[-1], 2),
            "parquet_file": os.path.relpath(parquet_path, self.output_dir),
            "videos": {
                "top": os.path.relpath(top_video_path, self.output_dir),
                "wrist": os.path.relpath(wrist_video_path, self.output_dir)
            },
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "custom_metadata": self.current_metadata
        }

        with open(os.path.join(self.output_dir, "meta", "episodes.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(ep_meta) + "\n")

        self.current_episode_index += 1
        self._ensure_info_json()

        self.last_saved_episode_info = ep_meta
        logger.info(f"Successfully saved {ep_name} ({num_steps} steps, {ep_meta['duration_sec']}s)")
        return ep_meta

    def discard_episode(self):
        """Immediately discards current episode in-memory buffer with zero disk residue"""
        num_steps = len(self.buffer_timestamps)
        self.buffer_timestamps.clear()
        self.buffer_indices.clear()
        self.buffer_states.clear()
        self.buffer_actions.clear()
        self.buffer_dones.clear()
        self.buffer_top_frames.clear()
        self.buffer_wrist_frames.clear()
        self.recording = False
        logger.info(f"Discarded episode buffer ({num_steps} steps). Ready for retry.")

    def _encode_video(self, frames: List[np.ndarray], output_path: str, default_w: int, default_h: int):
        """Encodes frame list to MP4 using OpenCV VideoWriter"""
        if not frames:
            # Generate black blank video if camera frames were missing
            frames = [np.zeros((default_h, default_w, 3), dtype=np.uint8) for _ in range(max(1, len(self.buffer_timestamps)))]

        h, w = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, float(self.fps), (w, h))

        for frame in frames:
            if frame.shape[:2] != (h, w):
                frame = cv2.resize(frame, (w, h))
            writer.write(frame)

        writer.release()
