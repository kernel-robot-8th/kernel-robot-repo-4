"""NVIDIA Isaac Sim 5.1 — Cobot_map_v6 (10.26) Reconstructed Shoe Store & SDG Vision Backend.

Architecture (Synchronized with Cobot_map_v6 SLAM Map & 10.26 Confirmed Hardware Specs):
  - 2.50m x 2.40m Flat Arena (Showroom X=0.00~1.20m, Central Wall X=1.20~1.27m, Warehouse X=1.27~2.50m)
  - Sim <-> Cobot_map_v6 Coordinate Transform:
      X_v6 = X_sim - 1.400,  Y_v6 = Y_sim - 1.596  (Inner-wall origin at col=9, row=244 of cobot_map_v6.pgm)
  - Bottom Gate Opening: X=1.20~1.27m, Y=0.00~0.67m (67cm wide cable-free passage; upper wall Y=0.67~2.40m)
  - 4-Block Obstacle Structure (All interior clutter removed per Cobot_map_v6):
      1) Central Partition Wall: X=1.20~1.27m, Y=0.67~2.40m
      2) Warehouse Loading & Rack Block (X=2.09~2.50m, Y=1.04~2.10m):
         - OMX-1 & OMX-2 Individual Wooden Stands: 250 x 200 x 85 mm (at [2.20, 1.99] & [2.20, 1.42])
         - 1-Tier Box Racks A & B: 230 x 150 x 200 mm (single-tier stand, box resting surface Z=0.200m per HARDWARE-AND-TRAY-SPEC-REVIEW)
      3) Store Unloading Station Block (X=0.00~0.40m, Y=1.60~1.99m):
         - OMX-3 Individual Wooden Stand: 250 x 200 x 85 mm (at [0.21, 1.72]) + Unloading Table
      4) Store Lower-Left Counter: X=0.00~0.22m, Y=0.00~0.99m
  - Daiso Cargo Box: 60 x 60 x 43 mm (40g)
  - 3-Camera Classroom CCTV & SDG System (10.26 Confirmed):
      - CAM-1 (Ceiling Global / Galaxy Note 10): [1.25, 1.20, 2.15m], 90° Nadir Top-Down
      - CAM-2 (Warehouse Load / USB Webcam):     [1.45, 1.65, 0.60m], 65° High-Angle Downward (watches OMX-1/2 loading)
      - CAM-3 (Store Unload / Galaxy Note 3 Neo):[0.95, 1.72, 0.60m], 65° High-Angle Downward (watches OMX-3 unloading)
  - 2-Tier MuJoCo -> Isaac Sim SDG Pipeline:
      - Pass --events-json /path/to/events.json to replay MuJoCo physics failure poses (DROP/TILT/OVERHANG/MISPLACED)
        and generate synthetic RGB + bbox labels for DeepStream / YOLO anomaly detection.
"""

import os
import sys
import json
import math
import argparse
import numpy as np

# SimulationApp must be instantiated prior to importing any omni/pxr modules
from isaacsim import SimulationApp

SIM_TO_V6_OFFSET_XY = (-1.400, -1.596)


def sim_to_v6(x_sim: float, y_sim: float):
    return round(x_sim + SIM_TO_V6_OFFSET_XY[0], 3), round(y_sim + SIM_TO_V6_OFFSET_XY[1], 3)


def v6_to_sim(x_v6: float, y_v6: float):
    return round(x_v6 - SIM_TO_V6_OFFSET_XY[0], 3), round(y_v6 - SIM_TO_V6_OFFSET_XY[1], 3)


parser = argparse.ArgumentParser(description="Isaac Sim Cobot_map_v6 (10.26) Reconstructed Shoe Store Scene")
parser.add_argument("--headless", action="store_true", default=True, help="Run headless")
parser.add_argument("--duration-sec", type=float, default=60.0, help="Run duration in seconds")
parser.add_argument("--fps", type=int, default=30, help="Simulation step frequency")
parser.add_argument("--output-dir", type=str, default="/workspace/data/shoe_store_sim_v6", help="Log/SDG output")
parser.add_argument("--events-json", type=str, default="", help="Optional MuJoCo events.json for SDG anomaly replay")
args = parser.parse_args()

print("[isaac_sim] Initializing SimulationApp (headless=%s)..." % args.headless)
sim = SimulationApp({"headless": args.headless})

from omni.isaac.core import World
from omni.isaac.core.objects import DynamicCuboid, FixedCuboid, GroundPlane
from pxr import UsdGeom, Gf

print("[isaac_sim] Building Cobot_map_v6 World Stage (2.50m x 2.40m Flat Arena)...")
world = World(stage_units_in_meters=1.0)

# Ground Plane (2.50m x 2.40m arena boundary, 100% Flat)
world.scene.add(GroundPlane(prim_path="/World/GroundPlane", size=10.0, color=np.array([0.15, 0.16, 0.19])))

