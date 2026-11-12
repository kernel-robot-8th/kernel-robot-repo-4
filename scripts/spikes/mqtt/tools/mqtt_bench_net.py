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
MQTT 학습 4단계 보강: 같은 데이터를 보낼 때 Wi-Fi 로 오간 바이트·패킷 수를 DDS 와 MQTT 로 비교한다.

왜 필요한가: 지연과 CPU 만 재서는 "MQTT 가 네트워크 부하를 줄이는가" 에 답할 수 없다.
양쪽 장비의 Wi-Fi 인터페이스 카운터(/proc/net/dev)가 시험 구간에 얼마나 늘었는지 재서
선로 위의 부하를 직접 비교한다. 이 방식은 sudo 가 필요 없다.

역할 (--role):
  sample: 인터페이스 카운터를 1초마다 'NETSAMPLE rx_bytes rx_pkts tx_bytes tx_pkts' 줄로 낸다.
          pinky1 에서는 이 스크립트를 stdin 으로 실행해서 쓴다 (파일을 남기지 않는다).
  run:    관제 PC 에서 돌리는 러너. 양쪽 카운터를 모으고, 경로·조건마다 프로세스를 띄워
          시험 구간의 증가량을 구한 뒤 직전 기준선(아무것도 안 돌릴 때)을 뺀다.

경로 (pinky1 -> 관제 PC 방향으로 데이터를 보낸다):
  dds:  pinky1 의 source(도메인 101) -> DDS 직접 -> 관제 PC 의 sink(도메인 101).
        기존 DDS 브릿지도 로봇 쪽 도메인을 네트워크로 구독하므로 선로 위 트래픽은 같다고 본다.
  mqtt: pinky1 의 source + ros2mqtt(둘 다 loopback 전용 DDS) -> LAN 브로커 -> 관제 PC 의
        mqtt2ros -> sink(도메인 102, loopback 전용). 선로에는 MQTT(TCP)만 지난다.

조건: idle(데이터 없이 연결만 유지)과 twist/laser 의 발행율. idle 로 탐색·유지 비용을 잰다.

종료 코드: 0 = 완료, 2 = 설정 오류.

안전:
  - 로봇 구동 없음. pinky1 은 도메인 101 에서 합성 메시지를 발행할 뿐 도메인 10 은 쓰지 않는다.
  - pinky1 의 DDS 설정 파일(~/.ros/cyclonedds_robot.xml)은 읽기만 하고 고치지 않는다.
  - 브로커는 사용자가 시험 중에만 LAN 에 열어 둔 것을 쓴다. 이 스크립트는 브로커 설정을 바꾸지 않는다.
  - 모든 프로세스에 --duration 이 있어 끝나면 스스로 멈춘다.

실행 (ROS 2 Jazzy 환경):
    source /opt/ros/jazzy/setup.bash
    python3 scripts/spikes/mqtt/tools/mqtt_bench_net.py --role run --broker-host 192.168.45.11 \
      --out <저장 경로>.json
"""

import argparse
import json
import logging
import os
from pathlib import Path
import shlex
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time

EXIT_OK = 0
EXIT_SETUP_FAILED = 2

SCRIPT_DIR = Path(__file__).resolve().parent
CORE_DIR = SCRIPT_DIR.parent / 'core'
NETDEV_PATH = '/proc/net/dev'
SAMPLE_MARK = 'NETSAMPLE '
RESULT_MARK = 'RESULT '
IDLE_RATE_HZ = 0.0001
CONDITIONS = ('idle', 'twist:10', 'twist:100', 'laser:5', 'laser:20')
MSG_NAMES = ('twist', 'laser')
STOP_WAIT_SEC = 5.0
TAIL_SEC = 4.0
# 이 PC 와 pinky1 의 DDS 를 loopback 에만 묶는 설정. 선로로 아무것도 나가지 않아야 한다.
LO_ONLY_URI = (
    '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces>'
    '<AllowMulticast>false</AllowMulticast></General><Discovery><Peers>'
    '<Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>')

LOGGER = logging.getLogger('mqtt_bench_net')


def parse_args(argv=None):
    """명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(description='DDS 대 MQTT 선로 부하 측정')
    parser.add_argument('--role', choices=('sample', 'run'), required=True)
    parser.add_argument('--iface', default='wlan0', help='sample: 읽을 인터페이스')
    parser.add_argument('--duration', type=float, default=60.0, help='sample: 실행 시간 [s]')
    parser.add_argument('--pc-iface', default='wlp0s20f3', help='run: 관제 PC 인터페이스')
    parser.add_argument('--pinky-host', default='pinky@192.168.45.21')
    parser.add_argument('--pinky-iface', default='wlan0')
    parser.add_argument('--broker-host', default='', help='run: pinky1 이 접속할 LAN 브로커')
    parser.add_argument('--broker-port', type=int, default=1883)
    parser.add_argument('--robot-dds-uri', default='file:///home/pinky/.ros/cyclonedds_robot.xml')
    parser.add_argument('--conditions', nargs='+', default=list(CONDITIONS))
    parser.add_argument('--paths', nargs='+', choices=('dds', 'mqtt'), default=['dds', 'mqtt'])
    parser.add_argument('--reps', type=int, default=3)
    parser.add_argument('--window-sec', type=float, default=30.0, help='데이터 시험 구간 [s]')
    parser.add_argument('--idle-window-sec', type=float, default=60.0, help='idle 구간 [s]')
    parser.add_argument('--baseline-sec', type=float, default=10.0, help='기준선 구간 [s]')
    parser.add_argument('--setup-sec', type=float, default=8.0, help='발견·접속 대기 [s]')
    parser.add_argument('--out', default='', help='원자료 JSON 저장 경로')
    return parser.parse_args(argv)


