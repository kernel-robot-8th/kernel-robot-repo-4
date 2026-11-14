"""관제 fleet의 장치 작업 요청을 받아 OMX 추론 스크립트를 실행하는 노드."""

import json
import threading

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

from .omx_infer_utils import (build_command, build_result, parse_request, run_inference,
                              should_handle, slot_from_request, validate_command)


class OmxInferWorkerNode(Node):
    """요청 하나씩만 실행하고 결과를 /fleet/work_result로 돌려준다."""

    def __init__(self):
        super().__init__('omx_infer_worker')
        defaults = {
            'arm_id': 'omx1',
            'actions': ['pick'],
            'command': ['bash', '', '{slot}'],
            'working_dir': '',
            'slot_key': 'slot',
            'allowed_slots': [1, 2, 3, 4],
            'timeout_margin_sec': 10.0,
            'work_request_topic': '/fleet/work_request',
            'work_result_topic': '/fleet/work_result',
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)
        config = {name: self.get_parameter(name).value for name in defaults}
        self.arm_id = config['arm_id']
        self.actions = set(config['actions'])
        self.command = validate_command(config['command'])
        self.working_dir = config['working_dir']
        self.slot_key = config['slot_key']
        self.allowed_slots = tuple(config['allowed_slots'])
        self.timeout_margin_sec = float(config['timeout_margin_sec'])
        self.seen = set()
        self.lock = threading.Lock()
        self.running_request = None
        self.result_pub = self.create_publisher(String, config['work_result_topic'], 50)
        self.create_subscription(String, config['work_request_topic'], self._on_request, 50)
        self.get_logger().info(
            f'{self.arm_id} 추론 worker 시작: actions={sorted(self.actions)} '
            f'command={self.command}')

    def _on_request(self, message):
        try:
            request = parse_request(message.data)
        except (ValueError, TypeError) as error:
            self.get_logger().warning(f'작업 요청 무시: {error}')
            return
        if not should_handle(request, self.arm_id, self.actions):
            return
        request_id = request.get('request_id')
        with self.lock:
            if request_id in self.seen:
                return
            self.seen.add(request_id)
            busy = self.running_request
            if busy is None:
                try:
                    slot = slot_from_request(request, self.slot_key, self.allowed_slots)
                except ValueError as error:
                    # 팔을 움직이기 전에 거절하므로 같은 단계를 다시 시도해도 안전하다.
                    self._publish(request, False, str(error), retry_safe=True)
                    return
                self.running_request = request_id
        if busy is not None:
            self._publish(request, False, f'다른 요청 실행 중: {busy}', retry_safe=True)
            return
        threading.Thread(target=self._run, args=(request, slot), daemon=True).start()

    def _run(self, request, slot):
        command = build_command(self.command, slot)
        self.get_logger().info(f'추론 시작 request={request.get("request_id")} '
                               f'order={request.get("order_id")} slot={slot}')
        try:
            timeout_sec = float(request.get('timeout_sec', 300.0)) - self.timeout_margin_sec
            if timeout_sec <= 0:
                raise ValueError(f'요청 유효시간이 여유 시간보다 짧음: {timeout_sec:.1f}s')
            returncode, detail = run_inference(command, timeout_sec, self.working_dir)
        except (OSError, ValueError, TypeError) as error:
            # 실행 자체를 못 했으면 팔은 움직이지 않았다.
            self._finish(request, False, f'추론 실행 불가: {error}', slot, retry_safe=True)
            return
        except Exception as error:  # noqa: B902 - 실행 중 상태가 남아 다음 요청이 막히지 않게 한다
            self._finish(request, False, f'추론 중 예외: {error}', slot, retry_safe=False)
            return
        # 실행 도중 실패·시간 초과는 팔 자세가 불확실하므로 운영자 확인이 필요하다.
        self._finish(request, returncode == 0, detail, slot, retry_safe=False)

    def _finish(self, request, success, detail, slot, retry_safe):
        with self.lock:
            self.running_request = None
        self._publish(request, success, detail, retry_safe=retry_safe, slot=slot)

    def _publish(self, request, success, detail, retry_safe, slot=None):
        data = {'retry_safe': retry_safe}
        if slot is not None:
            data['slot'] = slot
        result = build_result(request, self.arm_id, success, detail, data)
        self.result_pub.publish(String(data=json.dumps(result, ensure_ascii=False)))
        text = f'결과 발행 request={request.get("request_id")} success={success}: {detail}'
        # rclpy는 같은 호출 위치에서 로그 수준을 바꾸면 예외를 내므로 호출을 나눈다.
        if success:
            self.get_logger().info(text)
        else:
            self.get_logger().warning(text)


def main(args=None):
    """추론 PC에서 worker를 시작한다."""
    rclpy.init(args=args)
    node = OmxInferWorkerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
