"""Supervise the version-correct ACT comparison independently of an interactive session."""

import argparse
from datetime import datetime
import fcntl
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

from .act044_report import evidence, render
from .act044_training import provenance, score, trial_plan
from .common import REPOSITORY, read_json, utc_now, write_json
from .retraining_runner import execute
from .runner import publish_report


def run_comparison(run, source, publish=True):
    """Freeze comparisons, adopt running workers, choose by validation, and then score held-out data."""
    run = Path(run)
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / "supervisor.lock").open("w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    current = provenance()
    plan = trial_plan()
    if (run / "plan.json").exists():
        prior = read_json(run / "plan.json")
        if {k: v for k, v in prior.items() if k != "frozen_at"} != plan:
            raise ValueError("Frozen 0.4.4 comparison plan changed; use a separate run directory")
        plan = prior
    else:
        plan["frozen_at"] = utc_now()
        write_json(run / "plan.json", plan)
    write_json(run / "provenance.json", current)
    started = datetime.fromisoformat(plan["frozen_at"]).timestamp()
    deadline = started + plan["maximum_hours"] * 3600
    report_root = REPOSITORY / "docs/mujoco_validation/lerobot044"
    state = {
        "status": "running",
        "phase": "training_validation",
        "started_at": plan["frozen_at"],
        "deadline_epoch": deadline,
        "pid": os.getpid(),
        "current_job": None,
        "failures": [],
        "publication": "pending" if publish else "not_requested",
        "expected_jobs": plan["expected_jobs"],
        "expected_comparison_cells": plan["expected_comparison_cells"],
        "lerobot_version": current["lerobot_version"],
    }
    (run / "pid").write_text(str(os.getpid()))

    def report():
        data = evidence(run)
        state.update(
            completed_jobs=len(data["jobs"]),
            completed_comparisons=len(data["measurements"]),
            updated_at=utc_now(),
        )
        write_json(run / "status.json", state)
        render(run, report_root / "report.html")

    try:
        report()
        for cfg in plan["trials"]:
            if (run / "STOP").exists() or time.time() >= deadline - plan["final_reserve_seconds"]:
                break
            output = run / "jobs" / cfg["name"]
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "config.json", cfg)
            state.update(phase="training_validation", current_job=cfg["name"])
            report()
            command = [
                sys.executable,
                "-m",
                "cobot_mujoco.act044_worker",
                "--source",
                str(source),
                "--output",
                str(output),
                "--config",
                str(output / "config.json"),
                "--deadline",
                str(min(deadline - plan["final_reserve_seconds"], time.time() + 7200)),
            ]
            if execute(command, output, run, deadline, report) is None:
                state["failures"].append(cfg["name"])
        data = evidence(run)
        complete = (
            len(data["jobs"]) == plan["expected_jobs"]
            and len(data["measurements"]) == plan["expected_comparison_cells"]
            and all(j["status"] == "completed" for j in data["jobs"])
        )
        if complete and not (run / "STOP").exists():
            if (run / "selected.json").exists():
                selected = read_json(run / "selected.json")
            else:
                selected = {
                    "selected_at": utc_now(),
                    "criterion": "Validation only, before held-out scoring",
                    "models": {
                        architecture: min(
                            [r for r in data["measurements"] if r["config"]["architecture"] == architecture],
                            key=lambda r: r["validation"]["control_mae"],
                        )
                        for architecture in ["standard", "light"]
                    },
                }
                write_json(run / "selected.json", selected)
            heldout = read_json(run / "heldout.json") if (run / "heldout.json").exists() else {}
            for architecture, row in selected["models"].items():
                state.update(phase="heldout_validation", current_job=row["config"]["name"])
                report()
                if architecture not in heldout and time.time() < deadline:
                    root = run / "jobs" / row["config"]["name"] / "dataset"
                    heldout[architecture] = score(
                        row["checkpoint"], root, plan["split_plan"]["test"], stride=6
                    )
                    write_json(run / "heldout.json", heldout)
                target = run / "selected" / architecture
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.symlink_to(Path(row["checkpoint"]).resolve(), target_is_directory=True)
            complete &= len(heldout) == 2
        state.update(
            status="stopped"
            if (run / "STOP").exists()
            else "completed"
            if complete and not state["failures"]
            else "incomplete",
            phase="finished",
            current_job=None,
            finished_at=utc_now(),
            elapsed_s=time.time() - started,
        )
        report()
    except BaseException as error:
        state.update(status="failed", error=f"{type(error).__name__}: {error}", finished_at=utc_now())
        (run / "supervisor_error.log").write_text(traceback.format_exc())
        report()
        raise
    finally:
        for name in [
            "plan.json",
            "provenance.json",
            "status.json",
            "selected.json",
            "heldout.json",
            "smoke_validation.json",
        ]:
            if (run / name).exists():
                shutil.copyfile(run / name, report_root / name)
        data = evidence(run)
        write_json(report_root / "job_results.json", data["jobs"])
        write_json(report_root / "comparison_measurements.json", data["measurements"])
        if publish:
            try:
                publish_report(report_root)
                state["publication"] = "pushed"
            except Exception as error:
                state.update(publication="failed", publication_error=str(error))
            write_json(run / "status.json", state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def main():
    """Launch a durable ACT training and validation supervisor with exact runtime checks."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()
    run_comparison(args.run, args.source, not args.no_push)


if __name__ == "__main__":
    main()
