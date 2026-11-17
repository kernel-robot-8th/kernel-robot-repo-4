"""Prepare the box-on-Pinky datasets (omx_1022_success, omx_v1) for training.

Steps (originals in data/ are never modified):
  fix    data/omx_v1 -> data/omx_v1_fixed
         omx_v1's meta/episodes only lists episode 20 (the recorder overwrote it). Rebuild all 21
         rows from the per-episode data files and the video frame counts.
  prep   data/{omx_1022_success, omx_v1_fixed} -> data/box_{1022,v1}
         one English task text for both datasets
  grip   data/box_X -> data/box_X_grip
         observation.state = 6 joints + aux.gripper_current (7 values)
  merge  data/box_1022 + data/box_v1 -> data/box_merged (same for *_grip)

Usage (inside the training image; datasets under $DATA_DIR, default ./data):
  ./tools.sh 0 prepare_box_datasets.py [fix|prep|grip|merge|all]
"""

import glob
import json
import os
import shutil
import sys
from pathlib import Path

import av
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from lerobot.datasets.compute_stats import get_feature_stats

DATA = Path(os.environ.get("DATA_DIR", "data"))
TASK = "Pick up the box and place it on the white round robot."
GRIP_NAME = "gripper.current"


def stats_row(arr):
    """Per-episode stats in the meta/episodes format (1-D arrays per key)."""
    arr = np.asarray(arr)
    if arr.ndim == 1:
        arr = arr[:, None]
    return {k: np.asarray(v).reshape(-1) for k, v in get_feature_stats(arr, axis=0, keepdims=False).items()}


def video_frames(path):
    with av.open(str(path)) as c:
        st = c.streams.video[0]
        return st.frames or sum(1 for _ in c.decode(st))


# ---------------------------------------------------------------- fix omx_v1
def fix_v1(src=DATA / "omx_v1", dst=DATA / "omx_v1_fixed"):
    if dst.exists():
        print(f"{dst} exists, skip fix")
        return
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".cache"))
    info = json.loads((dst / "meta/info.json").read_text())
    fps = info["fps"]
    old = pd.read_parquet(dst / "meta/episodes/chunk-000/file-000.parquet")
    template = old.iloc[0]
    global_stats = json.loads((dst / "meta/stats.json").read_text())
    video_keys = [k for k, f in info["features"].items() if f["dtype"] == "video"]
    numeric_keys = [k for k, f in info["features"].items() if f["dtype"] not in ("video", "image", "string")]

    data_files = sorted(glob.glob(str(dst / "data/chunk-000/*.parquet")))
    vfiles = {k: sorted(glob.glob(str(dst / f"videos/{k}/chunk-000/*.mp4"))) for k in video_keys}
    vframes = {k: [video_frames(p) for p in fs] for k, fs in vfiles.items()}
    vpos = {k: [0, 0] for k in video_keys}  # (file index, frame offset)

    rows, start = [], 0
    for f in data_files:
        d = pd.read_parquet(f)
        ep = int(d["episode_index"].iloc[0])
        assert d["episode_index"].nunique() == 1, f
        n = len(d)
        row = {
            "episode_index": ep,
            "tasks": list(template["tasks"]),
            "length": n,
            "data/chunk_index": 0,
            "data/file_index": int(Path(f).stem.split("-")[1]),
            "dataset_from_index": start,
            "dataset_to_index": start + n,
        }
        assert int(d["index"].iloc[0]) == start, (f, d["index"].iloc[0], start)
        for k in video_keys:
            fi, off = vpos[k]
            if off + n > vframes[k][fi]:
                fi, off = fi + 1, 0
            row[f"videos/{k}/chunk_index"] = 0
            row[f"videos/{k}/file_index"] = fi
            row[f"videos/{k}/from_timestamp"] = off / fps
            row[f"videos/{k}/to_timestamp"] = (off + n) / fps
            vpos[k] = [fi, off + n]
        row["meta/episodes/chunk_index"] = 0
        row["meta/episodes/file_index"] = 0
        for k in numeric_keys:
            for s, v in stats_row(np.stack(d[k].to_numpy()) if d[k].dtype == object else d[k].to_numpy()).items():
                row[f"stats/{k}/{s}"] = v
        for k in video_keys:  # per-episode image stats are not recomputed; use the dataset-level values
            for s in ("min", "max", "mean", "std", "q01", "q10", "q50", "q90", "q99"):
                # stored as nested (channels, 1, 1) lists, like the recorder writes them
                row[f"stats/{k}/{s}"] = np.asarray(global_stats[k][s], dtype=float).reshape(-1, 1, 1).tolist()
            row[f"stats/{k}/count"] = np.asarray(template[f"stats/{k}/count"])
        rows.append(row)
        start += n

    for k in video_keys:  # every frame of every video file must be used
        fi, off = vpos[k]
        assert fi == len(vframes[k]) - 1 and off == vframes[k][fi], (k, vpos[k], vframes[k])
    # the rebuilt last episode must match the one row the recorder left behind
    last = rows[-1]
    for c in ["dataset_from_index", "dataset_to_index"] + [c for c in old.columns if c.startswith("videos/")]:
        assert np.isclose(float(last[c]), float(template[c])), (c, last[c], template[c])

    new = pd.DataFrame(rows)[list(old.columns)]
    for c in new.columns:  # match the recorder's dtypes (e.g. float32 vs float64 stats arrays)
        dt = np.asarray(template[c]).dtype
        if c.startswith("stats/") and dt.kind != "O":
            new[c] = [np.asarray(v, dtype=dt) for v in new[c]]
    new.to_parquet(dst / "meta/episodes/chunk-000/file-000.parquet")
    print(f"rebuilt {len(new)} episode rows -> {dst}")


