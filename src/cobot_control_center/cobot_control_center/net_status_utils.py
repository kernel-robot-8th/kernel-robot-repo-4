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
네트워크 상태 화면의 순수 로직 (ROS 없음).

- 측정 쪽(net_status_node): 핑 결과 모으기·판정, 토픽 수신 주기, 관제 PC Wi-Fi 신호 읽기.
- 화면 쪽(fleet_api /api/network): 이미 있는 상태값(fleet_status·작업 노드·팔)과 측정값을 묶어
  구조도 상자·선의 상태를 정한다.

상태 이름은 화면 점 색과 같다: ok 초록, warn 주황, bad 빨강, na 회색(해당 없음·모름).
원격 PC(로봇·팔 PC)의 DDS 종류는 ROS 로 물어볼 수 없어 '데이터가 오는지'로만 적는다.
"""

import collections
import fnmatch
import json
import re
import socket
import threading
import time

OK, WARN, BAD, NA = 'ok', 'warn', 'bad', 'na'
_RANK = {NA: 0, OK: 1, WARN: 2, BAD: 3}

# ping 출력의 'time=2.43 ms' (리눅스 iputils). 'time<1 ms' 도 받는다.
_RTT_RE = re.compile(r'time[=<]\s*([0-9.]+)\s*ms')

# fleet_status 의 infra 판정 → 상태, 화면 글 (상단 바 점 설명과 같은 뜻)
_INFRA = {'ok': OK, 'missing': BAD, 'duplicate': BAD, 'unknown': WARN, 'n/a': NA}
_INFRA_TEXT = {'ok': '정상', 'missing': '없음', 'duplicate': '중복 (두 벌)',
               'unknown': '확인 불가', 'n/a': '해당 없음'}
# 자세히 칸 설명 (상자 안에는 위 짧은 글)
_INFRA_NOTE = {'duplicate': '같은 도메인에 두 벌이 떠 있음',
               'unknown': '발행은 보이는데 노드 이름이 안 보임 → DDS 구현이 다를 수 있음',
               'n/a': '실물 관제 도메인이 아니라 검사하지 않음'}


def worst(states):
    """가장 나쁜 상태 (na 는 다른 값이 있으면 무시). 비면 na."""
    states = list(states)
    return max(states, key=lambda s: _RANK.get(s, 0)) if states else NA


def tcp_probe(host, port, timeout, connect=socket.create_connection, clock=time.monotonic):
    """
    TCP 연결 시도로 잰 왕복 시간 [ms]. 응답이 없으면 None.

    ping 명령이 없을 때(관제 도커 이미지) 쓴다. 권한이 필요 없다. 연결이 되거나 거절(RST)되면
    장치가 응답한 것이라 시간을 돌려준다. 시간 초과·경로 없음이면 None.
    """
    started = clock()
    try:
        conn = connect((host, port), timeout=timeout)
        conn.close()
    except ConnectionRefusedError:
        pass
    except OSError:
        return None
    return round((clock() - started) * 1000.0, 2)


def parse_ping_rtt(text):
    """핑 한 번(ping 명령 출력)의 왕복 시간 [ms]. 응답이 없으면 None."""
    match = _RTT_RE.search(text or '')
    return float(match.group(1)) if match else None


class PingWindow:
    """한 대상의 최근 핑 결과 (성공이면 rtt[ms], 실패면 None)를 window 개까지 보관한다."""

    def __init__(self, window):
        self._samples = collections.deque(maxlen=int(window))
        self._last_ok = None

    def add(self, rtt_ms, now):
        self._samples.append(rtt_ms)
        if rtt_ms is not None:
            self._last_ok = now

    def summary(self, now, warn_ms, warn_loss_pct, bad_fails):
        """
        화면용 요약과 판정.

        bad: 마지막 bad_fails 번이 모두 실패. warn: 손실률 warn_loss_pct 이상 또는 평균 warn_ms 이상.
        아직 한 번도 안 쟀으면 na.
        """
        samples = list(self._samples)
        if not samples:
            return {'state': NA, 'samples': 0, 'last_ms': None, 'avg_ms': None,
                    'max_ms': None, 'loss_pct': None, 'last_ok_age': None}
        good = [s for s in samples if s is not None]
        loss = 100.0 * (len(samples) - len(good)) / len(samples)
        avg = sum(good) / len(good) if good else None
        tail = samples[-int(bad_fails):]
        if len(tail) >= int(bad_fails) and all(s is None for s in tail):
            state = BAD
        elif loss >= warn_loss_pct or (avg is not None and avg >= warn_ms):
            state = WARN
        else:
            state = OK
        return {'state': state, 'samples': len(samples),
                'last_ms': None if samples[-1] is None else round(samples[-1], 1),
                'avg_ms': None if avg is None else round(avg, 1),
                'max_ms': round(max(good), 1) if good else None,
                'loss_pct': round(loss, 1),
                'last_ok_age': None if self._last_ok is None else round(now - self._last_ok, 1)}


class RateMeter:
    """토픽을 받은 시각으로 수신 주기 [Hz] 와 마지막 수신 뒤 지난 시간을 잰다."""

    def __init__(self, window_sec):
        self.window_sec = float(window_sec)
        self._times = collections.deque()
        self._last = None
        self._first = None

    def tick(self, now):
        if self._first is None:
            self._first = now
        self._times.append(now)
        self._last = now
        self._trim(now)

    def _trim(self, now):
        while self._times and now - self._times[0] > self.window_sec:
            self._times.popleft()

    def summary(self, now, stale_sec, expect_hz=None):
        """{hz, age, state}. stale_sec 넘게 안 오면 bad, 기대 주기의 절반 미만이면 warn."""
        self._trim(now)
        age = None if self._last is None else now - self._last
        # 받기 시작한 지 구간보다 짧으면 그 시간으로 나눈다 (켜자마자 주기가 낮게 보여 주황이 되지 않게).
        # 한 번만 받았으면 간격을 모르므로 0.
        span = min(self.window_sec, now - self._first) if self._first is not None else 0.0
        hz = (len(self._times) - 1) / span if span > 0 and len(self._times) > 1 else 0.0
        if span >= self.window_sec:
            hz = len(self._times) / self.window_sec
        if age is None:
            state = NA
        elif age > stale_sec:
            state = BAD
        elif expect_hz and hz < 0.5 * expect_hz:
            state = WARN
        else:
            state = OK
        return {'hz': round(hz, 2), 'age': None if age is None else round(age, 2),
                'state': state}


def parse_wireless(text):
    """
    /proc/net/wireless → {인터페이스: {'link': 품질, 'level_dbm': 신호}}.

    앞 두 줄은 머리글이다. 유선만 있으면 빈 dict.
    """
    result = {}
    for line in (text or '').splitlines()[2:]:
        if ':' not in line:
            continue
        name, rest = line.split(':', 1)
        fields = rest.split()
        if len(fields) < 3:
            continue
        try:
            link = float(fields[1].rstrip('.'))
            level = float(fields[2].rstrip('.'))
        except ValueError:
            continue
        result[name.strip()] = {'link': link, 'level_dbm': level}
    return result


def wifi_state(level_dbm, warn_dbm):
    """신호 세기 판정. 값이 없으면 na."""
    if level_dbm is None:
        return NA
    return WARN if level_dbm < warn_dbm else OK


def parse_ip_addr(text):
    """`ip -o -4 addr show` → {인터페이스: ['192.168.45.9/24', ..]}."""
    result = {}
    for line in (text or '').splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[2] == 'inet':
            result.setdefault(fields[1], []).append(fields[3])
    return result


def _split_terse(line):
    """한 줄(nmcli -t)을 ':' 로 나눈다. 값 안의 ':' 는 역슬래시가 붙어 와서 나누지 않는다."""
    fields, cur, i = [], '', 0
    while i < len(line):
        if line[i] == '\\' and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if line[i] == ':':
            fields.append(cur)
            cur = ''
        else:
            cur += line[i]
        i += 1
    fields.append(cur)
    return fields


def parse_nmcli_wifi(text):
    """
    `nmcli -t -f IN-USE,SIGNAL,SSID,CHAN,RATE dev wifi list --rescan no` → 지금 연결과 같은 채널 AP.

    {'ssid', 'signal_pct', 'chan', 'rate', 'same_channel': [다른 AP 이름..]} 또는 연결이 없으면 None.
    다시 찾기(rescan)를 하지 않은 목록이라 주변 AP 는 조금 오래된 값일 수 있다.
    """
    entries = []
    for line in (text or '').splitlines():
        fields = _split_terse(line)
        if len(fields) < 5:
            continue
        try:
            signal = int(fields[1])
        except ValueError:
            continue
        entries.append({'in_use': fields[0].strip() == '*', 'signal_pct': signal,
                        'ssid': fields[2], 'chan': fields[3], 'rate': fields[4]})
    current = next((e for e in entries if e['in_use']), None)
    if current is None:
        return None
    same = [e['ssid'] or '(이름 없음)' for e in entries
            if not e['in_use'] and e['chan'] == current['chan']]
    return {'ssid': current['ssid'], 'signal_pct': current['signal_pct'],
            'chan': current['chan'], 'rate': current['rate'], 'same_channel': same}


def wifi_pct_state(signal_pct, warn_pct):
    if signal_pct is None:
        return NA
    return WARN if signal_pct < warn_pct else OK


def to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def parse_proc_arp(text):
    """
    /proc/net/arp → {IP: {'mac', 'dev', 'complete'}}. MAC 이 0 뿐인 줄(아직 못 찾음)은 뺀다.

    complete 는 Flags 의 0x2 (지금 유효한 항목). 거짓이면 예전에 알던 값이다.
    """
    result = {}
    for line in (text or '').splitlines()[1:]:
        fields = line.split()
        if len(fields) < 6 or fields[3] == '00:00:00:00:00:00':
            continue
        try:
            complete = bool(int(fields[2], 16) & 0x2)
        except ValueError:
            complete = False
        result[fields[0]] = {'mac': fields[3], 'dev': fields[5], 'complete': complete}
    return result


def parse_default_routes(text):
    """`ip -4 route show default` → {인터페이스: 게이트웨이}. 기본 경로(인터넷으로 나가는 길)가 걸린 연결."""
    result = {}
    for line in (text or '').splitlines():
        fields = line.split()
        if not fields or fields[0] != 'default':
            continue
        dev = fields[fields.index('dev') + 1] if 'dev' in fields[:-1] else None
        gw = fields[fields.index('via') + 1] if 'via' in fields[:-1] else None
        if dev and dev not in result:
            result[dev] = gw
    return result


def wifi_band(chan):
    """채널 번호 → 대역. 1~14 는 2.4 GHz, 그 위는 5 GHz (6 GHz 는 구분하지 않음)."""
    number = to_int(chan)
    if number is None:
        return None
    return '2.4 GHz' if number <= 14 else '5 GHz'


# 화면 묶음 순서와 이름 (유선 → 무선 → 기타, 보통 네트워크 설정 화면과 같은 순서)
KIND_ORDER = ('ethernet', 'wifi', 'vpn', 'other')
_KIND_TEXT = {'wifi': '무선', 'ethernet': '유선', 'vpn': 'VPN', 'other': '기타'}


def interface_badges(item):
    """용도 표시: 로봇망(공유기로 가는 연결), 기본 경로(인터넷), VPN."""
    badges = []
    if item.get('robot_net'):
        badges.append('로봇망')
    if item.get('default_route'):
        badges.append('기본 경로')
    if item.get('kind') == 'vpn':
        badges.append('VPN')
    return badges


def interface_state(item):
    """
    연결 하나의 판정. 켜져 있으면 ok (Wi-Fi 는 신호가 약하면 warn).

    꺼진 연결은 로봇망이면 bad, 아니면 na (쓰지 않는 포트일 수 있다).
    """
    up = item.get('oper') == 'up' or (item.get('oper') == 'unknown' and item.get('ips'))
    if not up:
        return BAD if item.get('robot_net') else NA
    wifi = item.get('wifi') or {}
    # 로봇망이 아닌 무선은 신호가 약해도 판정에 넣지 않는다 (참고용)
    if item.get('kind') == 'wifi' and item.get('robot_net'):
        return worst([OK, wifi.get('state', NA)])
    return OK


def kind_text(kind):
    return _KIND_TEXT.get(kind, '기타')


def interface_summary(item):
    """
    연결 한 줄 (이름·종류 제외, 화면이 '유선 enp130s0' 처럼 앞에 붙인다).

    유선: '연결됨 · 192.168.0.9/24 · 1000 Mb/s'
    무선: '연결됨 · 192.168.45.9/24 · SK_D490_5G · 77% · 5 GHz ch44 · 270 Mbit/s'
    """
    up = item.get('oper') == 'up' or (item.get('oper') == 'unknown' and item.get('ips'))
    if not up:
        return f'끊김 ({item.get("oper")})'
    parts = ['연결됨'] + list(item.get('ips') or [])
    wifi = item.get('wifi') or {}
    if item.get('kind') == 'wifi':
        if wifi.get('ssid'):
            parts.append(wifi['ssid'])
            if wifi.get('level_dbm') is not None:
                parts.append(f'{wifi["level_dbm"]:.0f} dBm')
            elif wifi.get('signal_pct') is not None:
                parts.append(f'{wifi["signal_pct"]}%')
            if wifi.get('chan'):
                band = wifi_band(wifi['chan'])
                parts.append(f'{band} ch{wifi["chan"]}' if band else f'ch{wifi["chan"]}')
            if wifi.get('rate'):
                parts.append(wifi['rate'])
        else:
            parts.append('신호 모름')
    elif item.get('kind') == 'ethernet' and item.get('speed_mbps') and item['speed_mbps'] > 0:
        parts.append(f'{item["speed_mbps"]} Mb/s'
                     + (' 반이중' if item.get('duplex') == 'half' else ''))
    return ' · '.join(parts)


class NetStore:
    """
    fleet_api 쪽: net_status 측정값의 최신 값과 대상별 지연 기록(그래프용)을 보관한다.

    ROS 콜백 스레드가 put() 으로 넣고, 웹 서버 스레드가 get()·history() 로 읽는다.
    기록은 받은 순서대로 (UNIX 시각, 마지막 rtt[ms] 또는 None) 를 history_max 개까지 둔다.
    """

    def __init__(self, stale_sec, history_max=300, clock=time.monotonic):
        self.stale_sec = float(stale_sec)
        self.clock = clock
        self._lock = threading.Lock()
        self._data = None
        self._received = None
        self._history = {}
        self._history_max = int(history_max)

    def put(self, text):
        """JSON 문자열을 넣는다. dict 가 아니면 False."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict) or not isinstance(data.get('targets'), dict):
            return False
        stamp = data.get('time') if isinstance(data.get('time'), (int, float)) else time.time()
        with self._lock:
            self._data = data
            self._received = self.clock()
            for key, target in data['targets'].items():
                if not isinstance(target, dict) or not target.get('samples'):
                    continue
                series = self._history.setdefault(
                    key, collections.deque(maxlen=self._history_max))
                series.append([round(stamp, 1), target.get('last_ms')])
        return True

    def online(self):
        with self._lock:
            return self._received is not None and self.clock() - self._received <= self.stale_sec

    def get(self):
        """(측정값 또는 None, 살아 있는지)."""
        with self._lock:
            data = self._data
            online = self._received is not None and self.clock() - self._received <= self.stale_sec
        return data, online

    def history(self):
        with self._lock:
            return {key: list(series) for key, series in self._history.items()}


