"""Copy a LeRobot dataset without some episodes (the rest are renumbered 0, 1, 2, ...).

omx_1031: episode 14 of Sungah/omx_1031_JH_v1_success is a duplicate recording, so it is removed
and episodes 15 and 16 become 14 and 15 (16 episodes, 13,527 frames).

Usage (lerobot 0.4.4, from the project root):
  python -I tools/delete_episodes.py SRC DST EPISODE [EPISODE ...]
  e.g. python -I tools/delete_episodes.py data/omx_1031_JH_v1_success data/omx_1031_no14 14
SRC is not modified.
"""

import sys
from pathlib import Path

from lerobot.datasets.dataset_tools import delete_episodes
from lerobot.datasets.lerobot_dataset import LeRobotDataset

if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if dst.exists():
        raise SystemExit(f"{dst} exists")
    ds = LeRobotDataset(f"local/{src.name}", root=src)
    new = delete_episodes(ds, episode_indices=[int(e) for e in sys.argv[3:]], output_dir=dst, repo_id=f"local/{dst.name}")
    print(f"made {dst}: {new.meta.total_episodes} episodes, {new.meta.total_frames} frames")
