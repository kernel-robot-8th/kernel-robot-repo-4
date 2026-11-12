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
MQTT 학습 4단계 (갈래 A): 한 PC 안에서 세 가지 중계 경로의 지연·수신율·CPU 를 비교하는 러너.

왜 필요한가: DDS 브릿지와 MQTT 중계를 같은 조건에서 여러 번 재야 비교가 된다. 수작업으로는
조건이 흔들리므로, 프로세스를 띄우고 정리하는 일을 한 스크립트가 맡는다.

경로 (--paths):
  direct:      source -> sink (같은 도메인, 중계 없음. 기준선)
  dds_bridge:  source(도메인 101) -> domain_bridge -> sink(도메인 102)
  mqtt_q0/q1:  source(101) -> mqtt_ros_relay(ros2mqtt) -> 브로커 -> mqtt_ros_relay(mqtt2ros)
               -> sink(102). 숫자는 MQTT QoS 다. 중계율 상한은 두지 않는다.

조건마다 --reps 번 반복해서 평균을 낸다. CPU 는 중계 프로세스(자식 포함)가 쓴 CPU 시간을
측정 시간으로 나눈 값이라 코어 하나를 다 쓰면 100% 다.

종료 코드: 0 = 완료, 2 = 설정 오류.

안전:
  - 로봇·장치·실제 도메인을 쓰지 않는다. 도메인은 --source-domain/--sink-domain(기본 101, 102)
    이고, 항상 CYCLONEDDS_URI 로 DDS 를 loopback(lo)에만 묶어 LAN 으로 나가지 않는다.
  - 시험용 DDS 브릿지 설정은 임시 폴더에 만들고 /bench/ 토픽만 담는다. 끝나면 지운다.
  - 브로커는 이미 떠 있는 localhost 의 것만 쓴다. retained 는 쓰지 않는다.

실행 (기존 브릿지를 쓰려면 두 setup.bash 를 모두 source):
    source /opt/ros/jazzy/setup.bash
    source src/cobot_navigation/install/setup.bash
    python3 scripts/spikes/mqtt/tools/mqtt_bench_run.py --reps 2 --out /tmp/bench.json
"""

import argparse
import json
import logging
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import tempfile
import time

import psutil

EXIT_OK = 0
EXIT_SETUP_FAILED = 2

SCRIPT_DIR = Path(__file__).resolve().parent
CORE_DIR = SCRIPT_DIR.parent / 'core'
MSG_TYPES = {
    'twist': 'geometry_msgs/msg/TwistStamped',
    'laser': 'sensor_msgs/msg/LaserScan',
    'odom': 'nav_msgs/msg/Odometry',
}
# 앞 5개는 처음 측정한 조건, 뒤 3개는 실제 토픽의 주기(/odom 약 30Hz, /scan 약 10Hz, 명령 20Hz).
CONDITIONS = (('twist', 10.0), ('twist', 100.0), ('twist', 300.0),
              ('laser', 5.0), ('laser', 20.0),
              ('odom', 30.0), ('laser', 10.0), ('twist', 20.0))
ALL_PATHS = ('direct', 'dds_bridge', 'mqtt_q0', 'mqtt_q1')
RESULT_MARK = 'RESULT '
SINK_TAIL_SEC = 2.0
STOP_WAIT_SEC = 5.0

LO_ONLY_URI = (
    '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces>'
    '<AllowMulticast>false</AllowMulticast></General><Discovery><Peers>'
    '<Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>')

LOGGER = logging.getLogger('mqtt_bench_run')


def parse_args(argv=None):
    """명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(description='중계 경로 비교 러너 (로컬 전용)')
    parser.add_argument('--paths', nargs='+', choices=ALL_PATHS, default=list(ALL_PATHS))
    parser.add_argument('--reps', type=int, default=2, help='조건마다 반복 횟수')
    parser.add_argument('--duration', type=float, default=8.0, help='발행 시간 [s]')
    parser.add_argument('--setup-sec', type=float, default=3.0, help='발견 대기 [s]')
    parser.add_argument('--source-domain', type=int, default=101)
    parser.add_argument('--sink-domain', type=int, default=102)
    parser.add_argument('--broker-host', default='127.0.0.1')
    parser.add_argument('--broker-port', type=int, default=1883)
    parser.add_argument('--only', nargs='*', default=[],
                        help='조건 필터. 예: twist:100 laser:20. 비우면 전부')
    parser.add_argument('--out', default='', help='원자료 JSON 저장 경로')
    return parser.parse_args(argv)