class HostStore:
    """
    fleet_api 쪽: PC 상태 보고(host_status_node)를 PC(host)마다 최신 값으로 보관한다.

    여러 PC 가 같은 토픽에 내므로 host 로 나눈다. stale_sec 넘게 안 오면 끊김으로 본다.
    """

    def __init__(self, stale_sec, clock=time.monotonic):
        self.stale_sec = float(stale_sec)
        self.clock = clock
        self._lock = threading.Lock()
        self._hosts = {}   # host → (data, 받은 monotonic)

    def put(self, text):
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict) or not isinstance(data.get('host'), str):
            return False
        with self._lock:
            self._hosts[data['host']] = (data, self.clock())
        return True

    def get_all(self):
        """{host: {'data', 'online', 'age'}}."""
        now = self.clock()
        with self._lock:
            items = dict(self._hosts)
        return {host: {'data': data, 'online': now - at <= self.stale_sec,
                       'age': round(now - at, 1)}
                for host, (data, at) in items.items()}


def local_info(rmw, domain_id, env, node_names, station_patterns=(), vision_patterns=(),
               hostname=None):
    """
    관제 PC 자기 정보. node_names 는 도메인 100 에서 이름이 보이는 노드 (같은 이름도 그대로).

    이름이 '_NODE_NAME_UNKNOWN_' 인 노드는 발행은 보이는데 이름 정보가 안 넘어온 것이다
    (Cyclone ↔ Fast DDS 처럼 DDS 구현이 다를 때). 개수만 따로 센다.
    station_nodes 는 그중 팔 노드로 보이는 이름 (station_patterns, 예: 'omx*_adapter').
    어느 PC 의 팔인지는 network_view 가 팔 배치(site.host)로 나눈다.
    vision_nodes 는 영상 분석·이상 감지 노드로 보이는 이름 (vision_patterns, 예: 'anomaly_monitor').
    ROS 그래프는 노드가 어느 PC 에서 도는지 알려 주지 않으므로 이름으로만 고른다.
    """
    unknown = sum(1 for n in node_names if 'NODE_NAME_UNKNOWN' in n)
    names = sorted({n for n in node_names if 'NODE_NAME_UNKNOWN' not in n})
    station = [n for n in names if any(fnmatch.fnmatchcase(n, p) for p in station_patterns)]
    vision = [n for n in names if any(fnmatch.fnmatchcase(n, p) for p in vision_patterns)]
    return {'rmw': rmw, 'domain_id': domain_id, 'hostname': hostname or None,
            'cyclonedds_uri': env.get('CYCLONEDDS_URI') or None,
            'rmw_env': env.get('RMW_IMPLEMENTATION') or None,
            'discovery_range': env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') or None,
            'static_peers': env.get('ROS_STATIC_PEERS') or None,
            'nodes': names, 'unknown_nodes': unknown, 'station_nodes': station,
            'vision_nodes': vision}


