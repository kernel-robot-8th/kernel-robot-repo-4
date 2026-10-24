"""Fetch the upstream robot at a pinned commit; never commit large assets."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import urllib.request

from .common import ROBOT_REPO, ROBOT_REVISION, write_json

DESCRIPTION = "open_manipulator_description"
MESHES = [
    "follower_01_base.stl",
    "follower_02_base_tilt_Revised.stl",
    "follower_03_middle_verticle.stl",
    "follower_04_middle_horizontal.stl",
    "follower_05_tip.stl",
    "follower_06_pan_Revised.stl",
    "follower_07_gripper_motorized.stl",
    "follower_08_gripper_gear.stl",
]


def fetch_robot(root):
    """Download original MJCF, meshes, URDF, and their Apache license."""
    root = Path(root)
    paths = [
        "LICENSE",
        f"{DESCRIPTION}/mujoco/omx/omx.xml",
        f"{DESCRIPTION}/urdf/omx_f/omx_f.urdf",
        *[f"{DESCRIPTION}/meshes/omx_f/{name}" for name in MESHES],
    ]

    def fetch(path):
        target = root / path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://raw.githubusercontent.com/{ROBOT_REPO}/{ROBOT_REVISION}/{path}"
            with urllib.request.urlopen(url, timeout=90) as response:
                payload = response.read()
            temporary = target.with_suffix(target.suffix + ".part")
            temporary.write_bytes(payload)
            temporary.replace(target)
        payload = target.read_bytes()
        return {"path": path, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    with ThreadPoolExecutor(max_workers=3) as executor:
        manifest = list(executor.map(fetch, paths))
    write_json(
        root / "manifest.json",
        {
            "repository": ROBOT_REPO,
            "revision": ROBOT_REVISION,
            "files": manifest,
        },
    )
    return root / DESCRIPTION / "mujoco/omx/omx.xml"
