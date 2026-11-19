"""격리 DDS를 통해 실제 감시 노드의 판정 입력과 기본 보강을 확인한다."""

import json
import os
from pathlib import Path
import time

import pytest


@pytest.mark.skipif(
    os.environ.get('ROS_DOMAIN_ID') != '77'
    or os.environ.get('ROS_LOCALHOST_ONLY') != '1'
    or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST',
    reason='requires isolated domain 77 LOCALHOST')
def test_judge_receives_dds_and_blocks_fake_arm(tmp_path, monkeypatch):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from cobot_anomaly_monitor import monitor_node

    package = Path(__file__).resolve().parents[1]
    shares = {'cobot_anomaly_monitor': package,
              'cobot_pinky_patrol': package.parent / 'cobot_navigation/cobot_pinky_patrol'}
    monkeypatch.setattr(monitor_node, 'get_package_share_directory',
                        lambda name: str(shares[name]))
    rclpy.init(args=['--ros-args', '-p', f'db_path:={tmp_path / "monitor.db"}',
                     '-p', 'console_port:=0', '-p', 'judge_mode:=enforce',
                     '-p', 'judge_hold_sec:=0.2', '-p', 'judge_min_frames:=2',
                     '-p', 'judge_fresh_sec:=1.5', '-p', 'judge_gap_sec:=0.8',
                     '-p', 'judge_drop_reach:=0.5'])
    monitor = peer = executor = None
    try:
        monitor = monitor_node.AnomalyMonitorNode()
        warnings = []
        logger = type('Logger', (), {'warning': lambda self, msg: warnings.append(msg)})()
        monkeypatch.setattr(monitor, 'get_logger', lambda: logger)
        peer = Node('isolated_judge_evidence')
        executor = SingleThreadedExecutor()
        executor.add_node(monitor)
        executor.add_node(peer)
        pubs = {k: peer.create_publisher(String, topic, 10) for k, topic in {
            'zones': '/anomaly_monitor/zone_evidence',
            'boxes': '/anomaly_monitor/box_evidence', 'arm': '/fleet/work_result'}.items()}
        deadline = time.monotonic() + 10
        while not all(p.get_subscription_count() for p in pubs.values()):
            assert time.monotonic() < deadline, 'DDS discovery timeout'
            executor.spin_once(timeout_sec=.02)
        assert monitor.judge.fresh_sec == 1.5 and monitor.judge.gap_sec == .8
        assert monitor.judge.drop_reach == .5
        now = time.time()
        bad = {'source_kind': 'model_output', 'stream_id': 'ceiling', 'stream_epoch': 'test',
               'model_id': 'pinky-v1', 'calibration_id': 'wrong', 'capture_time': now,
               'clock_error_sec': .05, 'frame_seq': 0, 'marker_state': 'OK',
               'zones': {'ZB': 'LOADED'}}
        pubs['zones'].publish(String(data=json.dumps(bad)))
        while not warnings:
            assert time.monotonic() < deadline
            executor.spin_once(timeout_sec=.02)
        assert '전부 폐기' in warnings[0] and not monitor.judge.zones
        received = time.time()
        for stage in ('PICK', 'LOAD'):
            pubs['arm'].publish(String(data=json.dumps({
                'order_id': 'test', 'robot_id': 'pinky1', 'stage': stage, 'source': 'omx1',
                'measured': True, 'finished': True, 'success': True,
                'data': {'arm_safe': True, 'fake': True}})))
        seq = 0
        deadline = time.monotonic() + 5
        while len(monitor.judge.zones) < 4 or len(monitor.judge.arm) < 2:
            assert time.monotonic() < deadline
            now = time.time()
            base = dict(bad, calibration_id='replay-v1', capture_time=now, frame_seq=seq)
            seq += 1
            pubs['zones'].publish(String(data=json.dumps(base)))
            pubs['boxes'].publish(String(data=json.dumps(dict(
                base, truncated=0, boxes=[], pinky=[{'name': 'pinky_loaded', 'zones': ['ZB'],
                                                    'bbox': [100, 100, 200, 200]}]))))
            end = time.monotonic() + .1
            while time.monotonic() < end:
                executor.spin_once(timeout_sec=.01)
        req = {'order_id': 'test', 'robot_id': 'pinky1',
               'stage': 'VERIFY_LOAD', 'route': {'pickup': 'ZB'}}
        result = monitor.judge.judge(req, received, time.time())
        assert result['verdict'] == 'wait' and result['reason'] == '팔 단계가 가짜 실행 결과'
        assert monitor._judge_warning_at == {}
    finally:
        if executor:
            executor.shutdown()
        for node in (monitor, peer):
            if node:
                node.destroy_node()
        rclpy.shutdown()
