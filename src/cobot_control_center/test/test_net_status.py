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

"""네트워크 상태 화면(net_status_utils.py, /api/network)을 ROS 없이 검사한다."""

import json

from cobot_control_center import net_status_utils as nu
from cobot_control_center.fleet_api_app import create_app
from cobot_control_center.fleet_api_utils import ArmStore, SnapshotStore, TaskStore
from fastapi.testclient import TestClient
import pytest

PING_OK = ('PING 192.168.45.21 (192.168.45.21) 56(84) bytes of data.\n'
           '64 bytes from 192.168.45.21: icmp_seq=1 ttl=64 time=2.43 ms\n')
WIRELESS = ('Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n'
            ' face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n'
            'wlp2s0: 0000   58.  -52.  -256        0      0      0      0     12        0\n')


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def summary(window, now=10.0):
    return window.summary(now, warn_ms=100.0, warn_loss_pct=10.0, bad_fails=3)


def test_parse_ping_rtt():
    assert nu.parse_ping_rtt(PING_OK) == 2.43
    assert nu.parse_ping_rtt('64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time<1 ms') == 1.0
    assert nu.parse_ping_rtt('1 packets transmitted, 0 received, 100% packet loss') is None
    assert nu.parse_ping_rtt(None) is None


def test_tcp_probe_when_no_ping_command():
    times = iter([10.0, 10.0042])

    class Conn:
        def close(self):
            pass

    def refused(addr, timeout):
        raise ConnectionRefusedError()

    def timed_out(addr, timeout):
        raise TimeoutError()

    # 연결 성공·거절(RST) 모두 응답이 온 것 → 왕복 시간
    assert nu.tcp_probe('h', 22, 1, connect=lambda a, timeout: Conn(),
                        clock=lambda: next(times)) == 4.2
    times = iter([0.0, 0.002])
    assert nu.tcp_probe('h', 22, 1, connect=refused, clock=lambda: next(times)) == 2.0
    assert nu.tcp_probe('h', 22, 1, connect=timed_out) is None


def test_ping_window_states():
    window = nu.PingWindow(10)
    assert summary(window)['state'] == nu.NA
    for _ in range(9):
        window.add(3.0, 1.0)
    first = summary(window)
    assert first['state'] == nu.OK and first['loss_pct'] == 0.0 and first['avg_ms'] == 3.0
    window.add(None, 2.0)          # 10 번 중 1 번 실패 = 10 % → 주황
    assert summary(window)['state'] == nu.WARN
    window.add(None, 3.0)
    window.add(None, 4.0)          # 마지막 3 번 연속 실패 → 빨강
    bad = summary(window)
    assert bad['state'] == nu.BAD and bad['last_ms'] is None and bad['last_ok_age'] == 9.0


def test_ping_window_slow_is_warn():
    window = nu.PingWindow(5)
    for _ in range(5):
        window.add(150.0, 0.0)
    assert summary(window)['state'] == nu.WARN


def test_rate_meter():
    meter = nu.RateMeter(5.0)
    assert meter.summary(0.0, 1.0)['state'] == nu.NA
    for i in range(50):            # 10 Hz 로 5초
        meter.tick(i * 0.1)
    ok = meter.summary(4.95, 1.0, expect_hz=10.0)
    assert ok['state'] == nu.OK and abs(ok['hz'] - 10.0) < 0.5
    assert meter.summary(4.95, 1.0, expect_hz=30.0)['state'] == nu.WARN
    assert meter.summary(7.0, 1.0)['state'] == nu.BAD


def test_parse_wireless_and_state():
    found = nu.parse_wireless(WIRELESS)
    assert found == {'wlp2s0': {'link': 58.0, 'level_dbm': -52.0}}
    assert nu.parse_wireless(WIRELESS.splitlines(True)[0]) == {}
    assert nu.wifi_state(-52.0, -70.0) == nu.OK
    assert nu.wifi_state(-80.0, -70.0) == nu.WARN
    assert nu.wifi_state(None, -70.0) == nu.NA


IP_ADDR = ('1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n'
           '2: enp130s0    inet 192.168.0.9/24 brd 192.168.0.255 scope global enp130s0\n'
           '3: wlo1    inet 192.168.45.9/24 brd 192.168.45.255 scope global dynamic wlo1\n')
NMCLI = (' :100:pinky_AP:1:270 Mbit/s\n'
         '*:77:SK_D490_5G:44:270 Mbit/s\n'
         ' :39:FASTCAMPUS_10F:44:540 Mbit/s\n'
         ' :20:a\\:b:44:130 Mbit/s\n')


def test_parse_ip_addr_and_nmcli():
    assert nu.parse_ip_addr(IP_ADDR) == {'lo': ['127.0.0.1/8'], 'enp130s0': ['192.168.0.9/24'],
                                         'wlo1': ['192.168.45.9/24']}
    wifi = nu.parse_nmcli_wifi(NMCLI)
    assert wifi['ssid'] == 'SK_D490_5G' and wifi['signal_pct'] == 77 and wifi['chan'] == '44'
    assert wifi['same_channel'] == ['FASTCAMPUS_10F', 'a:b']   # 이름 속 '\:' 는 ':' 로
    assert nu.parse_nmcli_wifi(' :100:pinky_AP:1:270 Mbit/s\n') is None
    assert nu.wifi_pct_state(30, 40.0) == nu.WARN and nu.wifi_pct_state(None, 40.0) == nu.NA


