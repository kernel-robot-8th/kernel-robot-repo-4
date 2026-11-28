# v015: resting shoe contact stability correction

User saw shoes twitching without being grasped. Reproduced with arm held in place: no finger contacts; after1s, peak-to-peak movement during1..4s was6.64/6.18mm in x and2.76/1.94mm in z. Max penetration over4s5.99mm. Zero MuJoCo warnings did NOT establish physically credible contact. Earlier900 settling trials only tested finite states/warnings and missed this.

Fix: preserve curved upper collision mesh for robot/object contact; replace shoe-to-white-table collision with a flat30x16x3mm sole proxy within the35x20mm shoe envelope. Collision categories make the upper ignore only the white table, with the sole providing table contact. Other world and arm colliders remain compatible. Shoe mass remains10g, split9g upper/1g sole. Contact stiffness solref0.005/1, solimp0.99/0.99/0.001 are numerical assumptions, not measured material. Shoes keep their free joints; no weld, attachment, frozen qpos, or pose reset during rollout.

Same test: no motion after1s to printed precision; settled vertical displacement -0.00123mm, max transient penetration0.0219mm. This only validates this rest case. Cloth/paper deformation, general contact realism and real transfer are not validated.

Reproduce from project root:
```bash
.venvs/omx_sim/bin/python versions/v015/code/contact_stability.py --out .local/stability_v015
# Output must not already exist. Prepared scene already exists in current workspace.
.venvs/omx_sim/bin/python versions/v015/code/replay_contact.py --view --gripper-zero 46.8 --out "versions/v015/runs/replay_$(date +%Y%m%d_%H%M%S)"
```

Replay retains v014 demonstration and uncalibrated gripper candidate. It does NOT fix historical/current shoe placement mismatch or establish grasp success. No changes to historical versions or hardware.
