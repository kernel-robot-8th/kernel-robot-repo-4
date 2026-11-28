"""Reject apparent grasps whose collision geometry is penetrated."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "evidence"
rows = []
for summary in sorted(root.glob("sweep_z*/summary.json")):
    result = json.loads(summary.read_text())
    force = json.loads((summary.parent / "force_summary.json").read_text())
    peak = result["peak_shoe_lift_m"][1]
    hold = result["max_bilateral_lift_hold_s"][1]
    penetration = force["max_finger_shoe_penetration_m"]
    rows.append({
        "run": summary.parent.name,
        "peak_lift_m": peak,
        "bilateral_hold_s": hold,
        "max_penetration_m": penetration,
        "apparent_lift": bool(peak > .03 and hold >= .5),
        "valid_under_1mm_penetration": bool(peak > .03 and hold >= .5 and penetration <= .001),
    })
out = {"runs": rows, "acceptance": "lift>3cm and bilateral hold>=0.5s and finger-shoe penetration<=1mm"}
(root / "sweep_validation.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