ARP = ('IP address       HW type     Flags       HW address            Mask     Device\n'
       '192.168.45.10    0x1         0x2         40:d1:33:34:56:ed     *        wlo1\n'
       '192.168.45.21    0x1         0x0         2c:cf:67:a8:67:b5     *        wlo1\n'
       '192.168.0.15     0x1         0x0         00:00:00:00:00:00     *        enp130s0\n')


def test_parse_proc_arp_and_mac_text():
    arp = nu.parse_proc_arp(ARP)
    assert arp['192.168.45.10'] == {'mac': '40:d1:33:34:56:ed', 'dev': 'wlo1', 'complete': True}
    assert arp['192.168.45.21']['complete'] is False
    assert '192.168.0.15' not in arp                 # 아직 못 찾은 줄은 뺀다
    assert nu.parse_proc_arp(None) == {}
    assert nu.mac_text({'mac': 'aa', 'mac_fresh': True}) == 'aa'
    assert nu.mac_text({'mac': 'aa', 'mac_fresh': False}) == 'aa (예전 값)'
    assert nu.mac_text(None).startswith('모름')


def test_local_info_station_nodes():
    info = nu.local_info('rmw', 100, {}, ['omx1_adapter', 'omx2_adapter', 'fleet_api_node',
                                          'omx_bridge'], ['omx*_adapter'])
    assert info['station_nodes'] == ['omx1_adapter', 'omx2_adapter']
    assert nu.local_info('rmw', 100, {}, ['omx1_adapter'])['station_nodes'] == []


def test_default_routes_and_band():
    text = ('default via 192.168.45.1 dev wlo1 proto dhcp src 192.168.45.9 metric 600\n'
            'default via 192.168.0.1 dev enp130s0 metric 100\n'
            'default dev tun0 scope link\n')
    assert nu.parse_default_routes(text) == {'wlo1': '192.168.45.1',
                                             'enp130s0': '192.168.0.1', 'tun0': None}
    assert nu.wifi_band('44') == '5 GHz' and nu.wifi_band('6') == '2.4 GHz'
    assert nu.wifi_band('') is None


WIFI_IF = {'name': 'wlo1', 'kind': 'wifi', 'oper': 'up', 'ips': ['192.168.45.9/24'],
           'robot_net': True, 'default_route': True,
           'wifi': {'ssid': 'SK_D490_5G', 'signal_pct': 77, 'level_dbm': None, 'chan': '44',
                    'rate': '270 Mbit/s', 'same_channel': ['X'], 'state': nu.OK}}
WIRED_IF = {'name': 'enp130s0', 'kind': 'ethernet', 'oper': 'up', 'ips': ['192.168.0.9/24'],
            'robot_net': False, 'default_route': False, 'speed_mbps': 1000, 'duplex': 'full'}
VPN_IF = {'name': 'tailscale0', 'kind': 'vpn', 'oper': 'unknown', 'ips': ['100.92.218.126/32'],
          'robot_net': False}


def test_interface_state_summary_badges():
    assert nu.interface_state(WIFI_IF) == nu.OK
    assert nu.interface_summary(WIFI_IF) == ('연결됨 · 192.168.45.9/24 · SK_D490_5G · 77% · '
                                             '5 GHz ch44 · 270 Mbit/s')
    assert nu.interface_badges(WIFI_IF) == ['로봇망', '기본 경로']
    weak = dict(WIFI_IF, wifi=dict(WIFI_IF['wifi'], state=nu.WARN))
    assert nu.interface_state(weak) == nu.WARN
    # 로봇망이 아닌 무선은 신호가 약해도 주황으로 보지 않는다
    assert nu.interface_state(dict(weak, robot_net=False)) == nu.OK
    assert nu.interface_summary(WIRED_IF) == '연결됨 · 192.168.0.9/24 · 1000 Mb/s'
    assert nu.interface_summary(dict(WIRED_IF, duplex='half')).endswith('1000 Mb/s 반이중')
    assert nu.interface_badges(VPN_IF) == ['VPN'] and nu.interface_state(VPN_IF) == nu.OK
    down = dict(WIFI_IF, oper='down')
    assert nu.interface_state(down) == nu.BAD
    assert nu.interface_state(dict(down, robot_net=False)) == nu.NA
    assert nu.interface_summary(down) == '끊김 (down)'


