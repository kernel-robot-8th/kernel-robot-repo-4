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

"""PC 상태 보고(host_info.py, host_status_node 값, Station PC 카드)를 ROS 없이 검사한다."""

import json

from cobot_control_center import host_info as hi
from cobot_control_center import net_status_utils as nu

MEMINFO = 'MemTotal:       15764660 kB\nMemFree:  100 kB\nMemAvailable:    5754076 kB\n'


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_cpu_percent_from_two_reads():
    first = hi.parse_cpu_times('cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3 4\n')
    second = hi.parse_cpu_times('cpu  200 0 200 1300 200 0 0 0 0 0\n')
    assert first == (1000, 800) and second == (1900, 1500)
    assert hi.cpu_percent(first, second) == round(100 * (900 - 700) / 900, 1)
    assert hi.cpu_percent(None, second) is None and hi.cpu_percent(second, second) is None
    assert hi.parse_cpu_times('') is None


def test_meminfo_and_temp():
    mem = hi.parse_meminfo(MEMINFO)
    assert mem == {'total_mb': 15395, 'used_pct': 63.5}
    assert hi.parse_meminfo('MemTotal: 10 kB\n') is None
    zones = [('acpitz', 27.8), ('x86_pkg_temp', 51.0), ('iwlwifi_1', 54.0)]
    assert hi.pick_cpu_temp(zones) == ('x86_pkg_temp', 51.0)
    assert hi.pick_cpu_temp([('cpu-thermal', 48.2)]) == ('cpu-thermal', 48.2)   # 라즈베리파이
    assert hi.pick_cpu_temp([('a', 30.0), ('b', 40.0)]) == ('b', 40.0)
    assert hi.pick_cpu_temp([]) == (None, None)


ROUTE = ('Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n'
         'wlo1\t00000000\t012DA8C0\t0003\t0\t0\t600\t00000000\t0\t0\t0\n'
         'enp130s0\t0000A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n'
         'tun0\t00000000\t00000000\t0001\t0\t0\t50\t00000000\t0\t0\t0\n')


def test_without_ip_command():
    # 관제 도커 이미지에는 ip 명령이 없다 → /proc/net/route·ioctl 로 읽는다
    assert hi.parse_proc_route(ROUTE) == {'wlo1': '192.168.45.1', 'tun0': None}
    assert hi.mask_to_prefix('255.255.255.0') == 24 and hi.mask_to_prefix('255.255.0.0') == 16
    assert hi.iface_ipv4('lo') == ['127.0.0.1/8']
    assert hi.iface_ipv4('no_such_iface0') == []


def test_host_reader_reads_this_pc():
    reader = hi.HostReader({'router_host': '', 'interface_skip_prefixes': ['lo'],
                            'nmcli_period_sec': 10.0, 'wifi_warn_dbm': -70.0,
                            'wifi_warn_pct': 40.0})
    system = reader.system()
    assert system['cpu_count'] and system['mem']['total_mb'] > 0
    assert 0 <= system['disk_pct'] <= 100
    assert reader.local_ip() is None            # 공유기 주소가 없으면 묻지 않는다
    assert all(i['name'] != 'lo' for i in reader.interfaces(None))


REPORT = {'host': 'station', 'hostname': 'station-pc', 'local_ip': '192.168.45.10',
          'dds': {'rmw': 'rmw_cyclonedds_cpp', 'domain_id': 100},
          'interfaces': [{'name': 'wlan0', 'kind': 'wifi', 'oper': 'up',
                          'ips': ['192.168.45.10/24'], 'robot_net': True, 'state': nu.OK,
                          'wifi': {'ssid': 'SK', 'signal_pct': 70, 'chan': '44',
                                   'state': nu.OK}}],
          'system': {'cpu_pct': 95.0, 'load1': 3.2, 'cpu_count': 8,
                     'mem': {'total_mb': 8192, 'used_pct': 40.0}, 'temp_c': 61.0,
                     'temp_zone': 'x86_pkg_temp', 'disk_pct': 50.0, 'uptime_sec': 90061},
          'thresholds': {'cpu_warn_pct': 90.0, 'mem_warn_pct': 90.0, 'temp_warn_c': 80.0,
                         'disk_warn_pct': 90.0}}