def base_env(domain):
    """자식 프로세스 환경. DDS 를 loopback 에만 묶어 선로로 아무것도 나가지 않게 한다."""
    env = dict(os.environ)
    env['ROS_DOMAIN_ID'] = str(domain)
    env.pop('ROS_AUTOMATIC_DISCOVERY_RANGE', None)
    env.pop('ROS_LOCALHOST_ONLY', None)
    # ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST 만으로는 부족하다. 이 PC 처럼 CYCLONEDDS_URI 가
    # Wi-Fi 인터페이스와 피어를 지정하면 그 설정이 이겨서 약 11 KB/s 가 Wi-Fi 로 샌다.
    env['CYCLONEDDS_URI'] = LO_ONLY_URI
    return env


def spawn(cmd, domain, directory):
    """
    프로세스를 새 세션으로 띄운다. 나중에 그룹째 정리하기 위해서다.

    출력은 파이프가 아니라 파일로 받는다. 파이프는 아무도 읽지 않으면 64 KB 에서 차서
    쓰는 쪽(중계의 로그 줄)이 멈추고, 그러면 측정값이 실제보다 나쁘게 나온다.
    """
    log_file = tempfile.NamedTemporaryFile(
        mode='w', dir=directory, prefix='proc_', suffix='.log', delete=False)
    proc = subprocess.Popen(
        cmd, env=base_env(domain), stdout=log_file, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    log_file.close()
    proc.log_path = log_file.name
    return proc


def read_log(proc):
    """프로세스가 파일에 남긴 출력을 읽는다."""
    return Path(proc.log_path).read_text(encoding='utf-8', errors='replace')


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
    """프로세스가 스스로 끝나길 timeout 초 기다린다. 못 끝나면 강제로 멈추고 출력을 돌려준다."""
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


def cpu_seconds(proc):
    """프로세스와 자식이 지금까지 쓴 CPU 시간 합계 [s]."""
    total = 0.0
    try:
        parent = psutil.Process(proc.pid)
        for item in [parent] + parent.children(recursive=True):
            times = item.cpu_times()
            total += times.user + times.system
    except psutil.NoSuchProcess:
        pass
    return total


def bridge_yaml(directory, msg, args):
    """시험용 DDS 브릿지 설정을 쓴다. /bench/ 토픽 하나만 담는다."""
    topic = f'/bench/{msg}'
    path = Path(directory) / 'bench_bridge.yaml'
    path.write_text(
        'name: bench_bridge\ntopics:\n'
        f'  {topic}:\n    type: {MSG_TYPES[msg]}\n'
        f'    from_domain: {args.source_domain}\n    to_domain: {args.sink_domain}\n',
        encoding='utf-8')
    return path


def run_once(path_name, msg, rate, args, directory):
    """조건 하나를 한 번 실행하고 결과 사전을 돌려준다."""
    stream = str(SCRIPT_DIR / 'mqtt_bench_stream.py')
    relay = str(CORE_DIR / 'mqtt_ros_relay.py')
    src_topic = f'/bench/{msg}'
    infra = []
    if path_name == 'direct':
        sink_domain, sink_topic = args.source_domain, src_topic
    elif path_name == 'dds_bridge':
        sink_domain, sink_topic = args.sink_domain, src_topic
        yaml_path = bridge_yaml(directory, msg, args)
        infra.append(spawn(['ros2', 'run', 'cobot_domain_bridge', 'domain_bridge',
                            str(yaml_path)], args.source_domain, directory))
    else:
        qos = path_name[-1]
        sink_domain, sink_topic = args.sink_domain, f'/mqtt_test/bench/{msg}'
        mqtt_topic = f'mqtt_learning/bench/{msg}'
        common = ['--msg-type', MSG_TYPES[msg], '--mqtt-topic', mqtt_topic,
                  '--mqtt-qos', qos, '--host', args.broker_host,
                  '--port', str(args.broker_port),
                  '--duration', str(args.duration + 20)]
        infra.append(spawn([sys.executable, relay, '--direction', 'ros2mqtt',
                            '--ros-topic', src_topic, '--max-rate-hz', '0'] + common,
                           args.source_domain, directory))
        infra.append(spawn([sys.executable, relay, '--direction', 'mqtt2ros',
                            '--ros-out-topic', sink_topic] + common, args.sink_domain, directory))
    sink = source = None
    try:
        time.sleep(1.0)
        sink = spawn([sys.executable, stream, '--role', 'sink', '--msg', msg,
                      '--topic', sink_topic,
                      '--duration', str(args.setup_sec + args.duration + SINK_TAIL_SEC)],
                     sink_domain, directory)
        time.sleep(args.setup_sec)
        source = spawn([sys.executable, stream, '--role', 'source', '--msg', msg,
                        '--topic', src_topic, '--rate-hz', str(rate),
                        '--duration', str(args.duration)], args.source_domain, directory)
        cpu_start = [cpu_seconds(proc) for proc in infra]
        time.sleep(args.duration)
        cpu_used = sum(cpu_seconds(p) - s for p, s in zip(infra, cpu_start))
        # 두 스크립트는 --duration 이 지나면 스스로 RESULT 를 쓰고 끝난다. 그때까지 기다린다.
        source_out = finish(source, STOP_WAIT_SEC)
        sink_out = finish(sink, SINK_TAIL_SEC + STOP_WAIT_SEC)
    finally:
        for proc in [source, sink] + infra:
            if proc is not None:
                stop(proc)
    sent = parse_result(source_out)
    got = parse_result(sink_out)
    published = sent.get('published', 0)
    received = got.get('unique', 0)
    return {
        'path': path_name, 'msg': msg, 'rate_hz': rate,
        'published': published, 'achieved_hz': sent.get('achieved_hz', 0.0),
        'received': got.get('received', 0), 'unique': received,
        'delivered_pct': round(100.0 * received / published, 2) if published else 0.0,
        'p50_ms': got.get('p50_ms', 0.0), 'p95_ms': got.get('p95_ms', 0.0),
        'max_ms': got.get('max_ms', 0.0),
        'cpu_pct': round(100.0 * cpu_used / args.duration, 1),
    }


def summarize(rows):
    """같은 (경로, 메시지, 발행율) 행들을 평균 내서 표용 사전으로 돌려준다."""
    keys = ('achieved_hz', 'delivered_pct', 'p50_ms', 'p95_ms', 'max_ms', 'cpu_pct')
    out = {'path': rows[0]['path'], 'msg': rows[0]['msg'], 'rate_hz': rows[0]['rate_hz'],
           'reps': len(rows)}
    for key in keys:
        out[key] = round(statistics.mean(row[key] for row in rows), 2)
    return out


def select_conditions(only):
    """--only 필터를 적용한 (메시지, 발행율) 목록."""
    if not only:
        return list(CONDITIONS)
    wanted = {tuple(item.split(':')) for item in only}
    return [(msg, rate) for msg, rate in CONDITIONS if (msg, str(int(rate))) in wanted]


def main(argv=None):
    """모든 조건을 돌리고 표를 로그로 남긴다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    args = parse_args(argv)
    conditions = select_conditions(args.only)
    if not conditions:
        LOGGER.error('--only 에 맞는 조건이 없다')
        return EXIT_SETUP_FAILED
    raw = []
    with tempfile.TemporaryDirectory(prefix='mqtt_bench_') as directory:
        for msg, rate in conditions:
            for path_name in args.paths:
                rows = []
                for rep in range(args.reps):
                    row = run_once(path_name, msg, rate, args, directory)
                    rows.append(row)
                    raw.append(row)
                    LOGGER.info('원자료 %s', json.dumps(row))
                    time.sleep(1.0)
                LOGGER.info('평균 %s', json.dumps(summarize(rows)))
    if args.out:
        Path(args.out).write_text(json.dumps(raw, indent=1), encoding='utf-8')
        LOGGER.info('원자료 저장: %s', args.out)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
