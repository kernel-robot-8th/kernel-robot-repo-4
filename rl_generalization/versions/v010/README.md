# v010: movable workcell draft

Two shoes, an open hollow box and a separate lid now have free joints. The retaining rim remains fixed. The robot loading destination is a stationary cylinder proxy with a target site. This supports future manipulation but has no opening, grasping, closing or loading controller yet. CURRENT remains v004.

User measurements and the curved Converse-like visual design are inherited from v009. Box walls, masses, friction, lid clearance and detachable lid topology are assumptions in configs/dynamics.json. The real lid connection and logistics robot dimensions/parking pose are pending. Do not treat the cylinder as a measured Pinky model. Cloth compression and paper deformation are NOT simulated: all bodies are rigid. Real motor zeros/signs and gripper mapping remain unverified.

## Rebuild
From the project root, generate the v009 scene using its layout.py, then:

```bash
.venvs/omx_sim/bin/python versions/v010/code/prepare.py /path/to/v009_scene /path/to/new_v010_scene versions/v010/configs/dynamics.json
```

The portable archive includes generated scene/ and upstream robot assets/license, check.py, run_remote.sh, requirements.txt, and this document. Run `bash run_remote.sh` on the remote host. First install needs internet; subsequent physics calculations do not. Remote host must remain powered and awake. Local PC can be off after detached tmux launch.

## Meaning of the 900 trials
Each trial is only 2 simulated seconds of settling, with three assumed friction values, three small drop offsets and seeded shoe offsets. It records numerical warnings and body positions. It does not execute the task, assess graspability or certify successful sim-to-real transfer. Expected runtime is minutes, not overnight training. Completion is not task success.

Next: confirm lid type and loading tray geometry/pose; validate collision shapes and gripper calibration; implement and test open → pick/insert two shoes → close → lift/load stage controllers and success predicates before RL training.
