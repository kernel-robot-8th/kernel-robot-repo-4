# v007 — retaining rim and annotated layout draft

User confirms square retaining rim7x7cm, height1cm, box6x6cm fits inside. Implemented as four static walls (no filled support under box). Outer7cm interpretation, inner6cm and wall0.5cm remain inferred: actual wall thickness, clearance and bottom sheet are not measured. Box bottom stays at tabletop17.5cm, not raised to18.5cm. Model properties and real gripper mapping remain unverified.

Image measurements preserved verbatim in control_audit/layout_annotations_20261120.json. Axes: x away from robot, y robot-left. Both shoes are now on robot-right of box, one near and one far. Yellow left10.8/right11 and near6.5/far4 give estimated box center offsets y+0.1cm/x+1.25cm using opposing-gap differences, assuming matching opposite reference edges. Which rectangle the yellow arrows refer to is unresolved. Inconsistent sums are not silently treated as exact: brown6cm reference implies27.8x16.5cm tabletop, outer-rim7cm implies28.8x17.5cm, versus measured28x17.2cm.

Shoes provisionally axis-aligned, right edge gap3cm each, near/far gaps3/3.5cm respectively. With shoe length3.5cm and tabletop17.2cm, intershoe gap3.7cm (image3.5cm; residual0.2cm). Blue6.7/8 and remaining red4/4.5 marks are recorded but not forced into positions until endpoints/yaw clarified. Do not claim an exact reconstruction.

Validated scene load, measured table height/gap, all object footprints inside table and both shoes right of box. Candidate arrange pose generated no contacts; static check only. Preview rendered/inspected. Prior versions untouched. CURRENT remainsv004. All objects remain static proxies, not a grasp environment; old900 sweep not updated or launched.

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v007/code/layout.py \
  --out ".local/layout_$(date +%Y%m%d_%H%M%S)" --view
```

Source model and v005 audit required as forv006. Generated absolute asset paths require rebuilding if output is moved.
