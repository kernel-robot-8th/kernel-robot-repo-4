"""Merge LeRobot datasets into one (episodes keep their order: SRC1's, then SRC2's, ...).

shoebox: shoebox_a (10 episodes) + shoebox_b (10) -> shoebox_ab, a = episodes 0-9, b = 10-19.

Usage (lerobot 0.4.4, from the project root):
  python -I tools/merge_datasets.py DST SRC1 SRC2 [SRC ...]
  e.g. python -I tools/merge_datasets.py data/shoebox_ab data/shoebox_a data/shoebox_b
SRCs are not modified.
"""

import sys
from pathlib import Path

from lerobot.datasets.dataset_tools import merge_datasets
from lerobot.datasets.lerobot_dataset import LeRobotDataset

if __name__ == "__main__":
    dst, srcs = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
    if dst.exists():
        raise SystemExit(f"{dst} exists")
    dss = [LeRobotDataset(f"local/{s.name}", root=s) for s in srcs]
    new = merge_datasets(dss, output_repo_id=f"local/{dst.name}", output_dir=dst)
    print(f"made {dst}: {new.meta.total_episodes} episodes, {new.meta.total_frames} frames")
