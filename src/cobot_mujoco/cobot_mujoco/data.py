"""Auditable recording splits and decoded camera caches for offline learning."""

import hashlib
from pathlib import Path
import subprocess

import numpy as np
import pyarrow.parquet as pq
import torch

from .common import SOURCE_REPO, SOURCE_REVISION, read_json, utc_now, write_json

SPLITS = {"train": list(range(8)), "validation": [8, 9], "test": list(range(10, 15))}
CAMERAS = ["wrist", "top"]
HEIGHT, WIDTH = 96, 128


def validate_split_plan(plan):
    """Reject overlapping recording roles before fitting or evaluating a model."""
    required = {"train", "validation", "test"}
    if not required <= set(plan):
        raise ValueError("Split plan needs train, validation, and test roles")
    sets = {}
    for role in required:
        ids = plan[role]
        if len(ids) != len(set(ids)) or any(not isinstance(i, int) or i < 0 for i in ids):
            raise ValueError("Recording ids must be unique nonnegative integers in each role")
        sets[role] = set(ids)
    if any(
        sets[a] & sets[b] for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]
    ):
        raise ValueError("Training, validation, and test recordings must be disjoint")
    return plan


def chunk_indices(start, end, index, horizon):
    """Pad the final action of this episode; never cross its recording boundary."""
    offsets = np.arange(horizon) + index
    return np.minimum(offsets, end - 1), offsets >= end


