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
sim_fleet_doctor.py: 시뮬레이션 환경 자동 설정, 실시간 토픽 진단 및 원클릭 RViz2 시각화 런처.
- 환경 자동 로드 (ROS 2 Jazzy, ROS_DOMAIN_ID 동기화)
- 핑키 1~3호기 및 로봇팔 1~3호기 실시간 토픽/좌표 수신 진단
- 2.5m x 2.4m 아레나 벽체/게이트 3D 마커 발행
- 사전 구성된 RViz2 원클릭 자동 기동
"""

import os
import sys
import glob
import time
import math
import subprocess
import argparse

# 1. ROS 2 환경 자동 로드 및 재실행 (Re-exec)
WORKSPACE_INSTALL = os.path.expanduser('~/kernel-robot-repo-4/install/setup.bash')
ROS_SETUP = '/opt/ros/jazzy/setup.bash'

if 'AMENT_PREFIX_PATH' not in os.environ:
    script_path = os.path.abspath(__file__)
    args = ' '.join(f'"{a}"' for a in sys.argv[1:])
    cmd = f'source {ROS_SETUP} && if [ -f {WORKSPACE_INSTALL} ]; then source {WORKSPACE_INSTALL}; fi && exec python3 "{script_path}" {args}'
    sys.exit(subprocess.call(['bash', '-c', cmd]))

# 2. 실행 중인 시뮬레이터 프로세스 및 ROS_DOMAIN_ID 자동 감지
def detect_sim_process():
    for pid_dir in glob.glob('/proc/[0-9]*'):
        try:
            pid = int(os.path.basename(pid_dir))
            with open(f'{pid_dir}/cmdline', 'rb') as f:
                cmdline = f.read().decode('utf-8', errors='ignore')
            if 'arena_sim_node' in cmdline or 'gz_sim' in cmdline:
                env = {}
                with open(f'{pid_dir}/environ', 'rb') as f:
                    for item in f.read().split(b'\0'):
                        line = item.decode('utf-8', errors='ignore')
                        if '=' in line:
                            k, v = line.split('=', 1)
                            env[k] = v
                domain = env.get('ROS_DOMAIN_ID', '0')
                proc_name = 'arena_sim_node (MuJoCo/Standard)' if 'arena_sim_node' in cmdline else 'Gazebo Sim'
                return pid, proc_name, domain
        except Exception:
            continue
    return None, None, None

sim_pid, sim_name, sim_domain = detect_sim_process()

# 사용자가 직접 환경변수를 준 경우가 아니면, 시뮬레이터 프로세스의 도메인 ID로 자동 동기화
if 'ROS_DOMAIN_ID' not in os.environ and sim_domain is not None:
    os.environ['ROS_DOMAIN_ID'] = sim_domain
current_domain = os.environ.get('ROS_DOMAIN_ID', '0')

import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy, QoSDurabilityPolicy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan, JointState
from geometry_msgs.msg import Twist, Point
from visualization_msgs.msg import Marker, MarkerArray

# 3. RViz2 사전 설정 파일 생성 (/tmp/sim_fleet_doctor.rviz)
RVIZ_CONFIG_PATH = '/tmp/sim_fleet_doctor.rviz'

def generate_rviz_config():
    rviz_config = {
        'Panels': [
            {
                'Class': 'rviz_common/Displays',
                'Help Height': 78,
                'Name': 'Displays',
                'Property Tree Widget': {
                    'Expanded': ['/Global Options1', '/Status1', '/Grid1'],
                    'Splitter Ratio': 0.5
                },
                'Tree Height': 700
            },
            {
                'Class': 'rviz_common/Views',
                'Expanded': ['/Current View1'],
                'Name': 'Views',
                'Splitter Ratio': 0.5
            }
        ],
        'Visualization Manager': {
            'Class': '',
            'Displays': [
                {
                    'Alpha': 0.5,
                    'Cell Size': 0.5,
                    'Class': 'rviz_default_plugins/Grid',
                    'Color': '160; 160; 164',
                    'Enabled': True,
                    'Line Style': {'Line Width': 0.03, 'Value': 'Lines'},
                    'Name': 'Arena Floor Grid (2.5m x 2.4m)',
                    'Normal Cell Count': 0,
                    'Offset': {'X': 1.25, 'Y': 1.20, 'Z': 0.0},
                    'Plane': 'XY',
                    'Plane Cell Count': 10,
                    'Reference Frame': 'map',
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/TF',
                    'Enabled': True,
                    'Frame Timeout': 15,
                    'Marker Scale': 0.25,
                    'Name': 'TF Tree',
                    'Show Arrows': True,
                    'Show Axes': True,
                    'Show Names': True,
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/LaserScan',
                    'Color': '255; 140; 0',
                    'Color Transformer': 'FlatColor',
                    'Decay Time': 0.0,
                    'Enabled': True,
                    'Name': 'Pinky 1 LiDAR (Orange)',
                    'Queue Size': 10,
                    'Size (m)': 0.04,
                    'Style': 'Flat Squares',
                    'Topic': {
                        'Depth': 5,
                        'Durability Policy': 'Volatile',
                        'History Policy': 'Keep Last',
                        'Reliability Policy': 'Best Effort',
                        'Value': '/pinky1/scan'
                    },
                    'Use Fixed Frame': True,
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/LaserScan',
                    'Color': '40; 180; 99',
                    'Color Transformer': 'FlatColor',
                    'Decay Time': 0.0,
                    'Enabled': True,
                    'Name': 'Pinky 2 LiDAR (Green)',
                    'Queue Size': 10,
                    'Size (m)': 0.04,
                    'Style': 'Flat Squares',
                    'Topic': {
                        'Depth': 5,
                        'Durability Policy': 'Volatile',
                        'History Policy': 'Keep Last',
                        'Reliability Policy': 'Best Effort',
                        'Value': '/pinky2/scan'
                    },
                    'Use Fixed Frame': True,
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/LaserScan',
                    'Color': '41; 128; 185',
                    'Color Transformer': 'FlatColor',
                    'Decay Time': 0.0,
                    'Enabled': True,
                    'Name': 'Pinky 3 LiDAR (Blue)',
                    'Queue Size': 10,
                    'Size (m)': 0.04,
                    'Style': 'Flat Squares',
                    'Topic': {
                        'Depth': 5,
                        'Durability Policy': 'Volatile',
                        'History Policy': 'Keep Last',
                        'Reliability Policy': 'Best Effort',
                        'Value': '/pinky3/scan'
                    },
                    'Use Fixed Frame': True,
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/Odometry',
                    'Enabled': True,
                    'Keep': 50,
                    'Name': 'Pinky 1 Odom Path',
                    'Shape': {'Alpha': 1.0, 'Axes': {'Length': 0.25, 'Radius': 0.02}, 'Color': '255; 140; 0', 'Type': 'Axes'},
                    'Topic': {'Depth': 5, 'Durability Policy': 'Volatile', 'History Policy': 'Keep Last', 'Reliability Policy': 'Reliable', 'Value': '/pinky1/odom'},
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/Odometry',
                    'Enabled': True,
                    'Keep': 50,
                    'Name': 'Pinky 2 Odom Path',
                    'Shape': {'Alpha': 1.0, 'Axes': {'Length': 0.25, 'Radius': 0.02}, 'Color': '40; 180; 99', 'Type': 'Axes'},
                    'Topic': {'Depth': 5, 'Durability Policy': 'Volatile', 'History Policy': 'Keep Last', 'Reliability Policy': 'Reliable', 'Value': '/pinky2/odom'},
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/Odometry',
                    'Enabled': True,
                    'Keep': 50,
                    'Name': 'Pinky 3 Odom Path',
                    'Shape': {'Alpha': 1.0, 'Axes': {'Length': 0.25, 'Radius': 0.02}, 'Color': '41; 128; 185', 'Type': 'Axes'},
                    'Topic': {'Depth': 5, 'Durability Policy': 'Volatile', 'History Policy': 'Keep Last', 'Reliability Policy': 'Reliable', 'Value': '/pinky3/odom'},
                    'Value': True
                },
                {
                    'Class': 'rviz_default_plugins/MarkerArray',
                    'Enabled': True,
                    'Name': 'Arena 3D Layout & Gate',
                    'Topic': {'Depth': 10, 'Durability Policy': 'Transient Local', 'History Policy': 'Keep Last', 'Reliability Policy': 'Reliable', 'Value': '/arena_markers'},
                    'Value': True
                }
            ],
            'Global Options': {
                'Background Color': '30; 34; 42',
                'Fixed Frame': 'map',
                'Frame Rate': 30
            }
        }
    }
    with open(RVIZ_CONFIG_PATH, 'w') as f:
        yaml.dump(rviz_config, f, default_flow_style=False)

# 4. 아레나 3D 시각화 마커 발행 노드 및 진단 노드
class SimDoctorNode(Node):
    def __init__(self):
        super().__init__('sim_fleet_doctor_node')
        
        # QoS 설정
        sensor_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10
        )
        marker_qos = QoSProfile(
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10
        )

        # 데이터 저장소
        self.robots = {
            'pinky1': {'pos': None, 'scan_pts': 0, 'odom_cnt': 0, 'last_odom': 0},
            'pinky2': {'pos': None, 'scan_pts': 0, 'odom_cnt': 0, 'last_odom': 0},
            'pinky3': {'pos': None, 'scan_pts': 0, 'odom_cnt': 0, 'last_odom': 0},
        }
        self.arms = {
            'omx_1': {'joints': 0, 'cnt': 0},
            'omx_2': {'joints': 0, 'cnt': 0},
            'omx_3': {'joints': 0, 'cnt': 0},
        }

        # 구독자 등록
        for ns in ['pinky1', 'pinky2', 'pinky3']:
            self.create_subscription(Odometry, f'/{ns}/odom', lambda m, r=ns: self._on_odom(r, m), 10)
            self.create_subscription(LaserScan, f'/{ns}/scan', lambda m, r=ns: self._on_scan(r, m), sensor_qos)
        for arm in ['omx_1', 'omx_2', 'omx_3']:
            self.create_subscription(JointState, f'/{arm}/joint_states', lambda m, a=arm: self._on_joint(a, m), 10)

        # 아레나 마커 발행자
        self.marker_pub = self.create_publisher(MarkerArray, '/arena_markers', marker_qos)
        self.publish_arena_markers()

        # 제어 명령 발행자 (모션 테스트용)
        self.cmd_pub = self.create_publisher(Twist, '/pinky1/cmd_vel', 10)

    def _on_odom(self, r_id, msg):
        self.robots[r_id]['pos'] = msg.pose.pose.position
        # Yaw 계산
        q = msg.pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self.robots[r_id]['yaw'] = math.atan2(siny_cosp, cosy_cosp)
        self.robots[r_id]['odom_cnt'] += 1

    def _on_scan(self, r_id, msg):
        self.robots[r_id]['scan_pts'] = len(msg.ranges)

    def _on_joint(self, a_id, msg):
        self.arms[a_id]['joints'] = len(msg.position)
        self.arms[a_id]['cnt'] += 1

    def publish_arena_markers(self):
        """2.5m x 2.4m 신발 매장 아레나 및 67cm 게이트 3D 마커 발행"""
        arr = MarkerArray()
        now = self.get_clock().now().to_msg()

        # 1. 외곽 벽체 4면 (2.5m x 2.4m, 높이 15cm)
        walls = [
            ('border_south', 1.25, -0.02, 0.075, 2.54, 0.04, 0.15, 0.6, 0.6, 0.7),
            ('border_north', 1.25, 2.42, 0.075, 2.54, 0.04, 0.15, 0.6, 0.6, 0.7),
            ('border_west', -0.02, 1.20, 0.075, 0.04, 2.44, 0.15, 0.6, 0.6, 0.7),
            ('border_east', 2.52, 1.20, 0.075, 0.04, 2.44, 0.15, 0.6, 0.6, 0.7),
            # 중앙 분리벽 (X=1.25, Y=0.67 ~ 2.40)
            ('central_wall', 1.25, 1.535, 0.075, 0.05, 1.73, 0.15, 0.7, 0.7, 0.8),
            # 67cm 통로 게이트 바닥 표식 (Y=0.00 ~ 0.67)
            ('gate_floor', 1.25, 0.335, 0.005, 0.10, 0.67, 0.01, 0.2, 0.9, 0.3),
        ]

        for i, (name, x, y, z, sx, sy, sz, cr, cg, cb) in enumerate(walls):
            m = Marker()
            m.header.frame_id = 'map'
            m.header.stamp = now
            m.ns = 'arena_walls'
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
            m.color.a = 0.8 if 'gate' not in name else 0.5
            arr.markers.append(m)

        # 2. 67cm 게이트 텍스트 라벨
        text_m = Marker()
        text_m.header.frame_id = 'map'
        text_m.header.stamp = now
        text_m.ns = 'arena_text'
        text_m.id = 100
        text_m.type = Marker.TEXT_VIEW_FACING
        text_m.action = Marker.ADD
        text_m.pose.position.x = 1.25
        text_m.pose.position.y = 0.335
        text_m.pose.position.z = 0.25
        text_m.scale.z = 0.12
        text_m.color.r = 0.2
        text_m.color.g = 1.0
        text_m.color.b = 0.3
        text_m.color.a = 1.0
        text_m.text = '67cm GATE'
        arr.markers.append(text_m)

        self.marker_pub.publish(arr)

    def trigger_test_drive(self):
        """테스트용 전진 명령 발행"""
        tw = Twist()
        tw.linear.x = 0.15
        self.cmd_pub.publish(tw)

def main():
    parser = argparse.ArgumentParser(description='시뮬레이션 진단 및 RViz2 런처')
    parser.add_argument('--no-rviz', action='store_true', help='RViz2 창을 띄우지 않고 진단만 수행')
    parser.add_argument('--drive', action='store_true', help='핑키 1호기에 1회 전진 명령 주입')
    args = parser.parse_args()

    print('\n' + '=' * 75)
    print('          SIMULATION FLEET DOCTOR & AUTO-VIEWER (Team Pinky4)')
    print('=' * 75)
    
    # 1. 상태 브리핑
    print(f'[*] Python Interpreter : {sys.executable}')
    print(f'[*] DDS Domain ID      : {current_domain} (동기화 완료)')
    if sim_pid:
        print(f'[*] Simulation Engine  : RUNNING ({sim_name}, PID: {sim_pid})')
    else:
        print('[!] Simulation Engine  : NOT RUNNING (아직 시뮬레이터가 켜지지 않음)')
        print('    -> 별도 터미널에서 실행: ros2 launch cobot_simulation bringup_sim.launch.py')

    print('-' * 75)
    print('토픽 수신 상태를 1.5초간 검사합니다...')

    rclpy.init()
    node = SimDoctorNode()

    start_time = time.time()
    while time.time() - start_time < 1.5:
        rclpy.spin_once(node, timeout_sec=0.1)

    # 2. 결과 테이블 출력
    print('\n' + '=' * 75)
    print('                      FLEET LIVE TELEMETRY STATUS')
    print('=' * 75)
    print(f' {"로봇 / 장치":<12} | {"실시간 위치 (X, Y, Yaw)":<26} | {"LiDAR":<10} | {"상태":<10}')
    print('-' * 75)

    for r_id in ['pinky1', 'pinky2', 'pinky3']:
        data = node.robots[r_id]
        if data['pos']:
            pos_str = f"X={data['pos'].x:5.3f} Y={data['pos'].y:5.3f} {math.degrees(data.get('yaw',0)):5.1f} deg"
            lidar_str = f"{data['scan_pts']} pts" if data['scan_pts'] > 0 else "No data"
            status_str = "HEALTHY"
        else:
            pos_str = "No Odom received"
            lidar_str = "-"
            status_str = "WAITING"
        print(f' {r_id:<12} | {pos_str:<26} | {lidar_str:<10} | {status_str:<10}')

    print('-' * 75)
    for a_id in ['omx_1', 'omx_2', 'omx_3']:
        data = node.arms[a_id]
        arm_status = f"{data['joints']}-DOF Joints" if data['joints'] > 0 else "Waiting"
        status_str = "HEALTHY" if data['cnt'] > 0 else "WAITING"
        print(f' {a_id:<12} | {arm_status:<26} | {"-":<10} | {status_str:<10}')
    print('=' * 75)

    if args.drive:
        print('[*] 핑키 1호기에 0.15 m/s 전진 명령을 1회 발행했습니다.')
        node.trigger_test_drive()

    # 3. RViz2 자동 설정 파일 생성
    generate_rviz_config()
    print(f'[*] 맞춤형 RViz2 설정 생성 완료: {RVIZ_CONFIG_PATH}')

    # 4. RViz2 자동 기동
    if not args.no_rviz:
        display = os.environ.get('DISPLAY')
        if not display:
            print('[!] DISPLAY 환경변수가 없습니다. (화면이 없는 터미널 환경)')
            print('    GUI 창 대신 웹 브라우저 http://localhost:5173/menus/6.5 를 이용하세요.')
        else:
            print(f'[*] RViz2 3D 시각화 창을 엽니다... (Fixed Frame: map, Domain: {current_domain})')
            rviz_cmd = f'export ROS_DOMAIN_ID={current_domain} && rviz2 -d {RVIZ_CONFIG_PATH}'
            subprocess.Popen(['bash', '-c', rviz_cmd])
            print('[*] RViz2가 백그라운드에서 기동되었습니다.')
            print('    - 핑키 3대의 라이다 레이저 광선(주황/초록/파랑)이 표시됩니다.')
            print('    - 2.5m x 2.4m 경기장 아레나 벽체와 67cm 게이트가 3D로 표출됩니다.')
    
    # 마커 유지를 위해 2초간 추가 spin
    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.1)

    node.destroy_node()
    rclpy.shutdown()
    print('진단 및 초기화 완료.\n')

if __name__ == '__main__':
    main()
