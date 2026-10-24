"""Durable experiment supervisor with a wall-clock ceiling and HTML finalizer."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from .common import PACKAGE, REPOSITORY, read_json, utc_now, write_json
from .report import make_report

BRANCH = "feature/manipulation-mujoco-validation"


def trial_grid(sweep):
    """Complete a diverse first seed before spending time on replications."""
    result = []
    for seed in sweep["seeds"]:
        for variation in sweep["experiments"]:
            config = {**sweep["base"], **variation, "seed": seed}
            config["name"] = f"{variation['name']}_seed{seed}"
            result.append(config)
    return result


def publish_report(report_dir):
    """Push only requested report artifacts on the dedicated feature branch."""
    current = subprocess.check_output(["git", "branch", "--show-current"], cwd=REPOSITORY, text=True).strip()
    if current != BRANCH:
        raise RuntimeError(f"Refusing to publish from unexpected branch {current}")
    expected = "https://github.com/kernel-robot-8th/kernel-robot-repo-4"
    remote = (
        subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=REPOSITORY, text=True)
        .strip()
        .removesuffix(".git")
    )
    if remote != expected:
        raise RuntimeError("Unexpected report publication destination")
    relative = Path(report_dir).relative_to(REPOSITORY)
    subprocess.run(["git", "add", "--", str(relative)], cwd=REPOSITORY, check=True)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPOSITORY).returncode
    if changed:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=HeoJiHyeok",
                "-c",
                "user.email=125938592+JiHyeokHeo@users.noreply.github.com",
                "commit",
                "-m",
                "docs(cobot_mujoco): record bounded training and simulation results",
            ],
            cwd=REPOSITORY,
            check=True,
        )
    subprocess.run(
        ["git", "push", "origin", f"HEAD:refs/heads/{BRANCH}"], cwd=REPOSITORY, check=True, timeout=120
    )


def run_sweep(cache, assets, run, report_dir, hours=12.0, push=False, sweep_path=None):
    """Run independently of an interactive terminal and resume completed trials."""
    run, report_dir = Path(run), Path(report_dir)
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / "runner.lock").open("w")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError("This run already has an active supervisor") from error
    started = time.time()
    schedule = run / "schedule.json"
    sweep = read_json(sweep_path or PACKAGE / "config/sweep.json")
    if schedule.exists():
        prior = read_json(schedule)
        wall_deadline = prior["deadline_epoch"]
        if prior["sweep"] != sweep:
            raise ValueError("Cannot change a persisted experiment plan during resume")
    else:
        wall_deadline = started + min(hours, sweep["maximum_hours"]) * 3600
        write_json(
            schedule,
            {
                "started_at": utc_now(),
                "deadline_epoch": wall_deadline,
                "sweep": sweep,
                "source_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
                ).strip(),
            },
        )
    grid = trial_grid(sweep)
    state = {
        "status": "running",
        "started_at": read_json(schedule)["started_at"],
        "deadline_epoch": wall_deadline,
        "planned_trials": len(grid),
        "pid": os.getpid(),
        "completed_trials": 0,
        "failures": [],
        "current_trial": None,
        "publication": "not_requested" if not push else "pending",
        "runtime_git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            text=True,
        ).strip(),
    }
    if (run / "status.json").exists():
        state["failures"] = read_json(run / "status.json").get("failures", [])
    report_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(cache) / "manifest.json", run / "data_manifest.json")
    if not (run / "scene.json").exists():
        shutil.copyfile(PACKAGE / "config/scene.json", run / "scene.json")
    state["scene_sha256"] = hashlib.sha256((run / "scene.json").read_bytes()).hexdigest()
    shutil.copyfile(schedule, report_dir / "schedule.json")
    (run / "pid").write_text(str(os.getpid()))
    child = None

    def report():
        state["updated_at"] = utc_now()
        write_json(run / "status.json", state)
        make_report(run, report_dir / "report.html", run / "evidence")

    try:
        report()
        test_already_opened = (run / "test_access.json").exists()
        for config in [] if test_already_opened else grid:
            trial = run / "trials" / config["name"]
            if (trial / "result.json").exists():
                state["completed_trials"] += 1
                continue
            if (run / "STOP").exists():
                state["status"] = "stopped"
                break
            remaining = wall_deadline - time.time() - sweep["finalization_reserve_seconds"]
            if remaining < 120:
                state["status"] = "budget_reached"
                break
            trial.mkdir(parents=True, exist_ok=True)
            write_json(trial / "config.json", config)
            state["current_trial"] = config["name"]
            report()
            budget = min(sweep["trial_budget_seconds"], remaining)
            command = [
                sys.executable,
                "-m",
                "cobot_mujoco.train",
                "--cache",
                str(cache),
                "--config",
                str(trial / "config.json"),
                "--output",
                str(trial),
                "--budget-s",
                str(budget),
            ]
            with (trial / "terminal.log").open("a", buffering=1) as log:
                log.write(f"\nSTART {utc_now()} {json.dumps(command)}\n")
                child = subprocess.Popen(
                    command, stdout=log, stderr=subprocess.STDOUT, cwd=REPOSITORY, env=os.environ.copy()
                )
                last_report = 0.0
                while child.poll() is None:
                    if (run / "STOP").exists() or time.time() >= wall_deadline:
                        child.terminate()
                        try:
                            child.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=10)
                        break
                    if time.monotonic() - last_report > 30:
                        report()
                        last_report = time.monotonic()
                    time.sleep(3)
                code = child.returncode
                child = None
            if code == 0 and (trial / "result.json").exists():
                state["completed_trials"] += 1
                state["failures"] = [f for f in state["failures"] if f["trial"] != config["name"]]
                if (trial / "failure.json").exists():
                    prior_failure = read_json(trial / "failure.json")
                    write_json(trial / "failure.json", {**prior_failure, "resolved_by_resume_at": utc_now()})
            else:
                state["failures"].append(
                    {"trial": config["name"], "exit_code": code, "log": str(trial / "terminal.log")}
                )
                write_json(trial / "failure.json", {"exit_code": code, "at": utc_now()})
                if len(state["failures"]) >= 3 and state["completed_trials"] == 0:
                    raise RuntimeError("Three trials failed without any successful training; see logs")
            report()
        trials = [read_json(p) for p in (run / "trials").glob("*/result.json")]
        state["completed_trials"] = len(trials)
        selected = read_json(run / "selected.json") if test_already_opened else []
        if not test_already_opened:
            for family in ["state", "cnn", "act"]:
                candidates = [t for t in trials if t["config"]["family"] == family]
                if candidates:
                    selected.append(min(candidates, key=lambda t: t["best_validation_mae"]))
        write_json(run / "selected.json", selected)
        state["phase"] = "final_locked_test_and_provisional_simulation"
        state["current_trial"] = None
        report()
        if selected and not (run / "STOP").exists() and time.time() < wall_deadline:
            from .evaluation import final_evaluation

            deadline = time.monotonic() + max(0, wall_deadline - time.time() - 120)
            final_evaluation(cache, assets, selected, sweep, run, deadline, progress=report)
        if state["status"] == "running":
            state["status"] = "completed_with_failures" if state["failures"] else "completed"
        state["phase"] = "finished"
        state["finished_at"] = utc_now()
        state["elapsed_s"] = time.time() - (wall_deadline - min(hours, sweep["maximum_hours"]) * 3600)
        report()
    except BaseException as error:
        if child is not None and child.poll() is None:
            child.terminate()
        state.update(status="failed", error=f"{type(error).__name__}: {error}", finished_at=utc_now())
        (run / "supervisor_error.log").write_text(traceback.format_exc())
        report()
        raise
    finally:
        for name in [
            "status.json",
            "diagnostics.json",
            "selected.json",
            "final_evaluation.json",
            "test_access.json",
            "scene.json",
        ]:
            if (run / name).exists():
                shutil.copyfile(run / name, report_dir / name)
        summaries = [read_json(p) for p in (run / "trials").glob("*/result.json")]
        write_json(report_dir / "trials.json", summaries)
        if push:
            try:
                state["publication"] = "report_committed_and_push_requested"
                report()
                shutil.copyfile(run / "status.json", report_dir / "status.json")
                publish_report(report_dir)
                state["publication"] = "pushed"
                write_json(run / "status.json", state)
            except Exception as error:
                state["publication"] = "failed"
                state["publication_error"] = f"{type(error).__name__}: {error}"
                write_json(run / "status.json", state)
                print(f"PUBLICATION_FAILED {error}", flush=True)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return state
