# v016: trajectory alignment and first bilateral contact

No hardware execution. No shoe repositioning, attachments, forced lift, joint-limit expansion or verified sim-to-real calibration.

## Evidence
- alignment_audit.py compares lowest recorded computed FK points in video-selected windows6..9s and23..27s (ep0) with current shoe origins. Correct order hypothesis shoe1→shoe0 yields common translation(+3.4972,-0.34276)cm and0.315cm residual per point. These TCP points are not measured shoe centers; this is an experimental trajectory offset, not a calibrated transform.
- gripper_gap.py computes visual mesh triangle cross sections in link5 local z=0. For candidate zero46.8 and recorded g48.94, gap at local x=.09193 is16.72mm but atx=.075 it is29.73mm. Finger shape and insertion depth matter; these visual surface calculations do not validate convex-hull collision contacts or real gripper zero.
- retarget.py uses the recorder's EE_OFFSET(.09193,-.0016,0) and translates recorded action TCP poses, preserving orientation approximately through numerical IK. Limits remain enforced. Max planned position residual0.127mm, orientation1.842deg in first12s. Initial simulated posture changes to translated initial command, not original initial observation.
- Horizontal-only translated trial: no finger contact/lift. At approx7.6s simulation fingers remained3.33/4.22mm from shoe1 collision mesh.
- Additional experimental z=-6mm trial: shoe1 finger contacts257 integration steps (0.514s), bilateral241 (0.482s), peak origin lift0.247mm. No >3cm sustained lift, so grasp/lift criterion FALSE. No warnings. Raw contact counts are not separate grasp attempts. This is progress from no contact to contact, not successful lifting.

## View the contact trial
From project root (v015 scene already generated):
```bash
.venvs/omx_sim/bin/python versions/v016/code/retarget_contact.py --view --shift-z -0.006 --out "versions/v016/runs/contact_$(date +%Y%m%d_%H%M%S)"
```
Omit --view for repeatable headless evaluation. Default x/y offsets and default gripper-zero46.8 are explicit uncalibrated experimental parameters. Results reject claims of real transfer. Viewer runs physical simulation with recorded gripper action and retargeted arm commands.

## Remaining
Need grip force/contact geometry/closure timing diagnostics for retention; actual gripper width calibration and historical/current workspace registration. Do not tune arbitrary friction solely to force a success. Cloth upper remains rigid; no physical material calibration. No RL training yet. CURRENT remainsv004.