def read_counters(iface):
    """인터페이스의 (rx_bytes, rx_pkts, tx_bytes, tx_pkts) 를 돌려준다. 없으면 None."""
    with open(NETDEV_PATH, encoding='utf-8') as handle:
        for line in handle:
            name, _, rest = line.partition(':')
            if name.strip() == iface:
                fields = rest.split()
                return (int(fields[0]), int(fields[1]), int(fields[8]), int(fields[9]))
    return None


class Series:
    """시각별 카운터 값을 모으고 임의 시각의 값을 선형 보간해서 돌려주는 클래스."""

    def __init__(self):
        self._lock = threading.Lock()
        self._points = []

    def add(self, stamp, values):
        """(시각, 카운터 4개) 를 추가한다."""
        with self._lock:
            self._points.append((stamp, values))

    def at(self, stamp):
        """지정한 시각의 카운터 값을 보간한다. 표본이 감싸지 않으면 None."""
        with self._lock:
            points = list(self._points)
        for (t_a, v_a), (t_b, v_b) in zip(points, points[1:]):
            if t_a <= stamp <= t_b:
                ratio = (stamp - t_a) / (t_b - t_a) if t_b > t_a else 0.0
                return tuple(a + (b - a) * ratio for a, b in zip(v_a, v_b))
        return None

    def rates(self, start, end):
        """[start, end] 구간의 초당 증가량 (rx_B, rx_pkt, tx_B, tx_pkt) 을 돌려준다."""
        first, last = self.at(start), self.at(end)
        if first is None or last is None:
            return None
        return tuple((b - a) / (end - start) for a, b in zip(first, last))


def run_local_sampler(series, iface, stop_event):
    """이 PC 의 카운터를 1초마다 읽는다. 별도 스레드에서 돈다."""
    while not stop_event.is_set():
        values = read_counters(iface)
        if values:
            series.add(time.time(), values)
        stop_event.wait(1.0)


def read_remote_samples(proc, series):
    """pinky1 샘플러의 출력 줄을 읽어 수신 시각과 함께 저장한다. 별도 스레드에서 돈다."""
    for line in proc.stdout:
        if line.startswith(SAMPLE_MARK):
            try:
                values = tuple(int(item) for item in line[len(SAMPLE_MARK):].split())
            except ValueError:
                continue
            if len(values) == 4:
                series.add(time.time(), values)


def sample_main(args):
    """표본 수집 역할: 카운터를 1초마다 출력한다."""
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stdout)
    end = time.monotonic() + args.duration
    while time.monotonic() < end:
        values = read_counters(args.iface)
        if values is None:
            return EXIT_SETUP_FAILED
        LOGGER.info('%s%d %d %d %d', SAMPLE_MARK, *values)
        sys.stdout.flush()
        time.sleep(1.0)
    return EXIT_OK


def local_env(domain, lan):
    """자식 프로세스 환경. lan 이 False 면 DDS 를 loopback 에만 묶는다."""
    env = dict(os.environ)
    env['ROS_DOMAIN_ID'] = str(domain)
    env.pop('ROS_LOCALHOST_ONLY', None)
    env.pop('ROS_AUTOMATIC_DISCOVERY_RANGE', None)
    if not lan:
        env['CYCLONEDDS_URI'] = LO_ONLY_URI
    return env


def spawn_local(cmd, env, directory):
    """로컬 프로세스를 새 세션으로 띄운다. 출력은 파이프가 아니라 파일로 받는다."""
    log_file = tempfile.NamedTemporaryFile(
        mode='w', dir=directory, prefix='net_', suffix='.log', delete=False)
    proc = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    log_file.close()
    proc.log_path = log_file.name
    return proc


