"""홈랩 격리 도메인에서 실제 수신한 센서 표본과 patrol 경고만 집계한다."""

from collections import deque
import json
import os
import time

from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
import rclpy
from rcl_interfaces.msg import Log
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Float32, String


TOPICS = {'scan': LaserScan, 'odom': Odometry, 'patrol_status': String,
          'battery/percent': Float32, 'amcl_pose': PoseWithCovarianceStamped}
WINDOW = 10.0


def link_state(source, destination, warmed):
    if not warmed:
        return '관측 중'
    if source and not destination:
        return '전달 미관측'
    if not source:
        return '원천 미관측' if not destination else '원천 확인 필요'
    return '양쪽 수신'


def main():
    domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))
    if domain not in (77, 140) or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST':
        raise SystemExit('격리 도메인 77/140 LOCALHOST 전용')
    contexts, executors, nodes = [], [], []
    samples, warnings = {}, deque(maxlen=100)
    start = report = time.monotonic()
    try:
        for offset in range(4):
            ctx = Context()
            rclpy.init(context=ctx, domain_id=domain + offset)
            contexts.append(ctx)
            node = rclpy.create_node(f'sim_link_probe_{domain + offset}', context=ctx,
                                     enable_rosout=False, start_parameter_services=False)
            nodes.append(node)
            executor = SingleThreadedExecutor(context=ctx)
            executor.add_node(node)
            executors.append(executor)
            robots = range(1, 4) if offset == 0 else [offset]
            for number in robots:
                robot = f'pinky{number}'
                for name, msg_type in TOPICS.items():
                    side = 'destination' if offset == 0 else 'source'
                    topic = f'/{robot}/{name}' if offset == 0 else f'/{name}'
                    times = samples[(robot, name, side)] = deque(maxlen=10000)
                    node.create_subscription(msg_type, topic, lambda _, q=times: q.append(
                        time.monotonic()), qos_profile_sensor_data)
            if offset:
                def warn(msg, robot=robot):
                    if 'patrol' in msg.name and msg.level >= Log.WARN:
                        warnings.append((time.monotonic(), robot, msg.name, msg.msg[:512]))
                node.create_subscription(Log, '/rosout', warn, qos_profile_sensor_data)
        pub = nodes[0].create_publisher(String, '/anomaly_monitor/sim_diagnostics', 5)
        while contexts[0].ok():
            for executor in executors:
                executor.spin_once(timeout_sec=.005)
            now = time.monotonic()
            if now - report < 1:
                continue
            report = now
            for q in samples.values():
                while q and q[0] < now - WINDOW:
                    q.popleft()
            rows = []
            for robot, name, side in samples:
                if side != 'source':
                    continue
                src = len(samples[(robot, name, side)])
                dst = len(samples[(robot, name, 'destination')])
                rows.append(dict(robot=robot, topic=name, source=src, destination=dst,
                                 state=link_state(src, dst, now - start >= WINDOW)))
            latest = [dict(robot=r, node=n, message=m, age_sec=round(now - t, 1))
                      for t, r, n, m in warnings if t >= now - 60]
            pub.publish(String(data=json.dumps(dict(at=time.time(), window_sec=WINDOW,
                                                    destination_domain=domain,
                                                    source_domains=list(range(domain + 1, domain + 4)),
                                                    links=rows, warnings=latest))))
    except KeyboardInterrupt:
        pass
    finally:
        for executor in executors:
            executor.shutdown()
        for node in nodes:
            node.destroy_node()
        for ctx in contexts:
            rclpy.try_shutdown(context=ctx)
