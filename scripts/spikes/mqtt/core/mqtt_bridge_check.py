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
MQTT 학습: 도메인 브릿지 설정(yaml)의 토픽 전부가 MQTT 로 제대로 오가는지 확인하는 스크립트.

왜 필요한가: 토픽을 하나씩 손으로 띄워 보면 21개를 확인하기 어렵다. 설정 파일을 읽어 토픽마다
같은 시험을 자동으로 돌리고, 결과를 표로 낸다.

두 가지 확인 방법 (--mode):
  fake: 토픽 이름·타입은 설정 파일 그대로지만 **가짜 메시지**를 격리 도메인(loopback)에서 보낸다.
        모든 필드를 알아볼 수 있는 값으로 채워 보내고, 도착한 값을 필드마다 비교한다.
        실제 로봇 도메인(10)과 실제 토픽을 쓰지 않으므로 명령 방향 토픽도 안전하다.
        도착한 쪽의 이름은 /mqtt_test/check/<목적지 이름> 이다.
  live: 로봇→관제 방향 토픽만, pinky1 도메인 10 을 **읽기 전용으로 구독**해 실제 값이 흐르는지
        본다 (승인된 예외 범위). 발행하는 노드가 꺼져 있으면 '발행 없음' 으로 표시한다.

serve 역할: 점검 대신 **중계를 계속 켜 둔다.** 로봇→관제 토픽(래치 토픽 제외)을 토픽마다
  pinky1(도메인 10, 읽기 전용, 상한 --serve-rate-hz) → MQTT → 이 PC(도메인 102, loopback)로 올려
  /mqtt_test/pinky1<원래 이름> 으로 보이게 한다. --serve-sec 가 지나거나 Ctrl+C 로 끝난다.

역할 (--role): run(관제 PC 에서 도는 오케스트레이터) / serve / pub / sink. pub·sink 는 run 이 알아서 띄우고,
pinky1 쪽은 이 파일을 ssh stdin 으로 흘려 보내 실행한다 (pinky1 에 파일을 남기지 않는다).

종료 코드: 0 = 완료 (표의 FAIL 여부와 무관), 2 = 설정 오류.

안전:
  - fake 모드는 loopback 전용 DDS 설정을 써서 선로와 실물 도메인으로 아무것도 나가지 않는다.
    관제→로봇 방향도 pinky1 의 /mqtt_test/ 토픽에만 도착하고 실제 /cmd_vel 등에는 가지 않는다.
  - live 모드는 pinky1 도메인 10 에서 구독만 한다. 재발행은 관제 PC 의 도메인 102 에서만 한다.
  - 설정 파일은 읽기만 한다. 모든 프로세스에 --duration 이 있어 스스로 끝난다.

실행 (ROS 2 Jazzy 환경, SSH 터널이 열려 있어야 함):
    source /opt/ros/jazzy/setup.bash
    python3 scripts/spikes/mqtt/core/mqtt_bridge_check.py --role run --mode fake --out <저장 경로>.json
"""

import argparse
import array
import ast
import json
import logging
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time

EXIT_OK = 0
EXIT_SETUP_FAILED = 2

SCRIPT_DIR = Path(__file__).resolve().parent
# pinky1 에서는 이 파일이 ssh 입력(stdin)으로 실행되어 상위 폴더가 모자랄 수 있다.
# 설정 파일은 관제 PC 에서 도는 run·serve 에서만 읽으므로, 모자라면 현재 폴더 기준으로 둔다.
REPO_ROOT = SCRIPT_DIR.parents[3] if len(SCRIPT_DIR.parents) > 3 else SCRIPT_DIR
DEFAULT_CONFIG = (REPO_ROOT / 'src' / 'cobot_navigation' / 'cobot_domain_bridge'
                  / 'config' / 'pinky_bridge_pinky1.yaml')
ROBOT_DOMAIN = 10
OUT_PREFIX = '/mqtt_test/check'
LIVE_OUT_PREFIX = '/mqtt_test/live'
MQTT_PREFIX = 'mqtt_learning/check'
# 마지막 값을 래치(transient_local)하는 토픽. 가짜 발행도 같은 방식으로 한 번만 보낸다.
LATCHED_TOPICS = ('/tf_static', '/amcl_pose')
LATCHED_HEAD_START_SEC = 4.0
# 래치 토픽 중계에 붙이는 옵션 (마지막 값 보관 + 정적 TF 여러 건을 담을 깊이).
LATCH_RELAY_ARGS = ['--ros-durability', 'transient_local', '--ros-depth', '100']
LIVE_RECEIVER_EXTRA_SEC = 12.0
SERVE_OUT_PREFIX = '/mqtt_test/pinky1'
SERVE_STARTUP_SEC = 15.0
# 실제 도메인 100 에 올려도 되는 토픽 (읽기용 상태값만). 이 목록 밖은 이 모드에서 제외한다.
REAL_DOMAIN_TOPICS = (
    '/battery/percent', '/battery/voltage', '/patrol_status', '/battery_state',
    '/zone_manager/request_entry', '/zone_manager/notify_exit', '/zone_manager/cancel_entry')
# --include-fast 일 때만 더해지는 빠른 토픽. 전송 상한 5Hz 를 넘기지 못하고, 부하가 높으면 중단한다.
REAL_DOMAIN_FAST_TOPICS = ('/odom', '/scan')
# --include-latched 일 때만 더해지는 래치 토픽 (실제 도메인에서는 이것만 허용).
REAL_DOMAIN_LATCHED_TOPICS = ('/tf_static',)
FAST_RATE_LIMIT_HZ = 5.0
FAST_RATE_MAX_HZ = 30.0
LOSS_WARN_RATIO = 0.05
LOAD_ABORT = 3.0
LOAD_CHECK_SEC = 15.0
PUBLISHER_CHECK_CODE = """
import sys, time, rclpy
rclpy.init()
node = rclpy.create_node('mqtt_pub_check')
end = time.time() + 4.0
while time.time() < end:
    rclpy.spin_once(node, timeout_sec=0.1)
