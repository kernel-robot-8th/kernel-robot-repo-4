"""Contact-only OMX box transfer using ROBOTIS geometry and dynamics."""

import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from .assets import DESCRIPTION
from .common import PACKAGE, read_json


def normalized_to_radians(values, calibration):
    """Invert LeRobot calibration, including its different gripper normalization."""
    values = np.asarray(values, dtype=float).copy()
    signs = np.asarray(calibration["drive_mode"], dtype=bool)
    values[:5] = np.where(signs[:5], -values[:5], values[:5])
    values[5] = 100 - values[5] if signs[5] else values[5]
    fraction = (values + 100) / 200
    fraction[5] = values[5] / 100
    low = np.asarray(calibration["range_min"])
    high = np.asarray(calibration["range_max"])
    ticks = low + fraction * (high - low)
    return (ticks - calibration["center_tick"]) * 2 * np.pi / calibration["ticks_per_revolution"]


def radians_to_normalized(values, calibration):
    """Map physical joint radians into calibrated LeRobot motor units."""
    values = np.asarray(values, dtype=float)
    ticks = values * calibration["ticks_per_revolution"] / (2 * np.pi)
    ticks += calibration["center_tick"]
    low = np.asarray(calibration["range_min"])
    high = np.asarray(calibration["range_max"])
    fraction = (ticks - low) / (high - low)
    out = fraction * 200 - 100
    out[5] = fraction[5] * 100
    signs = np.asarray(calibration["drive_mode"], dtype=bool)
    out[:5] = np.where(signs[:5], -out[:5], out[:5])
    out[5] = 100 - out[5] if signs[5] else out[5]
    return out.astype(np.float32)


