"""Build traceable box textures and image-based camera estimates from recorded frames."""

import argparse
import copy
import hashlib
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
import pyarrow.parquet as pq

from .common import PACKAGE, SOURCE_REPO, SOURCE_REVISION, read_json, utc_now, write_json
from .environment import OMXEnvironment

TOP_TWO = [[388, 144], [515, 140], [540, 262], [398, 266]]
TOP_ONE = [[344, 120], [459, 119], [476, 215], [350, 220]]
WRIST_TWO_5S = [[194, 43], [438, 55], [591, 151], [111, 143]]


def lid_corners(scene, boxes):
    """Define visible lid corners from the same geometry used in the simulator."""
    x, y = scene["box_center_xy"]
    hx, hy, hz = scene["box_half_size"]
    hx, hy = hx + 0.001, hy + 0.001
    z = scene["table_top"] + 2 * hz * boxes + 0.0012
    return np.array(
        [[x + hx, y + hy, z], [x + hx, y - hy, z], [x - hx, y - hy, z], [x - hx, y + hy, z]], dtype=np.float64
    )


def camera_estimate(points, pixels, fovy):
    """Estimate a camera from manually annotated lid corners and an assumed field of view."""
    focal = 240 / np.tan(np.deg2rad(fovy / 2))
    intrinsic = np.array([[focal, 0, 320], [0, focal, 240], [0, 0, 1]], dtype=np.float64)
    good, rotation, translation = cv2.solvePnP(points, np.array(pixels, dtype=np.float64), intrinsic, None)
    if not good:
        raise RuntimeError("Planar image camera estimate failed")
    matrix = cv2.Rodrigues(rotation)[0]
    position = (-matrix.T @ translation).ravel()
    axes = np.r_[matrix[0], -matrix[1]]
    projected = cv2.projectPoints(points, rotation, translation, intrinsic, None)[0].reshape(-1, 2)
    return position, axes, float(np.sqrt(np.mean((projected - pixels) ** 2)))


