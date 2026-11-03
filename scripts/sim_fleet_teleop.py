#!/usr/bin/env python3
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

"""
sim_fleet_teleop.py: 대화형 번호 입력 기반 핑키 로봇 주행 제어기 및 3D RViz2 실시간 연동기.
- 시뮬레이터 미실행 시 내장 엔진(Embedded ArenaSimNode) 자동 기동 (100% 자가 복구)
- 사전 세팅된 RViz2 3D 뷰어 자동 실행
- 번호(1~9) 입력 시 실시간 주행 명령 주입 및 RViz 화면 / 터미널 실시간 이동 궤적 확인
"""

import os
import sys
import time
import math
import glob
import threading
import subprocess

# 1. 워크스페이스 패스 우선 등록
WORKSPACE_DIR = os.path.expanduser('~/kernel-robot-repo-4')
WORKSPACE_INSTALL = os.path.join(WORKSPACE_DIR, 'install', 'setup.bash')
ROS_SETUP = '/opt/ros/jazzy/setup.bash'

EXTRA_PATHS = [
    os.path.join(WORKSPACE_DIR, 'src', 'cobot_simulation'),
    os.path.join(WORKSPACE_DIR, 'install', 'cobot_simulation', 'lib', 'python3.12', 'site-packages'),
    os.path.join(WORKSPACE_DIR, 'install', 'cobot_interfaces', 'lib', 'python3.12', 'site-packages'),
    os.path.join(WORKSPACE_DIR, 'install', 'pinky_fleet_sim', 'lib', 'python3.12', 'site-packages'),
]
for p in EXTRA_PATHS:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

# 2. ROS 2 및 워크스페이스 환경 자동 로드 (Re-exec)
needs_reexec = False
if not os.environ.get('_SIM_TELEOP_REEXEC'):
    try:
        import rclpy
    except ImportError:
        needs_reexec = True
    if 'cobot_interfaces' not in os.environ.get('AMENT_PREFIX_PATH', ''):
        needs_reexec = True
    try:
        import cobot_simulation
    except ImportError:
        needs_reexec = True

if needs_reexec:
    script_path = os.path.abspath(__file__)
    args = ' '.join(f'"{a}"' for a in sys.argv[1:])
    cmd = (
        f'export _SIM_TELEOP_REEXEC=1 && '
        f'if [ -f "{ROS_SETUP}" ]; then source "{ROS_SETUP}"; fi && '
        f'if [ -f "{WORKSPACE_INSTALL}" ]; then source "{WORKSPACE_INSTALL}"; fi && '
        f'exec python3 "{script_path}" {args}'
    )
    sys.exit(subprocess.call(['bash', '-c', cmd]))

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, PoseStamped, Point, Quaternion
from nav_msgs.msg import Odometry

# 2. 실행 중인 외부 시뮬레이터 및 맵 서버 감지
def check_external_sim():
    for pid_dir in glob.glob('/proc/[0-9]*'):
        try:
            with open(f'{pid_dir}/cmdline', 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='ignore')
            if 'arena_sim_node' in cmdline and str(os.getpid()) not in pid_dir:
                return True
        except Exception:
            continue
    return False

def check_map_server():
    for pid_dir in glob.glob('/proc/[0-9]*'):
        try:
            with open(f'{pid_dir}/cmdline', 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='ignore')
            if 'map_server' in cmdline and 'nav2' in cmdline:
                return True
        except Exception:
            continue
    return False

