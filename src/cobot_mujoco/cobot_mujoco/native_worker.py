"""Bound one unmodified upstream LeRobot training job and select its saved checkpoint."""

import argparse
import os
from pathlib import Path
import signal
import shlex
import subprocess
import time
import traceback

from .common import read_json, utc_now, write_json
from .native_training import (
    evaluate_native,
    native_checkpoints,
    native_command,
    native_provenance,
    prepare_native_root,
    verify_native_partition,
)


def run_native_job(source, config, output, settings):
    """Keep the upstream loop intact and record its actual command, outputs, and limits."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "worker.pid").write_text(str(os.getpid()))
    started = time.time()
    write_json(output / "status.json", {"status": "preparing", "started_at": utc_now(), "config": config})
    root = prepare_native_root(source, output / "dataset", config["split_plan"])
    actual_split = verify_native_partition(root, config["split_plan"])
    trainer_output = output / "upstream"
    command = native_command(
        root,
        trainer_output,
        actual_split,
        steps=settings["steps"],
        seed=config["seed"],
        batch_size=settings["batch_size"],
        save_freq=settings["save_freq"],
    )
    prior = native_checkpoints(trainer_output)
    if prior:
        command += [f"--config_path={prior[-1] / 'train_config.json'}", "--resume=true"]
    write_json(output / "command.json", command)
    (output / "command.sh").write_text("#!/usr/bin/env bash\nexec " + shlex.join(command) + "\n")
    write_json(output / "provenance.json", native_provenance())
    config_path = output / "config.json"
    write_json(config_path, config)
    terminated = False
    with (output / "upstream.log").open("a", buffering=1) as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"},
        )
        write_json(
            output / "status.json",
            {
                "status": "upstream_training",
                "upstream_pid": process.pid,
                "started_at": utc_now(),
                "config": config,
            },
        )
        while process.poll() is None:
            if time.time() - started >= settings["trial_budget_seconds"]:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                terminated = True
                break
            time.sleep(3)
    checkpoints = native_checkpoints(trainer_output)
    if not checkpoints:
        raise RuntimeError(
            f"Upstream trainer produced no checkpoint; exit={process.returncode}; see upstream.log"
        )
    validations = []
    if actual_split["validation"]:
        for checkpoint in checkpoints:
            value = evaluate_native(checkpoint, root, actual_split["validation"], stride=12)
            validations.append(value)
            write_json(output / "validation_checkpoints.json", validations)
        chosen = min(validations, key=lambda v: v["control_mae"])
        checkpoint = chosen["checkpoint"]
        score = chosen["control_mae"]
    else:
        chosen = None
        checkpoint = str(checkpoints[-1])
        score = None
    effective = read_json(checkpoints[-1] / "train_config.json")
    result = {
        "status": "time_limited_checkpoint"
        if terminated
        else "completed"
        if process.returncode == 0
        else "failed_with_checkpoint",
        "finished_at": utc_now(),
        "config": config,
        "effective_upstream_config": effective,
        "source_kind": "unmodified_lerobot_train",
        "checkpoint": checkpoint,
        "best_validation_mae": score,
        "validation_checkpoints": validations,
        "steps": int(checkpoints[-1].parent.name),
        "selected_step": int(Path(checkpoint).parent.name),
        "requested_steps": settings["steps"],
        "dataset_root": str(root),
        "elapsed_s": time.time() - started,
        "upstream_exit_code": process.returncode,
        "command": command,
        "normalization_fitted_on": actual_split["train"],
        "independent_test_available": bool(actual_split["test"]),
    }
    write_json(output / "result.json", result)
    write_json(output / "status.json", result)
    return result


def main():
    """Run a single native job independently of an interactive terminal."""
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--settings", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    try:
        result = run_native_job(args.source, read_json(args.config), args.output, read_json(args.settings))
        print("NATIVE_JOB_FINISHED", result["status"], result["steps"], flush=True)
    except BaseException as error:
        write_json(
            Path(args.output) / "failure.json",
            {"at": utc_now(), "error": str(error), "traceback": traceback.format_exc()},
        )
        raise


if __name__ == "__main__":
    main()