def test_health_control_lists_wired_then_wireless():
    ifaces = [dict(i, state=nu.interface_state(i)) for i in (VPN_IF, WIFI_IF, WIRED_IF)]
    data = dict(net_data(), interfaces=ifaces, local_ip='192.168.45.9')
    _, ctl = health_of(view(net=data), 'control')
    names = [n for n in ctl if n.startswith(('유선', '무선', 'VPN'))]
    assert names == ['유선 enp130s0', '무선 wlo1', 'VPN tailscale0']
    assert ctl['무선 wlo1']['value'].endswith('[로봇망] [기본 경로]')
    assert ctl['유선 enp130s0']['state'] == nu.OK and '로봇망' not in ctl
    # 로봇망이 아닌 연결이 끊겨도 회색 (판정 안 함)
    off = dict(WIRED_IF, oper='down')
    data2 = dict(data, interfaces=[dict(WIFI_IF, state=nu.OK), dict(off, state=nu.NA)])
    _, ctl2 = health_of(view(net=data2), 'control')
    assert ctl2['유선 enp130s0']['state'] == nu.NA
    _, missing = health_of(view(net=dict(data, interfaces=[dict(WIRED_IF, state=nu.OK)])),
                           'control')
    assert missing['로봇망']['state'] == nu.WARN
    _, local = health_of(view(net=dict(data, local_ip='127.0.0.1')), 'control')
    assert local['로봇망']['state'] == nu.NA


def test_local_info_counts_unknown_names():
    info = nu.local_info('rmw_cyclonedds_cpp', 100,
                         {'CYCLONEDDS_URI': 'file:///x.xml'},
                         ['fleet_api_node', '_NODE_NAME_UNKNOWN_', '_NODE_NAME_UNKNOWN_',
                          'fleet_api_node'])
    assert info['rmw'] == 'rmw_cyclonedds_cpp' and info['cyclonedds_uri'] == 'file:///x.xml'
    assert info['nodes'] == ['fleet_api_node'] and info['unknown_nodes'] == 2
    assert info['discovery_range'] is None


def net_data(**targets):
    base = {key: {'state': nu.OK, 'samples': 5, 'last_ms': 2.0} for key in
            ('router', 'station', 'pinky1', 'pinky2', 'pinky3')}
    for key, state in targets.items():
        base[key] = {'state': state, 'samples': 5, 'last_ms': None if state == nu.BAD else 2.0}
    return {'time': 100.0, 'ping_available': True, 'targets': base, 'topics': {},
            'wifi': {}, 'local_ip': '192.168.45.9'}


SNAP = {'robots': {'pinky1': {'online': True}, 'pinky2': {'online': False},
                   'pinky3': {'online': False}},
        'infra': {'zone_manager': {'state': 'ok'},
                  'bridges': {'pinky1': {'state': 'ok', 'node': 'b1'},
                              'pinky2': {'state': 'ok', 'node': 'b2'},
                              'pinky3': {'state': 'missing', 'node': 'b3'}}}}
ARMS_OK = {'controller_online': True,
           'arms': [{'arm_id': 'omx_1', 'online': True}, {'arm_id': 'omx_2', 'online': True}]}
ROBOTS = ['pinky1', 'pinky2', 'pinky3']


def view(snap=SNAP, net=None, arms=ARMS_OK, fresh=True, net_online=True):
    return nu.network_view({'rmw': 'rmw_cyclonedds_cpp'}, snap, fresh, True, arms,
                           net if net is not None else net_data(), net_online, ROBOTS,
                           ['omx_1', 'omx_2'])


def test_network_view_explains_where_it_broke():
    result = view(net=net_data(pinky2=nu.BAD))
    robots = {r['id']: r for r in result['robots']}
    assert robots['pinky1']['state'] == nu.OK
    # 핑이 끊김 → 네트워크 문제
    assert robots['pinky2']['state'] == nu.BAD and '핑 응답 없음' in robots['pinky2']['text']
    # 핑은 되는데 데이터 없음, 브릿지가 없음 → 브릿지 확인
    assert robots['pinky3']['state'] == nu.BAD and '브릿지' in robots['pinky3']['text']
    bridges = {b['robot']: b['state'] for b in result['bridges']}
    assert bridges == {'pinky1': nu.OK, 'pinky2': nu.OK, 'pinky3': nu.BAD}
    links = {link['to']: link['state'] for link in result['links']}
    assert links['pinky2'] == nu.BAD and links['router'] == nu.OK
    assert result['overall'] == nu.BAD
    assert result['station']['state'] == nu.OK and result['station']['text'] == '팔 2/2 연결'


def test_network_view_without_measurement_still_draws():
    result = view(net_online=False)
    assert result['net_online'] is False
    assert all(link['state'] == nu.NA for link in result['links'])
    net_box = {b['id']: b for b in result['control']}['net_status']
    assert net_box['state'] == nu.BAD
    # 핑이 없어도 데이터로 판정한다
    assert {r['id']: r['state'] for r in result['robots']}['pinky1'] == nu.OK


def test_network_view_stale_source_is_unknown():
    result = view(fresh=False)
    assert all(r['state'] == nu.NA for r in result['robots'])
    assert all(b['state'] == nu.NA for b in result['bridges'])