# ---------- 헬스체크 카드 (/api/network 의 health) ----------
# 로봇 판정은 fleet_status 의 경고(alerts)를 그대로 쓴다. 기준값(배터리 20 %, 시계 0.5 s 등)이
# 상단 경고 띠와 같아야 화면끼리 말이 어긋나지 않는다.

# 팔 화면 상태(arm_command_utils) → 헬스 판정
_ARM_STATE = {'STALE': (BAD, '미연결'), 'OFF': (OK, '꺼짐 (켜기 전)'), 'READY': (OK, '대기'),
              'BUSY': (OK, '작업·연결 중'), 'HOLD': (WARN, '정지 중'),
              'SOFT_LATCH': (WARN, '비상정지')}


def _check(name, state, value):
    return {'name': name, 'state': state, 'value': value}


def _ping_check(ping, net_online):
    if not ping or not ping.get('samples'):
        return _check('네트워크', NA, '아직 안 잼' if net_online else '측정 없음')
    avg, loss = ping.get('avg_ms'), ping.get('loss_pct') or 0.0
    text = f'핑 {avg:.0f} ms' if avg is not None else '응답 없음'
    return _check('네트워크', ping.get('state', NA), f'{text} · 손실 {loss:.0f}%')


def _alerts_by_robot(snapshot):
    result = {}
    for alert in snapshot.get('alerts') or []:
        if isinstance(alert, dict) and alert.get('robot'):
            result.setdefault(alert['robot'], {})[alert.get('code')] = alert
    return result


def _robot_health(box, robot, alerts, fresh, net_online):
    """로봇 한 대의 점검 줄. robot 은 fleet_status 의 그 로봇 (없으면 None)."""
    robot = robot or {}
    mine = alerts.get(box['id'], {})
    if not fresh:
        return [_check('연결', NA, '관제 노드 끊김 (모름)')]
    checks = []
    if robot.get('never_seen'):
        checks.append(_check('연결', NA, '받은 적 없음'))
    elif robot.get('online'):
        checks.append(_check('연결', OK, f'수신 중 ({robot.get("last_seen_age") or 0:.1f}초 전)'))
    else:
        age = robot.get('last_seen_age')
        checks.append(_check('연결', BAD, f'끊김 ({age:.0f}초)' if age is not None else '끊김'))

    checks.append(_ping_check(box.get('ping'), net_online))

    battery = robot.get('battery_percent')
    if battery is None:
        checks.append(_check('배터리', NA, '값 없음'))
    else:
        checks.append(_check('배터리', WARN if 'battery_low' in mine else OK, f'{battery:.0f}%'))

    teach = robot.get('teach') or {}
    if robot.get('pose') is None or not teach:
        checks.append(_check('위치 추정', NA, '위치 없음'))
    else:
        std = teach.get('std_xy')
        text = f'오차 {std * 100:.1f} cm' if isinstance(std, (int, float)) else '오차 모름'
        checks.append(_check('위치 추정', OK if teach.get('ok') else WARN,
                             text + ('' if teach.get('ok') else ' (불확실)')))

    state = robot.get('state')
    extra = robot.get('extra') or {}
    if state is None:
        checks.append(_check('작업 상태', NA, '값 없음 (patrol_status 아직)'))
    elif 'state_bad' in mine:
        checks.append(_check('작업 상태', BAD, mine['state_bad'].get('text', state)))
    elif 'stuck' in mine:
        checks.append(_check('작업 상태', WARN, '끼임 의심'))
    elif extra.get('central_latched'):
        checks.append(_check('작업 상태', WARN, f'{state} · 정지 잠금'))
    else:
        checks.append(_check('작업 상태', OK if robot.get('online') else NA, state))

    offset = robot.get('clock_offset_sec')
    if offset is None:
        checks.append(_check('시계', NA, '값 없음'))
    else:
        checks.append(_check('시계', WARN if 'clock_skew' in mine else OK, f'{offset:+.2f} 초'))

    # 로봇 안쪽(CPU·온도·Wi-Fi)은 로봇이 보내 줘야 한다. 아직 연결 안 됨을 그대로 보인다.
    checks.append(_check('로봇 내부', NA, 'CPU·온도·Wi-Fi 미연결 (/diagnostics 필요)'))
    return checks


def _rate_check(name, rate):
    """수신 주기 줄. 자세히 확인 때만 재므로 값이 없으면 회색."""
    if not rate:
        return _check(name, NA, '자세히 확인 때 잼')
    if rate.get('age') is None:
        return _check(name, rate.get('state', NA), '받지 못함')
    return _check(name, rate.get('state', NA), f'{rate.get("hz")} Hz')


def mac_text(ping):
    """핑 대상의 MAC (관제 PC ARP 표). 예전 값이면 표시."""
    mac = (ping or {}).get('mac')
    if not mac:
        return '모름 (핑 응답 뒤 채워짐)'
    return mac if (ping or {}).get('mac_fresh') else f'{mac} (예전 값)'