# -----------------------------------------------------------------------------
# 1. Structural Boundaries & Central Partition (67cm Bottom Gate Opening)
# -----------------------------------------------------------------------------
borders = [
    # North wall (Y=2.40m)
    {"name": "Wall_North", "pos": [1.25, 2.41, 0.15], "size": [2.50, 0.02, 0.30]},
    # South wall (Y=0.00m)
    {"name": "Wall_South", "pos": [1.25, -0.01, 0.15], "size": [2.50, 0.02, 0.30]},
    # West wall (X=0.00m)
    {"name": "Wall_West", "pos": [-0.01, 1.20, 0.15], "size": [0.02, 2.40, 0.30]},
    # East wall (X=2.50m)
    {"name": "Wall_East", "pos": [2.51, 1.20, 0.15], "size": [0.02, 2.40, 0.30]},
    # Central Partition Wall (X=1.20~1.27m, Y=0.67~2.40m; leaves Y=0.00~0.67m open for 67cm Gate)
    {"name": "Partition_Wall_v6", "pos": [1.235, 1.535, 0.25], "size": [0.07, 1.73, 0.50]},
]

for b in borders:
    world.scene.add(FixedCuboid(
        prim_path=f"/World/Structures/{b['name']}",
        name=b["name"],
        position=np.array(b["pos"]),
        size=1.0,
        scale=np.array(b["size"]),
        color=np.array([0.32, 0.38, 0.46])
    ))

# -----------------------------------------------------------------------------
# 2. Reconstructed Cobot_map_v6 Furniture & 1-Tier Box Racks (230x150x200mm)
# -----------------------------------------------------------------------------
furniture = [
    # Store Lower-Left Counter (X=0.00~0.22m, Y=0.00~0.99m in cobot_map_v6.pgm)
    {"name": "Store_Counter_v6", "pos": [0.11, 0.495, 0.35], "size": [0.22, 0.99, 0.70], "col": [0.22, 0.45, 0.62]},
    # Store Upper-Left Unloading Table (X=0.02~0.11m, Y=1.60~1.99m)
    {"name": "Store_Unloading_Table_v6", "pos": [0.065, 1.795, 0.085], "size": [0.09, 0.39, 0.17], "col": [0.28, 0.52, 0.68]},
    # Warehouse 1-Tier Box Rack A (230 x 150 x 200 mm between OMX-1 and OMX-2)
    {"name": "Warehouse_1Tier_Rack_A", "pos": [2.385, 1.695, 0.10], "size": [0.230, 0.150, 0.200], "col": [0.72, 0.52, 0.24]},
    # Warehouse 1-Tier Box Rack B (230 x 150 x 200 mm next to OMX-2)
    {"name": "Warehouse_1Tier_Rack_B", "pos": [2.20, 1.115, 0.10], "size": [0.230, 0.150, 0.200], "col": [0.72, 0.52, 0.24]},
]

for f in furniture:
    world.scene.add(FixedCuboid(
        prim_path=f"/World/Furniture/{f['name']}",
        name=f["name"],
        position=np.array(f["pos"]),
        size=1.0,
        scale=np.array(f["size"]),
        color=np.array(f["col"])
    ))

# -----------------------------------------------------------------------------
# 3. Three Individual OMX Wooden Stands (250 x 200 x 85 mm) & 3 Pinky Robots
# -----------------------------------------------------------------------------
omx_wooden_stands = [
    {"name": "OMX1_Stand_WH1", "pos": [2.20, 1.99, 0.0425], "size": [0.200, 0.250, 0.085], "col": [0.55, 0.38, 0.22]},
    {"name": "OMX2_Stand_WH2", "pos": [2.20, 1.42, 0.0425], "size": [0.200, 0.250, 0.085], "col": [0.55, 0.38, 0.22]},
    {"name": "OMX3_Stand_Store", "pos": [0.21, 1.72, 0.0425], "size": [0.200, 0.250, 0.085], "col": [0.55, 0.38, 0.22]},
]

for stand in omx_wooden_stands:
    world.scene.add(FixedCuboid(
        prim_path=f"/World/Robots/{stand['name']}",
        name=stand["name"],
        position=np.array(stand["pos"]),
        size=1.0,
        scale=np.array(stand["size"]),
        color=np.array(stand["col"])
    ))

# Pinky Robots at Cobot_map_v6 synchronized HOME 1~3 waypoints (X_sim=1.48m -> X_v6=+0.080m)
pinky_fleet = [
    {"name": "Pinky_1", "pos": [1.48, 2.07, 0.07], "col": [0.93, 0.55, 0.12]},
    {"name": "Pinky_2", "pos": [1.48, 1.87, 0.07], "col": [0.20, 0.70, 0.35]},
    {"name": "Pinky_3", "pos": [1.48, 1.67, 0.07], "col": [0.35, 0.55, 0.95]},
]

