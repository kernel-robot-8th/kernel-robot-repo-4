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
PC 상태 보고 노드: 이 PC 의 연결·CPU·메모리·온도·디스크·DDS 설정을 주기마다 관제에 보낸다.

관제 PC 가 아닌 PC(팔 PC 등)에서 이것 하나만 띄운다 (관제 백엔드·웹은 띄우지 않는다).
관제 PC 는 남의 PC 안쪽을 읽을 수 없어서, 각 PC 가 자기 것을 읽어 보내는 방식이다.
  ROS_DOMAIN_ID=100 ros2 launch cobot_control_center host_status.launch.xml host:=station

- 발행: /control_center/host_status (std_msgs/String JSON). 여러 PC 가 같은 토픽에 내고 host 로 구분한다.
- 읽기만 한다: /proc, /sys, ip·nmcli(다시 찾기 없이). 다른 토픽을 구독하지 않고 명령을 내지 않는다.
"""

import json
import socket
import time

from cobot_control_center.host_info import HostReader, WarnLatch
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

PARAMS = {
    'host': 'station',            # 화면에서 이 PC 를 찾는 이름 (관제 network_hosts 와 같게)
    'label': '팔 PC',
    'router_host': '192.168.45.1',  # 이 주소로 가는 연결을 '로봇망'으로 본다
    'publish_topic': '/control_center/host_status',
    'publish_period_sec': 3.0,
    'nmcli_period_sec': 10.0,
    'interface_skip_prefixes': ['lo', 'docker', 'veth', 'br-', 'p2p', 'virbr'],
    'wifi_warn_dbm': -70.0,
    'wifi_warn_pct': 40.0,
    'cpu_warn_pct': 90.0,
    'cpu_clear_pct': 80.0,
    'cpu_warn_hold_sec': 10.0,
    'mem_warn_pct': 90.0,
    'temp_warn_c': 80.0,
    'disk_warn_pct': 90.0,
}


class HostStatusNode(Node):
    """HostReader 로 읽은 이 PC 상태를 publish_period_sec 마다 JSON 하나로 낸다."""

    def __init__(self):
        super().__init__('host_status_node')
        self.cfg = {name: self.declare_parameter(name, default).value
                    for name, default in PARAMS.items()}
        self.reader = HostReader(self.cfg)
        # CPU 는 순간값이 문턱을 오르내려 경고·회복이 번갈아 찍혀서, 판정을 여기서 이어서 한다.
        self.cpu_latch = WarnLatch(self.cfg['cpu_warn_pct'], self.cfg['cpu_clear_pct'],
                                   self.cfg['cpu_warn_hold_sec'])
        self.hostname = socket.gethostname()
        self.pub = self.create_publisher(
            String, self.cfg['publish_topic'],
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        self.create_timer(float(self.cfg['publish_period_sec']), self._publish)
        self.get_logger().info(
            f'PC 상태 보고 시작: host={self.cfg["host"]} ({self.hostname}), '
            f'{self.cfg["publish_period_sec"]} s 마다 {self.cfg["publish_topic"]}')

    def _publish(self):
        c = self.cfg
        local_ip = self.reader.local_ip()
        system = self.reader.system()
        system['cpu_warn'] = self.cpu_latch.update(system.get('cpu_pct'), time.monotonic())
        data = {
            'host': c['host'], 'label': c['label'], 'hostname': self.hostname,
            'time': time.time(), 'period_sec': c['publish_period_sec'],
            'local_ip': local_ip,
            'dds': self.reader.dds(rclpy.get_rmw_implementation_identifier(),
                                   self.context.get_domain_id()),
            'interfaces': self.reader.interfaces(local_ip),
            'system': system,
            'thresholds': {k: c[k] for k in ('cpu_warn_pct', 'cpu_clear_pct', 'cpu_warn_hold_sec',
                                             'mem_warn_pct', 'temp_warn_c', 'disk_warn_pct',
                                             'wifi_warn_dbm', 'wifi_warn_pct')},
        }
        self.pub.publish(String(data=json.dumps(data, ensure_ascii=False)))


def main(args=None):
    rclpy.init(args=args)
    node = HostStatusNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