def _station_pc_health(station, arms, net_online, local, report=None):
    """
    팔 PC 카드 (관제 PC 처럼 PC 하나): 네트워크, MAC, 팔 노드 수, 보이는 노드 이름, PC 내부.

    arms 는 이 PC(관제 PC 가 아닌 팔 PC)의 팔만 담은 스냅샷이다 (split_arms_by_host).
    팔 하나하나의 상태는 팔 카드에 따로 있다. 노드 이름은 station 상자의 nodes
    (관제 PC 팔 이름을 뺀 팔 노드)다. 팔 상태는 오는데 이름이 안 보이면 DDS 구현이 다를 수 있다.
    """
    ping = station.get('ping')
    checks = [_ping_check(ping, net_online), _check('MAC', NA, mac_text(ping))]
    names = station.get('nodes') or []
    if not arms or not arms.get('controller_online'):
        checks.append(_check('팔 노드', NA, '팔 명령 노드 꺼짐 (모름)'))
        online, total = 0, 0
    elif not arms.get('arms'):
        checks.append(_check('팔 노드', NA, '이 PC 에 놓인 팔 없음'))
        online, total = 0, 0
    else:
        items = [a for a in arms.get('arms', []) if isinstance(a, dict)]
        online, total = sum(1 for a in items if a.get('online')), len(items)
        state = OK if items and online == total else WARN if online else BAD
        checks.append(_check('팔 노드', state, f'{online}/{total} 연결'))
    if names:
        state = OK if not total or len(names) >= total else WARN
        checks.append(_check('노드', state, f'{len(names)}개: {", ".join(names)}'))
    elif online:
        checks.append(_check('노드', WARN, '팔 상태는 오는데 이름이 안 보임 (DDS 가 다를 수 있음)'))
    else:
        checks.append(_check('노드', NA, '보이는 노드 없음'))
    # 연결·CPU·온도 등은 팔 PC 가 스스로 보내야 안다 (host_status_node host:=station)
    checks += host_report_checks(report, local)
    return checks


def _arm_health(arm, controller_online, rates):
    """
    로봇팔 한 대의 점검 줄 (팔 자체만). 팔이 도는 PC 의 네트워크는 그 PC 카드에 있다.

    arm 은 ArmStore.snapshot() 의 팔 하나 (없으면 None). rates: {arm_id: 상태 주기}.
    """
    rate = (rates or {}).get((arm or {}).get('arm_id'))
    if not controller_online:
        return [_check('연결', NA, '팔 명령 노드 꺼짐 (모름)')]
    if arm is None:
        return [_check('연결', NA, '팔 목록에 없음')]
    checks = []
    age = arm.get('age')
    if arm.get('online'):
        checks.append(_check('연결', OK, f'수신 중 ({age or 0:.1f}초 전)'))
    else:
        checks.append(_check('연결', BAD, f'끊김 ({age:.0f}초)' if age is not None else '받은 적 없음'))
    state, text = _ARM_STATE.get(arm.get('state'), (NA, str(arm.get('state'))))
    checks.append(_check('상태', state if arm.get('online') else NA,
                         text if arm.get('online') else '모름'))
    status = arm.get('status') or {}
    # 꺼진(OFF) 팔은 전원이 없는 게 정상이다. 켜진 뒤에만 본다.
    if not arm.get('online') or arm.get('state') == 'OFF' or status.get('power_present') is None:
        checks.append(_check('전원', NA, '꺼짐' if arm.get('state') == 'OFF' else '모름'))
    else:
        checks.append(_check('전원', OK if status['power_present'] else WARN,
                             '있음' if status['power_present'] else '없음'))
    checks.append(_rate_check('상태 주기', rate))
    return checks


def _arm_group_check(group):
    """이 PC 에서 도는 팔 묶음(local_arms 상자) → '팔 노드' 점검 줄."""
    rows = group.get('arms') or []
    online = sum(1 for a in rows if a.get('online'))
    names = '·'.join(a.get('alias') or a.get('arm_id') or '?' for a in rows)
    return _check('팔 노드', group['state'], f'{names} {online}/{len(rows)} 연결')


def _control_health(control_boxes, local, net, net_online, report=None, local_arms=None):
    nodes = [b for b in control_boxes if not b['id'].startswith('bridge_')]
    bridges = [b for b in control_boxes if b['id'].startswith('bridge_')]
    bad_nodes = [b['label'] for b in nodes if b['state'] == BAD]
    checks = [_check('관제 노드', BAD if bad_nodes else OK,
                     f'응답 없음: {", ".join(bad_nodes)}' if bad_nodes
                     else f'{len(nodes)}개 정상')]
    bridge_state = worst([b['state'] for b in bridges])
    checks.append(_check('브릿지', bridge_state,
                         '해당 없음' if bridge_state == NA else
                         f'{sum(1 for b in bridges if b["state"] == OK)}/{len(bridges)} 정상'))
    unknown = (local or {}).get('unknown_nodes') or 0
    checks.append(_check('DDS', WARN if unknown else OK,
                         f'{(local or {}).get("rmw") or "?"}'
                         + (f' · 이름 안 보이는 노드 {unknown}' if unknown else '')))
    if local_arms:
        checks.append(_arm_group_check(local_arms))
    checks += interface_checks((net or {}).get('interfaces') or [],
                               (net or {}).get('local_ip') or '', net_online,
                               '모름 (측정 노드 필요)')
    # 관제 PC 안쪽 (host_status_node host:=control). 연결·DDS 는 위에 이미 있으므로 안쪽 줄만 붙인다.
    if report is None:
        checks.append(_check('PC 내부', NA, '보고 노드 없음 (fleet_api.launch.xml 이 띄움)'))
    elif not report.get('online'):
        checks.append(_check('PC 내부', BAD, f'보고 끊김 ({report.get("age", 0):.0f}초)'))
    else:
        data = report.get('data') or {}
        checks += system_checks(data.get('system'), data.get('thresholds'))
    return checks


def interface_checks(interfaces, local_ip, known, unknown_text):
    """
    PC 연결 줄: 보통 네트워크 설정 화면처럼 유선 → 무선 → 기타 순서로 하나씩, 용도는 배지로.

    판정은 로봇망(공유기로 가는 연결)만 한다. 나머지는 끊겨도 회색 (참고용).
    known 이 거짓이면 연결 정보를 받지 못한 것이라 '로봇망' 줄을 unknown_text 로 회색 처리한다.
    """
    checks = []
    ifaces = sorted(interfaces,
                    key=lambda i: (KIND_ORDER.index(i.get('kind'))
                                   if i.get('kind') in KIND_ORDER else len(KIND_ORDER),
                                   i.get('name') or ''))
    for item in ifaces:
        state = item.get('state', NA) if item.get('robot_net') else (
            OK if item.get('state') == OK else NA)
        badges = ''.join(f' [{b}]' for b in interface_badges(item))
        checks.append(dict(_check(f'{kind_text(item.get("kind"))} {item.get("name")}', state,
                                  interface_summary(item) + badges),
                           group=item.get('kind')))
    if (local_ip or '').startswith('127.'):
        # 가짜 핑키·시험(net_hosts:=local): 공유기 대신 127.0.0.1 로 재므로 로봇망 연결이 없다
        checks.append(_check('로봇망', NA, '이 PC 안 시험 (127.0.0.1)'))
    elif not any(i.get('robot_net') for i in ifaces):
        checks.append(_check('로봇망', WARN if known else NA,
                             '공유기로 가는 연결을 못 찾음' if known else unknown_text))
    return checks


def _uptime_text(sec):
    if sec is None:
        return '모름'
    days, rest = divmod(int(sec), 86400)
    return (f'{days}일 ' if days else '') + f'{rest // 3600}시간 {rest % 3600 // 60}분'


