import os
import shutil
import tempfile
import numpy as np
import pyarrow.parquet as pq
import pytest

from recorder.lerobot_recorder import LeRobotDatasetRecorder

def test_lerobot_recorder_lifecycle():
    temp_dir = tempfile.mkdtemp()
    try:
        rec = LeRobotDatasetRecorder(output_dir=temp_dir, fps=30, task_name="task_load_s1")

        # 1. Start episode
        rec.start_episode(metadata={"stop_dx_cm": 1.2, "stop_dy_cm": -0.8})
        assert rec.recording is True

        # 2. Record 30 steps with dummy images
        dummy_top = np.zeros((720, 1280, 3), dtype=np.uint8)
        dummy_wrist = np.zeros((480, 640, 3), dtype=np.uint8)

        for i in range(30):
            obs_state = [0.1 * i] * 12
            action = [0.05 * i] * 6
            rec.record_step(obs_state, action, dummy_top, dummy_wrist)

        assert len(rec.buffer_timestamps) == 30

        # 3. Stop and Save
        meta = rec.stop_and_save()
        assert meta is not None
        assert meta["episode_index"] == 0
        assert meta["length"] == 30
        assert rec.recording is False

        # 4. Verify Parquet File
        parquet_file = os.path.join(temp_dir, meta["parquet_file"])
        assert os.path.exists(parquet_file)

        table = pq.read_table(parquet_file)
        assert table.num_rows == 30
        assert "observation.state" in table.column_names
        assert "action" in table.column_names
        assert "next.done" in table.column_names
        assert table["next.done"][-1].as_py() is True
        assert table["next.done"][0].as_py() is False

        # 5. Verify Video Files
        top_video = os.path.join(temp_dir, meta["videos"]["top"])
        wrist_video = os.path.join(temp_dir, meta["videos"]["wrist"])
        assert os.path.exists(top_video)
        assert os.path.exists(wrist_video)
        assert os.path.getsize(top_video) > 0
        assert os.path.getsize(wrist_video) > 0

    finally:
        shutil.rmtree(temp_dir)

def test_lerobot_recorder_discard():
    temp_dir = tempfile.mkdtemp()
    try:
        rec = LeRobotDatasetRecorder(output_dir=temp_dir, fps=30)
        rec.start_episode()
        for _ in range(15):
            rec.record_step([0.0]*12, [0.0]*6)
        assert len(rec.buffer_timestamps) == 15

        rec.discard_episode()
        assert rec.recording is False
        assert len(rec.buffer_timestamps) == 0

        # Ensure no parquet file was created
        chunk_dir = os.path.join(temp_dir, "data", "chunk-000")
        assert len(os.listdir(chunk_dir)) == 0
    finally:
        shutil.rmtree(temp_dir)
