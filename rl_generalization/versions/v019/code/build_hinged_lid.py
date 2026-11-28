"""Build a provisional hinged-lid variant from the v018 scene.

The v018 scene has a detached free body for the lid.  This builder preserves
the closed-lid geometry in world coordinates, then nests it under
``paper_box`` and replaces the lid free joint with a single hinge along the
rear (positive-y) edge.  It is a structural model change only; it does not
claim that the real cardboard lid has this hinge axis or stiffness.
"""

from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def _vec(text: str) -> list[float]:
    return [float(x) for x in text.split()]


def _fmt(values: list[float]) -> str:
    return " ".join(f"{v:.12g}" for v in values)


def build(source: Path, out: Path) -> Path:
    if out.exists():
        raise FileExistsError(f"output already exists: {out}")
    shutil.copytree(source, out)
    scene_path = out / "scene.xml"
    root = ET.parse(scene_path).getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        raise ValueError("scene has no worldbody")
    box = worldbody.find("./body[@name='paper_box']")
    lid = worldbody.find("./body[@name='paper_lid']")
    if box is None or lid is None:
        raise ValueError("expected paper_box and paper_lid bodies")
    if lid.find("freejoint") is None:
        raise ValueError("paper_lid is not the expected detached free body")

    box_pos = _vec(box.get("pos", "0 0 0"))
    lid_pos = _vec(lid.get("pos", "0 0 0"))
    top = lid.find("./geom[@name='lid_top']")
    if top is None:
        raise ValueError("paper_lid/lid_top missing")
    top_pos = _vec(top.get("pos", "0 0 0"))
    top_size = _vec(top.get("size", "0 0 0"))
    if len(top_size) != 3:
        raise ValueError("lid_top size must have three entries")

    # Put the child-body frame at the rear outer edge.  Shifting each geom by
    # -half_y exactly preserves the detached lid's closed world pose.
    half_y = top_size[1]
    child_pos = [
        lid_pos[0] - box_pos[0],
        lid_pos[1] - box_pos[1] + top_pos[1] + half_y,
        lid_pos[2] - box_pos[2],
    ]
    lid.set("pos", _fmt(child_pos))
    lid.remove(lid.find("freejoint"))
    joint = ET.Element(
        "joint",
        {
            "name": "lid_hinge",
            "type": "hinge",
            "pos": "0 0 0",
            "axis": "1 0 0",
            "range": "-1.57079632679 0",
            "limited": "true",
            "damping": "0.02",
            "frictionloss": "0.01",
        },
    )
    lid.insert(0, joint)

    for geom in lid.findall("geom"):
        if geom.get("pos") is not None:
            p = _vec(geom.get("pos"))
            p[1] -= half_y
            geom.set("pos", _fmt(p))
        if geom.get("fromto") is not None:
            pts = _vec(geom.get("fromto"))
            if len(pts) != 6:
                raise ValueError(f"unexpected fromto on {geom.get('name')}")
            pts[1] -= half_y
            pts[4] -= half_y
            geom.set("fromto", _fmt(pts))

    worldbody.remove(lid)
    box.append(lid)
    ET.ElementTree(root).write(scene_path, encoding="utf-8", xml_declaration=False)
    (out / "hinge_spec.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "hinge_axis": "paper_box local +x",
                "closed_pose_preserved": True,
                "hinge_range_rad": [-1.57079632679, 0.0],
                "hinge_frame_relative_to_paper_box_m": child_pos,
                "status": "provisional_structural_variant",
            },
            indent=2,
        )
        + "\n"
    )
    return scene_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    path = build(args.source, args.out)
    print(path)


if __name__ == "__main__":
    main()