def system_checks(system, thresholds):
    """PC 안쪽 줄 (host_status_node 보고): CPU, 메모리, 온도, 디스크, 켜진 시간."""
    s, t = system or {}, thresholds or {}

    def judge(value, key):
        if value is None:
            return NA
        limit = t.get(key)
        return WARN if limit is not None and value >= limit else OK

    cpu = s.get('cpu_pct')
    # 보고 노드가 이어서 판정한 값(cpu_warn)이 있으면 그것을 쓴다. 옛 보고 노드는 문턱값 하나로.
    latched = s.get('cpu_warn')
    cpu_state = (judge(cpu, 'cpu_warn_pct') if not isinstance(latched, bool) or cpu is None
                 else WARN if latched else OK)
    load = s.get('load1')
    cpu_text = ('측정 중' if cpu is None else f'{cpu:.0f}%') + (
        f' · 부하 {load:.2f}' if load is not None else '') + (
        f' ({s["cpu_count"]}코어)' if s.get('cpu_count') else '')
    mem = s.get('mem') or {}
    used = mem.get('used_pct')
    mem_text = ('모름' if used is None else f'{used:.0f}%') + (
        f' / {mem["total_mb"] / 1024:.1f} GB' if mem.get('total_mb') else '')
    temp = s.get('temp_c')
    disk = s.get('disk_pct')
    return [
        _check('CPU', cpu_state, cpu_text),
        _check('메모리', judge(used, 'mem_warn_pct'), mem_text),
        _check('온도', judge(temp, 'temp_warn_c'),
               '모름' if temp is None else f'{temp:.0f}°C ({s.get("temp_zone") or "?"})'),
        _check('디스크', judge(disk, 'disk_warn_pct'), '모름' if disk is None else f'{disk:.0f}% (/)'),
        _check('켜진 시간', OK if s.get('uptime_sec') is not None else NA,
               _uptime_text(s.get('uptime_sec'))),
    ]


def host_report_checks(report, local):
    """
    PC 상태 보고(host_status_node) 한 대분 줄: 보고 노드, DDS(관제와 비교), 연결, 안쪽.

    report 는 HostStore.get_all() 의 값 하나 또는 None (보고 노드를 안 띄움).
    """
    if report is None:
        return [_check('PC 내부', NA, '보고 노드 없음 (host_status.launch.xml 을 띄우면 채워짐)')]
    data = report.get('data') or {}
    if not report.get('online'):
        return [_check('보고 노드', BAD, f'끊김 ({report.get("age", 0):.0f}초)')]
    age = report.get('age', 0)
    checks = [_check('보고 노드', OK, f'{data.get("hostname") or "?"} · {age:.0f}초 전')]
    dds = data.get('dds') or {}
    mine = (local or {}).get('rmw')
    rmw = dds.get('rmw') or '?'
    if mine and dds.get('rmw') and dds['rmw'] != mine:
        checks.append(_check('DDS', WARN, f'{rmw} · 관제({mine})와 다름'))
    else:
        checks.append(_check('DDS', OK if dds.get('rmw') else NA, rmw))
    domain, my_domain = dds.get('domain_id'), (local or {}).get('domain_id')
    if domain is not None:
        same = my_domain is None or domain == my_domain
        checks.append(_check('도메인', OK if same else WARN,
                             f'{domain}' + ('' if same else f' · 관제({my_domain})와 다름')))
    checks += interface_checks(data.get('interfaces') or [], data.get('local_ip') or '', True, '')
    checks += system_checks(data.get('system'), data.get('thresholds'))
    return checks


def _cctv_checks(box, net_online):
    """천장 카메라 카드: 핑, 현장영상 중계(보는 사람이 있을 때만 붙음), 주소."""
    checks = [_ping_check(box.get('ping'), net_online)]
    relay = box.get('relay')
    if relay is None:
        checks.append(_check('현장영상 중계', NA, '꺼짐 (cctv_url 비어 있음)'))
    elif relay.get('connected'):
        age = relay.get('age_sec')
        checks.append(_check('현장영상 중계', OK,
                             '받는 중' + (f' · 마지막 장면 {age:.1f}초 전' if age is not None else '')))
    elif relay.get('viewers') and relay.get('error'):
        checks.append(_check('현장영상 중계', BAD, f'못 받음: {relay["error"]}'))
    else:
        checks.append(_check('현장영상 중계', NA, '보는 사람이 없어 연결 안 함 (화면을 열면 붙음)'))
    if relay and relay.get('url'):
        checks.append(_check('주소', NA, relay['url']))
    return checks


def _vision_checks(box, net_online):
    """영상 분석·이상 감지 카드: 브로커 핑, 근거 수신기·이상 감지 노드, 근거 수신 주기, YOLO PC."""
    ping_check = _ping_check(box.get('broker_ping'), net_online)
    checks = [dict(ping_check, name='MQTT 브로커')]
    seen = box.get('nodes') or []
    absent = NA if box.get('local_test') else WARN
    for pattern, label in VISION_NODE_LABELS:
        names = [n for n in seen if fnmatch.fnmatchcase(n, pattern)]
        checks.append(_check(label, OK if names else absent,
                             f'{", ".join(names)} 보임' if names else '노드 안 보임'))
    for key, label in (box.get('rate_labels') or {}).items():
        checks.append(_rate_check(label, (box.get('rates') or {}).get(key)))
    checks.append(_check('YOLO PC', NA, box.get('pc_label') or '모름'))
    return checks


def health_view(snapshot, fresh, robot_boxes, station, arms, control_boxes, local, net,
                net_online, hosts=None, wired=None, arm_rates=None, local_arms=None,
                remote_arms=None):
    """
    헬스체크 카드: 로봇마다, 로봇팔마다, PC 두 대, 유선망 둘. 카드 상태는 그 카드 점검 중 가장 나쁜 것.

    PC 는 팔 PC(카드 id 'station')·관제 PC, 유선망은 천장 카메라·영상 분석·이상 감지다.
    kind: robot·arm (장비 줄), station·control (PC 줄), camera·vision (유선망 줄).
    팔 카드의 select 는 그 팔이 도는 PC 상자다: 관제 PC 에서 돌면 'control', 아니면 'station'.
    local_arms: 관제 PC 팔 묶음 상자 (없으면 None). remote_arms: 팔 PC 팔만 담은 스냅샷.
    issues 는 정상이 아닌 점검을 나쁜 것부터 (화면 '지금 볼 것' 목록).
    """
    alerts = _alerts_by_robot(snapshot)
    robots = snapshot.get('robots') or {}
    cards = [{'id': box['id'], 'label': box['label'], 'kind': 'robot', 'select': box['id'],
              'checks': _robot_health(box, robots.get(box['id']), alerts, fresh, net_online)}
             for box in robot_boxes]
    controller_online = bool(arms and arms.get('controller_online'))
    arm_list = {a.get('arm_id'): a for a in (arms or {}).get('arms', []) if isinstance(a, dict)}
    if arm_rates is None:
        arm_rates = station.get('rates') or {}
    local_ids = {a.get('arm_id') for a in (local_arms or {}).get('arms') or []}
    arm_ids = list(arm_rates) or list(arm_list)
    for arm_id in arm_ids:
        arm = arm_list.get(arm_id)
        zone = ((arm or {}).get('site') or {}).get('station')
        cards.append({'id': arm_id, 'label': f'{arm_id} 로봇팔' + (f' · {zone}' if zone else ''),
                      'kind': 'arm', 'select': 'control' if arm_id in local_ids else 'station',
                      'checks': _arm_health(arm, controller_online, arm_rates)})
    station_report = (hosts or {}).get('station')
    station_name = ((station_report or {}).get('data') or {}).get('hostname')
    label = station['label']
    if station_name and station_name.lower() not in label.lower():
        label = f'{label} (보고 이름 {station_name})'
    cards.append({'id': 'station', 'label': label, 'kind': 'station', 'select': 'station',
                  'checks': _station_pc_health(station, arms if remote_arms is None
                                               else remote_arms, net_online, local,
                                               station_report)})
    cards.append({'id': 'control', 'label': _pc_label('관제 PC', (local or {}).get('hostname')),
                  'kind': 'control', 'select': 'control',
                  'checks': _control_health(control_boxes, local, net, net_online,
                                            (hosts or {}).get('control'), local_arms)})
    if wired:
        cards.append({'id': 'cctv', 'label': '천장 카메라', 'kind': 'camera', 'select': 'cctv',
                      'checks': _cctv_checks(wired['cctv'], net_online)})
        cards.append({'id': 'vision', 'label': '영상 분석·이상 감지', 'kind': 'vision',
                      'select': 'vision', 'checks': _vision_checks(wired['vision'], net_online)})
    issues = []
    counts = {OK: 0, WARN: 0, BAD: 0, NA: 0}
    for card in cards:
        card['state'] = worst(c['state'] for c in card['checks'])
        for check in card['checks']:
            counts[check['state']] = counts.get(check['state'], 0) + 1
            if check['state'] in (WARN, BAD):
                issues.append({'card': card['id'], 'select': card['select'],
                               'label': card['label'], **check})
    issues.sort(key=lambda i: -_RANK[i['state']])
    return {'state': worst(c['state'] for c in cards), 'counts': counts,
            'cards': cards, 'issues': issues}


