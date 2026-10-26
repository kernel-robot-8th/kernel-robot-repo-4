"""lerobot-record (lerobot 0.4.4) with the bundle's extensions loaded, for running a policy.

lerobot 0.4.4 has no lerobot-rollout; a policy is run with lerobot-record --policy.path=...
(omx_rollout.py is the lerobot 0.6.1 counterpart).

- registers the omx_follower_grip robot type (omx_grip_robot.py)

Usage: same arguments as lerobot-record, e.g.
  python omx_record.py --policy.path=models/smolvla_merged --robot.type=omx_follower_grip \
      --dataset.repo_id=local/eval_smolvla --dataset.single_task="..." ...
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import omx_grip_robot  # noqa: E402,F401  (registers robot type)

from lerobot.scripts.lerobot_record import main  # noqa: E402

if __name__ == "__main__":
    main()
