# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Main simulation node coordinating 3 Pinky robots and 3 OMX arms in the Shoe Store arena."""

import math
from typing import Dict

from cobot_simulation.arena_model import ObstacleBox, ShoeStoreArena
from cobot_simulation.omx_agent import OmxSimAgent
from cobot_simulation.pinky_agent import PinkySimAgent
from geometry_msgs.msg import Point, PoseStamped, Quaternion, TransformStamped, Twist, Vector3
from nav_msgs.msg import Odometry
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import JointState, LaserScan
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster
from visualization_msgs.msg import Marker, MarkerArray

try:
    from cobot_interfaces.msg import ArmCommand, ArmStatus, FleetCommand, RobotStatus
    HAVE_COBOT_MSGS = True
except ImportError:
    HAVE_COBOT_MSGS = False


def yaw_to_quaternion(yaw: float) -> Quaternion:
    """Convert a planar yaw angle in radians to a geometry_msgs Quaternion."""
    return Quaternion(
        x=0.0,
        y=0.0,
        z=math.sin(yaw / 2.0),
        w=math.cos(yaw / 2.0),
    )


class ArenaSimNode(Node):
    """ROS 2 simulation node providing multi-robot physics, kinematics, and TF trees."""

    def __init__(self):
        """Initialize parameters, publishers, subscribers, Pinky fleet, and OMX arms."""
        super().__init__('arena_sim_node')

        # Declare parameters
        self.declare_parameter('rate_hz', 50.0)
        self.declare_parameter('publish_tf', True)
        self.declare_parameter('enable_lidar', True)
        self.declare_parameter('num_pinky', 3)
        self.declare_parameter('gate_clearance_m', 0.67)

        self.rate_hz = self.get_parameter('rate_hz').value
        self.dt = 1.0 / self.rate_hz
        self.publish_tf = self.get_parameter('publish_tf').value
        self.enable_lidar = self.get_parameter('enable_lidar').value
        self.num_pinky = self.get_parameter('num_pinky').value
        self.gate_clearance_m = float(self.get_parameter('gate_clearance_m').value)

        # Initialize Arena (supports dynamic gate width)
        self.arena = ShoeStoreArena(gate_clearance_m=self.gate_clearance_m)
        self.tf_broadcaster = TransformBroadcaster(self)

        # QoS profiles
        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        status_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # 1. Initialize Pinky mobile fleet
        self.pinkies: Dict[str, PinkySimAgent] = {}
        self.pinky_subs = {}
        self.pinky_goal_subs = {}
        self.pinky_odom_pubs = {}
        self.pinky_scan_pubs = {}
        self.pinky_joint_pubs = {}
        self.pinky_status_pubs = {}

        spawn_poses = {
            'pinky1': (1.41, 2.05375, -math.pi / 2.0),
            'pinky2': (1.41, 1.8575, -math.pi / 2.0),
            'pinky3': (1.41, 1.66125, -math.pi / 2.0),
        }

        for i in range(1, self.num_pinky + 1):
            ns = f'pinky{i}'
            init_pose = spawn_poses.get(ns, (1.41, 1.5, 0.0))
            agent = PinkySimAgent(robot_id=ns, initial_pose=init_pose)
            self.pinkies[ns] = agent

            # Subscribers
            self.pinky_subs[ns] = self.create_subscription(
                Twist,
                f'/{ns}/cmd_vel',
                lambda msg, robot=agent: robot.set_cmd_vel(msg.linear.x, msg.angular.z),
                10,
            )
            self.pinky_goal_subs[ns] = self.create_subscription(
                PoseStamped,
                f'/{ns}/goal_pose',
                lambda msg, robot=agent: self._handle_goal_pose(robot, msg),
                10,
            )

            # Publishers
            self.pinky_odom_pubs[ns] = self.create_publisher(Odometry, f'/{ns}/odom', 10)
            if self.enable_lidar:
                self.pinky_scan_pubs[ns] = self.create_publisher(
                    LaserScan, f'/{ns}/scan', sensor_qos
                )
            self.pinky_joint_pubs[ns] = self.create_publisher(
                JointState, f'/{ns}/joint_states', 10
            )

            if HAVE_COBOT_MSGS:
                self.pinky_status_pubs[ns] = self.create_publisher(
                    RobotStatus, f'/{ns}/robot_status', status_qos
                )
            else:
                self.pinky_status_pubs[ns] = self.create_publisher(
                    String, f'/{ns}/robot_status', status_qos
                )

        # 2. Initialize 3 OpenManipulator-X arms
        self.arms: Dict[str, OmxSimAgent] = {
            'omx_1': OmxSimAgent('omx_1', base_pos=(2.015, 2.105, 0.085), base_yaw=0.0),
            'omx_2': OmxSimAgent('omx_2', base_pos=(2.015, 1.5375, 0.085), base_yaw=0.0),
            'omx_3': OmxSimAgent('omx_3', base_pos=(0.415, 1.85, 0.085), base_yaw=math.pi),
        }
        self.arm_joint_pubs = {}
        self.arm_status_pubs = {}
        self.arm_cmd_subs = {}

        for arm_id, arm in self.arms.items():
            self.arm_joint_pubs[arm_id] = self.create_publisher(
                JointState, f'/{arm_id}/joint_states', 10
            )
            if HAVE_COBOT_MSGS:
                self.arm_status_pubs[arm_id] = self.create_publisher(
                    ArmStatus, f'/{arm_id}/arm_status', status_qos
                )
                self.arm_cmd_subs[arm_id] = self.create_subscription(
                    ArmCommand,
                    f'/{arm_id}/arm_command',
                    lambda msg, target_arm=arm: self._handle_arm_command(target_arm, msg),
                    10,
                )
            else:
                self.arm_status_pubs[arm_id] = self.create_publisher(
                    String, f'/{arm_id}/arm_status', status_qos
                )
                self.arm_cmd_subs[arm_id] = self.create_subscription(
                    String,
                    f'/{arm_id}/arm_command',
                    lambda msg, target_arm=arm: self._handle_string_arm_command(target_arm, msg),
                    10,
                )

        # 3. Fleet Command subscriber for high-level coordination
        if HAVE_COBOT_MSGS:
            self.create_subscription(
                FleetCommand, '/fms/fleet_command', self._handle_fleet_command, 10
            )
        self.create_subscription(
            String, '/fms/string_command', self._handle_string_fleet_command, 10
        )

        # 4. 3D Visual Markers for RViz2 and FMS viewers
        self.arena_marker_pub = self.create_publisher(
            MarkerArray, '/arena_markers', status_qos
        )
        self.robot_marker_pub = self.create_publisher(
            MarkerArray, '/robot_visual_markers', 10
        )
        self._arena_marker_counter = 0
        self._publish_arena_markers()

        # Main simulation timer loop
        self.sim_timer = self.create_timer(self.dt, self._sim_loop)
        self.get_logger().info(
            f'Lightweight Arena Simulation started: {len(self.pinkies)} Pinky robots, '
            f'{len(self.arms)} OMX arms @ {self.rate_hz:.1f} Hz'
        )

    def _handle_goal_pose(self, robot: PinkySimAgent, msg: PoseStamped):
        """Extract target goal coordinates from PoseStamped."""
        q = msg.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        robot.set_goal(msg.pose.position.x, msg.pose.position.y, yaw)
        deg = math.degrees(yaw)
        self.get_logger().info(
            f'[{robot.robot_id}] New goal pose: ({msg.pose.position.x:.2f}, '
            f'{msg.pose.position.y:.2f}, {deg:.1f}°)'
        )

    def _handle_fleet_command(self, msg):
        """Dispatch high-level fleet command."""
        target_id = getattr(msg, 'robot_id', None)
        if target_id in self.pinkies:
            target_wp = getattr(msg, 'target_waypoint', '')
            if target_wp in self.arena.waypoints:
                wp = self.arena.waypoints[target_wp]
                self.pinkies[target_id].set_goal(wp[0], wp[1], math.radians(wp[2]))
                self.get_logger().info(f'Dispatched {target_id} to waypoint {target_wp}')

    def _handle_string_fleet_command(self, msg: String):
        """Parse string commands like goto:pinky1,WP_LOAD_1."""
        text = msg.data.strip()
        if text.startswith('goto:'):
            parts = text[5:].split(',')
            if len(parts) == 2:
                rid, wp_name = parts[0].strip(), parts[1].strip()
                if rid in self.pinkies and wp_name in self.arena.waypoints:
                    wp = self.arena.waypoints[wp_name]
                    self.pinkies[rid].set_goal(wp[0], wp[1], math.radians(wp[2]))
                    self.get_logger().info(f'String cmd: {rid} -> {wp_name}')

    def _handle_arm_command(self, arm: OmxSimAgent, msg):
        """Handle structured ArmCommand."""
        action = getattr(msg, 'action', '')
        if 'pick' in action.lower():
            arm.trigger_pick_sequence()
        elif hasattr(msg, 'target_joint_positions') and len(msg.target_joint_positions) >= 6:
            arm.set_target_joints(np.array(msg.target_joint_positions[:6]))

    def _handle_string_arm_command(self, arm: OmxSimAgent, msg: String):
        """Handle string commands like pick or home."""
        cmd = msg.data.strip().lower()
        if cmd == 'pick':
            arm.trigger_pick_sequence()
        elif cmd == 'home':
            arm.set_target_joints(arm.PRESET_POSES['HOME'])

    def _sim_loop(self):
        """Step simulation and publish ROS 2 telemetry."""
        if not rclpy.ok():
            return
        now = self.get_clock().now().to_msg()

        # Step Pinky fleet
        for rid, robot in self.pinkies.items():
            robot.step(self.dt)
            rx, ry, ryaw = robot.get_pose()
            rv, rw = robot.get_twist()
            q = yaw_to_quaternion(ryaw)

            # 1. Publish TF: map -> {rid}/odom -> {rid}/base_footprint
            if self.publish_tf:
                t_odom = TransformStamped()
                t_odom.header.stamp = now
                t_odom.header.frame_id = 'map'
                t_odom.child_frame_id = f'{rid}/odom'
                t_odom.transform.translation.x = 0.0
                t_odom.transform.translation.y = 0.0
                t_odom.transform.translation.z = 0.0
                t_odom.transform.rotation = Quaternion(x=0.0, y=0.0, z=0.0, w=1.0)
                self.tf_broadcaster.sendTransform(t_odom)

                t_base = TransformStamped()
                t_base.header.stamp = now
                t_base.header.frame_id = f'{rid}/odom'
                t_base.child_frame_id = f'{rid}/base_footprint'
                t_base.transform.translation.x = rx
                t_base.transform.translation.y = ry
                t_base.transform.translation.z = 0.0
                t_base.transform.rotation = q
                self.tf_broadcaster.sendTransform(t_base)

            # 2. Publish Odometry
            odom_msg = Odometry()
            odom_msg.header.stamp = now
            odom_msg.header.frame_id = f'{rid}/odom'
            odom_msg.child_frame_id = f'{rid}/base_footprint'
            odom_msg.pose.pose.position = Point(x=rx, y=ry, z=0.0)
            odom_msg.pose.pose.orientation = q
            odom_msg.twist.twist.linear = Vector3(x=rv, y=0.0, z=0.0)
            odom_msg.twist.twist.angular = Vector3(x=0.0, y=0.0, z=rw)
            self.pinky_odom_pubs[rid].publish(odom_msg)

            # 3. Publish JointStates (wheels)
            js = JointState()
            js.header.stamp = now
            js.name = [f'{rid}/left_wheel_joint', f'{rid}/right_wheel_joint']
            js.position = [robot.left_wheel_pos, robot.right_wheel_pos]
            self.pinky_joint_pubs[rid].publish(js)

            # 4. Publish LaserScan (2D LiDAR)
            if self.enable_lidar:
                dynamic_obs = []
                for other_id, other_bot in self.pinkies.items():
                    if other_id != rid:
                        ox, oy, _ = other_bot.get_pose()
                        dynamic_obs.append(
                            ObstacleBox(other_id, ox - 0.07, ox + 0.07, oy - 0.07, oy + 0.07)
                        )

                scan_ranges = self.arena.raycast_scan(
                    rx, ry, ryaw, num_rays=180, min_range=0.05, max_range=3.5,
                    extra_obstacles=dynamic_obs
                )
                scan_msg = LaserScan()
                scan_msg.header.stamp = now
                scan_msg.header.frame_id = f'{rid}/rplidar_link'
                scan_msg.angle_min = -math.pi
                scan_msg.angle_max = math.pi
                scan_msg.angle_increment = (2.0 * math.pi) / 180.0
                scan_msg.time_increment = 0.0
                scan_msg.scan_time = self.dt
                scan_msg.range_min = 0.05
                scan_msg.range_max = 3.5
                scan_msg.ranges = [float(r) for r in scan_ranges]
                self.pinky_scan_pubs[rid].publish(scan_msg)

            # 5. Publish Robot Status
            if HAVE_COBOT_MSGS:
                st = RobotStatus()
                st.header.stamp = now
                st.header.frame_id = 'map'
                st.robot_id = rid
                st.state = robot.state_str
                st.localized = True
                st.motor_power_present = True
                st.battery_percentage = 98.0
                st.linear_vel = float(rv)
                st.angular_vel = float(rw)
                st.current_pose.position = Point(x=rx, y=ry, z=0.0)
                st.current_pose.orientation = q
                self.pinky_status_pubs[rid].publish(st)
            else:
                s_msg = String()
                deg = math.degrees(ryaw)
                s_msg.data = f'{rid}:{robot.state_str}:pose=({rx:.2f},{ry:.2f},{deg:.1f})'
                self.pinky_status_pubs[rid].publish(s_msg)

        # Step OMX arms
        for arm_id, arm in self.arms.items():
            arm.step(self.dt)
            joint_dict = arm.get_joint_states()

            # Publish JointStates
            js = JointState()
            js.header.stamp = now
            js.name = list(joint_dict.keys())
            js.position = list(joint_dict.values())
            self.arm_joint_pubs[arm_id].publish(js)

            # Publish TF: map -> {arm_id}/base_link
            if self.publish_tf:
                t_arm = TransformStamped()
                t_arm.header.stamp = now
                t_arm.header.frame_id = 'map'
                t_arm.child_frame_id = f'{arm_id}/base_link'
                t_arm.transform.translation.x = arm.base_pos[0]
                t_arm.transform.translation.y = arm.base_pos[1]
                t_arm.transform.translation.z = arm.base_pos[2]
                t_arm.transform.rotation = yaw_to_quaternion(arm.base_yaw)
                self.tf_broadcaster.sendTransform(t_arm)

            # Publish Arm Status
            if HAVE_COBOT_MSGS:
                ast = ArmStatus()
                ast.header.stamp = now
                ast.arm_id = arm_id
                ast.joint_unit = 'RAD'
                ast.joint_names = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5']
                ast.joint_positions = [float(x) for x in arm.q[:5]]
                ast.gripper_position = float(arm.q[5])
                ast.torque_enabled = True
                ast.power_present = True
                ast.retract_safe = True
                ast.work_step = arm.state_str
                self.arm_status_pubs[arm_id].publish(ast)
            else:
                s_arm = String()
                s_arm.data = f'{arm_id}:{arm.state_str}:busy={arm.is_busy}:cargo={arm.has_cargo}'
                self.arm_status_pubs[arm_id].publish(s_arm)

        # 3. Publish 3D visual markers for RViz2
        self._publish_robot_markers(now)
        self._arena_marker_counter += 1
        if self._arena_marker_counter >= int(self.rate_hz):
            self._arena_marker_counter = 0
            self._publish_arena_markers()

    def _publish_arena_markers(self):
        """Publish persistent 3D markers for arena walls, racks, gate and waypoints."""
        arr = MarkerArray()
        now = self.get_clock().now().to_msg()

        # 1. Arena Outer Walls & Furniture
        walls = [
            ('border_south', 1.25, -0.025, 0.075, 2.55, 0.05, 0.15, 0.55, 0.58, 0.65),
            ('border_north', 1.25, 2.425, 0.075, 2.55, 0.05, 0.15, 0.55, 0.58, 0.65),
            ('border_west', -0.025, 1.20, 0.075, 0.05, 2.45, 0.15, 0.55, 0.58, 0.65),
            ('border_east', 2.525, 1.20, 0.075, 0.05, 2.45, 0.15, 0.55, 0.58, 0.65),
            ('central_partition_wall', 1.25, (self.gate_clearance_m + 2.40) / 2.0, 0.075, 0.10, (2.40 - self.gate_clearance_m), 0.15, 0.65, 0.68, 0.72),
            ('wh_top_rack', (1.42 + 2.40) / 2.0, (2.14 + 2.40) / 2.0, 0.10, (2.40 - 1.42), (2.40 - 2.14), 0.20, 0.72, 0.52, 0.24),
            ('wh_right_rack', (2.16 + 2.40) / 2.0, (0.67 + 2.40) / 2.0, 0.10, (2.40 - 2.16), (2.40 - 0.67), 0.20, 0.72, 0.52, 0.24),
            ('store_counter', (0.14 + 1.04) / 2.0, (2.14 + 2.34) / 2.0, 0.10, (1.04 - 0.14), (2.34 - 2.14), 0.20, 0.25, 0.48, 0.62),
            ('store_display_a', (0.44 + 0.82) / 2.0, (1.29 + 1.45) / 2.0, 0.075, (0.82 - 0.44), (1.45 - 1.29), 0.15, 0.30, 0.50, 0.60),
            ('store_bench_b', (0.34 + 0.79) / 2.0, (0.74 + 0.92) / 2.0, 0.075, (0.79 - 0.34), (0.92 - 0.74), 0.15, 0.30, 0.50, 0.60),
            ('store_rack_1', (0.04 + 0.36) / 2.0, (1.64 + 2.09) / 2.0, 0.075, (0.36 - 0.04), (2.09 - 1.64), 0.15, 0.30, 0.50, 0.60),
            ('store_rack_2', (0.82 + 1.14) / 2.0, (1.64 + 2.09) / 2.0, 0.075, (1.14 - 0.82), (2.09 - 1.64), 0.15, 0.30, 0.50, 0.60),
        ]

        for i, (name, x, y, z, sx, sy, sz, cr, cg, cb) in enumerate(walls):
            m = Marker()
            m.header.frame_id = 'map'
            m.header.stamp = now
            m.ns = 'arena_layout'
            m.id = i
            m.type = Marker.CUBE
            m.action = Marker.ADD
            m.pose.position.x = float(x)
            m.pose.position.y = float(y)
            m.pose.position.z = float(z)
            m.scale.x = float(sx)
            m.scale.y = float(sy)
            m.scale.z = float(sz)
            m.color.r = float(cr)
            m.color.g = float(cg)
            m.color.b = float(cb)
            m.color.a = 0.85
            arr.markers.append(m)

        # 2. 67cm Transfer Gate Floor Visualizer (Green Stripe & Text)
        m_gate = Marker()
        m_gate.header.frame_id = 'map'
        m_gate.header.stamp = now
        m_gate.ns = 'arena_gate'
        m_gate.id = 50
        m_gate.type = Marker.CUBE
        m_gate.action = Marker.ADD
        m_gate.pose.position.x = 1.25
        m_gate.pose.position.y = self.gate_clearance_m / 2.0
        m_gate.pose.position.z = 0.002
        m_gate.scale.x = 0.10
        m_gate.scale.y = self.gate_clearance_m
        m_gate.scale.z = 0.004
        m_gate.color.r = 0.2
        m_gate.color.g = 0.85
        m_gate.color.b = 0.4
        m_gate.color.a = 0.6
        arr.markers.append(m_gate)

        m_gt = Marker()
        m_gt.header.frame_id = 'map'
        m_gt.header.stamp = now
        m_gt.ns = 'arena_gate'
        m_gt.id = 51
        m_gt.type = Marker.TEXT_VIEW_FACING
        m_gt.action = Marker.ADD
        m_gt.pose.position.x = 1.25
        m_gt.pose.position.y = self.gate_clearance_m / 2.0
        m_gt.pose.position.z = 0.25
        m_gt.scale.z = 0.10
        m_gt.color.r = 0.2
        m_gt.color.g = 1.0
        m_gt.color.b = 0.3
        m_gt.color.a = 1.0
        m_gt.text = f'{int(self.gate_clearance_m * 100)}cm GATE'
        arr.markers.append(m_gt)

        # 3. Waypoint Markers & Labels
        wp_id = 100
        for wp_name, wp_coord in self.arena.waypoints.items():
            wx, wy, _ = wp_coord
            mw = Marker()
            mw.header.frame_id = 'map'
            mw.header.stamp = now
            mw.ns = 'waypoints'
            mw.id = wp_id
            mw.type = Marker.SPHERE
            mw.action = Marker.ADD
            mw.pose.position.x = float(wx)
            mw.pose.position.y = float(wy)
            mw.pose.position.z = 0.02
            mw.scale.x = 0.08
            mw.scale.y = 0.08
            mw.scale.z = 0.04
            if 'ZA' in wp_name:
                mw.color.r, mw.color.g, mw.color.b = 1.0, 0.4, 0.1
            elif 'ZB' in wp_name:
                mw.color.r, mw.color.g, mw.color.b = 0.1, 0.8, 0.4
            elif 'ZC' in wp_name:
                mw.color.r, mw.color.g, mw.color.b = 0.2, 0.6, 1.0
            else:
                mw.color.r, mw.color.g, mw.color.b = 0.8, 0.8, 0.8
            mw.color.a = 0.8
            arr.markers.append(mw)

            ml = Marker()
            ml.header.frame_id = 'map'
            ml.header.stamp = now
            ml.ns = 'waypoint_labels'
            ml.id = wp_id + 500
            ml.type = Marker.TEXT_VIEW_FACING
            ml.action = Marker.ADD
            ml.pose.position.x = float(wx)
            ml.pose.position.y = float(wy)
            ml.pose.position.z = 0.10
            ml.scale.z = 0.06
            ml.color.r, ml.color.g, ml.color.b, ml.color.a = 1.0, 1.0, 1.0, 0.9
            ml.text = wp_name
            arr.markers.append(ml)
            wp_id += 1

        self.arena_marker_pub.publish(arr)

    def _publish_robot_markers(self, now):
        """Publish real-time 3D markers for 3 Pinky robots and 3 OMX arms."""
        arr = MarkerArray()
        colors = {
            'pinky1': (0.95, 0.55, 0.15),  # Orange
            'pinky2': (0.25, 0.75, 0.35),  # Green
            'pinky3': (0.35, 0.55, 0.95),  # Blue
        }

        # 1. Pinky Fleet 3D Cylinders, Lidar and Heading
        for idx, (rid, robot) in enumerate(self.pinkies.items()):
            rx, ry, ryaw = robot.get_pose()
            cr, cg, cb = colors.get(rid, (0.7, 0.7, 0.7))

            # Chassis Cylinder
            mc = Marker()
            mc.header.frame_id = 'map'
            mc.header.stamp = now
            mc.ns = 'pinky_bodies'
            mc.id = idx * 10
            mc.type = Marker.CYLINDER
            mc.action = Marker.ADD
            mc.pose.position.x = rx
            mc.pose.position.y = ry
            mc.pose.position.z = 0.025
            mc.scale.x = 0.14
            mc.scale.y = 0.14
            mc.scale.z = 0.05
            mc.color.r, mc.color.g, mc.color.b, mc.color.a = cr, cg, cb, 0.95
            arr.markers.append(mc)

            # Lidar Cylinder
            ml = Marker()
            ml.header.frame_id = 'map'
            ml.header.stamp = now
            ml.ns = 'pinky_lidars'
            ml.id = idx * 10 + 1
            ml.type = Marker.CYLINDER
            ml.action = Marker.ADD
            ml.pose.position.x = rx
            ml.pose.position.y = ry
            ml.pose.position.z = 0.06
            ml.scale.x = 0.05
            ml.scale.y = 0.05
            ml.scale.z = 0.025
            ml.color.r, ml.color.g, ml.color.b, ml.color.a = 0.1, 0.1, 0.1, 1.0
            arr.markers.append(ml)

            # Heading Indicator Arrow
            ma = Marker()
            ma.header.frame_id = 'map'
            ma.header.stamp = now
            ma.ns = 'pinky_headings'
            ma.id = idx * 10 + 2
            ma.type = Marker.ARROW
            ma.action = Marker.ADD
            ma.pose.position.x = rx
            ma.pose.position.y = ry
            ma.pose.position.z = 0.03
            ma.pose.orientation = yaw_to_quaternion(ryaw)
            ma.scale.x = 0.12
            ma.scale.y = 0.025
            ma.scale.z = 0.025
            ma.color.r, ma.color.g, ma.color.b, ma.color.a = 1.0, 1.0, 1.0, 1.0
            arr.markers.append(ma)

            # Text Label
            mt = Marker()
            mt.header.frame_id = 'map'
            mt.header.stamp = now
            mt.ns = 'pinky_labels'
            mt.id = idx * 10 + 3
            mt.type = Marker.TEXT_VIEW_FACING
            mt.action = Marker.ADD
            mt.pose.position.x = rx
            mt.pose.position.y = ry
            mt.pose.position.z = 0.14
            mt.scale.z = 0.07
            mt.color.r, mt.color.g, mt.color.b, mt.color.a = cr, cg, cb, 1.0
            mt.text = rid.upper()
            arr.markers.append(mt)

        # 2. OMX Arms 3D Base and Articulated Stands
        for idx, (aid, arm) in enumerate(self.arms.items()):
            bx, by, bz = arm.base_pos

            # Stand box
            ms = Marker()
            ms.header.frame_id = 'map'
            ms.header.stamp = now
            ms.ns = 'omx_stands'
            ms.id = idx * 10
            ms.type = Marker.CUBE
            ms.action = Marker.ADD
            ms.pose.position.x = bx
            ms.pose.position.y = by
            ms.pose.position.z = bz / 2.0
            ms.scale.x = 0.12
            ms.scale.y = 0.08
            ms.scale.z = bz
            ms.color.r, ms.color.g, ms.color.b, ms.color.a = 0.5, 0.55, 0.6, 1.0
            arr.markers.append(ms)

            # Arm Base Cylinder
            mb = Marker()
            mb.header.frame_id = 'map'
            mb.header.stamp = now
            mb.ns = 'omx_bases'
            mb.id = idx * 10 + 1
            mb.type = Marker.CYLINDER
            mb.action = Marker.ADD
            mb.pose.position.x = bx
            mb.pose.position.y = by
            mb.pose.position.z = bz + 0.02
            mb.scale.x = 0.08
            mb.scale.y = 0.08
            mb.scale.z = 0.04
            mb.color.r, mb.color.g, mb.color.b, mb.color.a = 0.2, 0.2, 0.2, 1.0
            arr.markers.append(mb)

            # Arm Link Column
            mlk = Marker()
            mlk.header.frame_id = 'map'
            mlk.header.stamp = now
            mlk.ns = 'omx_links'
            mlk.id = idx * 10 + 2
            mlk.type = Marker.CYLINDER
            mlk.action = Marker.ADD
            mlk.pose.position.x = bx
            mlk.pose.position.y = by
            mlk.pose.position.z = bz + 0.12
            mlk.scale.x = 0.035
            mlk.scale.y = 0.035
            mlk.scale.z = 0.16
            mlk.color.r, mlk.color.g, mlk.color.b, mlk.color.a = 0.7, 0.7, 0.75, 1.0
            arr.markers.append(mlk)

            # Text Label
            mat = Marker()
            mat.header.frame_id = 'map'
            mat.header.stamp = now
            mat.ns = 'omx_labels'
            mat.id = idx * 10 + 3
            mat.type = Marker.TEXT_VIEW_FACING
            mat.action = Marker.ADD
            mat.pose.position.x = bx
            mat.pose.position.y = by
            mat.pose.position.z = bz + 0.26
            mat.scale.z = 0.07
            mat.color.r, mat.color.g, mat.color.b, mat.color.a = 0.3, 0.8, 1.0, 1.0
            mat.text = aid.upper()
            arr.markers.append(mat)

        self.robot_marker_pub.publish(arr)


def main(args=None):
    """Entry point for the arena_sim_node."""
    rclpy.init(args=args)
    node = ArenaSimNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as e:
        if rclpy.ok():
            node.get_logger().error(f'Simulation error: {e}')
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
