# v012: simulated pregrasp approach

Implements damped numerical inverse kinematics, simulator joint-limit clipping, four candidate downward angles (45/60/75/90 degrees from horizontal), a sampled joint-path collision check, and smooth position-actuator tracking. Each shoe is evaluated independently from the candidate arrange pose. No hardware connection or learned policy. CURRENT remains v004.

Run locally from project root (after inspection/view_workcell.py has built the scene):

```bash
.venvs/omx_sim/bin/python versions/v012/code/approach.py --out "versions/v012/runs/approach_$(date +%Y%m%d_%H%M%S)" --view
```

Omit --view for headless execution. Viewer opens once per shoe; closing it cancels that shoe's execution (the next shoe may open a new window). Simulation time is throttled for viewing. Results contain per-shoe status, selected angles, inverse-kinematics errors, final tracked errors and CSV trajectories. Output directory must be new.

The target is 4cm above the maximum nominal shoe height. TCP is a provisional link5-local point [0.075,-0.00165,0]m, not measured finger contact center. Axis-only IK leaves wrist roll unconstrained; gripper command remains0 and is NOT a calibrated open grasp width. A different wrist orientation will likely be required for grasping.

Reject IK position error>3mm or direction error>8deg. Before actuation, check121 samples of the joint interpolation. During simulation check contacts every integration step: penetration>0.5mm involving a moving arm link stops execution. Fixed base-to-support contact is excluded. Finite-state, MuJoCo warning and joint-limit checks also stop execution. These are diagnostic checks, not a certified safety controller. APPROACH_REACHED requires final error<1cm and axis error<8deg, and does NOT mean grasp success.

Local nominal results: shoe0 selected75deg, final error2.006mm/direction0.564deg; shoe1 selected60deg, final error3.174mm/direction0.737deg. No detected threshold violations or numerical warnings. Vertical-only attempts failed the IK tolerance; this solver result does not prove global unreachability.

Before grasping: identify actual finger contact surfaces and gap versus joint angle; constrain wrist roll; verify collisions rather than attach/weld the shoe. Then add descent, closure, contact-based lift and sustained retention tests. Simulator target coordinates are privileged state, not camera estimates. Real calibration, soft materials, varied locations, insertion, lid manipulation and loading are not validated.
