import os
import shutil
import tempfile
import numpy as np
import pyarrow.parquet as pq
import pytest

from recorder.lerobot_recorder import LeRobotDatasetRecorder

def test_lerobot_recorder_lifecycle_success_and_fail():
    temp_dir = tempfile.mkdtemp()
    try:
        rec = LeRobotDatasetRecorder(output_dir=temp_dir, fps=30, task_name="task_load_s1")

        # 1. Start episode 0 (Success)
        rec.start_episode(metadata={"stop_dx_cm": 1.2, "stop_dy_cm": -0.8})
        assert rec.recording is True

        dummy_top = np.zeros((720, 1280, 3), dtype=np.uint8)
        dummy_wrist = np.zeros((480, 640, 3), dtype=np.uint8)

        for i in range(30):
            obs_state = [0.1 * i] * 12
            action = [0.05 * i] * 6
            rec.record_step(obs_state, action, dummy_top, dummy_wrist)

        assert len(rec.buffer_timestamps) == 30

        # Stop with success
        meta = rec.stop_and_save(status="success")
        assert meta is not None
        assert meta["episode_index"] == 0
        assert meta["status"] == "success"
        assert meta["success"] is True

        parquet_file = os.path.join(temp_dir, meta["parquet_file"])
        assert os.path.exists(parquet_file)
        table = pq.read_table(parquet_file)
        assert table.num_rows == 30
        assert table["success"][0].as_py() is True
        assert table["status"][0].as_py() == "success"

        # 2. Start episode 1 (Fail)
        rec.start_episode(task_name="task_load_s1")
        for i in range(15):
            rec.record_step([0.2 * i] * 12, [0.1 * i] * 6, dummy_top, dummy_wrist)

        meta_fail = rec.stop_and_save(status="fail")
        assert meta_fail is not None
        assert meta_fail["episode_index"] == 1
        assert meta_fail["status"] == "fail"
        assert meta_fail["success"] is False

        parquet_file_fail = os.path.join(temp_dir, meta_fail["parquet_file"])
        assert os.path.exists(parquet_file_fail)
        table_fail = pq.read_table(parquet_file_fail)
        assert table_fail.num_rows == 15
        assert table_fail["success"][0].as_py() is False
        assert table_fail["status"][0].as_py() == "fail"

        # Check videos created for both
        assert os.path.exists(os.path.join(temp_dir, meta_fail["videos"]["top"]))
        assert os.path.exists(os.path.join(temp_dir, meta_fail["videos"]["wrist"]))

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
