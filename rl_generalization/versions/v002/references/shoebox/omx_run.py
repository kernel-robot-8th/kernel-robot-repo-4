"""lerobot-record (lerobot 0.4.4) with all of this bundle's extensions, for running a policy.

lerobot 0.4.4 has no lerobot-rollout; a policy is run with lerobot-record --policy.path=...

- robot type omx_follower_grip       : gripper current in observation.state (omx_grip_robot.py)
- robot type omx_follower_grip_depth : + MoGe-2 depth camera (omx_depth_robot.py; MoGe is loaded only when used,
                                       depth computed on the frames the policy predicts)
- PHASE_INFO=<model>/phase_info.json : phase tracking for per-phase models (omx_phase.py)
- BOX=<1-4> [N_BOX=4]                : box-number one-hot in observation.state (omx_box.py)
- ACT_ENSEMBLE_K=<k>                 : ACT k-step temporal ensembling (act_ensemble.py)

Usage: same arguments as lerobot-record (infer.sh / inference.sh pass them).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import omx_depth_robot  # noqa: E402  (registers omx_follower_grip_depth)
import omx_grip_robot  # noqa: E402,F401  (registers omx_follower_grip)

if os.environ.get("PHASE_INFO"):
    import omx_phase  # noqa: E402

    omx_phase.install(os.environ["PHASE_INFO"])

if os.environ.get("BOX"):
    import omx_box  # noqa: E402

    omx_box.install(int(os.environ["BOX"]), int(os.environ.get("N_BOX", "4")))

if os.environ.get("ACT_ENSEMBLE_K"):
    import act_ensemble  # noqa: E402,F401  (patches ACTPolicy)

    print(f"ACT k-step temporal ensembling: k={act_ensemble.K}, m={act_ensemble.M}")

# last, so it sees (and fills) the observation dict the eval recording also stores; no-op without a depth robot
omx_depth_robot.install()

from lerobot.scripts.lerobot_record import main  # noqa: E402

if __name__ == "__main__":
    main()