def camera_axes(position, target):
    """Orient a MuJoCo camera down local -Z, with local +Y up."""
    z = np.asarray(position, float) - np.asarray(target, float)
    z /= np.linalg.norm(z)
    up = np.array([0.0, 0.0, 1.0])
    if abs(z @ up) > 0.98:
        up = np.array([0.0, 1.0, 0.0])
    x = np.cross(up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return " ".join(str(v) for v in np.r_[x, y])


def text_vector(values):
    """Serialize a numeric vector for MuJoCo XML attributes."""
    return " ".join(str(float(v)) for v in values)


def placed_success(position, velocity, lifted, released, config, support_height=None):
    """Require a previously lifted box to rest fully inside the receiver."""
    half = np.asarray(config["box_half_size"])
    margin = config["receiver_radius"] - np.linalg.norm(half[:2])
    xy_ok = np.linalg.norm(np.asarray(position)[:2] - config["receiver_center_xy"]) < margin
    support_height = config["receiver_top"] if support_height is None else support_height
    z_ok = abs(position[2] - support_height - half[2]) < 0.012
    return bool(lifted and released and xy_ok and z_ok and np.linalg.norm(velocity) < config["settle_speed"])


def build_scene(robot_assets, config):
    """Extend the pinned upstream model; no kinematic attachment or forced grasps."""
    source = Path(robot_assets) / DESCRIPTION / "mujoco/omx/omx.xml"
    root = ET.parse(source).getroot()
    root.find("compiler").set("meshdir", str(Path(robot_assets) / DESCRIPTION))
    option = root.find("option")
    option.set("timestep", str(config["timestep"]))
    option.set("integrator", "implicitfast")
    option.set("gravity", "0 0 -9.81")
    if "actuator_kp" in config:
        for position in root.findall("./default/default/position"):
            position.set("kp", str(config["actuator_kp"]))
    if "joint_frictionloss" in config:
        for joint in root.findall(".//worldbody//joint"):
            joint.set("frictionloss", str(config["joint_frictionloss"]))
    # Upstream home keyframe has seven robot qpos; scene adds free joints.
    root.remove(root.find("keyframe"))
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "global", offwidth="1280", offheight="960")
    ET.SubElement(visual, "headlight", ambient="0.45 0.45 0.45", diffuse="0.6 0.6 0.6")
    appearance = config.get("appearance")
    if appearance:
        headlight = visual.find("headlight")
        headlight.set("ambient", "0.65 0.65 0.65")
        headlight.set("diffuse", "0.25 0.25 0.25")
        for marker in root.findall(".//body[@name='end_effector_link']/geom"):
            marker.set("rgba", "0 0 0 0")
        asset = root.find("asset")
        if asset is None:
            asset = ET.SubElement(root, "asset")
        for name in ["lid_two", "lid_one", "carpet", "wood"]:
            path = PACKAGE / "config/textures" / f"{name}.png"
            ET.SubElement(asset, "texture", name=name, type="2d", file=str(path))
            ET.SubElement(
                asset,
                "material",
                name=name,
                texture=name,
                texrepeat="1 1",
                texuniform="false",
                specular="0.05",
                shininess="0.1",
            )
        asset.find("material[@name='carpet']").set("texrepeat", "8 8")
        asset.find("material[@name='carpet']").set("texuniform", "true")
    world = root.find("worldbody")
    ET.SubElement(
        world, "light", pos="0.2 0 1.2", dir="0 0 -1", diffuse="0.1 0.1 0.1" if appearance else "0.8 0.8 0.8"
    )
    ET.SubElement(
        world,
        "geom",
        name="floor",
        type="plane",
        size="2 2 0.02",
        pos="0 0 -0.025",
        rgba="0.24 0.25 0.24 1",
        friction="1 0.005 0.0001",
    )
    if appearance:
        floor = world.find("geom[@name='floor']")
        floor.set("material", "carpet")
        floor.set("rgba", "1 1 1 1")
    ET.SubElement(
        world,
        "geom",
        name="base_board",
        type="box",
        size="0.13 0.14 0.01",
        pos="0.015 0 -0.01",
        rgba="0.62 0.42 0.23 1",
    )
    if appearance:
        board = world.find("geom[@name='base_board']")
        board.set("material", "wood")
        board.set("rgba", "1 1 1 1")
    top = config["table_top"]
    ET.SubElement(
        world,
        "geom",
        name="source_table",
        type="box",
        pos=text_vector([*config["table_center_xy"], top / 2]),
        size=text_vector([*config["table_half_xy"], top / 2]),
        rgba="0.93 0.92 0.88 1",
        friction="1 0.005 0.0001",
    )
    receiver = ET.SubElement(
        world, "body", name="receiver", pos=text_vector([*config["receiver_center_xy"], 0])
    )
    ET.SubElement(
        receiver,
        "geom",
        name="receiver_base",
        type="cylinder",
        pos=f"0 0 {config['receiver_top'] / 2}",
        size=f"{config['receiver_radius']} {config['receiver_top'] / 2}",
        rgba="0.95 0.96 0.96 1",
        friction="1.3 0.005 0.0001",
    )
    half = np.asarray(config["box_half_size"])
    for i in range(config["box_count"]):
        body = ET.SubElement(
            world,
            "body",
            name=f"box_{i}",
            pos=text_vector([*config["box_center_xy"], top + half[2] * (2 * i + 1) + 0.001]),
        )
        ET.SubElement(body, "freejoint", name=f"box_{i}_free")
        collision = ET.SubElement(
            body,
            "geom",
            name=f"box_{i}_geom",
            type="box",
            size=text_vector(half),
            mass=str(config["box_mass"]),
            rgba="0.78 0.27 0.22 1",
            condim="4",
            friction=f"{config['friction']} 0.005 0.0001",
            solref="0.008 1",
        )
        if appearance:
            collision.set("rgba", "0.58 0.21 0.15 1")
            split_collision = appearance.get("lid_collision_split", True)
            if split_collision:
                collision.set("size", text_vector([half[0], half[1], half[2] * 0.65]))
                collision.set("pos", f"0 0 {-half[2] * 0.35}")
                collision.set("mass", str(config["box_mass"] * 0.65))
            ET.SubElement(
                body,
                "geom",
                name=f"box_{i}_cap_collision",
                type="box",
                size=text_vector([half[0] + 0.001, half[1] + 0.001, half[2] * 0.35]),
                pos=f"0 0 {half[2] * 0.65}",
                mass=str(config["box_mass"] * 0.35 if split_collision else 0),
                rgba="0.89 0.87 0.81 1",
                friction=f"{config['friction']} 0.005 0.0001",
                condim="4",
                solref="0.008 1",
                contype="1" if split_collision else "0",
                conaffinity="1" if split_collision else "0",
            )
        ET.SubElement(
            body,
            "geom",
            name=f"box_{i}_lid",
            type="box",
            size=text_vector([half[0] + 0.001, half[1] + 0.001, 0.001]),
            pos=f"0 0 {half[2] + (0.0001 if appearance else 0)}",
            rgba="0.98 0.92 0.85 1",
            contype="0",
            conaffinity="0",
            mass="0",
        )
        if appearance:
            lid = body.find(f"geom[@name='box_{i}_lid']")
            lid.set("size", text_vector([half[0] + 0.001, half[1] + 0.001, 0.0001]))
            lid.set("rgba", "1 1 1 1")
            lid.set("material", "lid_one" if config["box_count"] == 1 else "lid_two")
            continue
        # Small heart-like markings represent the observed printed lids.
        for x in [-0.014, 0.0, 0.014]:
            for y in [-0.014, 0.0, 0.014]:
                ET.SubElement(
                    body,
                    "geom",
                    type="sphere",
                    size="0.0035",
                    pos=f"{x} {y} {half[2] + 0.001}",
                    rgba="0.8 0.2 0.23 1",
                    contype="0",
                    conaffinity="0",
                    mass="0",
                )
    position, target = config["top_camera_position"], config["top_camera_target"]
    top_camera = ET.SubElement(
        world,
        "camera",
        name="top",
        pos=text_vector(position),
        xyaxes=camera_axes(position, target),
        fovy=str(config["top_camera_fovy"]),
    )
    if "top_camera_xyaxes" in config:
        top_camera.set("xyaxes", text_vector(config["top_camera_xyaxes"]))
    wrist = root.find(".//body[@name='link5']")
    position, target = config["wrist_camera_position"], config["wrist_camera_target"]
    wrist_camera = ET.SubElement(
        wrist,
        "camera",
        name="wrist",
        pos=text_vector(position),
        xyaxes=camera_axes(position, target),
        fovy=str(config["wrist_camera_fovy"]),
    )
    if "wrist_camera_xyaxes" in config:
        wrist_camera.set("xyaxes", text_vector(config["wrist_camera_xyaxes"]))
    return ET.tostring(root, encoding="unicode")


