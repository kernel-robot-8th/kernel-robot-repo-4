# v009 — Converse-like visual styling and material observations

User reports soft, readily compressed cloth upper, hard sole (Converse), paper/cardboard box. Recorded in config as qualitative observations, NOT fitted physical parameters.

Visual changes: pink curved upper, white rubber sole/toe accent, black sole band, crossed white laces; cardboard lid seam. All accents have contype=conaffinity=0 and mass0, so decorative strands do not introduce artificial grasp contacts. Upper envelope contact is still the previous rigid static mesh. No opening/deformable cloth/cardboard crushing/hinged lid implemented. Sole thickness3mm and design proportions are artistic assumptions; total footprint/profiles use existing measured envelope. This is approximate styling, not exact product geometry.

## Sensor audit

Collected remote OmxFollower line153 writes OperatingMode.CURRENT_POSITION for gripper. get_observation reads Present_Position, not Present_Current. Fleet source has no current/pressure logging found. HF reference omx_grip_robot.py is a separate current-observation variant, not evidence of the active fleet path. Six-dimensional ACT observation does not contain an extra current channel.

Therefore these inputs cannot identify grip force or material compliance. A future read-only log should capture timestamp, requested and sent gripper goal, actual position, Present_Current with model-specific units, mode/current-limit settings, and independently measured jaw aperture/contact/deformation. Current is not pressure. Any conversion needs actuator/transmission calibration; pressure also needs contact area. Motor torque saturation, mechanical transmission and object deformation cannot be distinguished from joint position alone. No live motor configuration or current limits changed here.

Next physics work must distinguish stiff sole and compliant upper, and separately model cardboard walls/lid; use measured parameters or label a sensitivity range as assumed. A softer solver contact parameter is not proof of cloth/cardboard deformation. Current scene remains static visual/collision layout, not training.

## Preview (local)
```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v009/code/layout.py \
 --out ".local/layout_$(date +%Y%m%d_%H%M%S)" --view --shoe-closeup
```

Validation: mesh bounds/topology assertions, compiled footprint/height/gap checks, candidate static scene contact report passed; EGL render inspected. Decoration adds no collision response. Physical material fitting not performed. CURRENT remainsv004.