def test_network_view_station_states():
    partial = {'controller_online': True,
               'arms': [{'arm_id': 'omx_1', 'online': True}, {'arm_id': 'omx_2', 'online': False}]}
    assert view(arms=partial)['station']['state'] == nu.WARN
    none_online = {'controller_online': True, 'arms': [{'arm_id': 'omx_1', 'online': False}]}
    station = view(arms=none_online, net=net_data(station=nu.BAD))['station']
    assert station['state'] == nu.BAD and '핑 응답 없음' in station['text']
    assert view(arms={'controller_online': False, 'arms': []})['station']['state'] == nu.NA


def health_of(result, card_id):
    card = {c['id']: c for c in result['health']['cards']}[card_id]
    return card, {c['name']: c for c in card['checks']}


def test_health_uses_fleet_status_alerts():
    robots = {
        'pinky1': {'online': True, 'last_seen_age': 0.2, 'battery_percent': 15.0,
                   'pose': {'x': 0}, 'teach': {'ok': False, 'std_xy': 0.08},
                   'state': 'FAILED', 'clock_offset_sec': 0.9, 'extra': {}},
        'pinky2': {'online': False, 'last_seen_age': 12.0, 'battery_percent': None},
        'pinky3': {'online': True, 'last_seen_age': 0.1, 'battery_percent': 80.0,
                   'pose': {'x': 0}, 'teach': {'ok': True, 'std_xy': 0.01},
                   'state': 'IDLE', 'clock_offset_sec': 0.01,
                   'extra': {'central_latched': True}}}
    alerts = [{'robot': 'pinky1', 'code': 'battery_low', 'level': 'warn'},
              {'robot': 'pinky1', 'code': 'state_bad', 'level': 'bad', 'text': 'FAILED: x'},
              {'robot': 'pinky1', 'code': 'clock_skew', 'level': 'warn'},
              {'robot': 'pinky2', 'code': 'offline', 'level': 'bad'}]
    snap = {'robots': robots, 'alerts': alerts, 'infra': SNAP['infra']}
    result = view(snap=snap)
    card, checks = health_of(result, 'pinky1')
    assert checks['배터리']['state'] == nu.WARN and checks['배터리']['value'] == '15%'
    assert checks['작업 상태']['state'] == nu.BAD and checks['작업 상태']['value'] == 'FAILED: x'
    assert checks['시계']['state'] == nu.WARN and checks['위치 추정']['state'] == nu.WARN
    assert checks['로봇 내부']['state'] == nu.NA
    assert card['state'] == nu.BAD
    _, checks2 = health_of(result, 'pinky2')
    assert checks2['연결']['state'] == nu.BAD and checks2['연결']['value'] == '끊김 (12초)'
    _, checks3 = health_of(result, 'pinky3')
    assert checks3['작업 상태']['state'] == nu.WARN and '정지 잠금' in checks3['작업 상태']['value']
    issues = result['health']['issues']
    assert issues[0]['state'] == nu.BAD
    assert result['overall'] == nu.BAD and result['health']['state'] == nu.BAD


def test_health_one_card_per_arm():
    arms = {'controller_online': True, 'arms': [
        {'arm_id': 'omx_1', 'online': True, 'age': 0.1, 'state': 'READY',
         'status': {'power_present': True}},
        {'arm_id': 'omx_2', 'online': True, 'age': 0.1, 'state': 'READY',
         'status': {'power_present': False}}]}
    result = view(arms=arms)
    ids = [c['id'] for c in result['health']['cards']]
    # 팔은 팔마다, PC(Station PC·관제 PC)는 따로, 그 뒤 유선망(천장 카메라·영상 분석)
    assert ids[-6:] == ['omx_1', 'omx_2', 'station', 'control', 'cctv', 'vision']
    card1, arm1 = health_of(result, 'omx_1')
    assert card1['select'] == 'station' and card1['state'] == nu.OK
    assert '네트워크' not in arm1                       # 네트워크는 Station PC 카드에
    assert arm1['상태 주기']['state'] == nu.NA          # 자세히 확인 때만 잰다
    station, st = health_of(result, 'station')
    assert station['kind'] == 'station' and st['팔 노드']['value'] == '2/2 연결'
    assert st['네트워크']['state'] == nu.OK and st['PC 내부']['state'] == nu.NA
    # view() 의 local 에 노드 이름이 없다 → 팔 상태는 오는데 이름이 안 보임 (DDS 다를 수 있음)
    assert st['노드']['state'] == nu.WARN and 'DDS' in st['노드']['value']
    named = nu.network_view({'rmw': 'r', 'station_nodes': ['omx1_adapter', 'omx2_adapter']},
                            SNAP, True, True, arms, dict(net_data(), targets=dict(
                                net_data()['targets'],
                                station={'state': nu.OK, 'samples': 3, 'last_ms': 2.0,
                                         'mac': '40:d1:33:34:56:ed', 'mac_fresh': True})),
                            True, ROBOTS, ['omx_1', 'omx_2'])
    _, st_named = health_of(named, 'station')
    assert st_named['노드']['state'] == nu.OK
    assert st_named['노드']['value'] == '2개: omx1_adapter, omx2_adapter'
    assert st_named['MAC']['value'] == '40:d1:33:34:56:ed'
    assert named['station']['nodes'] == ['omx1_adapter', 'omx2_adapter']
    card2, arm2 = health_of(result, 'omx_2')
    assert arm2['전원']['state'] == nu.WARN and card2['state'] == nu.WARN
    issue = [i for i in result['health']['issues'] if i['card'] == 'omx_2'][0]
    assert issue['select'] == 'station'
    stale = {'controller_online': True, 'arms': [
        {'arm_id': 'omx_1', 'online': False, 'age': 9.0, 'state': 'STALE', 'status': None},
        {'arm_id': 'omx_2', 'online': True, 'age': 0.1, 'state': 'OFF',
         'status': {'power_present': False}}]}
    stale_result = view(arms=stale)
    _, s1 = health_of(stale_result, 'omx_1')
    assert s1['연결']['state'] == nu.BAD and s1['연결']['value'] == '끊김 (9초)'
    _, s2 = health_of(stale_result, 'omx_2')
    assert s2['전원']['state'] == nu.NA and s2['상태']['value'] == '꺼짐 (켜기 전)'
    _, st2 = health_of(stale_result, 'station')
    assert st2['팔 노드']['state'] == nu.WARN and st2['팔 노드']['value'] == '1/2 연결'
    _, off = health_of(view(arms={'controller_online': False, 'arms': []}), 'omx_1')
    assert off['연결']['state'] == nu.NA