class OMXEnvironment:
    """Simulation owns only MuJoCo state and never opens a device or ROS node."""

    def __init__(self, assets, config=None, seed=0, scenario="nominal"):
        """Compile the pinned robot and the selected task perturbation."""
        import mujoco

        self.mujoco = mujoco
        self.config = copy.deepcopy(config or read_json(PACKAGE / "config/scene.json"))
        rng = np.random.default_rng(seed)
        if scenario == "object_shift":
            self.config["box_center_xy"] = (
                np.asarray(self.config["box_center_xy"]) + rng.uniform(-0.015, 0.015, 2)
            ).tolist()
        elif scenario == "low_friction":
            self.config["friction"] = 0.5
        elif scenario == "heavy_box":
            self.config["box_mass"] *= 2
        elif scenario == "camera_shift":
            self.config["top_camera_position"] = (
                np.asarray(self.config["top_camera_position"]) + [0.025, -0.02, 0.01]
            ).tolist()
        elif scenario == "single_box":
            self.config["box_count"] = 1
            self.config["initial_state"] = self.config.get(
                "single_box_initial_state", self.config["initial_state"]
            )
            self.config.update(copy.deepcopy(self.config.get("single_box_camera_override", {})))
        elif scenario != "nominal":
            raise ValueError(f"Unknown predeclared scenario: {scenario}")
        self.model = mujoco.MjModel.from_xml_string(build_scene(assets, self.config))
        self.data = mujoco.MjData(self.model)
        self.robot_joints = [
            self.model.joint(n).qposadr.item()
            for n in ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]
        ]
        self.renderers = {}
        self.reset()

    def reset(self, state=None):
        """Reset physics and clear lift, placement, and controller histories."""
        self.mujoco.mj_resetData(self.model, self.data)
        self.set_robot_state(self.config["initial_state"] if state is None else state)
        self.control_step = 0
        self.lifted = [False] * self.config["box_count"]
        self.holds = [0] * self.config["box_count"]
        self.placed = [False] * self.config["box_count"]
        self.initial_heights = [
            self.data.body(f"box_{i}").xpos[2].item() for i in range(self.config["box_count"])
        ]
        self.max_lift = 0.0
        self.contact_frames = 0
        self.force_saturation_frames = 0
        self.target_jumps = []
        self.previous_action = self.state()
        self.command_history = [self.state().astype(float).copy() for _ in range(31)]
        return self.state()

    def set_robot_state(self, state):
        """Set the recorded joint configuration for initialization or geometry checks."""
        q = normalized_to_radians(state, self.config["calibration"])
        self.data.qpos[self.robot_joints] = q
        self.data.joint("gripper_joint_2").qpos[0] = -q[5]
        self.data.ctrl[:] = q
        self.mujoco.mj_forward(self.model, self.data)

    def state(self):
        """Read six simulated motor positions in calibrated dataset units."""
        return radians_to_normalized(self.data.qpos[self.robot_joints], self.config["calibration"])

    def step(self, action):
        """Apply a delayed motor target and advance exactly one control interval."""
        action = np.asarray(action, float)
        if action.shape != (6,) or not np.isfinite(action).all():
            raise ValueError("Action must have six finite normalized motor positions")
        current = self.state()
        action = np.clip(action, [-100] * 5 + [0], [100] * 6)
        limit = self.config["max_relative_target"]
        action = current + np.clip(action - current, -limit, limit)
        self.target_jumps.append(float(np.linalg.norm(action - self.previous_action)))
        self.previous_action = action
        self.command_history.append(action.copy())
        self.command_history = self.command_history[-31:]
        identification = self.config.get("system_identification", {})
        delays = identification.get("delay_steps", [0] * 6)
        bias = np.asarray(identification.get("command_bias", [0] * 6))
        delayed = np.array([self.command_history[-1 - delay][j] for j, delay in enumerate(delays)])
        self.data.ctrl[:] = normalized_to_radians(delayed + bias, self.config["calibration"])
        # Alternating 16/17 physics steps preserves exactly 30 Hz with a 2 ms step.
        self.control_step += 1
        until = self.control_step / self.config["fps"]
        while self.data.time < until - self.config["timestep"] / 2:
            self.mujoco.mj_step(self.model, self.data)
        if not np.isfinite(self.data.qpos).all():
            raise RuntimeError("Non-finite simulation state")
        self.contact_frames += int(self.data.ncon > 0)
        forces = np.abs(self.data.actuator_force)
        limits = np.max(np.abs(self.model.actuator_forcerange), axis=1)
        self.force_saturation_frames += int(np.any(forces >= limits * 0.99))
        # Gripper opening is an actual motor angle, not a fabricated attachment flag.
        released = self.data.qpos[self.robot_joints[-1]] > 0.57
        supports = self.receiver_supports()
        for i in range(self.config["box_count"]):
            body = self.data.body(f"box_{i}")
            lift = body.xpos[2] - self.initial_heights[i]
            self.max_lift = max(self.max_lift, float(lift))
            self.lifted[i] |= lift > self.config["lift_threshold"]
            good = i in supports and placed_success(
                body.xpos,
                body.cvel[3:],
                self.lifted[i],
                released,
                self.config,
                support_height=supports.get(i),
            )
            self.holds[i] = self.holds[i] + 1 if good else 0
            self.placed[i] = self.holds[i] >= self.config["success_hold_frames"]
        return self.state()

    def receiver_supports(self):
        """Require a physical support chain to the receiver, including stacked boxes."""
        contacts = []
        supports = {}
        for contact in self.data.contact:
            if contact.dist > 0.002:
                continue
            names = [self.model.body(self.model.geom_bodyid[g]).name for g in [contact.geom1, contact.geom2]]
            boxes = [int(name.split("_")[1]) for name in names if name.startswith("box_")]
            if len(boxes) == 1 and "receiver" in names:
                supports[boxes[0]] = self.config["receiver_top"]
            elif len(boxes) == 2:
                contacts.append(boxes)
        for _ in range(self.config["box_count"]):
            for first, second in contacts:
                first_z = self.data.body(f"box_{first}").xpos[2]
                second_z = self.data.body(f"box_{second}").xpos[2]
                lower, upper = (first, second) if first_z < second_z else (second, first)
                if lower in supports and upper not in supports:
                    supports[upper] = self.data.body(f"box_{lower}").xpos[2] + self.config["box_half_size"][2]
        return supports

    def render(self, camera="top", width=128, height=96):
        """Render one virtual camera without reading any physical device."""
        key = (width, height)
        if key not in self.renderers:
            self.renderers[key] = self.mujoco.Renderer(self.model, height=height, width=width)
        renderer = self.renderers[key]
        renderer.update_scene(self.data, camera=camera)
        if self.config.get("appearance", {}).get("soft_lighting", False):
            renderer.scene.flags[self.mujoco.mjtRndFlag.mjRND_SHADOW] = False
        return renderer.render().copy()

    def metrics(self):
        """Return provisional task and actuator diagnostics for this rollout."""
        return {
            "success_any_box": bool(any(self.placed)),
            "success_all_boxes": bool(all(self.placed)),
            "placed_boxes": int(sum(self.placed)),
            "lifted_boxes": int(sum(self.lifted)),
            "max_lift_m": self.max_lift,
            "contact_frames": self.contact_frames,
            "force_saturation_fraction": self.force_saturation_frames / max(1, self.control_step),
            "mean_target_jump_normalized": float(np.mean(self.target_jumps)) if self.target_jumps else 0.0,
            "steps": self.control_step,
            "scene_validated": False,
            "real_world_success_claim_allowed": False,
        }

    def close(self):
        """Release every offscreen renderer owned by this environment."""
        for renderer in self.renderers.values():
            renderer.close()
        self.renderers.clear()
