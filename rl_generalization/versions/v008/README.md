# v008 — corrected curved shoe envelope

User correction: 0.7cm means low toe height, not sole thickness; 2.5cm means central highest region continuing toward the rear. Replaced two-block proxy by an elliptical-plan closed triangular mesh with smooth longitudinal profile and rounded transverse crown. Dimensions length3.5cm width2cm peak2.5cm toe0.7cm. Rear2.2cm is a configurable unmeasured assumption, not supplied measurement. Toe+x orientation provisional. Material/sole detail/opening/laces not reconstructed. This is a smooth external envelope, not a scanned shoe or validated contact mesh. MuJoCo mesh contact may use convex geometry; visible contour does not prove accurate contact surface. All props remain static; no grasp claim.

Checks: mesh xy extents, max/toe height and closed oriented-edge topology assertions pass; full scene loads in MuJoCo3.3.7; shoe footprints inside table; candidate initial pose reports no contacts. Closeup EGL rendering inspected. Historical snapshots unchanged. CURRENT staysv004.

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v008/code/layout.py \
 --out ".local/layout_$(date +%Y%m%d_%H%M%S)" --view --shoe-closeup
```

Omit --shoe-closeup for overall view. Generated asset paths are absolute; rebuild after moving. v007 measurement ambiguities still apply.