def test_health_control_nodes_and_bridges():
    result = view()
    _, ctl = health_of(result, 'control')
    assert ctl['관제 노드']['state'] == nu.OK
    assert ctl['브릿지']['state'] == nu.BAD and ctl['브릿지']['value'] == '2/3 정상'
    assert ctl['DDS']['value'] == 'rmw_cyclonedds_cpp'


def test_health_when_source_is_stale():
    result = view(fresh=False)
    _, checks = health_of(result, 'pinky1')
    assert list(checks) == ['연결'] and checks['연결']['state'] == nu.NA


def test_network_alerts_only_network_and_pc():
    low = {'online': True, 'battery_percent': 5.0, 'state': 'IDLE'}
    snap = dict(SNAP, robots=dict(SNAP['robots'], pinky1=low),
                alerts=[{'robot': 'pinky1', 'code': 'battery_low', 'level': 'warn'}])
    stale = {'arm_id': 'omx_1', 'online': False, 'state': 'STALE'}
    arms = {'controller_online': True, 'arms': [stale]}
    result = view(snap=snap, net=net_data(pinky2=nu.BAD), arms=arms)
    alerts = nu.network_alerts(result)
    codes = {a['code'] for a in alerts}
    assert 'net:pinky2:네트워크' in codes            # 로봇 핑 끊김은 낸다
    assert not any(c.startswith('net:pinky1:') for c in codes)   # 배터리는 fleet_status 경고에 있음
    assert not any(c.startswith('net:omx_1:') for c in codes)    # 팔은 로봇팔 패널에 있음
    assert 'net:station:팔 노드' in codes                # Station PC 는 모두
    assert 'net:control:브릿지' not in codes             # 상단 점이 이미 보여 줌
    pinky2 = [a for a in alerts if a['code'] == 'net:pinky2:네트워크'][0]
    assert pinky2['robot'] == 'pinky2' and pinky2['level'] == nu.BAD


def test_net_alert_tracker_events():
    tracker = nu.NetAlertTracker()
    a = {'robot': 'pinky2', 'code': 'net:pinky2:네트워크', 'level': 'bad', 'text': '네트워크 응답 없음'}
    first = tracker.update([a], 100.0)
    assert first == [{'time': 100.0, 'robot': 'pinky2', 'kind': 'network', 'level': 'bad',
                      'text': '네트워크 응답 없음'}]
    # 값(텍스트)만 바뀌면 새 이벤트를 내지 않는다
    assert tracker.update([dict(a, text='네트워크 응답 없음 · 손실 50%')], 101.0) == []
    # 등급이 바뀌면 낸다
    assert tracker.update([dict(a, level='warn')], 102.0)[0]['level'] == 'warn'
    gone = tracker.update([], 103.0)
    assert gone == [{'time': 103.0, 'robot': 'pinky2', 'kind': 'network', 'level': 'info',
                     'text': '네트워크 회복'}]


def test_snapshot_store_add_events_goes_out_with_next_snapshot():
    store = SnapshotStore(3.0)
    store.add_events([{'time': 1.0, 'robot': 'pinky2', 'kind': 'network', 'level': 'bad',
                       'text': 'x'}])
    assert [e['id'] for e in store.events()] == [1]     # /api/events 에는 바로 보인다
    store.put(json.dumps({'robots': {}, 'events': [{'time': 2.0, 'text': 'y'}]}))
    _, snap = store.get()
    assert [e['id'] for e in snap['events']] == [1, 2]  # WebSocket 스냅샷에도 같이 실린다
    assert [e['id'] for e in store.events()] == [1, 2]
    store.put(json.dumps({'robots': {}}))
    assert store.get()[1]['events'] == []