def test_host_store():
    clock = FakeClock()
    store = nu.HostStore(10.0, clock=clock)
    assert not store.put('nope') and not store.put(json.dumps({'no_host': 1}))
    assert store.put(json.dumps(REPORT))
    clock.now = 4.0
    assert store.get_all()['station']['online'] and store.get_all()['station']['age'] == 4.0
    clock.now = 11.0
    assert store.get_all()['station']['online'] is False


def by_name(checks):
    return {c['name']: c for c in checks}


def test_host_report_checks():
    local = {'rmw': 'rmw_cyclonedds_cpp', 'domain_id': 100}
    rows = by_name(nu.host_report_checks({'data': REPORT, 'online': True, 'age': 1.0}, local))
    assert rows['보고 노드']['state'] == nu.OK and rows['보고 노드']['value'].startswith('station-pc')
    assert rows['DDS'] == {'name': 'DDS', 'state': nu.OK, 'value': 'rmw_cyclonedds_cpp'}
    assert rows['도메인']['state'] == nu.OK
    assert rows['무선 wlan0']['value'].endswith('[로봇망]')
    assert rows['CPU']['state'] == nu.WARN and rows['CPU']['value'] == '95% · 부하 3.20 (8코어)'
    assert rows['메모리']['value'] == '40% / 8.0 GB' and rows['온도']['value'] == '61°C (x86_pkg_temp)'
    assert rows['켜진 시간']['value'] == '1일 1시간 1분'
    # DDS·도메인이 관제와 다르면 주황
    other = dict(REPORT, dds={'rmw': 'rmw_fastrtps_cpp', 'domain_id': 101})
    rows2 = by_name(nu.host_report_checks({'data': other, 'online': True, 'age': 1.0}, local))
    assert rows2['DDS']['state'] == nu.WARN
    assert '관제(rmw_cyclonedds_cpp)와 다름' in rows2['DDS']['value']
    assert rows2['도메인']['state'] == nu.WARN
    gone = nu.host_report_checks({'data': REPORT, 'online': False, 'age': 30.0}, local)
    assert gone == [{'name': '보고 노드', 'state': nu.BAD, 'value': '끊김 (30초)'}]
    assert nu.host_report_checks(None, local)[0]['state'] == nu.NA


def test_control_card_adds_only_system_rows():
    control = dict(REPORT, host='control', hostname='8-OMEN')

    def rows_for(hosts):
        result = nu.network_view({'rmw': 'rmw_cyclonedds_cpp'}, {'robots': {}}, True, True,
                                 None, None, False, [], [], hosts)
        return by_name({c['id']: c for c in result['health']['cards']}['control']['checks'])

    rows = rows_for({'control': {'data': control, 'online': True, 'age': 1.0}})
    assert rows['CPU']['state'] == nu.WARN and rows['온도']['value'] == '61°C (x86_pkg_temp)'
    # 연결·DDS 는 측정 노드 값으로 이미 있으므로 보고에서 다시 붙이지 않는다
    assert '보고 노드' not in rows and '무선 wlan0' not in rows and '도메인' not in rows
    assert rows_for(None)['PC 내부']['state'] == nu.NA
    gone = rows_for({'control': {'data': control, 'online': False, 'age': 20.0}})
    assert gone['PC 내부'] == {'name': 'PC 내부', 'state': nu.BAD, 'value': '보고 끊김 (20초)'}


def test_station_card_uses_report():
    arms = {'controller_online': True, 'arms': [{'arm_id': 'omx_1', 'online': True}]}
    hosts = {'station': {'data': REPORT, 'online': True, 'age': 1.0}}
    result = nu.network_view({'rmw': 'rmw_cyclonedds_cpp', 'domain_id': 100,
                              'station_nodes': ['omx1_adapter']},
                             {'robots': {}}, True, True, arms, None, False, [], ['omx_1'], hosts)
    card = {c['id']: c for c in result['health']['cards']}['station']
    rows = by_name(card['checks'])
    assert rows['CPU']['state'] == nu.WARN and card['state'] == nu.WARN
    assert 'PC 내부' not in rows
    # 보고 노드를 안 띄웠으면 회색 한 줄
    plain = nu.network_view({'rmw': 'r'}, {'robots': {}}, True, True, arms, None, False, [],
                            ['omx_1'])
    rows3 = by_name({c['id']: c for c in plain['health']['cards']}['station']['checks'])
    assert rows3['PC 내부']['state'] == nu.NA
