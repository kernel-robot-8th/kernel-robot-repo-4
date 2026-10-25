"""Measure RGB print matching and frozen-policy responses before and after scene changes."""

import argparse
import copy
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import torch

from .common import PACKAGE, read_json, write_json
from .data import CAMERAS
from .environment import OMXEnvironment
from .evaluation import load_trial
from .learning import prepare_batch
from .print_detector import PrintedBoxDetector, annotated
from .sim_comparison import NativeController


def predict(controller, state, images, kind):
    """Hold joint state fixed and change only the two RGB observations supplied to the policy."""
    with torch.inference_mode():
        if kind == "native":
            batch = {"observation.state": torch.from_numpy(state.copy())[None]}
            for camera in CAMERAS:
                batch[f"observation.images.{camera}"] = (
                    torch.from_numpy(images[camera].transpose(2, 0, 1).copy())[None].float() / 255
                )
            output = controller.policy.predict_action_chunk(controller.pre(batch))
            return controller.post(output.reshape(-1, 6))[:10].cpu().numpy()
        policy, stats, cfg = controller
        pixels = np.stack([cv2.resize(images[c], (128, 96)).transpose(2, 0, 1) for c in CAMERAS])
        batch = {
            "observation.state": torch.tensor(
                (state - stats["state_mean"]) / stats["state_std"], dtype=torch.float32
            )[None],
            "pixels": torch.from_numpy(pixels)[None],
            "action": torch.zeros(1, cfg["horizon"], 6),
            "action_is_pad": torch.zeros(1, cfg["horizon"], dtype=torch.bool),
        }
        output = policy.predict_action_chunk(prepare_batch(batch, "cuda"))[0, :10].cpu().numpy()
        return output * stats["action_std"] + stats["action_mean"]


def polygon_iou(first, second):
    """Compare image-derived print polygons only when both matchers accept their geometry."""
    if not first["detected"] or not second["detected"]:
        return 0.0
    masks = []
    for row in [first, second]:
        mask = np.zeros((480, 640), np.uint8)
        cv2.fillConvexPoly(mask, np.int32(row["polygon"]), 1)
        masks.append(mask.astype(bool))
    return float((masks[0] & masks[1]).sum() / max(1, (masks[0] | masks[1]).sum()))


def probe(training, frames, assets, cache, output):
    """Use inspected recordings as diagnostic cases, never as a new independent test set."""
    training, frames, cache, output = map(Path, [training, frames, cache, output])
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(cache / "manifest.json")
    states = np.load(cache / "states.npy", mmap_mode="r")
    actions = np.load(cache / "actions.npy", mmap_mode="r")
    detector = PrintedBoxDetector()
    profiles = [
        ("before", "scene_legacy.json"),
        ("visual", "scene_appearance_visual.json"),
        ("v2", "scene_appearance_v2.json"),
    ]
    records = []
    observations = {}
    for episode in [0, 2, 11]:
        start = next(r["start"] for r in manifest["episodes"] if r["id"] == episode)
        for seconds in [0, 5, 10]:
            real = {
                c: np.asarray(Image.open(frames / f"ep{episode}_{c}_{seconds}s.png").convert("RGB"))
                for c in CAMERAS
            }
            real_detection = detector.detect(real["top"])
            name = f"ep{episode}_{seconds}s"
            Image.fromarray(annotated(real["top"], real_detection)).save(output / f"{name}_real.jpg")
            observations[name] = {"index": start + 30 * seconds, "real": real}
            for profile, config in profiles:
                scene = copy.deepcopy(read_json(PACKAGE / "config" / config))
                if episode == 11:
                    scene["box_count"] = 1
                    scene.update(scene.get("single_box_camera_override", {}))
                env = OMXEnvironment(assets, scene)
                try:
                    env.set_robot_state(states[start + 30 * seconds])
                    rendered = {c: env.render(c, 640, 480) for c in CAMERAS}
                finally:
                    env.close()
                detection = detector.detect(rendered["top"])
                Image.fromarray(annotated(rendered["top"], detection)).save(output / f"{name}_{profile}.jpg")
                Image.fromarray(rendered["wrist"]).save(output / f"{name}_{profile}_wrist.jpg")
                observations[name][profile] = rendered
                records.append(
                    {
                        "case": name,
                        "episode": episode,
                        "seconds": seconds,
                        "profile": profile,
                        "real_rgb_detection": real_detection,
                        "sim_rgb_detection": detection,
                        "print_polygon_iou": polygon_iou(real_detection, detection),
                    }
                )
    responses = []
    for kind, folder in [("native", "native_act_final_all15"), ("cnn", "lightweight_final_all15")]:
        result = read_json(training / "final" / folder / "result.json")
        controller = (
            NativeController(result["checkpoint"]) if kind == "native" else load_trial(result["checkpoint"])
        )
        for name, data in observations.items():
            index = data["index"]
            real_prediction = predict(controller, states[index], data["real"], kind)
            target = actions[index : index + 10]
            for profile, _ in profiles:
                value = predict(controller, states[index], data[profile], kind)
                responses.append(
                    {
                        "case": name,
                        "family": kind,
                        "profile": profile,
                        "same_joint_state": True,
                        "real_image_target_mae": float(np.mean(np.abs(real_prediction - target))),
                        "sim_image_target_mae": float(np.mean(np.abs(value - target))),
                        "real_vs_sim_prediction_mae": float(np.mean(np.abs(value - real_prediction))),
                        "checkpoint": result["checkpoint"],
                    }
                )
        del controller
        torch.cuda.empty_cache()
    result = {
        "scope": (
            "Inspected-recording diagnostic; RGB-only matcher is not fed to ACT/CNN. "
            "Same state, frozen weights, changing camera inputs. "
            "Not a semantic recognition or task success certificate."
        ),
        "camera_fit_recordings": [0, 11],
        "additional_inspected_recording": 2,
        "image_cases": records,
        "policy_responses": responses,
    }
    write_json(output / "probe.json", result)
    for profile, _ in profiles:
        rows = [r for r in records if r["profile"] == profile]
        print(
            "RGB_MATCH",
            profile,
            sum(r["sim_rgb_detection"]["detected"] for r in rows),
            "/",
            len(rows),
            flush=True,
        )
    return result


def main():
    """Run reproducible appearance and policy-observation diagnostics."""
    parser = argparse.ArgumentParser()
    for key in ["training", "frames", "assets", "cache", "output"]:
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    probe(args.training, args.frames, args.assets, args.cache, args.output)


if __name__ == "__main__":
    main()
