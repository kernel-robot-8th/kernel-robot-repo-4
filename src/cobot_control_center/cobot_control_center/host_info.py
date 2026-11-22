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
이 PC 정보 읽기 (ROS 없음): 네트워크 연결, CPU·메모리·온도·디스크, DDS 설정.

관제 PC 의 net_status_node 와 다른 PC(팔 PC 등)의 host_status_node 가 함께 쓴다.
리눅스 표준 파일(/proc, /sys)과 ip·nmcli 명령만 읽는다. 망에 패킷을 보내지 않는다
(로봇망 주소는 UDP connect 로 경로만 묻는다).
"""

import os
import shutil
import socket
import struct
import subprocess
import time

from cobot_control_center import net_status_utils as nu

SYS_NET = '/sys/class/net'
SYS_THERMAL = '/sys/class/thermal'
# CPU 온도로 볼 thermal zone 이름 (앞에 있을수록 먼저). 인텔 PC, 라즈베리파이·젯슨 순
CPU_ZONES = ('x86_pkg_temp', 'TCPU', 'cpu-thermal', 'cpu_thermal', 'CPU-therm', 'soc_thermal')


def read_text(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None


def run_text(args, timeout=3):
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return done.stdout if done.returncode == 0 else ''


# ---------- 순수 파싱 (시험용) ----------

def parse_cpu_times(text):
    """/proc/stat 첫 줄 → (전체, 쉰 시간). 사용률은 두 번 읽은 차이로 낸다."""
    for line in (text or '').splitlines():
        fields = line.split()
        if fields and fields[0] == 'cpu':
            values = [int(v) for v in fields[1:] if v.isdigit()]
            if len(values) < 4:
                return None
            idle = values[3] + (values[4] if len(values) > 4 else 0)   # idle + iowait
            return sum(values), idle
    return None


def cpu_percent(prev, cur):
    if not prev or not cur or cur[0] <= prev[0]:
        return None
    total, idle = cur[0] - prev[0], cur[1] - prev[1]
    return round(100.0 * (total - idle) / total, 1)


def parse_meminfo(text):
    """/proc/meminfo → {'total_mb', 'used_pct'} (사용 = 전체 - MemAvailable)."""
    values = {}
    for line in (text or '').splitlines():
        name, _, rest = line.partition(':')
        number = rest.split()
        if number and number[0].isdigit():
            values[name] = int(number[0])   # kB
    total, avail = values.get('MemTotal'), values.get('MemAvailable')
    if not total or avail is None:
        return None
    return {'total_mb': round(total / 1024), 'used_pct': round(100.0 * (total - avail) / total, 1)}


def parse_proc_route(text):
    """
    /proc/net/route → {인터페이스: 게이트웨이} (기본 경로만). `ip` 명령이 없을 때(도커 이미지 등) 쓴다.

    주소는 16진 리틀 엔디언이다 (012DA8C0 → 192.168.45.1).
    """
    result = {}
    for line in (text or '').splitlines()[1:]:
        fields = line.split()
        if len(fields) < 3 or fields[1] != '00000000' or fields[0] in result:
            continue
        try:
            gw = socket.inet_ntoa(int(fields[2], 16).to_bytes(4, 'little'))
        except (ValueError, OverflowError):
            continue
        result[fields[0]] = None if gw == '0.0.0.0' else gw
    return result


def mask_to_prefix(mask):
    try:
        return bin(int.from_bytes(socket.inet_aton(mask), 'big')).count('1')
    except OSError:
        return None


# ioctl 번호 (linux/sockios.h): 인터페이스 IPv4 주소·넷마스크
SIOCGIFADDR = 0x8915
SIOCGIFNETMASK = 0x891b


def iface_ipv4(name):
    """
    인터페이스 IPv4 주소 'a.b.c.d/n' 목록 (주 주소 하나). `ip` 명령 없이 표준 라이브러리로 읽는다.

    주소가 없으면 빈 목록.
    """
    import fcntl   # 리눅스 전용이라 여기서 부른다
    request = struct.pack('256s', name.encode()[:15])
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            addr = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)[20:24])
            mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), SIOCGIFNETMASK, request)[20:24])
    except OSError:
        return []
    prefix = mask_to_prefix(mask)
    return [f'{addr}/{prefix}' if prefix is not None else addr]


def pick_cpu_temp(zones):
    """[(이름, °C)] 에서 CPU 온도. 아는 이름이 없으면 가장 높은 값."""
    named = dict(zones)
    for name in CPU_ZONES:
        if name in named:
            return name, named[name]
    if not zones:
        return None, None
    return max(zones, key=lambda z: z[1])


# ---------- 읽기 ----------

class HostReader:
    """
    이 PC 상태를 읽는다. CPU 사용률은 앞 호출과의 차이라 같은 객체로 주기마다 부른다.

    cfg 키: router_host, interface_skip_prefixes, nmcli_period_sec, wifi_warn_dbm, wifi_warn_pct.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.ip_cmd = shutil.which('ip')
        self.nmcli_cmd = shutil.which('nmcli')
        self._wifi_cache = {}   # 인터페이스 → (monotonic, nmcli 결과)
        self._cpu_prev = parse_cpu_times(read_text('/proc/stat'))

    def local_ip(self):
        """공유기로 가는 경로의 이 PC 주소. UDP connect 는 패킷을 보내지 않는다."""
        router = self.cfg.get('router_host')
        if not router:
            return None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((router, 9))
                return sock.getsockname()[0]
        except OSError:
            return None

    def _wifi_info(self, name, now, proc_wireless):
        """
        무선 인터페이스 하나의 연결 정보.

        신호 [dBm] 는 /proc/net/wireless 에 있으면 쓰고 (드라이버에 따라 비어 있다), 연결 이름·신호 %·채널은
        nmcli 로 읽는다. nmcli 는 다시 찾기(rescan) 없이 nmcli_period_sec 에 한 번만 부른다.
        """
        cached = self._wifi_cache.get(name)
        if self.nmcli_cmd and (cached is None
                               or now - cached[0] >= float(self.cfg['nmcli_period_sec'])):
            text = run_text([self.nmcli_cmd, '-t', '-f', 'IN-USE,SIGNAL,SSID,CHAN,RATE',
                             'dev', 'wifi', 'list', 'ifname', name, '--rescan', 'no'])
            cached = (now, nu.parse_nmcli_wifi(text))
            self._wifi_cache[name] = cached
        info = dict(cached[1]) if cached and cached[1] else {}
        level = (proc_wireless.get(name) or {}).get('level_dbm')
        info['level_dbm'] = level
        if level is not None:
            info['state'] = nu.wifi_state(level, float(self.cfg['wifi_warn_dbm']))
        else:
            info['state'] = nu.wifi_pct_state(info.get('signal_pct'),
                                              float(self.cfg['wifi_warn_pct']))
        return info

    def interfaces(self, local_ip):
        """이 PC 의 네트워크 연결 (유선·무선 모두). 로봇망(공유기로 가는 경로)인 것에 robot_net 표시."""
        now = time.monotonic()
        # ip 명령이 없으면(관제 도커 이미지 등) 표준 라이브러리 ioctl·/proc/net/route 로 읽는다
        if self.ip_cmd:
            addrs = nu.parse_ip_addr(run_text([self.ip_cmd, '-o', '-4', 'addr', 'show']))
            defaults = nu.parse_default_routes(
                run_text([self.ip_cmd, '-4', 'route', 'show', 'default']))
        else:
            addrs = None
            defaults = parse_proc_route(read_text('/proc/net/route'))
        proc = read_text('/proc/net/wireless')
        proc_wireless = nu.parse_wireless(proc) if proc else {}
        skip = tuple(self.cfg.get('interface_skip_prefixes') or ())
        try:
            names = sorted(os.listdir(SYS_NET))
        except OSError:
            names = []
        result = []
        for name in names:
            if skip and name.startswith(skip):
                continue
            base = os.path.join(SYS_NET, name)
            wireless = (os.path.isdir(os.path.join(base, 'wireless'))
                        or os.path.exists(os.path.join(base, 'phy80211')))
            # 장치 종류 65534 = 터널(tailscale·wireguard 등 VPN)
            tunnel = read_text(os.path.join(base, 'type')) == '65534'
            kind = ('wifi' if wireless else 'vpn' if tunnel else
                    'ethernet' if os.path.exists(os.path.join(base, 'device')) else 'other')
            ips = addrs.get(name, []) if addrs is not None else iface_ipv4(name)
            item = {'name': name, 'kind': kind,
                    'oper': read_text(os.path.join(base, 'operstate')) or 'unknown',
                    'ips': ips,
                    'mac': None if tunnel else read_text(os.path.join(base, 'address')),
                    'gateway': defaults.get(name),
                    'default_route': name in defaults,
                    'robot_net': bool(local_ip) and any(a.split('/')[0] == local_ip for a in ips),
                    'carrier_changes': nu.to_int(read_text(os.path.join(base,
                                                                        'carrier_changes')))}
            if kind == 'ethernet':
                item['speed_mbps'] = nu.to_int(read_text(os.path.join(base, 'speed')))
                item['duplex'] = read_text(os.path.join(base, 'duplex'))
            if wireless:
                item['wifi'] = self._wifi_info(name, now, proc_wireless)
            item['state'] = nu.interface_state(item)
            result.append(item)
        return result

    def system(self):
        """CPU 사용률·부하, 메모리, CPU 온도, 디스크(/), 켜진 시간."""
        cur = parse_cpu_times(read_text('/proc/stat'))
        percent = cpu_percent(self._cpu_prev, cur)
        self._cpu_prev = cur
        load = (read_text('/proc/loadavg') or '').split()
        zones = []
        try:
            entries = sorted(os.listdir(SYS_THERMAL))
        except OSError:
            entries = []
        for entry in entries:
            if not entry.startswith('thermal_zone'):
                continue
            base = os.path.join(SYS_THERMAL, entry)
            temp = nu.to_int(read_text(os.path.join(base, 'temp')))
            if temp is not None and temp > 0:
                zones.append((read_text(os.path.join(base, 'type')) or entry, temp / 1000.0))
        zone, temp_c = pick_cpu_temp(zones)
        try:
            usage = shutil.disk_usage('/')
            disk = round(100.0 * usage.used / usage.total, 1)
        except OSError:
            disk = None
        uptime = (read_text('/proc/uptime') or '').split()
        return {'cpu_pct': percent, 'cpu_count': os.cpu_count(),
                'load1': float(load[0]) if load else None,
                'mem': parse_meminfo(read_text('/proc/meminfo')),
                'temp_c': None if temp_c is None else round(temp_c, 1), 'temp_zone': zone,
                'disk_pct': disk,
                'uptime_sec': round(float(uptime[0])) if uptime else None}

    @staticmethod
    def dds(rmw, domain_id):
        env = os.environ
        return {'rmw': rmw, 'domain_id': domain_id,
                'rmw_env': env.get('RMW_IMPLEMENTATION') or None,
                'cyclonedds_uri': env.get('CYCLONEDDS_URI') or None,
                'discovery_range': env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') or None}
