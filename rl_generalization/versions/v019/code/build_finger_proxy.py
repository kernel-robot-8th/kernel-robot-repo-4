"""Build v019 from a v018 workcell with correctly oriented finger proxies.

The visual STL collision on link6/link7 is disabled and replaced by thin
boxes.  The box long axis is the finger body's local x axis; its local y
thickness is the jaw-opening direction.  This is a collision diagnostic
proxy, not a calibrated gripper model.
"""
from __future__ import annotations

import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def build(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source, destination)
    robot_path = destination / "robotis_omx" / "omx.xml"
    tree = ET.parse(robot_path)
    root = tree.getroot()
    root.find("compiler").set("meshdir", str((robot_path.parent / "assets").resolve()))

    for body_name, name, y in (
        ("link6", "finger6_proxy_v019", -0.0091),
        ("link7", "finger7_proxy_v019", 0.0092),
    ):
        body = root.find(f".//body[@name='{body_name}']")
        if body is None:
            raise ValueError(f"missing {body_name}")
        # The STL is retained as a visual geom but cannot enter dynamics.
        for geom in body.findall("geom"):
            if geom.get("contype") != "0":
                geom.set("contype", "0")
                geom.set("conaffinity", "0")
        ET.SubElement(
            body,
            "geom",
            name=name,
            type="box",
            # Distal finger landmark in the measured mesh frame.  The x
            # half-size is the contact patch length; y is the thin side pad.
            pos=f"0.06243 {y} -0.004",
            size="0.012 0.001 0.004",
            mass="0",
            contype="3",
            conaffinity="3",
            friction="0.8 0.005 0.0001",
            solref="0.02 1",
            solimp="0.995 0.999 0.001",
            rgba="0.12 0.8 0.2 1",
        )
    tree.write(robot_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source, args.destination)
