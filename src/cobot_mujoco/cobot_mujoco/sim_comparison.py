"""Compare newly trained policies in a frozen, explicitly provisional MuJoCo scene."""

import argparse
import copy
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback

import numpy as np
import torch

from .common import PACKAGE, REPOSITORY, read_json, utc_now, write_json
from .environment import OMXEnvironment
from .evaluation import load_trial, replay_recording
from .learning import SimulationPolicy
from .runner import publish_report


class NativeController:
    """Use the saved upstream processors with original-resolution simulated camera images."""

    def __init__(self, checkpoint, interval=5):
        """Load an actual upstream ACT checkpoint without retraining or fitting statistics."""
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies.factory import make_pre_post_processors

        self.policy = ACTPolicy.from_pretrained(checkpoint).cuda().eval()
        self.pre, self.post = make_pre_post_processors(
            self.policy.config,
            pretrained_path=checkpoint,
            preprocessor_overrides={"device_processor": {"device": "cuda"}},
        )
        self.interval = interval
        self.queue = []

    @torch.inference_mode()
    def action(self, environment):
        """Return saved-processor motor commands, recomputing the future chunk when needed."""
        if not self.queue:
            batch = {"observation.state": torch.from_numpy(environment.state())[None]}
            for key, feature in self.policy.config.image_features.items():
                _, height, width = feature.shape
                pixels = environment.render(key.rsplit(".", 1)[1], width, height)
                batch[key] = torch.from_numpy(pixels.transpose(2, 0, 1).copy())[None].float() / 255
            prediction = self.policy.predict_action_chunk(self.pre(batch))
            motors = self.post(prediction.reshape(-1, 6)).reshape(-1, 6).cpu().numpy()
            self.queue = list(motors[: self.interval])
        return self.queue.pop(0)


def frozen_models(training):
    """Use one predeclared matched fold and seed, plus the two fixed all-data candidates."""
    training = Path(training)
    rows = []
    for kind in ["native", "trials"]:
        for path in sorted((training / kind).glob("*/result.json")):
            result = read_json(path)
            cfg = result["config"]
            if cfg["fold"] == 0 and cfg["seed"] == 17:
                rows.append({"name": cfg["name"], "kind": kind, "interval": 5, "result": result})
    for path in sorted((training / "final").glob("*/result.json")):
        result = read_json(path)
        kind = "native" if result["config"]["family"] == "native_act" else "trials"
        rows.append({"name": result["config"]["name"], "kind": kind, "interval": 5, "result": result})
        if kind == "native":
            rows.append(
                {
                    "name": "native_act_final_all15_interval100",
                    "kind": kind,
                    "interval": 100,
                    "result": result,
                }
            )
    rows.append({"name": "hold_current_state", "kind": "hold", "interval": 1})
    return rows


def scenarios(scene):
    """Fix paired two-box and one-box scenes and identical position shifts for all policies."""
    rows = []
    for boxes in [2, 1]:
        for seed in [0, 17, 42]:
            config = copy.deepcopy(scene)
            config["box_count"] = boxes
            if boxes == 1:
                config["initial_state"] = config["single_box_initial_state"]
            rows.append(
                {
                    "name": f"boxes{boxes}_seed{seed}",
                    "seed": seed,
                    "scenario": "nominal" if seed == 0 else "object_shift",
                    "scene": config,
                }
            )
    return rows


