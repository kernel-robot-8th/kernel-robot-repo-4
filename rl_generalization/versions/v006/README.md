# v006 — measured workcell layout draft

User measurements interpreted in cm: white support H17.5 W28 D17.2; wood H8 W27 D20; edge gap2.5; shoe L3.5 W2 H0.7–2.5; brown box W6 D6 H5.5. Stored as meters in configs/layout.json. World x from robot toward table, y width, z up. Both supports on same floor: top difference9.5cm. Table center x21.1cm relative to wood center. Centerline/mount origin interpretation remains assumed; user gap reply confirmed only2.5cm. Exact shoes/box xy and yaw not measured.

The scene preserves upstream physics properties except raising/placing robot root and adds measured static support boxes. Shoes are fixed two-block geometric proxies; brown box is a fixed solid proxy without cavity/lid. They are NOT yet graspable bodies. No mass/friction/deformation measurements have been invented. Shoe 0.7–2.5cm range is represented as a low sole/high heel proxy; the physical height distribution is unverified.

Validation: both candidate arm init poses compile in MuJoCo3.3.7; assertions on compiled table height and edge gap pass. No generated contacts in either static candidate pose (gripper0). This does not validate motion clearance, real mapping, or physical grasp. EGL layout preview rendered and inspected. Static props do not generate mutual dynamic contacts. Base mesh origin at wood center is an explicit approximation, not measured mounting alignment.

## Local preview

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v006/code/layout.py \
  --out ".local/layout_$(date +%Y%m%d_%H%M%S)" --view
```

For loading pose append --pose load. Existing output dirs are rejected. Source required: official OMX checkout under .local/sim_sources plus v005 evidence/model_audit.json. Output copies licensed upstream assets then modifies a local XML; original upstream is untouched. Generated mesh paths are absolute; rebuild after relocation. CURRENT remains v004; this script is independent from training runner.

## Before batch/RL

Do not use old sim_validation900 trials as workcell validation: it uses bare robot scene. First verify base transform and initial pose correspondence, create movable contact proxies and gripper mapping, then implement task-relevant scripted reach/close/lift tests. No new 900-run task launched. No robot device opened.
