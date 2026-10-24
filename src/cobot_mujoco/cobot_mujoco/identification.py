"""Reproduce empirical motor lag / residual identification using training recordings."""

from pathlib import Path

import numpy as np

from .common import read_json
from .data import SPLITS


def identify_command_response(cache):
    """Fit an integer command lag, then report residuals without held-out data."""
    cache = Path(cache)
    manifest = read_json(cache / "manifest.json")
    states = np.load(cache / "states.npy", mmap_mode="r")
    actions = np.load(cache / "actions.npy", mmap_mode="r")
    recordings = [r for r in manifest["episodes"] if r["id"] in SPLITS["train"]]
    result = []
    for joint in range(6):
        candidates = []
        for lag in range(31):
            differences = []
            for r in recordings:
                start, end = r["start"], r["end"]
                differences.append(
                    states[start + lag : end, joint] - actions[start : end - lag if lag else end, joint]
                )
            delta = np.concatenate(differences)
            candidates.append((float(np.mean(delta**2)), lag, float(np.mean(delta))))
        error, lag, bias = min(candidates)
        result.append(
            {
                "joint": joint,
                "delay_steps": lag,
                "rmse": error**0.5,
                "bias": bias,
                "zero_delay_rmse": candidates[0][0] ** 0.5,
            }
        )
    return {
        "training_recordings": SPLITS["train"],
        "joints": result,
        "limitation": "Approximate system identification; bias is not a physical encoder recalibration",
    }
