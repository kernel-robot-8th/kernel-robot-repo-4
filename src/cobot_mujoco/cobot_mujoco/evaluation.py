"""Replay diagnostics and final locked-test / provisional physics evaluation."""

from pathlib import Path
import time

import numpy as np
import torch
from torch.utils.data import DataLoader

from .common import read_json, utc_now, write_json
from .data import RecordingDataset, SPLITS
from .environment import OMXEnvironment
from .learning import SimulationPolicy, evaluate, make_policy


def persistence_baseline(cache, episodes):
    """Compare learning against holding the current joint state for ten future steps."""
    cache = Path(cache)
    manifest = read_json(cache / "manifest.json")
    states = np.load(cache / "states.npy", mmap_mode="r")
    actions = np.load(cache / "actions.npy", mmap_mode="r")
    rows = {}
    for recording in manifest["episodes"]:
        if recording["id"] not in episodes:
            continue
        indices = np.arange(recording["start"], recording["end"], 6)
        targets = indices[:, None] + np.arange(10)[None]
        valid = targets < recording["end"]
        targets = np.minimum(targets, recording["end"] - 1)
        error = np.abs(states[indices, None] - actions[targets])
        control = (error * valid[..., None]).sum((1, 2)) / (valid.sum(1) * 6)
        rows[str(recording["id"])] = {
            "control_mae": float(control.mean()),
            "point_mae": float(error[:, 0].mean()),
        }
    return {
        "name": "hold_current_state",
        "training_required": False,
        "control_mae": float(np.mean([r["control_mae"] for r in rows.values()])),
        "point_mae": float(np.mean([r["point_mae"] for r in rows.values()])),
        "per_episode": rows,
        "interpretation": "Low motor MAE alone can reward staying still; task success must be verified.",
    }


def replay_recording(cache, assets, episode=2, stride=1, config=None, video_path=None):
    """Execute recorded commands through the actuator dynamics, without object teleportation."""
    from PIL import Image

    cache = Path(cache)
    manifest = read_json(cache / "manifest.json")
    record = next(r for r in manifest["episodes"] if r["id"] == episode)
    states = np.load(cache / "states.npy", mmap_mode="r")
    actions = np.load(cache / "actions.npy", mmap_mode="r")
    ee = np.load(cache / "ee.npy", mmap_mode="r")
    env = OMXEnvironment(assets, config=config)
    env.reset(states[record["start"]])
    errors, tracking, snapshots = [], [], []
    try:
        for i in range(record["start"], record["end"]):
            env.step(actions[i])
            errors.append(np.linalg.norm(env.data.body("end_effector_link").xpos - ee[i, :3]))
            tracking.append(np.mean(np.abs(env.state() - states[i])))
            if video_path and (i - record["start"]) % (stride * 6) == 0:
                snapshots.append(Image.fromarray(env.render("top", 384, 288)))
        metrics = env.metrics()
        metrics.update(
            {
                "episode": episode,
                "ee_tracking_rmse_m": float(np.sqrt(np.mean(np.square(errors)))),
                "joint_tracking_mae": float(np.mean(tracking)),
                "mode": "recorded_action_replay_through_dynamics",
            }
        )
        if snapshots:
            Path(video_path).parent.mkdir(parents=True, exist_ok=True)
            snapshots[0].save(
                video_path,
                save_all=True,
                append_images=snapshots[1:],
                duration=200 * stride,
                loop=0,
                optimize=True,
            )
        return metrics
    finally:
        env.close()


def kinematic_check(cache, assets, episode=2):
    """Independently compare stored recorder FK with the upstream robot geometry."""
    cache = Path(cache)
    manifest = read_json(cache / "manifest.json")
    record = next(r for r in manifest["episodes"] if r["id"] == episode)
    states = np.load(cache / "states.npy", mmap_mode="r")
    ee = np.load(cache / "ee.npy", mmap_mode="r")
    env = OMXEnvironment(assets)
    errors = []
    try:
        for i in range(record["start"], record["end"], 10):
            env.set_robot_state(states[i])
            errors.append(np.linalg.norm(env.data.body("end_effector_link").xpos - ee[i, :3]))
        return {
            "episode": episode,
            "samples": len(errors),
            "ee_rmse_m": float(np.sqrt(np.mean(np.square(errors)))),
            "ee_max_error_m": float(np.max(errors)),
            "gate_pass": bool(np.max(errors) < 0.0001),
            "scope": "kinematic geometry only, does not validate camera, contacts, or task success",
        }
    finally:
        env.close()


