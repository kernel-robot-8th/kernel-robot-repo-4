"""Build a robot-facing-edge hinged lid from the detached v018 scene.

The OMX is at lower/negative world-x in the workcell model, so the lid hinge
is placed on the box's negative-x edge. The hinge axis is local +y. With the
chosen sign convention, q=0 is closed, q=-pi/2 is vertical, and q=-pi lays
the lid flat toward the OMX (negative x).
"""

from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def vec(text: str) -> list[float]:
    return [float(x) for x in text.split()]


def fmt(values: list[float]) -> str:
    return " ".join(f"{v:.12g}" for v in values)


def build(source: Path, out: Path) -> Path:
    if out.exists():
        raise FileExistsError(out)
    shutil.copytree(source, out)
    scene_path = out / "scene.xml"
    root = ET.parse(scene_path).getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        raise ValueError("scene has no worldbody")
    box = worldbody.find("./body[@name='paper_box']")
    lid = worldbody.find("./body[@name='paper_lid']")
    if box is None or lid is None or lid.find("freejoint") is None:
        raise ValueError("expected detached paper_lid and paper_box")
    top = lid.find("./geom[@name='lid_top']")
    if top is None:
        raise ValueError("paper_lid/lid_top missing")

    box_pos = vec(box.get("pos", "0 0 0"))
    lid_pos = vec(lid.get("pos", "0 0 0"))
    top_pos = vec(top.get("pos", "0 0 0"))
    half_x = vec(top.get("size", "0 0 0"))[0]

    # Child frame lies on the negative-x outer edge. Shifting all geometry by
    # +half_x preserves the detached lid's closed world pose exactly.
    child_pos = [
        lid_pos[0] - box_pos[0] + top_pos[0] - half_x,
        lid_pos[1] - box_pos[1],
        lid_pos[2] - box_pos[2],
    ]
    lid.set("pos", fmt(child_pos))
    lid.remove(lid.find("freejoint"))
    lid.insert(
        0,
        ET.Element(
            "joint",
            {
                "name": "lid_hinge",
                "type": "hinge",
                "pos": "0 0 0",
                "axis": "0 1 0",
                "range": "-3.14159265359 0",
                "limited": "true",
                "damping": "0.02",
                "frictionloss": "0.01",
            },
        ),
    )
    for geom in lid.findall("geom"):
        if geom.get("pos") is not None:
            p = vec(geom.get("pos"))
            p[0] += half_x
            geom.set("pos", fmt(p))
        if geom.get("fromto") is not None:
            p = vec(geom.get("fromto"))
            if len(p) != 6:
                raise ValueError(f"unexpected fromto on {geom.get('name')}")
            p[0] += half_x
            p[3] += half_x
            geom.set("fromto", fmt(p))
    worldbody.remove(lid)
    box.append(lid)
    ET.ElementTree(root).write(scene_path, encoding="utf-8")
    (out / "hinge_spec.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "hinge_edge": "paper_box local -x (robot-facing)",
                "hinge_axis": "paper_box local +y",
                "closed_pose_preserved": True,
                "hinge_range_rad": [-3.14159265359, 0.0],
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
    print(build(args.source, args.out))


if __name__ == "__main__":
    main()