def spawn_remote(args, script, script_args, domain, lan, directory):
    """pinky1 에서 스크립트를 stdin 으로 실행한다. 출력은 파일로 받는다."""
    uri = args.robot_dds_uri if lan else LO_ONLY_URI
    remote = (
        'source /opt/ros/jazzy/setup.bash; '
        f'export ROS_DOMAIN_ID={domain} RMW_IMPLEMENTATION=rmw_cyclonedds_cpp '
        f'CYCLONEDDS_URI={shlex.quote(uri)}; '
        f'python3 - {shlex.join(script_args)}')
    log_file = tempfile.NamedTemporaryFile(
        mode='w', dir=directory, prefix='net_remote_', suffix='.log', delete=False)
    with open(script, encoding='utf-8') as stdin_file:
        proc = subprocess.Popen(
            ['ssh', '-o', 'BatchMode=yes', args.pinky_host, remote], stdin=stdin_file,
            stdout=log_file, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    log_file.close()
    proc.log_path = log_file.name
    return proc


def read_log(proc):
    """프로세스가 파일에 남긴 출력을 읽는다. 파일이 없는 프로세스(샘플러)는 빈 문자열이다."""
    path = getattr(proc, 'log_path', None)
    return Path(path).read_text(encoding='utf-8', errors='replace') if path else ''


def stop(proc):
    """프로세스 그룹에 종료 신호를 보내고 끝나길 기다린 뒤 출력을 돌려준다."""
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=STOP_WAIT_SEC)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    return read_log(proc)


def finish(proc, timeout):
    """프로세스가 스스로 끝나길 기다린다. 못 끝나면 멈추고 출력을 돌려준다."""
    try:
        proc.wait(timeout=timeout)
        return read_log(proc)
    except subprocess.TimeoutExpired:
        return stop(proc)


def parse_result(output):
    """출력에서 RESULT JSON 한 줄을 찾아 사전으로 돌려준다. 없으면 빈 사전."""
    for line in output.splitlines():
        if RESULT_MARK in line:
            return json.loads(line.split(RESULT_MARK, 1)[1])
    return {}


def parse_condition(text):
    """'idle', 'twist:100' 같은 조건을 (이름, 메시지, 발행율) 로 바꾼다."""
    if text == 'idle':
        return 'idle', 'twist', IDLE_RATE_HZ
    msg, _, rate = text.partition(':')
    if msg not in MSG_NAMES or not rate:
        raise ValueError(f'조건 형식 오류: {text}')
    return text, msg, float(rate)


def start_processes(path_name, msg, rate, duration, args, directory):
    """경로에 맞는 프로세스를 띄우고 (그룹 이름, 프로세스) 목록을 돌려준다."""
    stream_local = str(SCRIPT_DIR / 'mqtt_bench_stream.py')
    relay_local = str(CORE_DIR / 'mqtt_ros_relay.py')
    stream = SCRIPT_DIR / 'mqtt_bench_stream.py'
    relay = CORE_DIR / 'mqtt_ros_relay.py'
    topic = f'/bench/{msg}'
    msg_types = {'twist': 'geometry_msgs/msg/TwistStamped',
                 'laser': 'sensor_msgs/msg/LaserScan'}
    source_args = ['--role', 'source', '--msg', msg, '--topic', topic,
                   '--rate-hz', str(rate), '--duration', str(duration)]
    procs = []
    if path_name == 'dds':
        sink = ['--role', 'sink', '--msg', msg, '--topic', topic, '--duration', str(duration)]
        procs.append(('sink', spawn_local(
            [sys.executable, stream_local] + sink, local_env(101, True), directory)))
        procs.append(('source', spawn_remote(args, stream, source_args, 101, True, directory)))
        return procs
    out_topic = f'/mqtt_test/bench/{msg}'
    mqtt_topic = f'mqtt_learning/bench/net_{msg}'
    relay_common = ['--msg-type', msg_types[msg], '--mqtt-topic', mqtt_topic,
                    '--duration', str(duration + 3.0)]
    sink = ['--role', 'sink', '--msg', msg, '--topic', out_topic, '--duration', str(duration)]
    procs.append(('pc_relay', spawn_local(
        [sys.executable, relay_local, '--direction', 'mqtt2ros', '--ros-out-topic', out_topic,
         '--host', '127.0.0.1'] + relay_common, local_env(102, False), directory)))
    procs.append(('sink', spawn_local(
        [sys.executable, stream_local] + sink, local_env(102, False), directory)))
    procs.append(('pinky_relay', spawn_remote(
        args, relay, ['--direction', 'ros2mqtt', '--ros-topic', topic, '--max-rate-hz', '0',
                      '--host', args.broker_host, '--port', str(args.broker_port)]
        + relay_common, 101, False, directory)))
    time.sleep(1.0)
    procs.append(('source', spawn_remote(args, stream, source_args, 101, False, directory)))
    return procs