# ---------------------------------------------------------------- prep (task text)
def prep(name, src):
    from lerobot.datasets.dataset_tools import modify_tasks
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    dst = DATA / f"box_{name}"
    if dst.exists():
        print(f"{dst} exists, skip prep")
        return
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".cache"))
    modify_tasks(LeRobotDataset(f"local/box_{name}", root=dst), new_task=TASK)
    print(f"prepared {dst}")


# ---------------------------------------------------------------- grip (state + gripper current)
def grip(name):
    src, dst = DATA / f"box_{name}", DATA / f"box_{name}_grip"
    if dst.exists():
        print(f"{dst} exists, skip grip")
        return
    shutil.copytree(src, dst)
    all_state = []
    for f in sorted(glob.glob(str(dst / "data/*/*.parquet"))):
        t = pq.read_table(f)
        st = np.stack(t.column("observation.state").to_numpy(zero_copy_only=False)).astype(np.float32)
        g = np.stack(t.column("aux.gripper_current").to_numpy(zero_copy_only=False)).astype(np.float32).reshape(-1, 1)
        new = np.concatenate([st, g], 1)
        all_state.append(new)
        col = pa.FixedSizeListArray.from_arrays(pa.array(new.reshape(-1), pa.float32()), new.shape[1])
        i = t.schema.get_field_index("observation.state")
        schema_md = t.schema.metadata
        t = t.set_column(i, pa.field("observation.state", col.type), col)
        # keep the huggingface features metadata in sync with the new shape
        if schema_md and b"huggingface" in schema_md:
            hf = json.loads(schema_md[b"huggingface"])
            feat = hf.get("info", {}).get("features", {}).get("observation.state")
            if feat and "length" in feat:
                feat["length"] = new.shape[1]
            schema_md = {**schema_md, b"huggingface": json.dumps(hf).encode()}
        pq.write_table(t.replace_schema_metadata(schema_md), f)

    info = json.loads((dst / "meta/info.json").read_text())
    fs = info["features"]["observation.state"]
    fs["shape"] = [7]
    fs["names"] = list(fs["names"]) + [GRIP_NAME]
    (dst / "meta/info.json").write_text(json.dumps(info, indent=4))

    stats = json.loads((dst / "meta/stats.json").read_text())
    stats["observation.state"] = {k: v.tolist() for k, v in stats_row(np.concatenate(all_state)).items()}
    (dst / "meta/stats.json").write_text(json.dumps(stats, indent=4))

    data = pd.concat(pd.read_parquet(f, columns=["episode_index", "observation.state"])
                     for f in sorted(glob.glob(str(dst / "data/*/*.parquet"))))
    for f in sorted(glob.glob(str(dst / "meta/episodes/*/*.parquet"))):
        e = pd.read_parquet(f)
        per_ep = [stats_row(np.stack(data[data.episode_index == ep]["observation.state"].to_numpy()))
                  for ep in e.episode_index]
        for s in per_ep[0]:
            e[f"stats/observation.state/{s}"] = [p[s] for p in per_ep]
        e.to_parquet(f)
    print(f"made {dst} (observation.state: 7 = 6 joints + {GRIP_NAME})")


# ---------------------------------------------------------------- merge
def merge(suffix=""):
    from lerobot.datasets.dataset_tools import merge_datasets
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    dst = DATA / f"box_merged{suffix}"
    if dst.exists():
        print(f"{dst} exists, skip merge")
        return
    parts = [LeRobotDataset(f"local/box_{n}{suffix}", root=DATA / f"box_{n}{suffix}") for n in ("1022", "v1")]
    merge_datasets(parts, output_repo_id=f"local/box_merged{suffix}", output_dir=dst)
    print(f"merged -> {dst}")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("fix", "all"):
        fix_v1()
    if step in ("prep", "all"):
        prep("1022", DATA / "omx_1022_success")
        prep("v1", DATA / "omx_v1_fixed")
    if step in ("grip", "all"):
        grip("1022")
        grip("v1")
    if step in ("merge", "all"):
        merge("")
        merge("_grip")