found = {}
for name in sys.argv[1:]:
    found[name] = len(node.get_publishers_info_by_topic(name))
print('PUBCOUNT', found)
node.destroy_node()
rclpy.shutdown()
"""
REAL_DOMAIN_DDS_CONFIG = Path.home() / '.ros' / 'cyclonedds_pc.xml'
SPIN_TIMEOUT_SEC = 0.01
SEQ_LEN_DEFAULT = 3
STOP_WAIT_SEC = 5.0
SUMMARY_RE = re.compile(r'받음 (\d+), 중계 (\d+)')
RESULT_MARK = 'RESULT '
# 시험 도메인. 두 장비 모두 DDS 를 loopback 에 묶는다. 장비 안에서만 의미가 있는 번호다.
PC_DOMAIN = 102
PINKY_DOMAIN = 101
LO_ONLY_URI = (
    '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces>'
    '<AllowMulticast>false</AllowMulticast></General><Discovery><Peers>'
    '<Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>')

LOGGER = logging.getLogger('mqtt_bridge_check')


def parse_args(argv=None):
    """명령행 인자를 읽는다."""
    parser = argparse.ArgumentParser(description='도메인 브릿지 토픽 전부의 MQTT 중계 확인')
    parser.add_argument('--role', choices=('run', 'serve', 'pub', 'sink'), default='run')
    parser.add_argument('--mode', choices=('fake', 'live'), default='fake')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG), help='run: 브릿지 yaml')
    parser.add_argument('--only', nargs='*', default=[], help='run: 이 토픽만 (예: /battery/percent)')
    parser.add_argument('--batch-size', type=int, default=4, help='run: 동시에 확인할 토픽 수')
    parser.add_argument('--window-sec', type=float, default=12.0, help='run: 토픽당 시험 구간 [s]')
    parser.add_argument('--setup-sec', type=float, default=7.0, help='run: 프로세스 시작 대기 [s]')
    parser.add_argument('--pinky-host', default='pinky@192.168.45.21')
    parser.add_argument('--min-ok', type=int, default=5, help='run: 통과에 필요한 일치 건수')
    parser.add_argument('--out', default='', help='run: 원자료 JSON 저장 경로')
    parser.add_argument('--serve-sec', type=float, default=600.0,
                        help='serve: 중계를 유지할 시간 [s]')
    parser.add_argument('--exact-names', action='store_true',
                        help='serve: 브릿지 yaml 의 도착 이름 그대로 발행 (도메인 102 전용)')
    parser.add_argument('--real-domain', type=int, choices=(100,), default=0,
                        help='serve: 실제 관제 도메인 100 에 원래 이름으로 발행 '
                             '(화이트리스트 토픽만, 같은 이름의 다른 발행자가 있으면 중단)')
    parser.add_argument('--include-fast', action='store_true',
                        help='serve --real-domain: /odom, /scan 도 올림 (상한 5Hz, 부하 3.0 초과 시 중단)')
    parser.add_argument('--include-latched', action='store_true',
                        help='serve: 래치 토픽(/amcl_pose, /tf_static)도 올림. 실제 도메인에서는 '
                             '/tf_static 만 허용. 끝나면 브로커의 보관 메시지를 지움')
    parser.add_argument('--fast-rate-hz', type=float, default=None,
                        help='serve --include-fast: /odom, /scan 만의 전송 상한 [Hz]. '
                             '0 이면 제한 없음, 기본은 --serve-rate-hz')
    parser.add_argument('--serve-rate-hz', type=float, default=5.0,
                        help='serve: pinky1 쪽 토픽당 전송 상한 [Hz]')
    parser.add_argument('--msg-type', default='', help='pub/sink: 예: std_msgs/msg/String')
    parser.add_argument('--topic', default='', help='pub/sink: ROS 토픽')
    parser.add_argument('--rate-hz', type=float, default=5.0, help='pub: 발행율 [Hz]')
    parser.add_argument('--duration', type=float, default=15.0, help='pub/sink: 실행 시간 [s]')
    parser.add_argument('--latched', action='store_true',
                        help='pub: transient_local 1회 발행 / sink: transient_local 구독')
    parser.add_argument('--seq-len', type=int, default=SEQ_LEN_DEFAULT, help='가변 배열 길이')
    return parser.parse_args(argv)


class Filler:
    """메시지의 모든 필드를 알아볼 수 있는 값으로 채운다. 같은 순서로 채우면 항상 같은 값이다."""

    def __init__(self, seq_len):
        self._seq_len = seq_len
        self._count = 0

    def _next(self):
        self._count += 1
        return self._count

    def fill(self, msg):
        """메시지를 채워서 돌려준다."""
        for name, ftype in msg.get_fields_and_field_types().items():
            setattr(msg, name, self._value(getattr(msg, name), ftype))
        return msg

    def _scalar(self, current):
        number = self._next()
        if isinstance(current, bool):
            return True
        if isinstance(current, int):
            return number % 100 + 1
        if isinstance(current, float):
            return number * 0.25
        if isinstance(current, str):
            return f's{number}'
        if isinstance(current, bytes):
            return bytes([number % 100 + 1])
        raise TypeError(f'채울 수 없는 타입: {type(current)}')

    @staticmethod
    def _proto(inner):
        if inner in ('float', 'double'):
            return 0.0
        if inner in ('string', 'wstring'):
            return ''
        if inner == 'boolean':
            return False
        return 0

    def _value(self, current, ftype):
        if ftype.startswith('sequence<'):
            inner = ftype[len('sequence<'):-1].split(',')[0].strip()
            return self._sequence(current, inner, self._seq_len)
        if ftype.endswith(']') and '[' in ftype:
            inner, _, size = ftype[:-1].partition('[')
            return self._sequence(current, inner, int(size) if size.isdigit() else self._seq_len)
        if hasattr(current, 'get_fields_and_field_types'):
            return self.fill(current)
        return self._scalar(current)

    def _sequence(self, current, inner, count):
        if '/' in inner:
            from rosidl_runtime_py.utilities import get_message
            parts = inner.split('/')
            full = f'{parts[0]}/msg/{parts[-1]}'
            return [self.fill(get_message(full)()) for _ in range(count)]
        items = [self._scalar(self._proto(inner)) for _ in range(count)]
        if isinstance(current, array.array):
            return array.array(current.typecode, items)
        return items


def to_jsonable(value):
    """JSON 이 모르는 타입(numpy 배열 등)을 리스트로 바꾼다."""
    if hasattr(value, 'tolist'):
        return value.tolist()
    raise TypeError(f'JSON 으로 바꿀 수 없는 타입: {type(value)}')


def normalize(msg):
    """메시지를 비교 가능한 순수 파이썬 구조(사전·리스트)로 바꾼다."""
    from rosidl_runtime_py.convert import message_to_ordereddict
    return json.loads(json.dumps(message_to_ordereddict(msg), default=to_jsonable))


def first_diff(left, right, path=''):
    """두 구조가 처음 다른 곳을 설명하는 문장을 돌려준다. 같으면 빈 문자열."""
    if isinstance(left, dict) and isinstance(right, dict):
        for key in left:
            if key not in right:
                return f'{path}/{key} 없음'
            found = first_diff(left[key], right[key], f'{path}/{key}')
            if found:
                return found
        return ''
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f'{path} 길이 {len(left)} 대 {len(right)}'
        for index, (item_l, item_r) in enumerate(zip(left, right)):
            found = first_diff(item_l, item_r, f'{path}[{index}]')
            if found:
                return found
        return ''
    if isinstance(left, float) and isinstance(right, float) and math.isclose(left, right):
        return ''
    return '' if left == right else f'{path}: {left!r} 대 {right!r}'


def run_pub(args):
    """가짜 메시지를 발행한다. 결과를 RESULT 줄로 남긴다."""
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from rosidl_runtime_py.utilities import get_message
    msg_class = get_message(args.msg_type)
    expected = Filler(args.seq_len).fill(msg_class())
    durability = DurabilityPolicy.TRANSIENT_LOCAL if args.latched else DurabilityPolicy.VOLATILE
    qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=durability)
    rclpy.init()
    node = rclpy.create_node('check_pub')
    publisher = node.create_publisher(msg_class, args.topic, qos)
    published = 0
    start = time.monotonic()
    next_send = start + 1.0
    deadline = start + args.duration
    while rclpy.ok() and time.monotonic() < deadline:
        if time.monotonic() >= next_send and not (args.latched and published >= 1):
            publisher.publish(expected)
            published += 1
            next_send += 1.0 / args.rate_hz
        rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
    LOGGER.info('%s%s', RESULT_MARK, json.dumps({'role': 'pub', 'published': published}))
    node.destroy_node()
    rclpy.shutdown()
    return EXIT_OK


def run_sink(args):
    """도착한 메시지를 기대한 값과 비교한다. 결과를 RESULT 줄로 남긴다."""
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from rosidl_runtime_py.utilities import get_message
    msg_class = get_message(args.msg_type)
    durability = DurabilityPolicy.TRANSIENT_LOCAL if args.latched else DurabilityPolicy.VOLATILE
    expected = normalize(Filler(args.seq_len).fill(msg_class()))
    state = {'received': 0, 'ok': 0, 'mismatch': 0, 'first': ''}

    def on_message(msg):
        """받을 때마다 기대한 값과 비교한다."""
        state['received'] += 1
        found = first_diff(expected, normalize(msg))
        if found:
            state['mismatch'] += 1
            state['first'] = state['first'] or found
        else:
            state['ok'] += 1

    rclpy.init()
    node = rclpy.create_node('check_sink')
    node.create_subscription(
        msg_class, args.topic, on_message,
        QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE, durability=durability))
    deadline = time.monotonic() + args.duration
    while rclpy.ok() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=SPIN_TIMEOUT_SEC)
    LOGGER.info('%s%s', RESULT_MARK, json.dumps(
        {'role': 'sink', 'received': state['received'], 'ok': state['ok'],
         'mismatch': state['mismatch'], 'first_mismatch': state['first']}))
    node.destroy_node()
    rclpy.shutdown()
    return EXIT_OK


def load_topics(config_path, only):
    """브릿지 yaml 에서 (이름, 타입, 출발 도메인, 도착 도메인, 도착 이름) 목록을 읽는다."""
    import yaml
    data = yaml.safe_load(Path(config_path).read_text(encoding='utf-8'))
    topics = []
    for name, spec in (data.get('topics') or {}).items():
        if only and name not in only:
            continue
        topics.append({
            'name': name, 'type': spec['type'],
            'from_domain': int(spec['from_domain']), 'to_domain': int(spec['to_domain']),
            'dest_name': spec.get('remap') or name})
    return topics


def env_for(domain, lo_only):
    """자식 프로세스 환경변수 사전."""
    env = dict(os.environ)
    env['ROS_DOMAIN_ID'] = str(domain)
    env.pop('ROS_LOCALHOST_ONLY', None)
    env.pop('ROS_AUTOMATIC_DISCOVERY_RANGE', None)
    if lo_only:
        env['CYCLONEDDS_URI'] = LO_ONLY_URI
    return env


def spawn_local(cmd, domain, lo_only, directory):
    """이 PC 에서 프로세스를 띄운다. 출력은 파이프가 아니라 파일로 받는다."""
    log_file = tempfile.NamedTemporaryFile(
        mode='w', dir=directory, prefix='chk_', suffix='.log', delete=False)
    proc = subprocess.Popen(
        cmd, env=env_for(domain, lo_only), stdout=log_file, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    log_file.close()
    proc.log_path = log_file.name
    return proc


def spawn_remote(args, script, script_args, domain, lo_only, directory):
    """pinky1 에서 스크립트를 stdin 으로 실행한다. 파일을 복사하지 않는다."""
    parts = ['source /opt/ros/jazzy/setup.bash;',
             f'export ROS_DOMAIN_ID={domain} RMW_IMPLEMENTATION=rmw_cyclonedds_cpp']
    if lo_only:
        parts.append(f'CYCLONEDDS_URI={shlex.quote(LO_ONLY_URI)}')
    remote = ' '.join(parts) + f'; python3 - {shlex.join(script_args)}'
    log_file = tempfile.NamedTemporaryFile(
        mode='w', dir=directory, prefix='chk_remote_', suffix='.log', delete=False)
    with open(script, encoding='utf-8') as stdin_file:
        proc = subprocess.Popen(
            ['ssh', '-o', 'BatchMode=yes', args.pinky_host, remote], stdin=stdin_file,
            stdout=log_file, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    log_file.close()
    proc.log_path = log_file.name
    return proc


def spawn_on(side, args, script, script_args, domain, lo_only, directory):
    """장비 구분이 'pc' 면 이 PC 에서, 'pinky' 면 pinky1 에서 실행한다."""
    if side == 'pc':
        return spawn_local([sys.executable, str(script)] + script_args, domain, lo_only,
                           directory)
    return spawn_remote(args, script, script_args, domain, lo_only, directory)


def stop(proc):
    """프로세스 그룹에 종료 신호를 보내고 출력을 돌려준다."""
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
    return Path(proc.log_path).read_text(encoding='utf-8', errors='replace')


def finish(proc, timeout):
    """프로세스가 스스로 끝나길 기다린다. 못 끝나면 멈추고 출력을 돌려준다."""
    try:
        proc.wait(timeout=timeout)
        return Path(proc.log_path).read_text(encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        return stop(proc)


def parse_result(output):
    """출력에서 RESULT JSON 한 줄을 찾아 사전으로 돌려준다. 없으면 빈 사전."""
    for line in output.splitlines():
        if RESULT_MARK in line:
            return json.loads(line.split(RESULT_MARK, 1)[1])
    return {}


def parse_summary(output):
    """중계 요약 줄에서 (받음, 중계) 건수를 찾는다. 없으면 (None, None)."""
    found = SUMMARY_RE.search(output)
    return (int(found.group(1)), int(found.group(2))) if found else (None, None)


def side_of(domain):
    """브릿지 설정의 도메인 번호를 어느 장비인지로 바꾼다. 10 은 pinky1, 그 외는 이 PC."""
    return 'pinky' if domain == ROBOT_DOMAIN else 'pc'


def test_domain(side):
    """시험용 격리 도메인."""
    return PINKY_DOMAIN if side == 'pinky' else PC_DOMAIN


def sanitize(name):
    """토픽 이름을 MQTT 토픽에 쓸 수 있는 문자열로 바꾼다."""
    return name.strip('/').replace('/', '_')


def start_fake_pub(topic, args, directory):
    """가짜 발행 방식: 출발 쪽에서 가짜 메시지를 발행하는 프로세스를 띄운다."""
    stream = SCRIPT_DIR / 'mqtt_bridge_check.py'
    src_side = side_of(topic['from_domain'])
    latched = topic['name'] in LATCHED_TOPICS
    total = args.window_sec + args.setup_sec + LATCHED_HEAD_START_SEC + 2.0
    pub_args = ['--role', 'pub', '--msg-type', topic['type'], '--topic', topic['name'],
                '--duration', str(total), '--seq-len', str(args.seq_len)]
    if latched:
        pub_args.append('--latched')
    return {'pub': spawn_on(src_side, args, stream, pub_args, test_domain(src_side), True,
                            directory)}


def start_fake_relays(topic, args, directory):
    """가짜 발행 방식의 중계 두 개와 확인 프로세스를 띄운다."""
    stream = SCRIPT_DIR / 'mqtt_bridge_check.py'
    relay = SCRIPT_DIR / 'mqtt_ros_relay.py'
    src_side, dst_side = side_of(topic['from_domain']), side_of(topic['to_domain'])
    out_topic = OUT_PREFIX + topic['dest_name']
    mqtt_topic = f'{MQTT_PREFIX}/{sanitize(topic["name"])}'
    total = args.window_sec + args.setup_sec
    relay_common = ['--msg-type', topic['type'], '--mqtt-topic', mqtt_topic,
                    '--host', '127.0.0.1', '--duration', str(total)]
    latched = topic['name'] in LATCHED_TOPICS
    latch_args = LATCH_RELAY_ARGS if latched else []
    procs = {}
    procs['dst_relay'] = spawn_on(
        dst_side, args, relay,
        ['--direction', 'mqtt2ros', '--ros-out-topic', out_topic] + latch_args + relay_common,
        test_domain(dst_side), True, directory)
    procs['sink'] = spawn_on(
        dst_side, args, stream,
        ['--role', 'sink', '--msg-type', topic['type'], '--topic', out_topic,
         '--duration', str(total), '--seq-len', str(args.seq_len)]
        + (['--latched'] if latched else []),
        test_domain(dst_side), True, directory)
    procs['src_relay'] = spawn_on(
        src_side, args, relay,
        ['--direction', 'ros2mqtt', '--ros-topic', topic['name'], '--max-rate-hz', '0']
        + latch_args + (['--mqtt-retain'] if latched else []) + relay_common,
        test_domain(src_side), True, directory)
    return procs


def start_live(topic, args, directory):
    """실제 토픽 방식: pinky1 도메인 10 읽기 전용 구독 + 이 PC 의 재발행 프로세스를 띄운다."""
    relay = SCRIPT_DIR / 'mqtt_ros_relay.py'
    out_topic = LIVE_OUT_PREFIX + topic['dest_name']
    mqtt_topic = f'mqtt_learning/live/{sanitize(topic["name"])}'
    total = args.window_sec + args.setup_sec
    common = ['--msg-type', topic['type'], '--mqtt-topic', mqtt_topic, '--host', '127.0.0.1']
    procs = {}
    # 받는 쪽(이 PC)이 먼저 시작하고 pinky1 쪽은 ssh·import 때문에 늦게 시작한다. 받는 쪽을
    # 보내는 쪽보다 더 오래 살려 두지 않으면 마지막 몇 초분이 '유실' 로 잘못 집계된다.
    procs['dst_relay'] = spawn_local(
        [sys.executable, str(relay), '--direction', 'mqtt2ros', '--ros-out-topic', out_topic,
         '--duration', str(total + LIVE_RECEIVER_EXTRA_SEC)] + common, PC_DOMAIN, True, directory)
    procs['src_relay'] = spawn_remote(
        args, relay,
        ['--direction', 'ros2mqtt', '--ros-topic', topic['name'], '--max-rate-hz', '5',
         '--duration', str(total)] + common, ROBOT_DOMAIN, False, directory)
    return procs


def judge_fake(topic, row, args):
    """가짜 발행 방식의 결과로 통과 여부와 사유를 정한다."""
    latched = topic['name'] in LATCHED_TOPICS
    need = 1 if latched else args.min_ok
    if row['ok'] >= need and row['mismatch'] == 0:
        return 'PASS', ''
    if row['mismatch']:
        return 'FAIL', f'값 불일치: {row["first_mismatch"]}'
    if latched:
        return 'FAIL', '래치 토픽의 마지막 값을 못 받음'
    return 'FAIL', f'도착 {row["received"]}건 (필요 {need}건)'


def judge_live(row):
    """실제 토픽 방식의 결과로 통과 여부와 사유를 정한다."""
    if not row['src_in']:
        return 'NO-DATA', '지금 발행하는 노드가 없음 (또는 래치 토픽)'
    if row['dst_out'] and row['dst_out'] >= row['src_out'] - 1:
        return 'PASS', ''
    return 'FAIL', f'로봇 중계 {row["src_out"]}건, 관제 재발행 {row["dst_out"]}건'


def collect(topic, procs, args):
    """프로세스들이 끝나길 기다려 결과 행을 만든다."""
    wait = args.window_sec + args.setup_sec + LATCHED_HEAD_START_SEC + STOP_WAIT_SEC + 15.0
    outputs = {key: finish(proc, wait) for key, proc in procs.items()}
    src_in, src_out = parse_summary(outputs.get('src_relay', ''))
    dst_in, dst_out = parse_summary(outputs.get('dst_relay', ''))
    row = {'topic': topic['name'], 'type': topic['type'],
           'direction': '로봇→관제' if topic['from_domain'] == ROBOT_DOMAIN else '관제→로봇',
           'dest': topic['dest_name'], 'src_in': src_in, 'src_out': src_out,
           'dst_in': dst_in, 'dst_out': dst_out}
    if args.mode == 'fake':
        pub = parse_result(outputs.get('pub', ''))
        sink = parse_result(outputs.get('sink', ''))
        row.update({'published': pub.get('published', 0), 'received': sink.get('received', 0),
                    'ok': sink.get('ok', 0), 'mismatch': sink.get('mismatch', 0),
                    'first_mismatch': sink.get('first_mismatch', '')})
        row['status'], row['reason'] = judge_fake(topic, row, args)
    else:
        row['status'], row['reason'] = judge_live(row)
    return row


def run_batch(batch, args, directory):
    """토픽 몇 개를 동시에 확인하고 결과 행 목록을 돌려준다."""
    started = []
    if args.mode == 'fake':
        # 발행자를 먼저 띄운다. 래치 토픽은 값을 쥔 채 기다려야, 늦게 붙는 중계가 그 값을
        # 받는지(= 현재 중계의 한계) 드러난다.
        for topic in batch:
            started.append((topic, start_fake_pub(topic, args, directory)))
            time.sleep(0.3)
        time.sleep(LATCHED_HEAD_START_SEC)
        for topic, procs in started:
            procs.update(start_fake_relays(topic, args, directory))
            time.sleep(0.3)
    else:
        for topic in batch:
            started.append((topic, start_live(topic, args, directory)))
            time.sleep(0.3)
    return [collect(topic, procs, args) for topic, procs in started]


def check_tunnel(args):
    """pinky1 에서 127.0.0.1:1883 (SSH 터널로 이어진 브로커) 에 닿는지 확인한다."""
    code = ('import socket,sys\ns=socket.socket();s.settimeout(3)\n'
            'try:\n s.connect(("127.0.0.1",1883));sys.exit(0)\nexcept OSError:\n sys.exit(1)\n')
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.pinky_host, 'python3', '-c',
                             shlex.quote(code)], capture_output=True, text=True, check=False)
    return result.returncode == 0


def run_all(args):
    """모든 토픽을 배치로 확인하고 표를 로그로 남긴다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    topics = load_topics(args.config, args.only)
    if args.mode == 'live':
        topics = [item for item in topics if item['from_domain'] == ROBOT_DOMAIN]
    if not topics:
        LOGGER.error('확인할 토픽이 없다 (--config, --only 확인)')
        return EXIT_SETUP_FAILED
    if not check_tunnel(args):
        LOGGER.error('pinky1 의 127.0.0.1:1883 에 닿지 않는다. SSH 역방향 터널을 먼저 열어야 한다')
        return EXIT_SETUP_FAILED
    LOGGER.info('시작 mode=%s 토픽 %d개 (배치 %d개씩)', args.mode, len(topics), args.batch_size)
    rows = []
    with tempfile.TemporaryDirectory(prefix='mqtt_bridge_check_') as directory:
        for index in range(0, len(topics), args.batch_size):
            batch = topics[index:index + args.batch_size]
            LOGGER.info('배치 %d: %s', index // args.batch_size + 1,
                        ', '.join(item['name'] for item in batch))
            for row in run_batch(batch, args, directory):
                rows.append(row)
                LOGGER.info('결과 %s', json.dumps(row, ensure_ascii=False))
            time.sleep(1.0)
    counts = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    LOGGER.info('요약 %s', json.dumps(counts, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                  encoding='utf-8')
        LOGGER.info('원자료 저장: %s', args.out)
    return EXIT_OK


def serve_pinky_load(args):
    """pinky1 의 부하(load average)와 중계 프로세스 수 한 줄. 실패하면 사유 문자열."""
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', args.pinky_host,
         'echo "load: $(cut -d" " -f1-3 /proc/loadavg) / 코어 $(nproc)"; '
         'echo "중계 프로세스: $(pgrep -fc "python3 - --direction ros2mqtt")"'],
        capture_output=True, text=True, check=False)
    return result.stdout.strip().replace('\n', ' / ') or result.stderr.strip()


