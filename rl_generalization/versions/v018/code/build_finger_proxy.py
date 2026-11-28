"""Build a diagnostic scene with separate thin finger collision proxies."""
import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def build(source: Path, destination: Path, finger_z: float = -0.004) -> None:
    shutil.copytree(source, destination)
    robot_path = destination / "robotis_omx" / "omx.xml"
    robot = ET.parse(robot_path)
    root = robot.getroot()
    root.find("compiler").set("meshdir", str((robot_path.parent / "assets").resolve()))
    for body_name, name, y in (("link6", "finger6_proxy", -0.0091), ("link7", "finger7_proxy", 0.0092)):
        body = root.find(f".//body[@name='{body_name}']")
        for geom in body.findall("geom"):
            if geom.get("contype") != "0":
                geom.set("contype", "0")
                geom.set("conaffinity", "0")
        ET.SubElement(
            body,
            "geom",
            name=name,
            type="capsule",
            pos=f"0.06243 {y} {finger_z}",
            size="0.002 0.012",
            mass="0",
            contype="3",
            conaffinity="3",
            friction="0.8 0.005 0.0001",
            solref="0.005 1",
            solimp="0.99 0.99 0.001",
            rgba="0.1 0.1 0.1 1",
        )
    robot.write(robot_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--finger-z", type=float, default=-0.004,
                        help="local z of the proxy capsule center in each finger link")
    args = parser.parse_args()
    build(args.source, args.destination, args.finger_z)