def run_once(path_name, name, msg, rate, args, pc_series, pk_series, directory):
    """조건 하나를 한 번 실행해 기준선을 뺀 증가량을 돌려준다."""
    window = args.idle_window_sec if name == 'idle' else args.window_sec
    base_start = time.time()
    time.sleep(args.baseline_sec)
    base_end = time.time()
    duration = args.setup_sec + window + TAIL_SEC
    procs = start_processes(path_name, msg, rate, duration, args, directory)
    time.sleep(args.setup_sec)
    start = time.time()
    time.sleep(window)
    end = time.time()
    outputs = {}
    for group, proc in procs:
        outputs[group] = finish(proc, TAIL_SEC + STOP_WAIT_SEC + 12.0)
    time.sleep(1.5)
    result = {'path': path_name, 'condition': name, 'window_s': window}
    for label, series in (('pc', pc_series), ('pinky', pk_series)):
        base = series.rates(base_start, base_end)
        data = series.rates(start, end)
        if base is None or data is None:
            result[label] = None
            continue
        keys = ('rx_Bps', 'rx_pps', 'tx_Bps', 'tx_pps')
        result[label] = {key: round(d - b, 1) for key, d, b in zip(keys, data, base)}
        result[label + '_baseline'] = {key: round(b, 1) for key, b in zip(keys, base)}
    sent = parse_result(outputs.get('source', ''))
    got = parse_result(outputs.get('sink', ''))
    result['published'] = sent.get('published', 0)
    result['received'] = got.get('unique', 0)
    return result


def summarize(rows):
    """같은 (경로, 조건) 행들의 평균을 표용 사전으로 돌려준다."""
    out = {'path': rows[0]['path'], 'condition': rows[0]['condition'], 'reps': len(rows)}
    for label in ('pc', 'pinky'):
        valid = [row[label] for row in rows if row.get(label)]
        for key in ('rx_Bps', 'tx_Bps', 'rx_pps', 'tx_pps'):
            out[f'{label}_{key}'] = (
                round(statistics.mean(item[key] for item in valid), 1) if valid else None)
    published = sum(row['published'] for row in rows)
    out['delivered_pct'] = (
        round(100.0 * sum(row['received'] for row in rows) / published, 1) if published else None)
    return out


def run_all(args):
    """모든 경로·조건·반복을 돌리고 평균을 로그로 남긴다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if 'mqtt' in args.paths and not args.broker_host:
        LOGGER.error('mqtt 경로는 --broker-host (LAN 에서 pinky1 이 접속할 주소) 가 필요하다')
        return EXIT_SETUP_FAILED
    try:
        conditions = [parse_condition(text) for text in args.conditions]
    except ValueError as error:
        LOGGER.error('%s', error)
        return EXIT_SETUP_FAILED
    pc_series, pk_series = Series(), Series()
    stop_event = threading.Event()
    threading.Thread(target=run_local_sampler, daemon=True,
                     args=(pc_series, args.pc_iface, stop_event)).start()
    total = (args.baseline_sec + args.setup_sec + args.idle_window_sec + 30.0)
    total *= len(conditions) * len(args.paths) * args.reps
    raw = []
    with tempfile.TemporaryDirectory(prefix='mqtt_bench_net_') as directory:
        with open(Path(__file__).resolve(), encoding='utf-8') as stdin_file:
            sampler = subprocess.Popen(
                ['ssh', '-o', 'BatchMode=yes', args.pinky_host,
                 f'python3 - --role sample --iface {shlex.quote(args.pinky_iface)} '
                 f'--duration {int(total)}'],
                stdin=stdin_file, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, start_new_session=True)
        threading.Thread(target=read_remote_samples, daemon=True,
                         args=(sampler, pk_series)).start()
        time.sleep(3.0)
        try:
            for name, msg, rate in conditions:
                for path_name in args.paths:
                    rows = []
                    for _ in range(args.reps):
                        row = run_once(path_name, name, msg, rate, args, pc_series,
                                       pk_series, directory)
                        rows.append(row)
                        raw.append(row)
                        LOGGER.info('원자료 %s', json.dumps(row))
                    LOGGER.info('평균 %s', json.dumps(summarize(rows)))
        finally:
            stop_event.set()
            stop(sampler)
    if args.out:
        Path(args.out).write_text(json.dumps(raw, indent=1), encoding='utf-8')
        LOGGER.info('원자료 저장: %s', args.out)
    return EXIT_OK


def main(argv=None):
    """역할에 맞게 실행하고 종료 코드를 돌려준다."""
    args = parse_args(argv)
    return sample_main(args) if args.role == 'sample' else run_all(args)


if __name__ == '__main__':
    sys.exit(main())
