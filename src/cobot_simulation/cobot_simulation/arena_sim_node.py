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

        self.rate_hz = self.get_parameter('rate_hz').value
        self.dt = 1.0 / self.rate_hz
        self.publish_tf = self.get_parameter('publish_tf').value
        self.enable_lidar = self.get_parameter('enable_lidar').value
        self.num_pinky = self.get_parameter('num_pinky').value

        # Initialize Arena
        self.arena = ShoeStoreArena()
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