def launch_map_server():
    if check_map_server():
        print('[*] 외부 맵 서버(map_server)가 이미 동작 중입니다.')
        return None, None
    map_yaml = os.path.expanduser(
        '~/kernel-robot-repo-4/src/cobot_bringup/config/maps/map_shoe_store_1021_gate67.yaml'
    )
    if not os.path.exists(map_yaml):
        print(f'[!] 정본 맵 파일을 찾을 수 없습니다: {map_yaml}')
        return None, None
    print(f'[*] 공식 정본 맵 서버(nav2_map_server)를 가동합니다... ({os.path.basename(map_yaml)})')
    p_map = subprocess.Popen([
        'ros2', 'run', 'nav2_map_server', 'map_server',
        '--ros-args', '-p', f'yaml_filename:={map_yaml}',
        '-p', 'topic_name:=map', '-p', 'frame_id:=map'
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    p_life = subprocess.Popen([
        'ros2', 'run', 'nav2_lifecycle_manager', 'lifecycle_manager',
        '--ros-args', '-p', 'autostart:=true', '-p', 'node_names:=[\'map_server\']'
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    return p_map, p_life

RVIZ_CONFIG = os.path.expanduser('~/.rviz2/default.rviz')

class TeleopController(Node):
    def __init__(self, embedded_sim=None):
        super().__init__('sim_teleop_controller')
        self.embedded_sim = embedded_sim
        self.cmd_pubs = {
            'pinky1': self.create_publisher(Twist, '/pinky1/cmd_vel', 10),
            'pinky2': self.create_publisher(Twist, '/pinky2/cmd_vel', 10),
            'pinky3': self.create_publisher(Twist, '/pinky3/cmd_vel', 10),
        }
        self.goal_pubs = {
            'pinky1': self.create_publisher(PoseStamped, '/pinky1/goal_pose', 10),
            'pinky2': self.create_publisher(PoseStamped, '/pinky2/goal_pose', 10),
            'pinky3': self.create_publisher(PoseStamped, '/pinky3/goal_pose', 10),
        }
        self.poses = {}
        for ns in ['pinky1', 'pinky2', 'pinky3']:
            self.create_subscription(Odometry, f'/{ns}/odom', lambda m, r=ns: self._on_odom(r, m), 10)

    def _on_odom(self, r_id, msg):
        pos = msg.pose.pose.position
        q = msg.pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        self.poses[r_id] = (pos.x, pos.y, yaw)

    def get_pose(self, r_id):
        if self.embedded_sim and r_id in self.embedded_sim.pinkies:
            return self.embedded_sim.pinkies[r_id].get_pose()
        return self.poses.get(r_id, (0.0, 0.0, 0.0))

    def move_distance(self, r_id, dist_m, speed=0.15):
        """지정된 거리만큼 전진/후진 (시간 적분 주입 및 실시간 위치 출력)"""
        tw = Twist()
        tw.linear.x = speed if dist_m > 0 else -speed
        duration = abs(dist_m) / speed
        end_time = time.time() + duration
        
        while time.time() < end_time:
            self.cmd_pubs[r_id].publish(tw)
            if self.embedded_sim:
                self.embedded_sim.pinkies[r_id].set_cmd_vel(tw.linear.x, 0.0)
            p = self.get_pose(r_id)
            print(f'   [주행 중] X={p[0]:6.3f}m, Y={p[1]:6.3f}m', end='\r')
            time.sleep(0.05)
        
        # 정지 명령
        stop_tw = Twist()
        self.cmd_pubs[r_id].publish(stop_tw)
        if self.embedded_sim:
            self.embedded_sim.pinkies[r_id].set_cmd_vel(0.0, 0.0)
        time.sleep(0.1)
        p = self.get_pose(r_id)
        print(f'   [도착 완료] X={p[0]:6.3f}m, Y={p[1]:6.3f}m                        ')

    def rotate_angle(self, r_id, angle_deg, speed=0.785):
        """지정된 각도(도)만큼 좌/우 회전"""
        tw = Twist()
        rad = math.radians(angle_deg)
        tw.angular.z = speed if rad > 0 else -speed
        duration = abs(rad) / speed
        end_time = time.time() + duration

        while time.time() < end_time:
            self.cmd_pubs[r_id].publish(tw)
            if self.embedded_sim:
                self.embedded_sim.pinkies[r_id].set_cmd_vel(0.0, tw.angular.z)
            p = self.get_pose(r_id)
            print(f'   [회전 중] Yaw={math.degrees(p[2]):6.1f}°', end='\r')
            time.sleep(0.05)

        stop_tw = Twist()
        self.cmd_pubs[r_id].publish(stop_tw)
        if self.embedded_sim:
            self.embedded_sim.pinkies[r_id].set_cmd_vel(0.0, 0.0)
        time.sleep(0.1)
        p = self.get_pose(r_id)
        print(f'   [회전 완료] Yaw={math.degrees(p[2]):6.1f}°                        ')

    def send_goal_and_track(self, r_id, x, y, yaw, timeout_sec=8.0):
        """목표 웨이포인트로 자율주행 명령 전달 및 도달 모니터링"""
        goal = PoseStamped()
        goal.header.frame_id = 'map'
        goal.header.stamp = self.get_clock().now().to_msg()
        goal.pose.position = Point(x=float(x), y=float(y), z=0.0)
        goal.pose.orientation = Quaternion(
            x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0)
        )
        self.goal_pubs[r_id].publish(goal)
        if self.embedded_sim:
            self.embedded_sim.pinkies[r_id].set_goal(x, y, yaw)

        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            p = self.get_pose(r_id)
            dist_to_goal = math.hypot(p[0] - x, p[1] - y)
            print(f'   [자율주행 중] 현재: ({p[0]:5.3f}, {p[1]:5.3f}) -> 잔여거리: {dist_to_goal:4.2f}m', end='\r')
            if dist_to_goal < 0.08:
                break
            time.sleep(0.1)

        p = self.get_pose(r_id)
        print(f'   [목표 도달 완료] 최종 위치: X={p[0]:5.3f}m, Y={p[1]:5.3f}m                       ')

    def reset_all(self):
        """모든 로봇 초기 위치 리셋"""
        spawns = {
            'pinky1': (1.41, 2.05375, -math.pi / 2.0),
            'pinky2': (1.41, 1.8575, -math.pi / 2.0),
            'pinky3': (1.41, 1.66125, -math.pi / 2.0),
        }
        for rid, (sx, sy, syaw) in spawns.items():
            if self.embedded_sim and rid in self.embedded_sim.pinkies:
                bot = self.embedded_sim.pinkies[rid]
                bot.x = sx
                bot.y = sy
                bot.yaw = syaw
                bot.v = 0.0
                bot.w = 0.0
                bot.target_goal = None
            else:
                self.send_goal_and_track(rid, sx, sy, syaw, timeout_sec=0.1)


def main():
    rclpy.init()
    has_ext_sim = check_external_sim()
    embedded_sim = None

    print('\n' + '=' * 75)
    print('      PINKY FLEET INTERACTIVE CONTROLLER & REAL-TIME RVIZ2 VIEWER')
    print('=' * 75)

    if has_ext_sim:
        print('[*] 외부 시뮬레이터(arena_sim_node)가 이미 실행 중입니다. 기존 세션에 연결합니다.')
    else:
        print('[*] 시뮬레이터가 켜져 있지 않습니다 -> 내장 시뮬레이터 엔진을 백그라운드로 자동 가동합니다.')
        from cobot_simulation.arena_sim_node import ArenaSimNode
        embedded_sim = ArenaSimNode()

    controller = TeleopController(embedded_sim=embedded_sim)

    executor = rclpy.executors.MultiThreadedExecutor()
    if embedded_sim:
        executor.add_node(embedded_sim)
    executor.add_node(controller)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    time.sleep(1.0)

    # 맵 서버 가동
    p_map, p_life = launch_map_server()

    # RViz2 실행
    rviz_proc = None
    if os.environ.get('DISPLAY'):
        print(f'[*] RViz2 3D 시각화 창을 엽니다... ({RVIZ_CONFIG})')
        rviz_proc = subprocess.Popen(['rviz2', '-d', RVIZ_CONFIG])
    else:
        print('[!] DISPLAY가 없습니다. 터미널 수치 모니터링 모드로 동작합니다.')

    print('-' * 75)
    print('준비 완료! 터미널에서 번호를 입력하면 로봇이 움직이며 RViz2 화면에서 즉시 확인됩니다.')

    try:
        while True:
            p1 = controller.get_pose('pinky1')
            p2 = controller.get_pose('pinky2')
            p3 = controller.get_pose('pinky3')

            print('\n' + '=' * 75)
            print('                       현재 로봇 위치 상태 (실시간)')
            print('=' * 75)
            print(f'  Pinky 1 (주황): X={p1[0]:6.3f}m, Y={p1[1]:6.3f}m, Yaw={math.degrees(p1[2]):6.1f}°')
            print(f'  Pinky 2 (초록): X={p2[0]:6.3f}m, Y={p2[1]:6.3f}m, Yaw={math.degrees(p2[2]):6.1f}°')
            print(f'  Pinky 3 (파랑): X={p3[0]:6.3f}m, Y={p3[1]:6.3f}m, Yaw={math.degrees(p3[2]):6.1f}°')
            print('-' * 75)
            print(' [1] 핑키 1호기: 25cm 전진 (Move Forward)')
            print(' [2] 핑키 1호기: 25cm 후진 (Move Backward)')
            print(' [3] 핑키 1호기: 좌회전 (Turn Left 45°)')
            print(' [4] 핑키 1호기: 우회전 (Turn Right 45°)')
            print(' [5] 핑키 1호기: 상차 구역(ZA)으로 자율주행 [X=2.015, Y=2.105]')
            print(' [6] 핑키 1호기: 67cm 통로 게이트 통과 -> 하차장(ZC) [X=0.415, Y=1.850]')
            print(' [7] 핑키 2호기: 25cm 전진')
            print(' [8] 핑키 3호기: 25cm 전진')
            print(' [9] 전체 로봇 초기 위치로 리셋')
            print(' [0] 프로그램 종료')
            print('=' * 75)

            try:
                choice = input('명령할 번호를 입력하세요 (1~9, 0: 종료): ').strip()
            except (EOFError, KeyboardInterrupt):
                break

            if choice == '0':
                print('[*] 프로그램을 종료합니다.')
                break
            elif choice == '1':
                print('[*] [명령 1] 핑키 1호기 25cm 전진 시작...')
                controller.move_distance('pinky1', 0.25)
            elif choice == '2':
                print('[*] [명령 2] 핑키 1호기 25cm 후진 시작...')
                controller.move_distance('pinky1', -0.25)
            elif choice == '3':
                print('[*] [명령 3] 핑키 1호기 좌회전 (45°)...')
                controller.rotate_angle('pinky1', 45.0)
            elif choice == '4':
                print('[*] [명령 4] 핑키 1호기 우회전 (45°)...')
                controller.rotate_angle('pinky1', -45.0)
            elif choice == '5':
                print('[*] [명령 5] 핑키 1호기 상차 구역(ZA: 2.015, 2.105)으로 자율주행 시작...')
                controller.send_goal_and_track('pinky1', 2.015, 2.105, 0.0)
            elif choice == '6':
                print('[*] [명령 6] 핑키 1호기 67cm 협소 게이트 통과 -> 하차장(ZC: 0.415, 1.850) 주행...')
                controller.send_goal_and_track('pinky1', 0.415, 1.850, math.pi, timeout_sec=12.0)
            elif choice == '7':
                print('[*] [명령 7] 핑키 2호기 25cm 전진...')
                controller.move_distance('pinky2', 0.25)
            elif choice == '8':
                print('[*] [명령 8] 핑키 3호기 25cm 전진...')
                controller.move_distance('pinky3', 0.25)
            elif choice == '9':
                print('[*] [명령 9] 모든 로봇 위치를 초기 스폰 좌표로 리셋합니다...')
                controller.reset_all()
                print('    -> 리셋 완료.')
            else:
                print('[!] 잘못된 입력입니다. 1번부터 9번까지의 숫자를 입력하세요.')

    finally:
        if rviz_proc:
            try:
                rviz_proc.terminate()
                rviz_proc.wait(timeout=1.0)
            except Exception:
                pass
        if p_life:
            try:
                p_life.terminate()
            except Exception:
                pass
        if p_map:
            try:
                p_map.terminate()
            except Exception:
                pass
        try:
            executor.shutdown()
        except Exception:
            pass
        try:
            controller.destroy_node()
        except Exception:
            pass
        if embedded_sim:
            try:
                embedded_sim.destroy_node()
            except Exception:
                pass
        if rclpy.ok():
            try:
                rclpy.shutdown()
            except Exception:
                pass
        print('[*] 정상적으로 종료되었습니다.\n')

if __name__ == '__main__':
    main()