# ---------- 경고 띠·이벤트 로그 ----------
# 네트워크 화면을 열지 않아도 문제가 보이게, 헬스체크 문제 중 네트워크·PC 것만 상단 경고 띠와
# 이벤트 로그에 낸다. 로봇의 배터리·FAILED·끼임 등은 fleet_status 가 이미 경고로 내고,
# 팔 상태는 로봇팔 패널에 있으므로 겹치지 않게 뺀다. 관제 노드·브릿지는 상단 점이 이미 보여 준다.

# 관제 PC 의 '팔 노드' 는 로봇팔 패널이 이미 보여 주므로 뺀다 (팔 카드를 빼는 것과 같은 이유).
_ALERT_SKIP = {'control': {'관제 노드', '브릿지', '팔 노드'}}
# 유선망 카드(남의 장치)는 장치가 아예 응답하지 않을 때만 경고 띠에 올린다.
_ALERT_ONLY_BAD = {'camera': {'네트워크'}, 'vision': {'MQTT 브로커'}}


def network_alerts(view):
    """
    헬스체크 issues → 경고 띠 항목 [{'robot', 'code', 'level', 'text'}] (fleet_status alerts 와 같은 모양).

    로봇 카드는 '네트워크' 줄만, 팔 카드는 넣지 않고, 팔 PC·관제 PC 는 위 _ALERT_SKIP 말고 모두,
    천장 카메라·영상 분석 카드는 _ALERT_ONLY_BAD 의 줄이 빨강일 때만.
    code 는 카드와 줄 이름으로 정해져 값(지연 ms 등)이 바뀌어도 같은 경고로 본다.
    """
    kinds = {c['id']: c['kind'] for c in (view.get('health') or {}).get('cards', [])}
    alerts = []
    for issue in (view.get('health') or {}).get('issues', []):
        kind = kinds.get(issue['card'])
        if kind == 'arm' or (kind == 'robot' and issue['name'] != '네트워크'):
            continue
        if kind in _ALERT_ONLY_BAD and (issue['name'] not in _ALERT_ONLY_BAD[kind]
                                        or issue['state'] != BAD):
            continue
        if issue['name'] in _ALERT_SKIP.get(kind, ()):
            continue
        who = issue['card'] if kind == 'robot' else issue['label']
        alerts.append({'robot': who, 'code': f'net:{issue["card"]}:{issue["name"]}',
                       'level': issue['state'], 'text': f'{issue["name"]} {issue["value"]}'})
    return alerts


class NetAlertTracker:
    """
    경고가 생기고 풀릴 때 이벤트 로그 항목을 만든다 (fleet_status diff_events 와 같은 모양).

    처음 부를 때 이미 있는 경고도 '생김'으로 낸다 (백엔드를 다시 켜도 지금 문제가 로그에 남게).
    """

    def __init__(self):
        self._active = {}   # code → alert

    def update(self, alerts, now):
        current = {a['code']: a for a in alerts}
        events = []
        for code, alert in current.items():
            before = self._active.get(code)
            if before is None or before['level'] != alert['level']:
                events.append({'time': now, 'robot': alert['robot'], 'kind': 'network',
                               'level': alert['level'], 'text': alert['text']})
        for code, alert in self._active.items():
            if code not in current:
                name = code.split(':', 2)[-1]
                events.append({'time': now, 'robot': alert['robot'], 'kind': 'network',
                               'level': 'info', 'text': f'{name} 회복'})
        self._active = current
        return events


def collect_network(store, tasks, arms, net, hosts, local, domain_id, network_ids,
                    cctv=None, vision_label=None):
    """
    지금 값들로 network_view 를 만든다. /api/network 와 경고 추적(fleet_api_node 타이머)이 같이 쓴다.

    store: SnapshotStore, tasks: TaskStore, arms: ArmStore, net: NetStore, hosts: HostStore
    (없으면 None), local: 이 PC 정보 dict 또는 None, network_ids: (로봇 목록, 팔 목록) 또는 None.
    cctv: CctvRelay (현장영상 중계) 또는 None, vision_label: YOLO 가 도는 PC 표시 글자.
    """
    _, snapshot = store.get()
    data, net_online = net.get() if net is not None else (None, False)
    robots, arm_ids = network_ids or (list(((snapshot or {}).get('robots') or {}).keys()), [])
    task_health = tasks.health() if tasks is not None else {'controller_online': False}
    return network_view(
        dict(local or {}, domain_id=domain_id) if local else {'domain_id': domain_id},
        snapshot, store.health()['source_online'], task_health['controller_online'],
        arms.snapshot() if arms is not None else None, data, net_online, robots, arm_ids,
        hosts.get_all() if hosts is not None else None,
        cctv=cctv.health() if cctv is not None else None, vision_label=vision_label)


# ---------- 화면용 구조도 (/api/network) ----------

def _ping(net, key):
    """측정값에서 한 대상의 핑 요약. 측정 노드가 꺼졌거나 대상이 없으면 None."""
    if not net:
        return None
    return (net.get('targets') or {}).get(key)


def _rate(net, key):
    if not net:
        return None
    return (net.get('topics') or {}).get(key)


def _infra_state(item, fresh):
    if not fresh or not isinstance(item, dict):
        return NA
    return _INFRA.get(item.get('state'), NA)


def _infra_text(item, fresh):
    if not fresh:
        return '모름 (관제 노드 끊김)'
    if not isinstance(item, dict):
        return '모름'
    return _INFRA_TEXT.get(item.get('state'), str(item.get('state')))


def _infra_note(item, fresh):
    if not fresh or not isinstance(item, dict):
        return None
    return _INFRA_NOTE.get(item.get('state'))


def _box(box_id, label, state, text, **extra):
    return dict({'id': box_id, 'label': label, 'state': state, 'text': text}, **extra)


def _robot_box(robot_id, robot, fresh, ping, rate, bridge_state):
    """
    로봇 상자: 데이터(fleet_status online)와 핑을 함께 본다.

    핑이 끊겼으면 네트워크 문제, 핑은 되는데 데이터가 없으면 로봇 노드·브릿지 쪽 문제로 적는다.
    """
    ping_state = ping['state'] if ping else NA
    if not fresh:
        state, text = NA, '관제 노드 끊김 (상태 모름)'
    elif robot is None:
        state, text = NA, '등록 안 됨'
    elif robot.get('online'):
        state = WARN if ping_state in (WARN, BAD) else OK
        text = '데이터 수신 중' + (' · 핑 불안정' if state == WARN else '')
    elif ping_state == BAD:
        state, text = BAD, '네트워크 끊김 (핑 응답 없음)'
    elif ping_state in (OK, WARN):
        state = BAD
        text = ('핑은 되는데 데이터 없음 (브릿지 확인)' if bridge_state in (BAD, WARN)
                else '핑은 되는데 데이터 없음 (로봇 노드 확인)')
    else:
        state, text = BAD, '데이터 없음'
    topic_age = (robot or {}).get('topic_age') or {}
    return _box(robot_id, robot_id, state, text, kind='robot',
                ping=ping, rate=rate, topic_age=topic_age,
                dds='브릿지 경유 데이터 수신됨' if robot and robot.get('online')
                else '알 수 없음 (데이터 없음)')