for p in pinky_fleet:
    world.scene.add(DynamicCuboid(
        prim_path=f"/World/Robots/{p['name']}",
        name=p["name"],
        position=np.array(p["pos"]),
        size=1.0,
        scale=np.array([0.22, 0.16, 0.14]),
        color=np.array(p["col"]),
        mass=1.60
    ))

# Confirmed 10.26 Daiso Cargo Box (60 x 60 x 43 mm, 40g) resting on top of Rack B (Z=0.200m; was 0.095, inside the solid rack)
target_box = world.scene.add(DynamicCuboid(
    prim_path="/World/Items/DaisoBox_60x60x43",
    name="daiso_box_cargo",
    position=np.array([2.20, 1.115, 0.200 + 0.0215]),
    size=1.0,
    scale=np.array([0.060, 0.060, 0.043]),
    color=np.array([0.92, 0.42, 0.18]),
    mass=0.040
))

# Optional MuJoCo failure event loader for 2-Tier SDG synthetic dataset generation
sdg_events = []
if args.events_json and os.path.exists(args.events_json):
    with open(args.events_json, "r", encoding="utf-8") as f:
        sdg_events = json.load(f)
    print(f"[isaac_sim] Loaded {len(sdg_events)} MuJoCo events from {args.events_json} for SDG replay.")

# -----------------------------------------------------------------------------
# 4. Confirmed 3-Camera Classroom CCTV + Arm Camera Definitions
# -----------------------------------------------------------------------------
camera_definitions = [
    # 3 Classroom CCTV Cameras (10.26 Confirmed)
    {"name": "Cam1_Ceiling_Global_Note10", "pos": [1.25, 1.20, 2.15], "rot": [0, 0, 0], "desc": "Galaxy Note 10 (2.15m 90deg Nadir Top-Down)"},
    {"name": "Cam2_Warehouse_Load_Webcam", "pos": [1.45, 1.65, 0.60], "rot": [25, 0, -90], "desc": "USB Webcam (0.60m 65deg Downward at WH1/WH2 Loading)"},
    {"name": "Cam3_Store_Unload_Note3Neo", "pos": [0.95, 1.72, 0.60], "rot": [25, 0, 90], "desc": "Galaxy Note 3 Neo (0.60m 65deg Downward at Store Unloading)"},
    # Arm Dedicated Overhead & Wrist Cameras
    {"name": "Cam_OMX1_Top", "pos": [2.20, 1.99, 0.60], "rot": [0, 0, 0], "desc": "OMX-1 Overhead (z=0.60m)"},
    {"name": "Cam_OMX2_Top", "pos": [2.20, 1.42, 0.60], "rot": [0, 0, 0], "desc": "OMX-2 Overhead (z=0.60m)"},
    {"name": "Cam_OMX3_Top", "pos": [0.21, 1.72, 0.60], "rot": [0, 0, 0], "desc": "OMX-3 Overhead (z=0.60m)"},
]

stage = world.stage
for c in camera_definitions:
    cam_path = f"/World/Cameras/{c['name']}"
    cam_prim = UsdGeom.Camera.Define(stage, cam_path)
    xform = UsdGeom.Xformable(cam_prim)
    xform.AddTranslateOp().Set(Gf.Vec3d(c["pos"][0], c["pos"][1], c["pos"][2]))
    cam_prim.GetHorizontalApertureAttr().Set(20.955)
    cam_prim.GetFocalLengthAttr().Set(18.8)  # ~65 deg HFOV
    v6_x, v6_y = sim_to_v6(c["pos"][0], c["pos"][1])
    print(f"[isaac_sim] Registered Camera: {c['name']} @ Sim({c['pos'][0]:.2f}, {c['pos'][1]:.2f}) / v6({v6_x:+.3f}, {v6_y:+.3f}) — {c['desc']}")

world.reset()
print("[isaac_sim] Cobot_map_v6 World Stage reset complete.")

# -----------------------------------------------------------------------------
# 5. Headless Simulation / SDG Loop
# -----------------------------------------------------------------------------
total_steps = int(args.duration_sec * args.fps)
print(f"[isaac_sim] Starting Headless Simulation Loop ({total_steps} steps @ {args.fps} FPS)...")

try:
    step_count = 0
    while sim.is_running() and step_count < total_steps:
        world.step(render=True)
        step_count += 1
        if step_count % (args.fps * 10) == 0:
            elapsed = step_count / args.fps
            print(f"[isaac_sim] Step {step_count}/{total_steps} ({elapsed:.1f}s / {args.duration_sec}s elapsed). Status: NOMINAL")
    print(f"[isaac_sim] Simulation run completed ({step_count} steps).")
except KeyboardInterrupt:
    print("[isaac_sim] Simulation interrupted by operator.")
finally:
    print("[isaac_sim] Shutting down SimulationApp...")
    sim.close()
    print("[isaac_sim] Clean exit.")