def test_api_network_includes_alerts():
    store = SnapshotStore(3.0)
    store.put(json.dumps(SNAP))
    net = nu.NetStore(3.0)
    net.put(json.dumps(net_data(pinky3=nu.BAD)))
    body = TestClient(create_app(store, net=net, network_ids=(ROBOTS, []))).get(
        '/api/network').json()
    assert any(a['code'] == 'net:pinky3:네트워크' for a in body['alerts'])


def test_net_store_history_and_stale():
    clock = FakeClock()
    store = nu.NetStore(3.0, history_max=2, clock=clock)
    assert store.get() == (None, False)
    assert not store.put('[]') and not store.put('nope')
    for i in range(3):
        assert store.put(json.dumps(dict(net_data(), time=100.0 + i)))
    data, online = store.get()
    assert online and data['local_ip'] == '192.168.45.9'
    assert store.history()['pinky1'] == [[101.0, 2.0], [102.0, 2.0]]
    clock.now = 3.5
    assert store.online() is False


def test_api_network():
    clock = FakeClock()
    store = SnapshotStore(3.0, clock=clock)
    store.put(json.dumps(SNAP))
    net = nu.NetStore(3.0, clock=clock)
    net.put(json.dumps(net_data()))
    arms = ArmStore(3.0, 1.0, clock=clock)
    arms.put_snapshot(json.dumps({'arms': ARMS_OK['arms']}))
    app = create_app(store, domain_id=100, tasks=TaskStore(3.0, 1.0, clock=clock), arms=arms,
                     net=net, local_network=lambda: {'rmw': 'rmw_cyclonedds_cpp', 'nodes': []},
                     network_ids=(ROBOTS, ['omx_1', 'omx_2']))
    client = TestClient(app)
    body = client.get('/api/network').json()
    assert body['local']['rmw'] == 'rmw_cyclonedds_cpp' and body['local']['domain_id'] == 100
    assert [r['id'] for r in body['robots']] == ROBOTS
    assert 'history' not in body
    with_history = client.get('/api/network?history=true').json()
    assert with_history['history']['router'] == [[100.0, 2.0]]


def test_api_network_check():
    clock = FakeClock()
    net = nu.NetStore(3.0, clock=clock)
    sent = []
    app = create_app(SnapshotStore(3.0), net=net, request_net_check=sent.append)
    client = TestClient(app)
    assert client.post('/api/network/check').status_code == 503   # 측정 노드 값이 아직 없음
    net.put(json.dumps(dict(net_data(), detail={'active': False, 'duration_sec': 10.0})))
    res = client.post('/api/network/check')
    assert res.status_code == 202 and res.json() == {'duration_sec': 10.0}
    assert sent == ['testclient']
    assert TestClient(create_app(SnapshotStore(3.0))).post('/api/network/check').status_code == 503


def test_api_network_without_net_store():
    store = SnapshotStore(3.0)
    body = TestClient(create_app(store, domain_id=101)).get('/api/network?history=1').json()
    assert body['net_online'] is False and body['robots'] == [] and body['history'] == {}
    assert body['local'] == {'domain_id': 101}


# ---------- 유선망 (영상·분석, 2026-11-22) ----------

VISION_NODES = ['mqtt_zone_evidence', 'anomaly_monitor']


def wired_net(**states):
    """net_data 에 유선 대상(wired_router·cctv·broker·station_wired)과 근거 주기를 더한다."""
    data = net_data()
    for key in ('wired_router', 'cctv', 'broker', 'station_wired'):
        state = states.get(key, nu.OK)
        data['targets'][key] = {'state': state, 'samples': 5,
                                'last_ms': None if state == nu.BAD else 1.0,
                                'host': f'192.168.0.{key}'}
    data['topics'] = states.get('topics', {})
    return data


def wired_view(net=None, nodes=VISION_NODES, cctv=None, label='11ubuntu (확인 전)'):
    return nu.network_view({'rmw': 'rmw_cyclonedds_cpp', 'vision_nodes': nodes,
                            'hostname': '8-OMEN'},
                           SNAP, True, True, ARMS_OK,
                           net if net is not None else wired_net(), True, ROBOTS,
                           ['omx_1', 'omx_2'], cctv=cctv, vision_label=label)


def test_wired_view_boxes_links_and_cards():
    result = wired_view()
    wired = result['wired']
    assert [b['id'] for b in wired['devices']] == ['cctv', 'broker', 'station_wired']
    assert wired['router']['state'] == nu.OK and wired['vision']['state'] == nu.OK
    links = {link['to']: link['state'] for link in wired['links']}
    assert links == {'wired_router': nu.OK, 'cctv': nu.OK, 'broker': nu.OK,
                     'station_wired': nu.OK}
    card, checks = health_of(result, 'vision')
    assert card['kind'] == 'vision' and checks['근거 수신기']['state'] == nu.OK
    assert checks['YOLO PC']['value'] == '11ubuntu (확인 전)'
    # 근거 주기는 자세히 확인 때만 잰다
    assert checks['구역 근거 주기']['state'] == nu.NA
    control, _ = health_of(result, 'control')
    assert control['label'] == '관제 PC · 8-OMEN'