def probe_port_table(wired_ids, wired_ports, router_port):
    """
    도커처럼 ping 명령이 없을 때 대상별로 TCP 연결을 시도할 포트 {대상 키: 포트}.

    표에 없는 대상(로봇·팔 PC·로봇망 공유기)은 net_status_node 의 tcp_probe_port(ssh 22)를 쓴다.
    유선 공유기는 ssh 가 없어 관리 화면(80) 같은 열린 포트를 따로 준다. 0 이하 포트는 넣지 않는다.
    """
    if len(wired_ids) != len(wired_ports):
        raise ValueError('wired_ids 와 wired_probe_ports 의 개수가 다름')
    table = {key: int(port) for key, port in zip(wired_ids, wired_ports) if int(port) > 0}
    if int(router_port or 0) > 0:
        table['wired_router'] = int(router_port)
    return table


def split_arms_by_host(arms, hostname):
    """
    팔을 도는 PC 로 나눈다 → (관제 PC 팔, 다른 PC 팔, 다른 PC 이름).

    팔 배치(site_arms.yaml, 스냅샷의 site.host)가 관제 PC hostname 과 같으면(대소문자 무시) 관제 PC 팔이다.
    host 가 비었거나 hostname 을 모르면 다른 PC 팔로 둔다 (예전처럼 팔 PC 상자에 들어간다).
    ROS 그래프는 노드가 어느 PC 에서 도는지 알려 주지 않아서 배치 표를 믿는다.
    """
    items = [a for a in (arms or {}).get('arms', []) if isinstance(a, dict)]
    me = (hostname or '').strip().lower()
    local, remote, names = [], [], []
    for arm in items:
        host = str((arm.get('site') or {}).get('host') or '').strip()
        if me and host.lower() == me:
            local.append(arm)
        else:
            remote.append(arm)
            if host and host not in names:
                names.append(host)
    return local, remote, ' · '.join(names)


def _arm_rows(items):
    return [{'arm_id': a.get('arm_id'), 'alias': a.get('alias'),
             'zone': (a.get('site') or {}).get('station'), 'online': bool(a.get('online')),
             'state': a.get('state'), 'age': a.get('age')} for a in items]


def _arm_nodes(names, items):
    """팔 노드 이름 중 이 팔들(alias → '<alias>_adapter')의 것."""
    wanted = {f'{a.get("alias")}_adapter' for a in items if a.get('alias')}
    return [n for n in names if n in wanted]


def _local_arms_box(arms, items, names, rates=None):
    """관제 PC 안에서 도는 팔 묶음 상자 (핑 없음: 같은 PC). 팔이 없으면 None."""
    if not items:
        return None
    rows = _arm_rows(items)
    online = sum(1 for a in rows if a['online'])
    if not arms or not arms.get('controller_online'):
        state, text = NA, '팔 명령 노드 꺼짐 (모름)'
    else:
        state = OK if online == len(rows) else WARN if online else BAD
        text = f'팔 {online}/{len(rows)} 연결'
    return _box('local_arms', '이 PC 팔 ' + '·'.join(a['alias'] or a['arm_id'] for a in rows),
                state, text, kind='arms', arms=rows, nodes=names, rates=rates or {})


def _station_box(arms, ping, rates, host_name=''):
    """팔 PC 상자 (id 'station'): 관제 PC 가 아닌 PC 에서 도는 팔의 연결 상태 + 핑."""
    ping_state = ping['state'] if ping else NA
    label = _pc_label('팔 PC', host_name)
    if not arms or not arms.get('controller_online'):
        return _box('station', label, NA,
                    '로봇팔 명령 노드 꺼짐 (팔 상태 모름)', kind='station', ping=ping,
                    rates=rates, arms=[], dds='알 수 없음')
    items = [a for a in arms.get('arms', []) if isinstance(a, dict)]
    online = [a for a in items if a.get('online')]
    if not items:
        return _box('station', label, NA, '이 PC 에 놓인 팔 없음', kind='station', ping=ping,
                    rates=rates, arms=[], dds='알 수 없음')
    if items and len(online) == len(items):
        state = WARN if ping_state in (WARN, BAD) else OK
        text = f'팔 {len(online)}/{len(items)} 연결'
    elif online:
        state, text = WARN, f'팔 {len(online)}/{len(items)} 연결'
    elif ping_state == BAD:
        state, text = BAD, '네트워크 끊김 (핑 응답 없음)'
    elif ping_state in (OK, WARN):
        state, text = BAD, '핑은 되는데 팔 상태 없음 (팔 노드 확인)'
    else:
        state, text = BAD, '팔 상태 없음'
    arm_rows = _arm_rows(items)
    return _box('station', label, state, text, kind='station', ping=ping,
                rates=rates, arms=arm_rows,
                dds='같은 도메인에서 데이터 수신됨' if online else '알 수 없음 (데이터 없음)')


def _pc_label(base, hostname):
    return f'{base} · {hostname}' if hostname else base


# 영상 분석·이상 감지 경로에서 관제 PC(도메인 100)에 보여야 할 노드: (이름 패턴, 카드 줄 이름)
VISION_NODE_LABELS = (('mqtt_zone_evidence', '근거 수신기'), ('anomaly_monitor', '이상 감지'))
# 자세히 확인 때 재는 근거 토픽 (net_status_node evidence_topics 의 키 'evidence<토픽>')
EVIDENCE_LABELS = {'evidence/anomaly_monitor/zone_evidence': '구역 근거 주기',
                   'evidence/anomaly_monitor/box_evidence': '상자 근거 주기'}


def _ping_box(box_id, label, ping, ok_text, kind, **extra):
    state = ping['state'] if ping else NA
    text = ('측정 없음' if not ping else ok_text if state == OK
            else '응답 없음' if state == BAD else '핑 불안정')
    return _box(box_id, label, state, text, kind=kind, ping=ping, **extra)


