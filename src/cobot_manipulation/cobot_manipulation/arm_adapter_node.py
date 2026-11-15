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
팔 1대의 관제 어댑터 노드.

관제 fleet_control 이 /fleet/work_request 로 보내는 요청 중 target 이 내 arm_id 인 것만
받아 백엔드에 맡기고, 실측 최종 결과를 /fleet/work_result 로 돌려준다.
팔 3대는 같은 실행 파일을 arm_id 만 바꿔 3번 띄운다 (한 대가 죽어도 나머지는 계속).
"""

import os
import sys
import time

from cobot_manipulation import arm_backend_utils as backends
from cobot_manipulation import arm_registry_utils as registry_utils
from cobot_manipulation import work_contract_utils as contract
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.logging import get_logger
from rclpy.node import Node
from std_msgs.msg import String


class AdapterConfigError(Exception):
    """노드 설정이 틀려 시작할 수 없음."""


class ArmAdapterNode(Node):
    """팔 1대: 탐지 → 요청 검사 → 백엔드 실행 → 결과 발행."""

    def __init__(self):
        super().__init__('arm_adapter')
        params = {
            'arm_id': '',
            'registry_file': '',
            'serial_by_id_dir': '/dev/serial/by-id',
            'request_topic': '/fleet/work_request',
            'result_topic': '/fleet/work_result',
            'backend': 'none',
            'fake_duration_sec': 2.0,
            'worker_command': '',
            'worker_timeout_sec': 300.0,
            'dedupe_size': 256,
            'detect_period_sec': 1.0,
            'tick_sec': 0.1,
        }
        for name, default in params.items():
            self.declare_parameter(name, default)
        value = {name: self.get_parameter(name).value for name in params}

        self.arm_id = value['arm_id']
        if not registry_utils.ARM_ID_PATTERN.fullmatch(self.arm_id or ''):
            raise AdapterConfigError('arm_id 파라미터가 필요합니다 (예: omx1)')
        try:
            self.registry = registry_utils.load_registry(value['registry_file'])
        except registry_utils.RegistryError as error:
            raise AdapterConfigError(str(error)) from error
        try:
            self.backend = backends.make_backend(
                value['backend'], value['fake_duration_sec'], {
                    'arm_id': self.arm_id,
                    'command': value['worker_command'],
                    'timeout_sec': value['worker_timeout_sec'],
                    'log': self.get_logger().info,
                })
        except ValueError as error:
            raise AdapterConfigError(str(error)) from error
        if self.backend.name == 'fake':
            ok, message = backends.check_domain(os.environ)
            if not ok:
                raise AdapterConfigError(message)
            self.get_logger().warning(f'fake 백엔드: 실제 팔은 움직이지 않습니다 ({message})')
        if self.backend.name == 'worker':
            if not self.backend.argv:
                raise AdapterConfigError('backend=worker 에는 worker_command 가 필요합니다')
            self.get_logger().warning(
                'worker 백엔드: 팔이 탐지되면 실행기가 팔에 연결해 토크를 켭니다 (실제 팔). '
                f'명령={self.backend.argv[0]}')

        self.by_id_dir = value['serial_by_id_dir']
        self.filter = contract.RequestFilter(self.arm_id, value['dedupe_size'])
        self.state, self.port, self.reason = None, None, ''
        self.held = False

        self.result_pub = self.create_publisher(String, value['result_topic'], 50)
        self.create_subscription(String, value['request_topic'], self._on_request, 50)
        self._detect()
        self.create_timer(value['detect_period_sec'], self._detect)
        self.create_timer(value['tick_sec'], self._tick)
        self.get_logger().info(
            f'{self.arm_id} 시작: backend={self.backend.name}, '
            f'요청 {value["request_topic"]} → 결과 {value["result_topic"]}')

    def _detect(self):
        state, port, reason = registry_utils.detect(
            self.arm_id, self.registry, registry_utils.list_by_id(self.by_id_dir),
            self.by_id_dir)
        if (state, port) == (self.state, self.port):
            return
        logger = self.get_logger()
        log = logger.info if state == registry_utils.READY else logger.warning
        log(f'{self.arm_id} 탐지 {state}: {reason}')
        lost = self.state == registry_utils.READY and state != registry_utils.READY
        self.state, self.port, self.reason = state, port, reason
        if state == registry_utils.READY:
            self.backend.attach(port, time.time())
        if lost and self.backend.busy():
            # 작업 중 보드가 사라지면 팔 자세를 모른다. 멈추고 재시도 금지 실패로 끝낸다.
            self._publish_finished(self.backend.hold(time.time()), '작업 중 팔 연결 끊김')

    def _on_request(self, message):
        try:
            request = contract.decode(message.data)
        except ValueError as error:
            self.get_logger().warning(f'요청 무시: {error}')
            return
        now = time.time()
        verdict, reason, retry_safe = self.filter.check(request, now)
        if verdict == contract.IGNORE:
            if reason != '다른 장치 요청':
                self.get_logger().warning(f'요청 무시 ({request.get("request_id")}): {reason}')
            return
        if verdict == contract.REJECT:
            self._reject(request, reason, retry_safe)
            return
        action = request['action']
        if action == 'hold':
            self.held = True
            self.get_logger().warning(f'{self.arm_id} 정지 (hold, order={request.get("order_id")})')
            self._publish_finished(self.backend.hold(now), '')
            return
        if action == 'release_hold':
            self.held = False
            self.backend.release_hold(now)
            self.get_logger().info(f'{self.arm_id} 정지 해제 (release_hold)')
            return
        # 아래 거절은 모두 팔을 움직이기 전이라 다시 해도 안전하다.
        if self.state != registry_utils.READY:
            self._reject(request, f'팔 탐지 안 됨: {self.reason}', True)
        elif self.held:
            self._reject(request, '정지 유지 중 (release_hold 필요)', True)
        else:
            error = self.backend.start(request, self.port, now)
            if error:
                self._reject(request, error, True)
            else:
                self.get_logger().info(
                    f'{self.arm_id} 작업 시작: {request["stage"]}/{action} '
                    f'(order={request.get("order_id")}, request={request["request_id"]})')

    def _tick(self):
        self._publish_finished(self.backend.poll(time.time()), '')

    def _reject(self, request, detail, retry_safe):
        self.get_logger().warning(f'{self.arm_id} 요청 거절 ({request.get("stage")}): {detail}')
        self._publish(contract.reject_result(request, self.arm_id, detail, retry_safe))

    def _publish_finished(self, finished, default_detail):
        for request, success, data, detail in finished:
            self._publish(contract.make_result(
                request, self.arm_id, success, data, detail or default_detail))

    def _publish(self, result):
        self.result_pub.publish(String(data=contract.encode(result)))
        self.get_logger().info(
            f'{self.arm_id} 결과: {result["stage"]} success={result["success"]} '
            f'request={result["request_id"]}')


def main(args=None):
    rclpy.init(args=args)
    try:
        node = ArmAdapterNode()
    except AdapterConfigError as error:
        get_logger('arm_adapter').fatal(f'시작 거부: {error}')
        rclpy.try_shutdown()
        sys.exit(1)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # Ctrl+C 면 rclpy 가 먼저 꺼져 노드 로거로는 rosout 에 못 쓴다. 실행기 마지막 로그는 노드 밖 로거로.
        if hasattr(node.backend, 'log'):
            node.backend.log = get_logger('arm_adapter_shutdown').info
        node.backend.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