def test_wired_unreachable_broker_and_missing_nodes():
    result = wired_view(net=wired_net(broker=nu.BAD), nodes=['anomaly_monitor'])
    assert result['wired']['broker']['state'] == nu.BAD
    assert result['wired']['vision']['state'] == nu.WARN
    _, checks = health_of(result, 'vision')
    assert checks['MQTT 브로커']['state'] == nu.BAD
    assert checks['근거 수신기']['state'] == nu.WARN and checks['이상 감지']['state'] == nu.OK
    # 이 PC 안 시험(127.0.0.1)이면 노드가 없어도 회색
    local = dict(wired_net(), local_ip='127.0.0.1')
    test_result = wired_view(net=local, nodes=[])
    assert test_result['wired']['vision']['state'] == nu.NA


def test_evidence_rate_checks():
    topics = {'evidence/anomaly_monitor/zone_evidence': {'state': nu.OK, 'hz': 10.0, 'age': 0.1},
              'evidence/anomaly_monitor/box_evidence': {'state': nu.WARN, 'hz': 4.0, 'age': 0.2}}
    _, checks = health_of(wired_view(net=wired_net(topics=topics)), 'vision')
    assert checks['구역 근거 주기'] == {'name': '구역 근거 주기', 'state': nu.OK, 'value': '10.0 Hz'}
    assert checks['상자 근거 주기']['state'] == nu.WARN


def test_cctv_card_uses_relay_state():
    # 보는 사람이 없어 중계가 안 붙은 것은 나쁜 게 아니다
    idle = {'url': 'http://cam/processed', 'connected': False, 'viewers': 0, 'error': ''}
    result = wired_view(cctv=idle)
    assert result['wired']['cctv']['state'] == nu.OK
    _, checks = health_of(result, 'cctv')
    assert checks['현장영상 중계']['state'] == nu.NA and checks['주소']['value'] == 'http://cam/processed'
    live = dict(idle, connected=True, viewers=1, age_sec=0.2)
    assert wired_view(cctv=live)['wired']['cctv']['text'] == '영상 받는 중'
    broken = dict(idle, viewers=2, error='연결 거절')
    bad = wired_view(cctv=broken)
    assert bad['wired']['cctv']['state'] == nu.BAD
    _, checks = health_of(bad, 'cctv')
    assert checks['현장영상 중계']['state'] == nu.BAD


def test_wired_alerts_only_when_device_unreachable():
    quiet = nu.network_alerts(wired_view(net=wired_net(cctv=nu.WARN), nodes=[]))
    assert not [a for a in quiet if a['code'].startswith(('net:cctv', 'net:vision'))]
    loud = nu.network_alerts(wired_view(net=wired_net(cctv=nu.BAD, broker=nu.BAD)))
    codes = {a['code'] for a in loud}
    assert {'net:cctv:네트워크', 'net:vision:MQTT 브로커'} <= codes


def test_local_info_vision_nodes_and_hostname():
    info = nu.local_info('rmw_cyclonedds_cpp', 100, {},
                         ['anomaly_monitor', 'mqtt_zone_evidence', 'fleet_api_node'],
                         ('omx*_adapter',), ('mqtt_zone_evidence', 'anomaly_monitor'), '8-OMEN')
    assert info['vision_nodes'] == ['anomaly_monitor', 'mqtt_zone_evidence']
    assert info['hostname'] == '8-OMEN' and info['station_nodes'] == []


def test_local_net_hosts_never_ping_real_wired_devices():
    """net_hosts:=local(가짜 핑키·가제보)이면 유선 대상도 모두 127.0.0.1 이어야 한다."""
    import xml.etree.ElementTree as ET
    from pathlib import Path
    root = ET.parse(Path(__file__).resolve().parents[1] / 'launch' / 'fleet_api.launch.xml')
    local = [n for n in root.getroot().iter('node')
             if n.get('exec') == 'net_status_node' and 'local' in (n.get('if') or '')]
    assert len(local) == 1
    params = {p.get('name'): p.get('value') for p in local[0].iter('param') if p.get('name')}
    assert params['wired_router_host'] == '127.0.0.1'
    assert params['wired_hosts'] == '[127.0.0.1, 127.0.0.1, 127.0.0.1]'


def site_arm(arm_id, alias, host, zone, online=True):
    return {'arm_id': arm_id, 'alias': alias, 'online': online, 'age': 0.1, 'state': 'READY',
            'status': {'power_present': True}, 'site': {'station': zone, 'host': host}}


SITE_ARMS = {'controller_online': True, 'arms': [
    site_arm('omx_1', 'omx1', '8-OMEN', 'ZA'), site_arm('omx_2', 'omx2', '8-OMEN', 'ZB'),
    site_arm('omx_3', 'omx3', 'OMEN-11', 'ZC')]}