def _wired_view(net, local, cctv, vision_label):
    """
    유선망(영상·분석) 묶음: 유선 공유기, 천장 카메라, MQTT 브로커, 팔 PC 유선, 영상 분석 상자.

    핑은 net_status_node 의 wired_* 대상이다. 천장 카메라는 핑과 현장영상 중계(cctv.health())를
    같이 본다. 중계는 보는 사람이 있을 때만 붙으므로 끊김 자체로는 나쁘다고 하지 않는다.
    영상 분석 상자는 브로커 핑 + 관제 PC 에서 보이는 근거 수신기·이상 감지 노드 + 근거 주기다.
    """
    router = _ping_box('wired_router', '유선 공유기', _ping(net, 'wired_router'), '핑 정상',
                       'router')
    cctv_box = _ping_box('cctv', '천장 카메라', _ping(net, 'cctv'), '핑 정상', 'camera',
                         relay=cctv)
    if cctv and cctv.get('connected') and cctv_box['state'] == OK:
        cctv_box['text'] = '영상 받는 중'
    elif cctv and cctv.get('viewers') and cctv.get('error'):
        cctv_box['state'], cctv_box['text'] = BAD, '영상 못 받음'
    broker = _ping_box('broker', 'MQTT 브로커', _ping(net, 'broker'), '핑 정상', 'broker')
    station = _ping_box('station_wired', '팔 PC 유선', _ping(net, 'station_wired'),
                        '같은 팔 PC', 'station_wired')
    nodes = (local or {}).get('vision_nodes') or []
    rates = {k: _rate(net, k) for k in EVIDENCE_LABELS}
    local_test = str((net or {}).get('local_ip') or '').startswith('127.')
    vision = {'id': 'vision', 'label': '영상 분석·이상 감지', 'kind': 'vision',
              'nodes': nodes, 'rates': rates, 'rate_labels': EVIDENCE_LABELS,
              'broker_ping': broker['ping'], 'pc_label': vision_label,
              'local_test': local_test}
    expected = len(VISION_NODE_LABELS)
    found = sum(1 for p, _ in VISION_NODE_LABELS
                if any(fnmatch.fnmatchcase(n, p) for n in nodes))
    if found == expected:
        vision['state'] = WARN if broker['state'] in (WARN, BAD) else OK
        suffix = ' · 브로커 응답 없음' if broker['state'] == BAD else ''
        vision['text'] = '근거 수신 노드 보임' + suffix
    elif local_test:
        vision['state'], vision['text'] = NA, '이 PC 안 시험 (이상 감지 없음)'
    else:
        vision['state'] = WARN
        vision['text'] = f'노드 {found}/{expected} 보임'
    devices = [cctv_box, broker, station]
    links = [{'from': 'control', 'to': 'wired_router', 'state': router['state'],
              'ms': (router['ping'] or {}).get('last_ms')}]
    for box in devices:
        links.append({'from': 'wired_router', 'to': box['id'], 'state': box['ping']['state']
                      if box['ping'] else NA,
                      'ms': (box['ping'] or {}).get('last_ms')})
    state = worst([router['state'], vision['state']] + [b['state'] for b in devices])
    return {'state': state, 'router': router, 'devices': devices, 'cctv': cctv_box,
            'broker': broker, 'station': station, 'vision': vision, 'links': links}


def network_view(local, snapshot, source_online, controller_online, arms, net, net_online,
                 robots, arm_ids, hosts=None, cctv=None, vision_label=None):
    """
    구조도 데이터: 관제 PC 안 노드·팔 상자, 공유기·로봇·팔 PC 상자, 그리고 선(핑).

    local: 관제 PC 자기 정보 (RMW·도메인·DDS 설정·도메인 100 노드 이름).
    snapshot: fleet_status 스냅샷 또는 None. arms: ArmStore.snapshot().
    net: net_status 측정값 또는 None, net_online: 측정 노드가 살아 있는지.
    hosts: HostStore.get_all() (다른 PC 의 상태 보고, 'station' 이면 팔 PC 카드에 쓴다) 또는 None.
    팔은 site.host 로 나눈다 (split_arms_by_host): 관제 PC 팔은 local_arms, 나머지는 station 상자.
    robots·arm_ids: 그릴 로봇·팔 목록 (측정 노드 설정이 없어도 상자는 그린다).
    """
    snap = snapshot or {}
    infra = snap.get('infra') or {}
    fresh = bool(source_online)
    net = net if net_online else None
    robot_data = snap.get('robots') or {}
    bridges = infra.get('bridges') or {}

    control = [
        _box('fleet_api', 'fleet_api', OK, '웹 백엔드 응답 중'),
        _box('fleet_status', 'fleet_status', OK if fresh else BAD,
             '상태 1 Hz 수신' if fresh else '상태 끊김'),
        _box('fleet_control', 'fleet_control', OK if controller_online else BAD,
             '작업 목록 수신' if controller_online else '작업 노드 응답 없음'),
        _box('zone_manager', 'zone_manager', _infra_state(infra.get('zone_manager'), fresh),
             _infra_text(infra.get('zone_manager'), fresh),
             note=_infra_note(infra.get('zone_manager'), fresh)),
        _box('arm_command', 'arm_command',
             OK if arms and arms.get('controller_online') else BAD,
             '팔 상태 모음 수신' if arms and arms.get('controller_online') else '팔 명령 노드 응답 없음'),
        _box('net_status', 'net_status', OK if net_online else BAD,
             '측정 중' if net_online else '측정 노드 응답 없음'),
    ]
    bridge_boxes = []
    for robot_id in robots:
        item = bridges.get(robot_id)
        state = _infra_state(item, fresh)
        text = _infra_text(item, fresh)
        bridge_boxes.append(_box(f'bridge_{robot_id}', f'브릿지 {robot_id}', state, text,
                                 node=(item or {}).get('node'), robot=robot_id,
                                 note=_infra_note(item, fresh)))

    router_ping = _ping(net, 'router')
    router = _box('router', '공유기', router_ping['state'] if router_ping else NA,
                  '핑 정상' if router_ping and router_ping['state'] == OK
                  else '측정 없음' if not router_ping else '핑 불안정',
                  kind='router', ping=router_ping)

    devices = []
    for robot_id in robots:
        bridge_state = _infra_state(bridges.get(robot_id), fresh)
        devices.append(_robot_box(robot_id, robot_data.get(robot_id), fresh,
                                  _ping(net, robot_id), _rate(net, f'{robot_id}/patrol_status'),
                                  bridge_state))
    arm_rates = {arm: _rate(net, f'{arm}/status') for arm in arm_ids}
    local_items, remote_items, remote_name = split_arms_by_host(
        arms, (local or {}).get('hostname'))
    remote_arms = dict(arms, arms=remote_items) if arms else arms
    names = (local or {}).get('station_nodes') or []
    local_names = _arm_nodes(names, local_items)
    local_ids = {a.get('arm_id') for a in local_items}
    local_arms = _local_arms_box(arms, local_items, local_names,
                                 {k: v for k, v in arm_rates.items() if k in local_ids})
    remote_ids = {a.get('arm_id') for a in remote_items}
    station = _station_box(remote_arms, _ping(net, 'station'),
                           {k: v for k, v in arm_rates.items() if k in remote_ids},
                           remote_name)
    station['nodes'] = [n for n in names if n not in local_names]

    # 선: 관제 PC─공유기, 공유기─각 장치. 상태는 그 구간 대상의 핑 판정.
    links = [{'from': 'control', 'to': 'router',
              'state': router_ping['state'] if router_ping else NA,
              'ms': router_ping['last_ms'] if router_ping else None}]
    for box in [station] + devices:
        ping = box.get('ping')
        links.append({'from': 'router', 'to': box['id'],
                      'state': ping['state'] if ping else NA,
                      'ms': ping['last_ms'] if ping else None})

    wired = _wired_view(net, local, cctv, vision_label)
    control_state = worst([b['state'] for b in control + bridge_boxes])
    health = health_view(snap, fresh, devices, station, arms, control + bridge_boxes, local,
                         net, net_online, hosts, wired=wired, arm_rates=arm_rates,
                         local_arms=local_arms, remote_arms=remote_arms)
    overall = worst([control_state, router['state'], station['state'], health['state'],
                     wired['state']]
                    + [d['state'] for d in devices]
                    + ([local_arms['state']] if local_arms else []))
    return {'overall': overall, 'health': health, 'local': local, 'control': control,
            'bridges': bridge_boxes, 'wired': wired, 'local_arms': local_arms,
            'control_state': control_state, 'router': router, 'station': station,
            'robots': devices, 'links': links, 'net_online': bool(net_online),
            'interfaces': [dict(i, summary=interface_summary(i), badges=interface_badges(i),
                                kind_text=kind_text(i.get('kind')))
                           for i in (net or {}).get('interfaces') or [] if isinstance(i, dict)],
            'detail': (net or {}).get('detail'),
            'local_ip': (net or {}).get('local_ip'),
            'ping_available': (net or {}).get('ping_available'),
            'probe': (net or {}).get('probe'), 'probe_port': (net or {}).get('probe_port'),
            'thresholds': (net or {}).get('thresholds')}
