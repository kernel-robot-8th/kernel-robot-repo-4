#!/usr/bin/env python3
"""
Lecture 27: ROS2 Gazebo Teleop Keyboard Controller (Fixed Motion Holding)
Features:
- Teleop Twist command publisher on /cmd_vel
- 'z' key safety speed damping (reduces max speed limit by 10% step)
- Keeps motion active until 'k' or 'space' (emergency stop) is pressed
"""

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import sys
import termios
import tty
import select

msg = """
=====================================================
Lecture 27: Pinky Pro Gazebo Teleop Control
-----------------------------------------------------
Moving around:
        i / w : Forward
  j / a       l / d : Turn Left / Right
        , / s : Backward

  k / space   : Emergency Stop
  z           : Speed Damping (Reduce Max Speed 10%)
  x / c       : Increase / Reset Max Speed

CTRL-C to quit
=====================================================
"""

moveBindings = {
    'i': (1.0, 0.0, 0.0, 0.0),
    'w': (1.0, 0.0, 0.0, 0.0),
    ',': (-1.0, 0.0, 0.0, 0.0),
    's': (-1.0, 0.0, 0.0, 0.0),
    'j': (0.0, 0.0, 0.0, 1.0),
    'a': (0.0, 0.0, 0.0, 1.0),
    'l': (0.0, 0.0, 0.0, -1.0),
    'd': (0.0, 0.0, 0.0, -1.0),
}

def getKey(settings):
    tty.setraw(sys.stdin.fileno())
    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
    if rlist:
        key = sys.stdin.read(1)
    else:
        key = ''
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
    return key

def main(args=None):
    settings = termios.tcgetattr(sys.stdin)
    rclpy.init(args=args)
    node = rclpy.create_node('pinky_gz_teleop_keyboard')
    pub = node.create_publisher(Twist, 'cmd_vel', 10)

    speed = 0.3
    turn = 0.8
    speed_scale = 1.0

    x = 0.0
    y = 0.0
    z = 0.0
    th = 0.0

    try:
        print(msg)
        print(f"Current Base Speed: {speed * speed_scale:.2f} m/s, Turn: {turn * speed_scale:.2f} rad/s\n")
        while rclpy.ok():
            key = getKey(settings)

            if key in moveBindings.keys():
                x = moveBindings[key][0]
                y = moveBindings[key][1]
                z = moveBindings[key][2]
                th = moveBindings[key][3]
                print(f"[MOVING] Linear: {x * speed * speed_scale:5.2f} m/s | Angular: {th * turn * speed_scale:5.2f} rad/s")
            elif key == 'z':
                speed_scale = max(0.1, speed_scale * 0.9)
                print(f"[Safety Damping] Max Speed Scale: {speed_scale*100:.0f}% -> Target Speed: {speed * speed_scale:.2f} m/s")
            elif key == 'x':
                speed_scale = min(3.0, speed_scale * 1.1)
                print(f"[Speed Boost] Max Speed Scale: {speed_scale*100:.0f}% -> Target Speed: {speed * speed_scale:.2f} m/s")
            elif key == 'c':
                speed_scale = 1.0
                print(f"[Speed Reset] Max Speed Scale: 100% -> Target Speed: {speed * speed_scale:.2f} m/s")
            elif key in ['k', ' ']:
                x = 0.0; y = 0.0; z = 0.0; th = 0.0
                print("[EMERGENCY STOP] Robot Stopped.")
            elif key == '\x03': # CTRL-C
                break
            else:
                # Keep current motion state active!
                pass

            twist = Twist()
            twist.linear.x = float(x * speed * speed_scale)
            twist.linear.y = float(y * speed * speed_scale)
            twist.linear.z = float(z * speed * speed_scale)
            twist.angular.x = 0.0
            twist.angular.y = 0.0
            twist.angular.z = float(th * turn * speed_scale)
            pub.publish(twist)

    except Exception as e:
        print(e)

    finally:
        twist = Twist()
        pub.publish(twist)
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