def test_split_arms_by_host():
    local, remote, name = nu.split_arms_by_host(SITE_ARMS, '8-omen')   # 대소문자 무시
    assert [a['arm_id'] for a in local] == ['omx_1', 'omx_2']
    assert [a['arm_id'] for a in remote] == ['omx_3'] and name == 'OMEN-11'
    # hostname 을 모르거나 host 가 비면 다른 PC 팔 (예전처럼 팔 PC 상자)
    local, remote, name = nu.split_arms_by_host(SITE_ARMS, None)
    assert not local and len(remote) == 3 and name == '8-OMEN · OMEN-11'
    _, remote, name = nu.split_arms_by_host({'arms': [{'arm_id': 'x'}]}, '8-OMEN')
    assert len(remote) == 1 and name == ''
    assert nu.split_arms_by_host(None, '8-OMEN') == ([], [], '')


def site_view(arms=SITE_ARMS, hostname='8-OMEN', nodes=('omx1_adapter', 'omx2_adapter',
                                                        'omx3_adapter')):
    local = {'rmw': 'r', 'hostname': hostname, 'station_nodes': list(nodes)}
    return nu.network_view(local, SNAP, True, True, arms, net_data(), True, ROBOTS,
                           ['omx_1', 'omx_2', 'omx_3'])


def test_arms_on_control_pc_leave_arm_pc_box():
    result = site_view()
    station = result['station']
    # 팔 PC 상자에는 다른 PC(OMEN-11) 팔만
    assert station['label'] == '팔 PC · OMEN-11' and station['text'] == '팔 1/1 연결'
    assert [a['arm_id'] for a in station['arms']] == ['omx_3']
    assert station['nodes'] == ['omx3_adapter'] and list(station['rates']) == ['omx_3']
    local = result['local_arms']
    assert local['label'] == '이 PC 팔 omx1·omx2' and local['state'] == nu.OK
    assert local['nodes'] == ['omx1_adapter', 'omx2_adapter']
    assert [a['zone'] for a in local['arms']] == ['ZA', 'ZB']
    _, ctl = health_of(result, 'control')
    assert ctl['팔 노드']['value'] == 'omx1·omx2 2/2 연결'
    _, st = health_of(result, 'station')
    assert st['팔 노드']['value'] == '1/1 연결' and st['노드']['value'] == '1개: omx3_adapter'
    cards = {c['id']: c for c in result['health']['cards']}
    assert cards['omx_1']['select'] == 'control' and cards['omx_3']['select'] == 'station'
    assert cards['omx_1']['label'] == 'omx_1 로봇팔 · ZA'
    # 팔 PC 핑이 끊겨도 관제 PC 팔은 정상으로 남는다
    cut = nu.network_view({'rmw': 'r', 'hostname': '8-OMEN'}, SNAP, True, True,
                          {'controller_online': True, 'arms': [
                              site_arm('omx_1', 'omx1', '8-OMEN', 'ZA'),
                              site_arm('omx_3', 'omx3', 'OMEN-11', 'ZC', online=False)]},
                          net_data(station=nu.BAD), True, ROBOTS, ['omx_1', 'omx_3'])
    assert cut['station']['state'] == nu.BAD and cut['local_arms']['state'] == nu.OK


def test_local_arm_problems_go_to_control_card_not_alert_strip():
    arms = {'controller_online': True, 'arms': [
        site_arm('omx_1', 'omx1', '8-OMEN', 'ZA', online=False),
        site_arm('omx_2', 'omx2', '8-OMEN', 'ZB')]}
    result = site_view(arms=arms)
    assert result['local_arms']['state'] == nu.WARN
    _, ctl = health_of(result, 'control')
    assert ctl['팔 노드']['state'] == nu.WARN
    # 다른 PC 팔이 없으면 팔 PC 상자는 회색 (핑만 보인다)
    assert result['station']['state'] == nu.NA and result['station']['label'] == '팔 PC'
    _, st = health_of(result, 'station')
    assert st['팔 노드']['state'] == nu.NA
    issue = [i for i in result['health']['issues'] if i['card'] == 'omx_1'][0]
    assert issue['select'] == 'control'
    codes = [a['code'] for a in nu.network_alerts(result)]
    assert 'net:control:팔 노드' not in codes            # 팔 패널이 이미 보여 준다


def test_arm_pc_card_shows_reported_hostname_when_different():
    hosts = {'station': {'online': True, 'age': 1.0, 'data': {'hostname': '11Ubuntu'}}}
    local = {'rmw': 'r', 'hostname': '8-OMEN'}
    result = nu.network_view(local, SNAP, True, True, SITE_ARMS, net_data(), True, ROBOTS,
                             ['omx_1', 'omx_2', 'omx_3'], hosts=hosts)
    card, _ = health_of(result, 'station')
    assert card['label'] == '팔 PC · OMEN-11 (보고 이름 11Ubuntu)'


def test_probe_port_table_gives_wired_router_its_own_port():
    table = nu.probe_port_table(['cctv', 'broker', 'station_wired'], [18086, 1883, 22], 80)
    assert table == {'cctv': 18086, 'broker': 1883, 'station_wired': 22, 'wired_router': 80}
    # 0 이면 표에 넣지 않는다 → tcp_probe_port(22) 를 쓴다
    assert nu.probe_port_table(['cctv'], [0], 0) == {}
    with pytest.raises(ValueError):
        nu.probe_port_table(['cctv', 'broker'], [18086], 80)
