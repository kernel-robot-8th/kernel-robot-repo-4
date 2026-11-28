"""Build a thinner, explicitly versioned finger collision proxy.

The v021 capsule proxies have a 2 mm radius and penetrate the shoe mesh by up
to 4.2 mm during replay.  v022 keeps the visual arm unchanged and reduces
only the collision proxy radius to 1 mm.  This is a calibration experiment,
not a claim about the physical finger radius; the resulting contact metrics
must still be checked against measured hardware.
"""
from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def build(source: Path, destination: Path, radius_m: float) -> Path:
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source, destination)
    scene_path = destination / "scene.xml"
    # The finger geoms live in the included OMX model, not the top-level
    # scene XML. MuJoCo resolves this include before compilation.
    model_path = destination / "robotis_omx" / "omx.xml"
    root = ET.parse(model_path).getroot()
    names = {"finger6_proxy", "finger7_proxy"}
    changed = []
    for geom in root.iter("geom"):
        if geom.get("name") in names:
            old = [float(x) for x in geom.get("size", "").split()]
            if len(old) != 2:
                raise ValueError(f"unexpected proxy size for {geom.get('name')}: {old}")
            geom.set("size", f"{radius_m:.9g} {old[1]:.9g}")
            changed.append({"name": geom.get("name"), "old_size": old, "new_size": [radius_m, old[1]]})
    if len(changed) != 2:
        raise ValueError(f"expected two finger proxies, found {len(changed)}")
    ET.ElementTree(root).write(model_path, encoding="utf-8")
    (destination / "proxy_calibration.json").write_text(json.dumps({
        "source": str(source),
        "radius_m": radius_m,
        "changed": changed,
        "visual_mesh_collision": "unchanged_disabled",
        "status": "thin_proxy_experiment_not_hardware_calibrated",
    }, indent=2) + "\n")
    return scene_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--radius-m", type=float, default=0.001)
    a = p.parse_args()
    if not 0 < a.radius_m <= 0.002:
        p.error("--radius-m must be in (0, 0.002]")
    print(build(a.source, a.destination, a.radius_m))