def prepare_dataset(source, cache, progress=print):
    """Materialize arrays and an immutable split manifest; fit no global statistics."""
    source, cache = Path(source), Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    ready = cache / "manifest.json"
    if ready.exists():
        manifest = read_json(ready)
        if manifest["source_revision"] != SOURCE_REVISION:
            raise ValueError("Cache belongs to a different dataset revision")
        return manifest
    info = read_json(source / "meta/info.json")
    records = []
    for path in sorted((source / "meta/episodes").rglob("*.parquet")):
        records.extend(pq.read_table(path).to_pylist())
    records.sort(key=lambda x: x["episode_index"])
    if [r["episode_index"] for r in records] != list(range(15)):
        raise ValueError("Predeclared split expects exactly the pinned 15 recordings")
    total = sum(r["length"] for r in records)
    images = np.lib.format.open_memmap(
        cache / "images.npy", mode="w+", dtype=np.uint8, shape=(total, 2, 3, HEIGHT, WIDTH)
    )
    states, actions, ee, episode_ids = [], [], [], []
    episodes, hashes = [], []
    offset = 0
    for record in records:
        episode = record["episode_index"]
        path = source / info["data_path"].format(
            chunk_index=record["data/chunk_index"], file_index=record["data/file_index"]
        )
        table = pq.read_table(path).to_pydict()
        keep = np.asarray(table["episode_index"]) == episode
        s = np.asarray(table["observation.state"], np.float32)[keep]
        a = np.asarray(table["action"], np.float32)[keep]
        pose = np.asarray(table["aux.ee_pose"], np.float32)[keep]
        length = len(s)
        if length != record["length"] or s.shape != (length, 6) or a.shape != s.shape:
            raise ValueError(f"Malformed episode {episode}")
        if not np.isfinite(s).all() or not np.isfinite(a).all():
            raise ValueError(f"Non-finite episode {episode}")
        for camera_index, camera in enumerate(CAMERAS):
            prefix = f"videos/observation.images.{camera}"
            video = source / info["video_path"].format(
                video_key=f"observation.images.{camera}",
                chunk_index=record[prefix + "/chunk_index"],
                file_index=record[prefix + "/file_index"],
            )
            start = record[prefix + "/from_timestamp"]
            command = [
                "ffmpeg",
                "-v",
                "error",
                "-threads",
                "2",
                "-ss",
                str(start),
                "-i",
                str(video),
                "-frames:v",
                str(length),
                "-vf",
                f"scale={WIDTH}:{HEIGHT}",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-threads",
                "1",
                "-",
            ]
            decoded = subprocess.run(command, capture_output=True, check=True).stdout
            frame_bytes = HEIGHT * WIDTH * 3
            count = len(decoded) // frame_bytes
            if count != length or len(decoded) % frame_bytes:
                raise ValueError(f"Video alignment mismatch episode {episode} {camera}: {count}/{length}")
            frames = np.frombuffer(decoded, np.uint8).reshape(length, HEIGHT, WIDTH, 3)
            images[offset : offset + length, camera_index] = frames.transpose(0, 3, 1, 2)
            hashes.append(
                {
                    "file": str(video.relative_to(source)),
                    "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                }
            )
        states.append(s)
        actions.append(a)
        ee.append(pose)
        episode_ids.extend([episode] * length)
        episodes.append(
            {
                "id": episode,
                "start": offset,
                "end": offset + length,
                "length": length,
                "duration_s": length / info["fps"],
                "recording_sha256": hashlib.sha256(s.tobytes() + a.tobytes()).hexdigest(),
            }
        )
        offset += length
        progress(f"DECODED episode={episode} frames={length}", flush=True)
    images.flush()
    states, actions, ee = np.concatenate(states), np.concatenate(actions), np.concatenate(ee)
    np.save(cache / "states.npy", states)
    np.save(cache / "actions.npy", actions)
    np.save(cache / "ee.npy", ee)
    np.save(cache / "episode_ids.npy", np.asarray(episode_ids, np.int32))
    hashes += [
        {"file": str(p.relative_to(source)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted((source / "data").rglob("*.parquet"))
    ]
    signatures = [e["recording_sha256"] for e in episodes]
    if len(signatures) != len(set(signatures)):
        raise ValueError("Duplicate recordings detected; group these before splitting")
    manifest = {
        "created_at": utc_now(),
        "source_repo": SOURCE_REPO,
        "source_revision": SOURCE_REVISION,
        "source_license": "apache-2.0",
        "total_frames": total,
        "fps": info["fps"],
        "episodes": episodes,
        "splits": SPLITS,
        "camera_order": CAMERAS,
        "image_shape": [3, HEIGHT, WIDTH],
        "files": hashes,
        "split_policy": "recording-disjoint; early session train/validation, later session locked test",
        "all_success_only": True,
        "limitations": [
            "Only two validation recordings",
            "Test session has five recordings",
            "No negative examples for a failure detector",
            "Later session changes starting posture",
        ],
    }
    write_json(ready, manifest)
    return manifest


class RecordingDataset(torch.utils.data.Dataset):
    """Read memory-mapped cameras with training-only normalization and masks."""

    def __init__(self, cache, episode_ids, horizon, statistics=None, stride=3, split_plan=None):
        """Bind recording indices and training-fitted normalization to memory-mapped arrays."""
        self.cache = Path(cache)
        self.manifest = read_json(self.cache / "manifest.json")
        self.states = np.load(self.cache / "states.npy", mmap_mode="r")
        self.actions = np.load(self.cache / "actions.npy", mmap_mode="r")
        self.images = np.load(self.cache / "images.npy", mmap_mode="r")
        self.horizon = horizon
        self.split_plan = validate_split_plan(split_plan or SPLITS)
        records = {r["id"]: r for r in self.manifest["episodes"]}
        self.episode_ids = list(episode_ids)
        if not self.episode_ids or not set(self.episode_ids) <= set(records):
            raise ValueError("Dataset needs known nonempty recording ids")
        self.indices, self.ends, self.recording_ids = [], [], []
        fitting = []
        for episode in self.episode_ids:
            r = records[episode]
            idx = list(range(r["start"], r["end"], stride))
            self.indices.extend(idx)
            self.ends.extend([r["end"]] * len(idx))
            self.recording_ids.extend([episode] * len(idx))
            fitting.extend(range(r["start"], r["end"]))
        if statistics is None:
            if not set(self.episode_ids) <= set(self.split_plan["train"]):
                raise ValueError("Normalization must be fitted on training recordings only")
            self.statistics = {
                "state_mean": np.mean(self.states[fitting], axis=0).tolist(),
                "state_std": np.maximum(np.std(self.states[fitting], axis=0), 1.0).tolist(),
                "action_mean": np.mean(self.actions[fitting], axis=0).tolist(),
                "action_std": np.maximum(np.std(self.actions[fitting], axis=0), 1.0).tolist(),
                "fitted_episodes": self.episode_ids,
            }
        else:
            if not set(statistics["fitted_episodes"]) <= set(self.split_plan["train"]):
                raise ValueError("Statistics include nontraining recordings")
            self.statistics = statistics

    def __len__(self):
        """Return the number of sampled recording frames."""
        return len(self.indices)

    def __getitem__(self, item):
        """Return an observation and a masked future chunk from the same recording."""
        index, end = self.indices[item], self.ends[item]
        ids, pad = chunk_indices(0, end, index, self.horizon)
        stats = self.statistics
        state = (self.states[index] - stats["state_mean"]) / stats["state_std"]
        action = (self.actions[ids] - stats["action_mean"]) / stats["action_std"]
        return {
            "observation.state": torch.tensor(state, dtype=torch.float32),
            "pixels": torch.from_numpy(self.images[index].copy()),
            "action": torch.tensor(action, dtype=torch.float32),
            "action_is_pad": torch.from_numpy(pad.copy()),
            "episode": self.recording_ids[item],
        }


def correction_sample_weights(dataset, correction_ids):
    """Assign equal source-domain probability and equal recording probability within domains."""
    from collections import Counter

    correction_ids = set(correction_ids)
    present = set(dataset.recording_ids)
    basic = present - correction_ids
    corrections = present & correction_ids
    if not basic or not corrections:
        raise ValueError("Balanced correction sampling requires both training domains")
    counts = Counter(dataset.recording_ids)
    return torch.tensor(
        [
            0.5 / (len(corrections if episode in corrections else basic) * counts[episode])
            for episode in dataset.recording_ids
        ],
        dtype=torch.float64,
    )