def prepare(frames, assets, cache):
    """Extract actual printed patterns rather than inventing marks or masking model observations."""
    frames, cache = Path(frames), Path(cache)
    directory = PACKAGE / "config/textures"
    directory.mkdir(exist_ok=True)
    definitions = [("lid_two", "ep0_top_0s.png", TOP_TWO), ("lid_one", "ep11_top_0s.png", TOP_ONE)]
    records = []
    for name, source, quad in definitions:
        image = cv2.imread(str(frames / source))
        transform = cv2.getPerspectiveTransform(
            np.float32(quad), np.float32([[0, 0], [511, 0], [511, 511], [0, 511]])
        )
        tile = cv2.warpPerspective(image, transform, (512, 512))
        tile = cv2.rotate(tile, cv2.ROTATE_90_CLOCKWISE)
        cv2.imwrite(str(directory / f"{name}.png"), tile)
        records.append(
            {
                "texture": name,
                "source_frame": source,
                "source_quad_pixels": quad,
                "source_sha256": hashlib.sha256((frames / source).read_bytes()).hexdigest(),
            }
        )
    image = cv2.imread(str(frames / "ep0_top_0s.png"))
    cv2.imwrite(str(directory / "carpet.png"), image[10:138, 10:138])
    wood = cv2.imread(str(frames / "ep0_wrist_0s.png"))
    cv2.imwrite(str(directory / "wood.png"), wood[170:330, 160:480])
    legacy = PACKAGE / "config/scene_legacy.json"
    scene = copy.deepcopy(read_json(legacy if legacy.exists() else PACKAGE / "config/scene.json"))
    scene["appearance"] = {
        "version": 2,
        "textures": "recorded lid perspective rectification",
        "lid_collision_split": True,
        "dimensions_measured": False,
        "soft_lighting": True,
    }
    for boxes, points in [(2, TOP_TWO), (1, TOP_ONE)]:
        position, axes, error = camera_estimate(lid_corners(scene, boxes), points, 50)
        values = {
            "top_camera_position": position.tolist(),
            "top_camera_xyaxes": axes.tolist(),
            "top_camera_fovy": 50,
        }
        if boxes == 2:
            scene.update(values)
        else:
            scene["single_box_camera_override"] = values
        records.append(
            {
                "camera": f"top_{boxes}_boxes",
                "fit_pixels": points,
                "reprojection_rmse_pixels": error,
                "fovy_assumed": 50,
                "scope": "Planar image fit, not independent physical calibration",
            }
        )
    position, axes, error = camera_estimate(lid_corners(scene, 2), WRIST_TWO_5S, 70)
    manifest = read_json(cache / "manifest.json")
    start = next(r["start"] for r in manifest["episodes"] if r["id"] == 0)
    states = np.load(cache / "states.npy", mmap_mode="r")
    env = OMXEnvironment(assets)
    try:
        env.set_robot_state(states[start + 150])
        body = env.data.body("link5")
        rotation = body.xmat.reshape(3, 3)
        scene["wrist_camera_position"] = (rotation.T @ (position - body.xpos)).tolist()
        scene["wrist_camera_xyaxes"] = np.r_[rotation.T @ axes[:3], rotation.T @ axes[3:]].tolist()
    finally:
        env.close()
    records.append(
        {
            "camera": "wrist",
            "episode": 0,
            "seconds": 5,
            "fit_pixels": WRIST_TWO_5S,
            "reprojection_rmse_pixels": error,
            "fovy_assumed": 70,
        }
    )
    scene["status"] = "recorded_texture_and_image_fit_v2_physical_calibration_pending"
    visual_only = copy.deepcopy(scene)
    visual_only["appearance"]["lid_collision_split"] = False
    visual_only["appearance"]["version"] = "visual_only"
    write_json(PACKAGE / "config/scene_appearance_visual.json", visual_only)
    write_json(PACKAGE / "config/scene_appearance_v2.json", scene)
    write_json(
        directory / "provenance.json",
        {
            "created_at": utc_now(),
            "source_repo": SOURCE_REPO,
            "source_revision": SOURCE_REVISION,
            "license": "Apache-2.0; source attribution retained",
            "records": records,
            "texture_uv_rotation": "90 degrees clockwise after perspective rectification",
            "files": [
                {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(directory.glob("*.png"))
            ],
            "warning": (
                "Manual visible-corner annotations and assumed size/FOV. "
                "These do not certify physical scale, camera pose, or grasp contacts."
            ),
        },
    )
    return scene


def extract_frames(source, frames):
    """Extract the declared recording observations without changing source videos."""
    source, frames = Path(source), Path(frames)
    frames.mkdir(parents=True, exist_ok=True)
    info = read_json(source / "meta/info.json")
    episodes = []
    for path in sorted((source / "meta/episodes").rglob("*.parquet")):
        episodes.extend(pq.read_table(path).to_pylist())
    for episode in [0, 2, 11]:
        record = next(r for r in episodes if r["episode_index"] == episode)
        for camera in ["top", "wrist"]:
            prefix = f"videos/observation.images.{camera}"
            video = source / info["video_path"].format(
                video_key=f"observation.images.{camera}",
                chunk_index=record[prefix + "/chunk_index"],
                file_index=record[prefix + "/file_index"],
            )
            for seconds in [0, 5, 10]:
                target = frames / f"ep{episode}_{camera}_{seconds}s.png"
                if not target.exists():
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-y",
                            "-ss",
                            str(record[prefix + "/from_timestamp"] + seconds),
                            "-i",
                            str(video),
                            "-frames:v",
                            "1",
                            str(target),
                        ],
                        check=True,
                    )


def main():
    """Reproduce attributed textures and camera profiles from the pinned local dataset."""
    parser = argparse.ArgumentParser()
    for key in ["source", "frames", "assets", "cache"]:
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    extract_frames(args.source, args.frames)
    prepare(args.frames, args.assets, args.cache)
    if args.activate:
        shutil.copyfile(PACKAGE / "config/scene_appearance_v2.json", PACKAGE / "config/scene.json")


if __name__ == "__main__":
    main()
