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
네트워크 측정 노드 (관제 PC): 핑·토픽 수신 주기·관제 PC Wi-Fi 신호를 재서 1 Hz 로 낸다.

두 가지 빠르기로 잰다 (헬스체크는 가볍게 계속, 자세한 확인은 필요할 때만):
- 평소: 대상마다 ping_period_sec(5 s)에 한 번 핑. 토픽은 구독하지 않는다.
- 자세히 확인: /control_center/net_check 요청을 받으면 detail_duration_sec(10 s) 동안
  detail_period_sec(1 s)마다 핑하고, 로봇 patrol_status·팔 ArmStatus·영상 분석 근거를 구독해
  수신 주기를 잰다.
  끝나면 구독을 지우고 마지막 결과(checked_at)를 그대로 낸다.
  팔 상태를 구독하면 Station PC 가 한 벌 더 보낼 수 있어서 평소에는 구독하지 않는다.

- 핑: 대상마다 스레드 하나가 `ping -c1 -W<초> -n <주소>` 를 되풀이한다 (시스템 명령, 새 의존성 없음).
  ping 이 없는 환경(도커 이미지 등)이면 '측정 불가'로 낸다.
- 발행: /control_center/net_status (std_msgs/String JSON, transient_local).
로봇·팔에는 아무것도 발행하지 않는다.
"""

import json
import os
import shutil
import subprocess
import threading
import time

from cobot_control_center import net_status_utils as nu
from cobot_control_center.host_info import HostReader, read_text
from cobot_interfaces.msg import ArmStatus
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

# 팔 노드 텔레메트리와 같은 QoS (arm_command_node TELEMETRY_QOS). BEST_EFFORT 는 RELIABLE 발행자와도 붙는다.
TELEMETRY_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
SNAPSHOT_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                          durability=DurabilityPolicy.TRANSIENT_LOCAL)
REQUEST_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)

PARAMS = {
    'robots': ['pinky1', 'pinky2', 'pinky3'],
    'robot_hosts': ['192.168.45.21', '192.168.45.22', '192.168.45.23'],
    'station_host': '192.168.45.10',
    'router_host': '192.168.45.1',
    'arm_ids': ['omx_1', 'omx_2', 'omx_3'],
    'status_topic_format': '/{robot}/patrol_status',
    'arm_status_topic_format': '/manipulation/{arm}/status',
    'publish_topic': '/control_center/net_status',
    'check_topic': '/control_center/net_check',
    'publish_period_sec': 1.0,
    'ping_period_sec': 5.0,
    'detail_period_sec': 1.0,
    'detail_duration_sec': 10.0,
    'ping_timeout_sec': 1,
    'tcp_probe_port': 22,   # ping 명령이 없을 때 연결을 시도할 포트 (로봇·Station PC 는 ssh)
    # 유선망(영상·분석): 관제 PC 의 다른 연결. 같은 순서의 목록이고 빈 주소는 재지 않는다.
    'wired_router_host': '192.168.0.1',
    'wired_ids': ['cctv', 'broker', 'station_wired'],
    'wired_hosts': ['192.168.0.7', '192.168.0.8', '192.168.0.4'],
    'wired_probe_ports': [18086, 1883, 22],   # ping 이 없을 때 대상별 TCP 연결 포트
    # 자세히 확인 때만 수신 주기를 잴 영상 분석 근거 토픽 (std_msgs/String)
    'evidence_topics': ['/anomaly_monitor/zone_evidence', '/anomaly_monitor/box_evidence'],
    'evidence_expect_hz': 10.0,
    'evidence_stale_sec': 1.0,
    'ping_window': 12,
    'ping_warn_ms': 100.0,
    'ping_warn_loss_pct': 10.0,
    'ping_bad_fails': 3,
    'robot_status_stale_sec': 3.0,
    'arm_status_stale_sec': 1.0,
    'arm_status_expect_hz': 10.0,
    'wifi_warn_dbm': -70.0,
    'wifi_warn_pct': 40.0,
    'nmcli_period_sec': 10.0,
    # 화면에 보이지 않을 인터페이스 이름 앞부분 (도커·가상 연결)
    'interface_skip_prefixes': ['lo', 'docker', 'veth', 'br-', 'p2p', 'virbr'],
}


class NetStatusNode(Node):
    """핑 스레드와 (자세히 확인 중) 토픽 구독으로 모은 값을 주기마다 JSON 하나로 낸다."""

    def __init__(self):
        super().__init__('net_status_node')
        self.cfg = {name: self.declare_parameter(name, default).value
                    for name, default in PARAMS.items()}
        c = self.cfg
        robots = [r for r in c['robots'] if r]
        hosts = list(c['robot_hosts'])
        if len(hosts) != len(robots):
            raise ValueError('robots 와 robot_hosts 의 개수가 다름')

        # 핑 대상: 키 → 주소. 빈 주소는 재지 않는다.
        targets = {'router': c['router_host'], 'station': c['station_host']}
        targets.update(zip(robots, hosts))
        wired_ids = list(c['wired_ids'])
        wired_hosts = list(c['wired_hosts'])
        wired_ports = list(c['wired_probe_ports'])
        if not len(wired_ids) == len(wired_hosts) == len(wired_ports):
            raise ValueError('wired_ids, wired_hosts, wired_probe_ports 의 개수가 다름')
        targets['wired_router'] = c['wired_router_host']
        targets.update(zip(wired_ids, wired_hosts))
        self.targets = {k: h for k, h in targets.items() if k and h}
        # ping 이 없을 때 대상별로 연결을 시도할 TCP 포트 (나머지는 tcp_probe_port)
        self.probe_ports = {k: int(p) for k, p in zip(wired_ids, wired_ports)}
        self.ping_cmd = shutil.which('ping')
        self.host = HostReader(c)   # 이 PC 연결 읽기 (host_status_node 와 같은 코드)
        self._lock = threading.Lock()
        # 자세히 확인 시작을 핑 스레드에 바로 알리려고 Condition 으로 기다린다.
        self._wake = threading.Condition(self._lock)
        self._windows = {k: nu.PingWindow(c['ping_window']) for k in self.targets}
        self._detail_until = 0.0     # monotonic. 이 시각까지 자세히 확인
        self._detail_started = None  # 마지막 자세히 확인 시작 (UNIX 시각)
        self._stop = threading.Event()
        self._threads = []
        # ping 명령이 없으면(관제 도커 이미지 등) TCP 연결 시도로 잰다. 권한이 필요 없고,
        # 연결이 거절돼도(RST) 응답이 온 것이라 장치가 살아 있고 왕복 시간을 안다.
        self.probe = 'icmp' if self.ping_cmd else 'tcp'
        if not self.ping_cmd:
            self.get_logger().warning(
                f'ping 명령이 없음: TCP {c["tcp_probe_port"]} 연결 시도로 잰다 '
                '(포트를 막은 장치는 응답 없음으로 보일 수 있음)')
        for key, host in self.targets.items():
            thread = threading.Thread(target=self._ping_loop, args=(key, host), daemon=True)
            thread.start()
            self._threads.append(thread)

        # 수신 주기는 자세히 확인 중에만 잰다. 키 → (토픽, 형식, QoS, stale, 기대 Hz)
        self._rate_specs = {}
        for robot in robots:
            self._rate_specs[f'{robot}/patrol_status'] = (
                c['status_topic_format'].format(robot=robot), String, 10,
                c['robot_status_stale_sec'], None)
        for arm in [a for a in c['arm_ids'] if a]:
            self._rate_specs[f'{arm}/status'] = (
                c['arm_status_topic_format'].format(arm=arm), ArmStatus, TELEMETRY_QOS,
                c['arm_status_stale_sec'], c['arm_status_expect_hz'])
        for topic in [t for t in c['evidence_topics'] if t]:
            self._rate_specs[f'evidence{topic}'] = (
                topic, String, 10, c['evidence_stale_sec'], c['evidence_expect_hz'])
        self._rates = {}       # 자세히 확인 중인 RateMeter
        self._subs = []
        self._rate_last = {}   # 마지막 자세히 확인 결과 (끝난 뒤에도 그대로 낸다)

        self.create_subscription(String, c['check_topic'], self._on_check, REQUEST_QOS)
        self.pub = self.create_publisher(String, c['publish_topic'], SNAPSHOT_QOS)
        self.create_timer(float(c['publish_period_sec']), self._publish)
        self.get_logger().info(
            '네트워크 측정 시작: 핑 ' + ', '.join(f'{k}={h}' for k, h in self.targets.items())
            + f' (평소 {c["ping_period_sec"]} s, 자세히 확인 {c["detail_duration_sec"]} s 동안 '
            + f'{c["detail_period_sec"]} s), 요청 {c["check_topic"]}, 발행 {c["publish_topic"]}')

    # ---------- 자세히 확인 ----------

    def _on_check(self, _msg):
        """자세히 확인 시작 (진행 중이면 끝 시각만 늘린다). 내용은 보지 않는다."""
        now = time.monotonic()
        with self._lock:
            starting = now >= self._detail_until
            self._detail_until = now + float(self.cfg['detail_duration_sec'])
            if starting:
                self._detail_started = time.time()
            self._wake.notify_all()
        if starting:
            self._start_rates()
            self.get_logger().info('자세히 확인 시작')

    def _start_rates(self):
        for key, (topic, msg_type, qos, _stale, _expect) in self._rate_specs.items():
            meter = nu.RateMeter(float(self.cfg['detail_duration_sec']))
            with self._lock:
                self._rates[key] = meter

            def on_msg(_m, meter=meter):
                with self._lock:
                    meter.tick(time.monotonic())
            self._subs.append(self.create_subscription(msg_type, topic, on_msg, qos))

    def _finish_rates(self, now):
        """자세히 확인이 끝나면 마지막 결과를 남기고 구독을 지운다 (ROS 스레드에서)."""
        with self._lock:
            self._rate_last = self._rate_summaries(now, checked_at=time.time())
            self._rates = {}
        for sub in self._subs:
            self.destroy_subscription(sub)
        self._subs = []
        self.get_logger().info('자세히 확인 끝')

    def _rate_summaries(self, now, checked_at=None):
        """수신 주기 요약 (lock 안에서 부른다)."""
        result = {}
        for key, meter in self._rates.items():
            topic, _type, _qos, stale, expect = self._rate_specs[key]
            result[key] = dict(meter.summary(now, stale, expect), topic=topic,
                               expect_hz=expect, checked_at=checked_at)
        return result

    # ---------- 핑 ----------

    def _ping_once(self, key, host):
        """한 번 핑. 응답 rtt[ms] 또는 None. 명령이 멈춰도 타임아웃보다 조금 더 기다리고 끊는다."""
        timeout = max(1, int(self.cfg['ping_timeout_sec']))
        if self.probe == 'tcp':
            port = self.probe_ports.get(key, int(self.cfg['tcp_probe_port']))
            return nu.tcp_probe(host, port, timeout)
        try:
            done = subprocess.run(
                [self.ping_cmd, '-c', '1', '-W', str(timeout), '-n', host],
                capture_output=True, text=True, timeout=timeout + 2, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return nu.parse_ping_rtt(done.stdout) if done.returncode == 0 else None

    def _ping_loop(self, key, host):
        while not self._stop.is_set():
            started = time.monotonic()
            rtt = self._ping_once(key, host)
            with self._wake:
                self._windows[key].add(rtt, time.monotonic())
                detail = time.monotonic() < self._detail_until
                period = float(self.cfg['detail_period_sec' if detail else 'ping_period_sec'])
                # 자세히 확인이 시작되면 notify 로 바로 깨어 다음 핑을 보낸다.
                self._wake.wait(max(0.0, period - (time.monotonic() - started)))

    # ---------- 발행 ----------

    def _publish(self):
        now = time.monotonic()
        c = self.cfg
        if self._subs and now >= self._detail_until:
            self._finish_rates(now)
        # 대상 MAC: 핑을 보내므로 이 PC 의 ARP 표에 이미 있다 (따로 패킷을 보내지 않는다)
        arp = nu.parse_proc_arp(read_text('/proc/net/arp'))
        with self._lock:
            detail = now < self._detail_until
            targets = {}
            for key, window in self._windows.items():
                summary = window.summary(now, c['ping_warn_ms'], c['ping_warn_loss_pct'],
                                         c['ping_bad_fails'])
                entry = arp.get(self.targets[key]) or {}
                targets[key] = dict(summary, host=self.targets[key], mac=entry.get('mac'),
                                    mac_fresh=entry.get('complete'))
            topics = self._rate_summaries(now) if detail else dict(self._rate_last)
            remaining = max(0.0, self._detail_until - now) if detail else 0.0
            started = self._detail_started
        local_ip = self.host.local_ip()
        data = {'time': time.time(), 'ping_available': bool(self.ping_cmd),
                'probe': self.probe,
                'probe_port': c['tcp_probe_port'] if self.probe == 'tcp' else None,
                'probe_ports': self.probe_ports if self.probe == 'tcp' else {},
                'targets': targets, 'topics': topics,
                'interfaces': self.host.interfaces(local_ip),
                'local_ip': local_ip, 'pid': os.getpid(),
                'detail': {'active': detail, 'remaining_sec': round(remaining, 1),
                           'started_at': started,
                           'duration_sec': c['detail_duration_sec']},
                # 화면 그래프의 기준선·설명이 이 노드 판정과 같게 함께 보낸다
                'thresholds': {'ping_warn_ms': c['ping_warn_ms'],
                               'ping_warn_loss_pct': c['ping_warn_loss_pct'],
                               'ping_bad_fails': c['ping_bad_fails'],
                               'wifi_warn_dbm': c['wifi_warn_dbm'],
                               'wifi_warn_pct': c['wifi_warn_pct'],
                               'ping_period_sec': c['ping_period_sec'],
                               'detail_period_sec': c['detail_period_sec']}}
        self.pub.publish(String(data=json.dumps(data, ensure_ascii=False)))

    def stop(self):
        self._stop.set()
        with self._wake:
            self._wake.notify_all()
        for thread in self._threads:
            thread.join(timeout=3.0)


def main(args=None):
    rclpy.init(args=args)
    node = NetStatusNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.try_shutdown()