def rate_for(topic, args):
    """토픽의 pinky1 쪽 전송 상한 [Hz]. 빠른 토픽은 --fast-rate-hz 가 있으면 그 값을 쓴다."""
    if topic['name'] in LATCHED_TOPICS:
        return 0.0
    if args.fast_rate_hz is not None and topic['name'] in REAL_DOMAIN_FAST_TOPICS:
        return args.fast_rate_hz
    return args.serve_rate_hz


def pinky_load1(args):
    """pinky1 의 1분 load average. 읽지 못하면 None."""
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', args.pinky_host,
         'cut -d" " -f1 /proc/loadavg'], capture_output=True, text=True, check=False)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def existing_publishers(domain, names):
    """실제 도메인에서 같은 이름의 발행자가 이미 있는 토픽 {이름: 수} 를 돌려준다. 읽기 전용."""
    result = subprocess.run(
        [sys.executable, '-c', PUBLISHER_CHECK_CODE] + names, env=env_for(domain, False),
        capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        if line.startswith('PUBCOUNT '):
            counts = ast.literal_eval(line[len('PUBCOUNT '):])
            return {key: val for key, val in counts.items() if val}
    LOGGER.error('발행자 확인 실패: %s', result.stderr.strip()[-200:])
    return None


def run_serve(args):
    """로봇→관제 토픽을 모두 MQTT 로 올려 두고 시간이 지나면 정리한다."""
    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    topics = [item for item in load_topics(args.config, args.only)
              if item['from_domain'] == ROBOT_DOMAIN
              and (args.include_latched or item['name'] not in LATCHED_TOPICS)]
    if not topics:
        LOGGER.error('올릴 토픽이 없다 (--config, --only 확인)')
        return EXIT_SETUP_FAILED
    domain = PC_DOMAIN
    if args.real_domain:
        domain = args.real_domain
        args.exact_names = True
        # 터미널에 LO 가 export 돼 있어도 실제 도메인은 관제 PC 의 정식 DDS 설정으로 연다.
        if not REAL_DOMAIN_DDS_CONFIG.exists():
            LOGGER.error('%s 가 없다. 실제 도메인 설정을 찾지 못했다', REAL_DOMAIN_DDS_CONFIG)
            return EXIT_SETUP_FAILED
        os.environ['CYCLONEDDS_URI'] = f'file://{REAL_DOMAIN_DDS_CONFIG}'
        allowed = (REAL_DOMAIN_TOPICS + (REAL_DOMAIN_FAST_TOPICS if args.include_fast else ())
                   + (REAL_DOMAIN_LATCHED_TOPICS if args.include_latched else ()))
        if args.include_fast and args.serve_rate_hz > FAST_RATE_LIMIT_HZ:
            LOGGER.error('빠른 토픽의 전송 상한은 %.0fHz 를 넘길 수 없다 (요청 %.1f)',
                         FAST_RATE_LIMIT_HZ, args.serve_rate_hz)
            return EXIT_SETUP_FAILED
        if args.fast_rate_hz is not None and not args.include_fast:
            LOGGER.error('--fast-rate-hz 는 --include-fast 와 함께만 쓴다')
            return EXIT_SETUP_FAILED
        if args.fast_rate_hz is not None and not 0 <= args.fast_rate_hz <= FAST_RATE_MAX_HZ:
            LOGGER.error('--fast-rate-hz 는 0(제한 없음) 이상 %.0f 이하여야 한다 (요청 %.1f)',
                         FAST_RATE_MAX_HZ, args.fast_rate_hz)
            return EXIT_SETUP_FAILED
        topics = [item for item in topics if item['name'] in allowed]
        if not topics:
            LOGGER.error('화이트리스트 토픽이 없다: %s', ', '.join(REAL_DOMAIN_TOPICS))
            return EXIT_SETUP_FAILED
        busy = existing_publishers(domain, [item['dest_name'] for item in topics])
        if busy is None or busy:
            LOGGER.error('도메인 %d 에 이미 발행자가 있어 중단한다 (브릿지가 켜져 있나?): %s',
                         domain, busy)
            return EXIT_SETUP_FAILED
        LOGGER.warning('실제 도메인 %d 에 발행한다: %s', domain,
                       ', '.join(item['dest_name'] for item in topics))
    elif args.exact_names:
        LOGGER.info('원래 이름으로 발행 (도메인 %d, loopback 전용)', PC_DOMAIN)
    if not check_tunnel(args):
        LOGGER.error('pinky1 의 127.0.0.1:1883 에 닿지 않는다. SSH 역방향 터널을 먼저 열어야 한다')
        return EXIT_SETUP_FAILED
    relay = SCRIPT_DIR / 'mqtt_ros_relay.py'
    total = args.serve_sec
    procs = []
    interrupted = True
    with tempfile.TemporaryDirectory(prefix='mqtt_bridge_serve_') as directory:
        try:
            # 받는 쪽(이 PC)을 먼저 띄우고 더 오래 살린다. 보내는 쪽은 ssh 때문에 늦게 시작한다.
            for topic in topics:
                common = ['--msg-type', topic['type'], '--host', '127.0.0.1', '--mqtt-topic',
                          f'mqtt_learning/serve/{sanitize(topic["name"])}']
                out_topic = topic['dest_name'] if args.exact_names else (
                    SERVE_OUT_PREFIX + topic['dest_name'])
                extra = ['--allow-any-out-topic'] if args.exact_names else []
                if args.real_domain:
                    extra += ['--confirm-real-domain', str(args.real_domain)]
                if topic['name'] in LATCHED_TOPICS:
                    extra += LATCH_RELAY_ARGS
                procs.append((topic, 'dst', spawn_local(
                    [sys.executable, str(relay), '--direction', 'mqtt2ros', '--ros-out-topic',
                     out_topic, '--duration', str(total + SERVE_STARTUP_SEC)] + extra + common,
                    domain, not args.real_domain, directory)))
            for topic in topics:
                common = ['--msg-type', topic['type'], '--host', '127.0.0.1', '--mqtt-topic',
                          f'mqtt_learning/serve/{sanitize(topic["name"])}']
                latch = (LATCH_RELAY_ARGS + ['--mqtt-retain']
                         if topic['name'] in LATCHED_TOPICS else [])
                procs.append((topic, 'src', spawn_remote(
                    args, relay, ['--direction', 'ros2mqtt', '--ros-topic', topic['name'],
                                  '--max-rate-hz', str(rate_for(topic, args)), '--duration',
                                  str(total)] + latch + common, ROBOT_DOMAIN, False,
                    directory)))
            LOGGER.info('토픽 %d개 중계 시작 (%.0f초). 이 PC 도메인 %d, 이름 %s<원래 이름>',
                        len(topics), total, domain,
                        '' if args.exact_names else SERVE_OUT_PREFIX)
            time.sleep(SERVE_STARTUP_SEC)
            LOGGER.info('pinky1 부하 %s', serve_pinky_load(args))
            aborted = False
            end = time.monotonic() + max(0.0, total - SERVE_STARTUP_SEC)
            while time.monotonic() < end:
                time.sleep(min(LOAD_CHECK_SEC, max(0.0, end - time.monotonic())))
                load = pinky_load1(args)
                if load is not None and load > LOAD_ABORT:
                    LOGGER.error('pinky1 load %.2f > %.1f 이라 중단한다', load, LOAD_ABORT)
                    aborted = True
                    break
                LOGGER.info('pinky1 load %s', load)
            interrupted = aborted
        except KeyboardInterrupt:
            LOGGER.info('중단 요청. 정리한다')
            interrupted = True
        finally:
            if interrupted:
                # 로컬 ssh 만 죽고 pinky1 의 구독 프로세스가 --duration 까지 남는 것을 막는다.
                subprocess.run(
                    ['ssh', '-o', 'BatchMode=yes', args.pinky_host,
                     "pkill -INT -f '^python3 - --direction ros2mqtt'"],
                    capture_output=True, check=False)
            counts = {}
            for topic in topics:
                if topic['name'] in LATCHED_TOPICS:
                    # 브로커에 남은 보관 메시지를 지운다 (다음 실행이 옛 값을 받지 않게).
                    subprocess.run(
                        ['mosquitto_pub', '-h', '127.0.0.1', '-r', '-n', '-t',
                         f'mqtt_learning/serve/{sanitize(topic["name"])}'],
                        capture_output=True, check=False)
            for topic, side, proc in procs:
                # 정상 종료면 스스로 끝나며 요약을 남기길 기다린다. 중단이면 바로 멈춘다.
                output = stop(proc) if interrupted else finish(proc, SERVE_STARTUP_SEC + 10.0)
                received, relayed = parse_summary(output)
                LOGGER.info('요약 %-34s %s 받음 %s 중계 %s', topic['name'], side, received,
                            relayed)
                counts[(topic['name'], side)] = (received, relayed)
            for topic in topics:
                sent = counts.get((topic['name'], 'src'), (None, None))[1]
                got = counts.get((topic['name'], 'dst'), (None, None))[0]
                if sent and got is not None and (sent - got) / sent > LOSS_WARN_RATIO:
                    LOGGER.warning('유실 경고 %s: 중계 %d 중 %d 만 도착 (%.1f%% 유실)',
                                   topic['name'], sent, got, 100.0 * (sent - got) / sent)
    return EXIT_OK


def main(argv=None):
    """역할에 맞게 실행하고 종료 코드를 돌려준다."""
    args = parse_args(argv)
    if args.role == 'run':
        return run_all(args)
    if args.role == 'serve':
        return run_serve(args)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if not args.msg_type or not args.topic:
        LOGGER.error('pub/sink 는 --msg-type 과 --topic 이 필요하다')
        return EXIT_SETUP_FAILED
    return run_pub(args) if args.role == 'pub' else run_sink(args)


if __name__ == '__main__':
    sys.exit(main())
