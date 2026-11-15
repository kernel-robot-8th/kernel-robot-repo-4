#!/usr/bin/env python3
"""
Lecture 27: ROS2 Gazebo Simulation Telemetry Monitor
Subscribes to Gazebo-bridged sensor topics (/odom, /scan, /imu_raw, /camera/image_raw)
and reports live physical simulation states in real-time.
"""

import rclpy
from rclpy.node import Node
import math
import time

from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan, Imu, Image

class GazeboTelemetryMonitor(Node):
    def __init__(self):
        super().__init__('pinky_gz_telemetry_monitor')

        self.odom_sub = self.create_subscription(Odometry, 'odom', self.odom_callback, 10)
        self.scan_sub = self.create_subscription(LaserScan, 'scan', self.scan_callback, 10)
        self.imu_sub = self.create_subscription(Imu, 'imu_raw', self.imu_callback, 10)
        self.cam_sub = self.create_subscription(Image, 'camera/image_raw', self.cam_callback, 10)

        # State storage
        self.pos_x = 0.0
        self.pos_y = 0.0
        self.yaw = 0.0
        self.linear_speed = 0.0
        self.angular_speed = 0.0

        self.min_range = 0.0
        self.scan_count = 0

        self.accel_z = 0.0
        self.gyro_z = 0.0

        self.cam_fps_count = 0
        self.cam_res = "N/A"
        self.last_cam_time = time.time()
        self.fps = 0.0

        # Periodic timer for status dashboard (1 Hz)
        self.timer = self.create_timer(1.0, self.display_dashboard)
        self.get_logger().info("=== Lecture 27: Gazebo Telemetry Monitor Started ===")

    def odom_callback(self, msg: Odometry):
        self.pos_x = msg.pose.pose.position.x
        self.pos_y = msg.pose.pose.position.y

        # Quaternion to Yaw
        q = msg.pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self.yaw = math.atan2(siny_cosp, cosy_cosp) * (180.0 / math.pi)

        self.linear_speed = msg.twist.twist.linear.x
        self.angular_speed = msg.twist.twist.angular.z

    def scan_callback(self, msg: LaserScan):
        valid_ranges = [r for r in msg.ranges if not math.isnan(r) and not math.isinf(r) and r > msg.range_min]
        self.scan_count = len(valid_ranges)
        self.min_range = min(valid_ranges) if valid_ranges else 0.0

    def imu_callback(self, msg: Imu):
        self.accel_z = msg.linear_acceleration.z
        self.gyro_z = msg.angular_velocity.z

    def cam_callback(self, msg: Image):
        self.cam_fps_count += 1
        self.cam_res = f"{msg.width}x{msg.height}"
        now = time.time()
        dt = now - self.last_cam_time
        if dt >= 1.0:
            self.fps = self.cam_fps_count / dt
            self.cam_fps_count = 0
            self.last_cam_time = now

    def display_dashboard(self):
        self.get_logger().info(
            f"\n[GZ TELEMETRY] Pose: ({self.pos_x:6.2f}m, {self.pos_y:6.2f}m, {self.yaw:5.1f}deg) | "
            f"Vel: ({self.linear_speed:4.2f}m/s, {self.angular_speed:4.2f}rad/s)\n"
            f"               LiDAR: Min Dist={self.min_range:4.2f}m ({self.scan_count} rays) | "
            f"IMU: AccZ={self.accel_z:5.2f}m/s² | Cam: {self.cam_res} ({self.fps:4.1f} FPS)"
        )

def main(args=None):
    rclpy.init(args=args)
    node = GazeboTelemetryMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