def rollout(controller, assets, case, output, seconds):
    """Advance real contact dynamics and store measurements, video, and sampled state traces."""
    from PIL import Image

    env = OMXEnvironment(assets, case["scene"], seed=case["seed"], scenario=case["scenario"])
    nsteps = int(seconds * env.config["fps"])
    movie = case["seed"] == 0
    process = None
    if movie:
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "384x288",
            "-r",
            "6",
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            str(output / "rollout.mp4"),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frames, trace, tracking = [], [], []
    limited = 0
    touches = 0
    reached = False
    fixed = env.state().copy()
    started = time.monotonic()
    try:
        for step in range(nsteps):
            action = fixed if controller is None else controller.action(env)
            limited += int(
                np.any(np.abs(np.asarray(action) - env.state()) > env.config["max_relative_target"])
            )
            env.step(action)
            tracking.append(float(np.mean(np.abs(env.state() - action))))
            contact = False
            for pair in env.data.contact:
                names = [env.model.body(env.model.geom_bodyid[g]).name for g in [pair.geom1, pair.geom2]]
                contact |= any(n.startswith("box_") for n in names) and any(
                    n in {"link6", "link7"} for n in names
                )
            touches += int(contact)
            reached |= any(env.placed)
            if step % 15 == 0:
                trace.append(
                    {
                        "step": step + 1,
                        "state": env.state().tolist(),
                        "target": np.asarray(action).tolist(),
                        "boxes": [
                            env.data.body(f"box_{i}").xpos.tolist() for i in range(env.config["box_count"])
                        ],
                    }
                )
            if movie and step % 5 == 0:
                process.stdin.write(env.render("top", 384, 288).tobytes())
            if step in {0, nsteps // 4, nsteps // 2, nsteps * 3 // 4, nsteps - 1}:
                frames.append(env.render("top", 256, 192))
        metrics = {
            **env.metrics(),
            "ever_stable_placement": reached,
            "finger_box_contact_frames": touches,
            "command_tracking_mae": float(np.mean(tracking)),
            "target_limit_fraction": limited / nsteps,
            "final_box_positions": [
                env.data.body(f"box_{i}").xpos.tolist() for i in range(env.config["box_count"])
            ],
            "box_count": env.config["box_count"],
            "completed_rollout": env.control_step == nsteps,
            "elapsed_s": time.monotonic() - started,
            "initial_state": fixed.tolist(),
            "actual_scene": env.config,
        }
        write_json(output / "trace.json", trace)
        Image.fromarray(np.concatenate(frames, axis=1)).save(output / "montage.jpg", quality=85)
        return metrics
    finally:
        env.close()
        if process:
            process.stdin.close()
            if process.wait(timeout=30) != 0:
                raise RuntimeError("Simulation video encoding failed")


def run_comparison(training, assets, cache, seconds=50, publish=True, smoke=False):
    """Persist every rollout independently and publish the revised report on completion."""
    from .retraining_report import write_retraining_report

    training = Path(training)
    run = training / ("simulation_smoke" if smoke else "mujoco_comparison")
    run.mkdir(parents=True, exist_ok=True)
    lock = (run / "runner.lock").open("w")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    scene = read_json(PACKAGE / "config/scene.json")
    models = frozen_models(training)
    cases = scenarios(scene)
    if smoke:
        models = [
            next(m for m in models if m["kind"] == "native"),
            next(m for m in models if m["kind"] == "trials"),
        ]
        cases = cases[:1]
    plan = {
        "created_at": utc_now(),
        "seconds": seconds,
        "models": models,
        "cases": cases,
        "selection": (
            "Fold 0, seed 17 chosen by fixed ID, not by test or simulation score; "
            "plus both frozen all-data models"
        ),
        "common_action_interval": 5,
        "native_default_interval_control": 100,
        "expected_policy_rollouts": len(models) * len(cases),
        "expected_replays": 0 if smoke else 6,
        "scene_validated": False,
        "real_world_success_claim_allowed": False,
    }
    if (run / "plan.json").exists():
        prior = read_json(run / "plan.json")
        if {k: v for k, v in prior.items() if k != "created_at"} != {
            k: v for k, v in plan.items() if k != "created_at"
        }:
            raise ValueError("Simulation plan changed; use a separate output directory")
        plan = prior
    write_json(run / "plan.json", plan)
    state = {
        "status": "running",
        "phase": "mujoco_comparison",
        "started_at": plan["created_at"],
        "pid": os.getpid(),
        "current_job": None,
        "completed_rollouts": 0,
        "expected_rollouts": plan["expected_policy_rollouts"],
        "completed_replays": 0,
        "failures": [],
    }
    report_root = REPOSITORY / "docs/mujoco_validation"

    def report():
        state["updated_at"] = utc_now()
        state["completed_rollouts"] = len(list((run / "rollouts").glob("*/*/result.json")))
        state["completed_replays"] = len(list((run / "replays").glob("*/result.json")))
        write_json(run / "status.json", state)
        if not smoke:
            write_retraining_report(training, report_root / "report.html")

    try:
        report()
        for model in models:
            controller = None
            if model["kind"] == "native":
                controller = NativeController(model["result"]["checkpoint"], model["interval"])
            elif model["kind"] == "trials":
                policy, stats, cfg = load_trial(model["result"]["checkpoint"])
                controller = SimulationPolicy(policy, stats, {**cfg, "action_steps": model["interval"]})
            for case in cases:
                output = run / "rollouts" / model["name"] / case["name"]
                if (output / "result.json").exists():
                    continue
                output.mkdir(parents=True, exist_ok=True)
                state["current_job"] = model["name"] + "/" + case["name"]
                report()
                if controller:
                    controller.queue = []
                    if hasattr(controller, "step"):
                        controller.step, controller.chunks = 0, []
                try:
                    result = rollout(controller, assets, case, output, seconds)
                    write_json(
                        output / "result.json",
                        {
                            "model": model["name"],
                            "kind": model["kind"],
                            "action_interval": model["interval"],
                            "case": case["name"],
                            "seed": case["seed"],
                            "checkpoint": model.get("result", {}).get("checkpoint"),
                            **result,
                        },
                    )
                    print(
                        "ROLLOUT",
                        state["current_job"],
                        result["success_any_box"],
                        result["max_lift_m"],
                        flush=True,
                    )
                except Exception:
                    state["failures"].append(state["current_job"])
                    (output / "error.log").write_text(traceback.format_exc())
                report()
            del controller
            if model["kind"] == "trials":
                del policy
            torch.cuda.empty_cache()
        for episode in [] if smoke else [0, 1, 2, 11, 12, 13]:
            output = run / "replays" / f"episode{episode}"
            if (output / "result.json").exists():
                continue
            output.mkdir(parents=True, exist_ok=True)
            cfg = copy.deepcopy(scene)
            cfg["box_count"] = 2 if episode < 11 else 1
            state["current_job"] = f"recorded_replay_{episode}"
            report()
            result = replay_recording(cache, assets, episode=episode, config=cfg)
            write_json(output / "result.json", {"box_count": cfg["box_count"], **result})
            report()
        state.update(
            status="completed" if not state["failures"] else "incomplete",
            current_job=None,
            finished_at=utc_now(),
        )
    except BaseException:
        state.update(status="failed", error=traceback.format_exc(), finished_at=utc_now())
        raise
    finally:
        report()
        if not smoke:
            target = report_root / "retraining_20261025/mujoco_comparison"
            target.mkdir(parents=True, exist_ok=True)
            for name in ["plan.json", "status.json"]:
                shutil.copyfile(run / name, target / name)
            for kind in ["rollouts", "replays"]:
                for path in (run / kind).rglob("*"):
                    if path.is_file() and path.name in {
                        "result.json",
                        "montage.jpg",
                        "rollout.mp4",
                        "error.log",
                    }:
                        dest = target / path.relative_to(run)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, dest)
            if publish:
                publish_report(report_root)


def main():
    """Run a durable matched-scene policy comparison, or a short adapter smoke test."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--seconds", type=int, default=50)
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(4)
    run_comparison(args.training, args.assets, args.cache, args.seconds, not args.no_push, args.smoke)


if __name__ == "__main__":
    main()
