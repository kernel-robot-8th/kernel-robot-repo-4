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
아직 없는 팔 대신 /fleet/work_request 에 '성공'으로 답하는 시험 도구 (팔은 움직이지 않는다).

팔 노드의 fake 백엔드는 실물 도메인(100 등)에서 시작을 거부한다. 실물 관제·핑키·다른 팔과 함께
돌리며 아직 학습 전인 팔(예: omx1 선반 반환)만 건너뛰고 싶을 때 쓴다.

  source /opt/ros/jazzy/setup.bash && source install/setup.bash
  python3 scripts/fake_arm_result.py omx1            # omx1 작업 요청에만 3초 뒤 성공
  python3 scripts/fake_arm_result.py omx1 omx3 --delay 5

- 그 팔의 실제 어댑터(<팔>_adapter)가 같은 도메인에 떠 있으면 시작하지 않는다 (답이 둘 나가면 안 됨).
- 노드 이름은 arm_adapter 다. 이상 감지 관제 수동 어댑터가 허용하는 팔 노드 이름이라 그쪽을 막지 않는다.
- 결과 data 에 fake=true 를 붙인다. 정지(SAFETY hold/release_hold)에는 답하지 않는다 (관제가 기다리지 않음).
- 실제 물건은 옮겨지지 않는다. 시험이 끝나면 Ctrl+C 로 끈다.
"""

import argparse
import json
import re
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

REQUEST_TOPIC = '/fleet/work_request'
RESULT_TOPIC = '/fleet/work_result'
WORK_ACTIONS = {'pick', 'load', 'unload', 'warehouse_store', 'arrange_shoe'}


class FakeArmResult(Node):
    """지정한 팔의 작업 요청에만 delay 초 뒤 성공 결과를 보낸다."""

    def __init__(self, targets, delay):
        super().__init__('arm_adapter')
        self.targets, self.delay = set(targets), delay
        self.seen = set()
        self.pub = self.create_publisher(String, RESULT_TOPIC, 50)
        self.create_subscription(String, REQUEST_TOPIC, self._on_request, 50)
        self.get_logger().warning(
            f'가짜 팔 결과: {sorted(self.targets)} 작업 요청에 {delay:g}초 뒤 성공으로 답함 '
            '(팔은 움직이지 않음)')

    def real_adapters(self):
        """결과 토픽에 이미 있는 그 팔의 실제 어댑터 이름."""
        names = {info.node_name for info in self.get_publishers_info_by_topic(RESULT_TOPIC)}
        return sorted(f'{t}_adapter' for t in self.targets if f'{t}_adapter' in names)

    def _on_request(self, msg):
        try:
            request = json.loads(msg.data)
        except ValueError:
            return
        if (not isinstance(request, dict) or request.get('target') not in self.targets
                or request.get('action') not in WORK_ACTIONS
                or request.get('request_id') in self.seen):
            return
        self.seen.add(request['request_id'])
        self.get_logger().info(
            f'{request["target"]} {request.get("stage")} {request["action"]} 요청 '
            f'({request.get("order_id")}) → {self.delay:g}초 뒤 성공')
        threading.Timer(self.delay, self._reply, args=(request,)).start()

    def _reply(self, request):
        result = {key: request.get(key) for key in ('request_id', 'order_id', 'robot_id', 'stage')}
        result.update(source=request['target'], measured=True, finished=True, success=True,
                      data={'arm_safe': True, 'fake': True})
        self.pub.publish(String(data=json.dumps(result, ensure_ascii=False, sort_keys=True)))


def main(argv=None):
    """시작 전 실제 어댑터가 없는지 확인하고 돈다."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('targets', nargs='+', help='팔 이름 (omx1 등)')
    parser.add_argument('--delay', type=float, default=3.0, help='성공으로 답하기까지 [s]')
    options = parser.parse_args(argv)
    if any(not re.fullmatch(r'omx[0-9]+', t) for t in options.targets):
        parser.error('팔 이름은 omx<번호>')
    if not 0 < options.delay <= 120:
        parser.error('delay 범위: 0~120초')
    rclpy.init()
    node = FakeArmResult(options.targets, options.delay)
    deadline = time.time() + 3.0
    while time.time() < deadline:  # 발견에 시간이 걸리므로 잠깐 둘러본 뒤 판단한다
        rclpy.spin_once(node, timeout_sec=0.2)
    clash = node.real_adapters()
    if clash:
        node.get_logger().error(f'실제 팔 어댑터가 떠 있어 시작하지 않음: {clash}')
        node.destroy_node()
        rclpy.shutdown()
        return 1
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
