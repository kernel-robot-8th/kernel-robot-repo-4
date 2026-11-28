# v014: recorded command physical replay diagnostic

This replaces the frozen gripper/kinematic-only playback with position-actuator commands and mj_step. Uses actual shoebox_D episode0 action stream at30Hz, first12 seconds by default. Initial arm/gripper state is initialized once; thereafter dynamics run. Objects keep v011 placement. No welded shoe, attachment, kinematic lift or reward is added.

Gripper mapping is NOT calibrated: q=(g-zero)*4095/4096*2pi/100. Candidate zero47.16 inferred from the late low-current near-closed recorded state. First run stops7.502s because recorded command falls below candidate zero. A separate sensitivity test at46.8 is not a calibration result. No silent clipping or joint-range expansion. Stop on invalid command, numerical warning, or moving-arm support penetration>2mm. Finger-shoe contacts and sustained bilateral contact with lift>3cm for0.5s are logged, not independently validated success measures.

```bash
# See physical motion using the alternative, UNCALIBRATED zero candidate:
.venvs/omx_sim/bin/python versions/v014/code/replay_contact.py --view --gripper-zero 46.8 --out "versions/v014/runs/contact_$(date +%Y%m%d_%H%M%S)"
```

Local video exists under classification/shoebox_D/videos, although its data parquet files are LFS pointers. Episode0 metadata says top video file000 offset0..45.1s. Contact sheet sampled every3s confirms physical shoe pick/placement in that recording. At8s recorded computed FK+[0,0,0.08] = [0.211274,-0.094304,0.205346]m; v011 shoe centers are [0.1725,-0.1] and [0.2445,-0.1]. Approximately3.4–3.9cm planar separation exists, but computed TCP is not an independently measured shoe centroid. Do not move shoes automatically to make a grasp appear successful. The historical demo layout and current measured layout need registration.

Recorder core/kinematics.py explicitly defines EE_OFFSET=(0.09193,-0.0016,0), confirming v013 numerical inference; its FK is computed, not external measurement. Current is not pressure. Need validate gripper zero/link geometry and historical-to-current workspace registration before real transfer or RL claims. No robot access.
