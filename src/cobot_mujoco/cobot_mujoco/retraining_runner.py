"""Supervise revised data-role experiments, official training, and final all-data fits."""

import argparse
from datetime import datetime
import fcntl
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np
import torch
from torch.utils.data import DataLoader

from .common import PACKAGE, REPOSITORY, SOURCE_REPO, SOURCE_REVISION, read_json, utc_now, write_json
from .data import RecordingDataset
from .evaluation import load_trial, persistence_baseline
from .learning import evaluate
from .native_training import evaluate_native, native_provenance
from .retraining_protocol import lightweight_grid, native_grid
from .retraining_report import aggregate_holdouts, results_in, write_retraining_report
from .runner import publish_report


def alive(pid):
    """Check whether an adopted job is still running."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat")
        if stat.exists() and stat.read_text().split()[2] == "Z":
            return False
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False


def stop_job(output, pid):
    """Stop a worker and its upstream trainer rather than leaving GPU jobs orphaned."""
    status = read_json(Path(output) / "status.json") if (Path(output) / "status.json").exists() else {}
    upstream = status.get("upstream_pid")
    for target in [upstream, pid]:
        if target and alive(target):
            try:
                os.killpg(int(target), signal.SIGTERM)
            except ProcessLookupError:
                pass


def execute(command, output, run, deadline, report):
    """Adopt an existing native job or start one isolated process with durable evidence."""
    output, run = Path(output), Path(run)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "result.json").exists():
        return read_json(output / "result.json")
    pidfile = output / "worker.pid" if (output / "worker.pid").exists() else output / "process.pid"
    pid = int(pidfile.read_text()) if pidfile.exists() else None
    child = None
    if not alive(pid):
        with (output / "worker.log").open("a") as log:
            child = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                cwd=REPOSITORY,
                env={**os.environ, "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "MUJOCO_GL": "egl"},
            )
        pid = child.pid
        (output / "process.pid").write_text(str(pid))
    tick = 0.0
    while child.poll() is None if child is not None else alive(pid):
        if (run / "STOP").exists() or time.time() >= deadline:
            stop_job(output, pid)
            if child is not None:
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(pid, signal.SIGKILL)
            return None
        if (output / "result.json").exists():
            break
        if time.monotonic() - tick > 30:
            report()
            tick = time.monotonic()
        time.sleep(3)
    if (output / "result.json").exists():
        return read_json(output / "result.json")
    error = {
        "error": "Job exited without a result",
        "command": command,
        "exit_code": child.returncode if child is not None else None,
        "at": utc_now(),
    }
    write_json(output / "failure.json", error)
    return None


def evaluate_lightweight(cache, trial):
    """Use the frozen checkpoint on the two recordings held out of that particular fit."""
    cfg = trial["config"]
    policy, stats, _ = load_trial(trial["checkpoint"])
    dataset = RecordingDataset(
        cache, cfg["split_plan"]["test"], cfg["horizon"], stats, stride=6, split_plan=cfg["split_plan"]
    )
    metrics = evaluate(policy, DataLoader(dataset, batch_size=cfg["batch_size"]), stats)
    del policy
    torch.cuda.empty_cache()
    return metrics


def run_retraining(run, source, cache, publish=True, plan_path=None):
    """Run the revised plan and publish an honest report even when a budget or job fails."""
    run, source, cache = Path(run), Path(source), Path(cache)
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / "supervisor.lock").open("w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    plan = read_json(plan_path or PACKAGE / "config/retrain.json")
    if (run / "plan.json").exists() and read_json(run / "plan.json") != plan:
        raise ValueError("Frozen collection-role plan changed; create a separate run")
    write_json(run / "plan.json", plan)
    frozen = (
        read_json(run / "frozen_trial_plan.json")
        if (run / "frozen_trial_plan.json").exists()
        else {"frozen_at": utc_now(), "lightweight": lightweight_grid(plan), "native": native_grid(plan)}
    )
    write_json(run / "frozen_trial_plan.json", frozen)
    started = datetime.fromisoformat(frozen["frozen_at"]).timestamp()
    deadline = started + plan["maximum_hours"] * 3600
    state = {
        "status": "running",
        "started_at": frozen["frozen_at"],
        "deadline_epoch": deadline,
        "pid": os.getpid(),
        "phase": "native_training",
        "current_job": None,
        "failures": [],
        "publication": "pending" if publish else "not_requested",
    }
    (run / "pid").write_text(str(os.getpid()))
    write_json(run / "native_provenance.json", native_provenance())
    write_json(
        run / "data_source.json",
        {
            "repository": SOURCE_REPO,
            "revision": SOURCE_REVISION,
            "local_source": str(source),
            "decoded_cache": str(cache),
            "active_partition": "Per-trial split_plan in frozen_trial_plan.json",
            "legacy_cache_partition_labels_used": False,
        },
    )
    report_root = REPOSITORY / "docs/mujoco_validation"
    archive = report_root / "round1_report.html"
    if not archive.exists() and (report_root / "report.html").exists():
        shutil.copyfile(report_root / "report.html", archive)
    report_data = report_root / "retraining_20261025"
    report_data.mkdir(parents=True, exist_ok=True)

    def report():
        state["updated_at"] = utc_now()
        state["completed_lightweight"] = len(results_in(run, "trials"))
        state["completed_native"] = len(results_in(run, "native"))
        write_json(run / "status.json", state)
        write_retraining_report(run, report_root / "report.html")

    try:
        report()
        native_settings = run / "native_settings.json"
        write_json(native_settings, plan["native"])
        training_closed = (run / "training_closed.json").exists()
        for cfg in [] if training_closed else frozen["native"]:
            if time.time() >= deadline - plan["finalization_reserve_seconds"] or (run / "STOP").exists():
                break
            output = run / "native" / cfg["name"]
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "config.json", cfg)
            state.update(phase="native_training", current_job=cfg["name"])
            report()
            command = [
                sys.executable,
                "-m",
                "cobot_mujoco.native_worker",
                "--source",
                str(source),
                "--config",
                str(output / "config.json"),
                "--settings",
                str(native_settings),
                "--output",
                str(output),
            ]
            if execute(command, output, run, deadline, report) is None:
                state["failures"].append(cfg["name"])
        for cfg in [] if training_closed else frozen["lightweight"]:
            if time.time() >= deadline - plan["finalization_reserve_seconds"] or (run / "STOP").exists():
                break
            output = run / "trials" / cfg["name"]
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "config.json", cfg)
            state.update(phase="lightweight_training", current_job=cfg["name"])
            report()
            command = [
                sys.executable,
                "-m",
                "cobot_mujoco.train",
                "--cache",
                str(cache),
                "--config",
                str(output / "config.json"),
                "--output",
                str(output),
                "--budget-s",
                str(plan["trial_budget_seconds"]),
            ]
            if execute(command, output, run, deadline, report) is None:
                state["failures"].append(cfg["name"])
        light, native = results_in(run, "trials"), results_in(run, "native")
        recipes = []
        for family in ["cnn", "act"]:
            for regime in ["correction_concat", "correction_balanced"]:
                rows = [
                    t for t in light if t["config"]["family"] == family and t["config"]["regime"] == regime
                ]
                if len({r["config"]["fold"] for r in rows}) == 4:
                    recipes.append(
                        {
                            "family": family,
                            "regime": regime,
                            "validation_mean": float(np.mean([r["best_validation_mae"] for r in rows])),
                            "trials": [r["config"]["name"] for r in rows],
                        }
                    )
        if training_closed and (run / "selected_recipes.json").exists():
            chosen = read_json(run / "selected_recipes.json")["lightweight"]
        else:
            chosen = min(recipes, key=lambda r: r["validation_mean"]) if recipes else None
            write_json(
                run / "selected_recipes.json",
                {
                    "selected_at": utc_now(),
                    "lightweight": chosen,
                    "native": "correction_concat",
                    "basis": "Validation scores only; held-out evaluation follows",
                },
            )
        if not (run / "STOP").exists():
            write_json(
                run / "training_closed.json",
                {"closed_at": utc_now(), "reason": "Freeze training and recipes before hold-out metrics"},
            )
        evaluations = (
            read_json(run / "heldout_evaluations.json") if (run / "heldout_evaluations.json").exists() else []
        )
        for kind, rows in [("native", native), ("lightweight", light)]:
            for trial in rows:
                cfg = trial["config"]
                if any(r["name"] == cfg["name"] for r in evaluations):
                    continue
                if time.time() >= deadline - 3000 or (run / "STOP").exists():
                    break
                state.update(phase="heldout_evaluation", current_job=cfg["name"])
                report()
                metrics = (
                    evaluate_native(trial["checkpoint"], trial["dataset_root"], cfg["split_plan"]["test"])
                    if kind == "native"
                    else evaluate_lightweight(cache, trial)
                )
                evaluations.append(
                    {
                        "name": cfg["name"],
                        "family": cfg["family"],
                        "regime": cfg["regime"],
                        "fold": cfg["fold"],
                        "seed": cfg["seed"],
                        "metrics": metrics,
                        "persistence": persistence_baseline(cache, cfg["split_plan"]["test"]),
                    }
                )
                write_json(run / "heldout_evaluations.json", evaluations)
        if chosen and not (run / "STOP").exists() and time.time() < deadline - 2600:
            rows = [t for t in light if t["config"]["name"] in chosen["trials"]]
            cfg = dict(rows[0]["config"])
            steps = int(
                np.median(
                    [
                        min(r["history"], key=lambda h: abs(h["validation_mae"] - r["best_validation_mae"]))[
                            "step"
                        ]
                        for r in rows
                    ]
                )
            )
            cfg.update(
                name="lightweight_final_all15",
                seed=plan["refit"]["seed"],
                train_episodes=15,
                train_ids=list(range(15)),
                correction_train_ids=plan["correction_ids"],
                split_plan={"train": list(range(15)), "validation": [], "test": []},
                max_steps=max(plan["refit"]["minimum_steps"], min(steps, plan["refit"]["maximum_steps"])),
            )
            output = run / "final/lightweight_final_all15"
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "config.json", cfg)
            state.update(phase="all_data_refit", current_job=cfg["name"])
            report()
            execute(
                [
                    sys.executable,
                    "-m",
                    "cobot_mujoco.refit",
                    "--cache",
                    str(cache),
                    "--config",
                    str(output / "config.json"),
                    "--output",
                    str(output),
                    "--budget-s",
                    str(min(plan["refit"]["budget_seconds"], max(1, deadline - time.time() - 2600))),
                ],
                output,
                run,
                deadline,
                report,
            )
        native_aug = [r for r in native if r["config"]["regime"] == "correction_concat"]
        if native_aug and not (run / "STOP").exists() and time.time() < deadline - 300:
            cfg = {
                "name": "native_act_final_all15",
                "family": "native_act",
                "regime": "all_data",
                "seed": 17,
                "split_plan": {"train": list(range(15)), "validation": [], "test": []},
            }
            settings = {
                **plan["native"],
                "steps": max(1500, int(np.median([r["selected_step"] for r in native_aug]))),
                "trial_budget_seconds": min(
                    plan["native"]["refit_budget_seconds"], max(1, deadline - time.time() - 120)
                ),
            }
            output = run / "final/native_act_final_all15"
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "config.json", cfg)
            write_json(output / "settings.json", settings)
            state.update(phase="all_data_refit", current_job=cfg["name"])
            report()
            execute(
                [
                    sys.executable,
                    "-m",
                    "cobot_mujoco.native_worker",
                    "--source",
                    str(source),
                    "--config",
                    str(output / "config.json"),
                    "--settings",
                    str(output / "settings.json"),
                    "--output",
                    str(output),
                ],
                output,
                run,
                deadline,
                report,
            )
        state.update(
            status="stopped"
            if (run / "STOP").exists()
            else "completed"
            if len(light) == 48
            and len(native) == 8
            and len(evaluations) == 56
            and len(results_in(run, "final")) == 2
            and not state["failures"]
            and all(r["status"] == "completed" for r in native + results_in(run, "final"))
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
            "frozen_trial_plan.json",
            "lineage_audit.json",
            "native_provenance.json",
            "data_source.json",
            "status.json",
            "selected_recipes.json",
            "training_closed.json",
            "heldout_evaluations.json",
        ]:
            if (run / name).exists():
                shutil.copyfile(run / name, report_data / name)
        write_json(report_data / "lightweight_results.json", results_in(run, "trials"))
        write_json(report_data / "native_results.json", results_in(run, "native"))
        write_json(report_data / "all_data_refits.json", results_in(run, "final"))
        if (run / "heldout_evaluations.json").exists():
            write_json(
                report_data / "comparison_summary.json",
                aggregate_holdouts(read_json(run / "heldout_evaluations.json"), plan),
            )
        if publish:
            try:
                publish_report(report_root)
                state["publication"] = "pushed"
            except Exception as error:
                state["publication"] = "failed"
                state["publication_error"] = str(error)
            write_json(run / "status.json", state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def main():
    """Launch the revised durable experiment supervisor."""
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args()
    run_retraining(args.run, args.source, args.cache, publish=not args.no_push)


if __name__ == "__main__":
    main()
