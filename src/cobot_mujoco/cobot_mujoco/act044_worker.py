"""Bound one genuine LeRobot 0.4.4 ACT training job and validate its saved checkpoints."""

import argparse
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
import traceback

from .act044_training import command, provenance, score, verify_training_ids
from .common import read_json, utc_now, write_json
from .native_training import native_checkpoints, prepare_native_root


def train_job(source, output, cfg, deadline):
    """Preserve upstream source, explicit partitions, actual steps, and comparable validation metrics."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "worker.pid").write_text(str(os.getpid()))
    runtime = provenance()
    write_json(output / "provenance.json", runtime)
    write_json(output / "config.json", cfg)
    started = time.time()
    root = prepare_native_root(source, output / "dataset", cfg["split_plan"])
    partition = verify_training_ids(root, cfg)
    write_json(output / "training_partition.json", partition)
    upstream = output / "upstream"
    args = command(root, upstream, cfg)
    prior = native_checkpoints(upstream)
    if prior:
        args += [f"--config_path={prior[-1] / 'train_config.json'}", "--resume=true"]
    write_json(output / "command.json", args)
    (output / "command.sh").write_text("#!/usr/bin/env bash\nexec " + shlex.join(args) + "\n")
    peak = 0
    limited = False
    with (output / "upstream.log").open("a") as log:
        process = subprocess.Popen(
            args,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=Path.home() / "il_ws/src/lerobot",
            env={**os.environ, "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"},
        )
        write_json(
            output / "status.json",
            {
                "status": "training",
                "started_at": utc_now(),
                "worker_pid": os.getpid(),
                "upstream_pid": process.pid,
                "config": cfg,
            },
        )
        while process.poll() is None:
            if time.time() >= deadline:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                limited = True
                break
            try:
                memory = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=5,
                )
                peak = max(peak, int(memory.strip().splitlines()[0]))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            time.sleep(5)
    checkpoints = native_checkpoints(upstream)
    if not checkpoints:
        raise RuntimeError(f"No upstream checkpoint, exit {process.returncode}; see upstream.log")
    write_json(output / "status.json", {"status": "validating", "worker_pid": os.getpid(), "config": cfg})
    measurements = read_json(output / "measurements.json") if (output / "measurements.json").exists() else []
    for checkpoint in checkpoints:
        step = int(checkpoint.parent.name)
        if step not in cfg["comparison_steps"] or any(r["step"] == step for r in measurements):
            continue
        if time.time() >= deadline:
            limited = True
            break
        validation = score(checkpoint, root, cfg["split_plan"]["validation"], stride=12)
        fitted = score(checkpoint, root, cfg["split_plan"]["train"], stride=48)
        measurements.append(
            {
                "step": step,
                "checkpoint": str(checkpoint),
                "validation": validation,
                "training_probe": fitted,
                "gap": validation["control_mae"] - fitted["control_mae"],
                "config": cfg,
                "lerobot_version": runtime["lerobot_version"],
            }
        )
        write_json(output / "measurements.json", measurements)
        print("ACT044_VALIDATED", cfg["name"], step, validation["control_mae"], flush=True)
    if provenance()["trainer_sha256"] != runtime["trainer_sha256"]:
        raise RuntimeError("Upstream 0.4.4 trainer source changed during this job")
    result = {
        "status": "completed"
        if process.returncode == 0 and not limited
        else "time_limited"
        if limited
        else "failed_with_checkpoint",
        "config": cfg,
        "actual_steps": int(checkpoints[-1].parent.name),
        "requested_steps": cfg["steps"],
        "upstream_exit_code": process.returncode,
        "measurements": measurements,
        "elapsed_s": time.time() - started,
        "finished_at": utc_now(),
        "gpu_peak_device_mib": peak,
        "gpu_memory_scope": (
            "Whole GPU memory sampled while upstream trainer runs; includes other GPU processes"
        ),
        "source": runtime,
        "checkpoint_root": str(upstream / "checkpoints"),
        "dataset_root": str(root),
        "training_frames": partition["frames"],
    }
    write_json(output / "result.json", result)
    write_json(output / "status.json", result)


def main():
    """Run a durable isolated training and validation worker."""
    parser = argparse.ArgumentParser()
    for key in ["source", "output", "config"]:
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    args = parser.parse_args()
    try:
        train_job(args.source, args.output, read_json(args.config), args.deadline)
    except BaseException as error:
        write_json(
            Path(args.output) / "failure.json",
            {"at": utc_now(), "error": str(error), "traceback": traceback.format_exc()},
        )
        raise


if __name__ == "__main__":
    main()