def load_trial(path, device="cuda"):
    """Restore a locally generated checkpoint and its training-only normalization."""
    saved = torch.load(Path(path), map_location=device, weights_only=False)
    policy = make_policy(saved["config"], pretrained_backbone=False).to(device)
    policy.load_state_dict(saved["model"])
    policy.eval()
    return policy, saved["statistics"], saved["config"]


def final_evaluation(cache, assets, selected, sweep, output, deadline=None, progress=None):
    """Select using validation before opening the test, then evaluate once per family."""
    output = Path(output)
    results = (
        read_json(output / "final_evaluation.json") if (output / "final_evaluation.json").exists() else []
    )
    access = output / "test_access.json"
    scene = read_json(output / "scene.json") if (output / "scene.json").exists() else None
    selection = [x["config"]["name"] for x in selected]
    if access.exists() and read_json(access)["selected_trials"] != selection:
        raise ValueError("Locked test was already opened for a different model selection")
    if not access.exists():
        write_json(
            access,
            {
                "opened_at": utc_now(),
                "episodes": SPLITS["test"],
                "selected_trials": selection,
                "policy": "No hyperparameter selection on test results",
            },
        )
    for trial in selected:
        policy, stats, config = load_trial(trial["checkpoint"])
        record = next((r for r in results if r["trial"] == config["name"]), None)
        if record is None:
            dataset = RecordingDataset(cache, SPLITS["test"], config["horizon"], stats, stride=6)
            loader = DataLoader(dataset, batch_size=config["batch_size"], num_workers=0)
            test = evaluate(policy, loader, stats)
            ablations = {name: evaluate(policy, loader, stats, ablation=name) for name in ["wrist", "top"]}
            record = {
                "trial": config["name"],
                "family": config["family"],
                "selected_by": "validation only, before locked test evaluation",
                "test": test,
                "persistence_baseline": persistence_baseline(cache, SPLITS["test"]),
                "camera_ablations": ablations,
                "simulation": [],
            }
            results.append(record)
            write_json(output / "final_evaluation.json", results)
        for scenario in sweep["simulation_scenarios"]:
            for seed in sweep["simulation_seeds"]:
                for mode in sweep["simulation_control_modes"]:
                    if any(
                        s["scenario"] == scenario
                        and s["seed"] == seed
                        and s["mode"] == mode
                        and s.get("completed_rollout", True)
                        for s in record["simulation"]
                    ):
                        continue
                    if deadline is not None and time.monotonic() >= deadline:
                        record["simulation_incomplete_reason"] = "global_wall_clock_budget"
                        break
                    env = OMXEnvironment(assets, config=scene, seed=seed, scenario=scenario)
                    controller = SimulationPolicy(policy, stats, config, ensemble=mode == "temporal_ensemble")
                    snapshots = []
                    try:
                        nsteps = int(sweep["simulation_seconds"] * env.config["fps"])
                        for frame in range(nsteps):
                            if deadline is not None and time.monotonic() >= deadline:
                                break
                            env.step(controller.action(env))
                            if (
                                scenario == "nominal"
                                and seed == sweep["simulation_seeds"][0]
                                and mode == "chunk"
                                and frame in {0, nsteps // 4, nsteps // 2, nsteps * 3 // 4, nsteps - 1}
                            ):
                                snapshots.append(env.render("top", 256, 192))
                        record["simulation"].append(
                            {
                                "scenario": scenario,
                                "seed": seed,
                                "mode": mode,
                                "completed_rollout": env.control_step == nsteps,
                                **env.metrics(),
                            }
                        )
                    finally:
                        env.close()
                    if snapshots:
                        from PIL import Image

                        directory = output / "evidence"
                        directory.mkdir(exist_ok=True)
                        name = f"rollout_{config['name']}.jpg"
                        Image.fromarray(np.concatenate(snapshots, axis=1)).save(directory / name, quality=78)
                        record["rollout_montage"] = name
                    write_json(output / "final_evaluation.json", results)
                    if progress:
                        progress()
        del policy
        torch.cuda.empty_cache()
        write_json(output / "final_evaluation.json", results)
    return results
