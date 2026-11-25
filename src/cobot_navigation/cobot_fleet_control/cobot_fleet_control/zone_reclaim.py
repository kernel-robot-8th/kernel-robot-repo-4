"""홈 초기위치 때 다시 켜져 토큰을 잊은 로봇의 구역을 푼다. 시간 초과만으로는 풀지 않는다."""

import math

ZONE_STATUS_MAX_AGE_SEC = 3.0   # zone_manager 는 1초마다 상태를 다시 낸다 [s]
RADIUS_M = 0.3                  # AMCL 이 홈에 왔다고 볼 거리 [m]
TIMEOUT_SEC = 10.0              # 초기위치를 낸 뒤 AMCL 을 기다리는 시간 [s]


class ZoneReclaim:
    """초기위치 요청과 AMCL 확인을 분리한다. 대기는 메모리에만 두어 관제 재시작이면 버린다."""

    def __init__(self, scenario, fleet, gateway, radius_m=RADIUS_M, timeout_sec=TIMEOUT_SEC):
        if not all(math.isfinite(v) and v > 0 for v in (radius_m, timeout_sec)):
            raise ValueError('구역 회수 거리·시간은 양수')
        self.scenario, self.fleet, self.gateway = scenario, fleet, gateway
        self.radius_m, self.timeout_sec = radius_m, timeout_sec
        self.pending = {}

    def refusal(self, robot, zone):
        """풀면 안 되는 이유. 풀어도 되면 빈 문자열."""
        scenario = self.scenario
        state, age = self.gateway.zone_state(zone)
        if state is None or age > ZONE_STATUS_MAX_AGE_SEC:
            return '구역 상태를 zone_manager 에서 받지 못함'
        if state != f'occupied_by:{robot}':
            return f'점유자가 {robot} 이 아님 ({state})'
        if not scenario._fresh(robot):
            return '로봇 상태 또는 배터리 수신이 오래됨'
        status = scenario.health.get(robot, {}).get('status', {})
        if status.get('busy') is not False:
            return '로봇이 멈춰 있는지 확인되지 않음'
        if 'held_zone' not in status or status['held_zone'] is not None:
            return '로봇이 토큰을 잊었는지 확인되지 않음'
        if scenario.store.has_open_order(robot) or self.fleet.repository.busy(robot):
            return '진행 중이거나 결과를 모르는 주문·작업이 있음'
        claim = scenario.store.zone_claim(zone)
        boot = status.get('boot_id')
        if claim is None or claim[0] != robot or not boot:
            return '점유 당시 부팅 기록이 없음'
        if claim[1] == boot:
            return '점유한 뒤 로봇이 다시 켜지지 않음'
        return ''

    def request(self, robot, zones, home, source):
        """지금 조건이 맞는 구역만 대기로 둔다. (대기 구역, {건너뛴 구역: 이유}) 를 돌려준다."""
        self.discard(robot, '새 초기위치 요청')
        skipped = {zone: reason for zone in zones if (reason := self.refusal(robot, zone))}
        waiting = [zone for zone in zones if zone not in skipped]
        if waiting:
            self.pending[robot] = {
                'zones': waiting, 'home': tuple(home), 'source': source,
                'boot_id': self.scenario.health[robot]['status']['boot_id'],
                'deadline': self.scenario.clock() + self.timeout_sec}
        return waiting, skipped

    def observe_pose(self, robot, x, y):
        """요청 뒤 받은 AMCL 위치가 홈 근처일 때만 조건을 다시 보고 한 번 푼다."""
        pending = self.pending.get(robot)
        if pending is None:
            return
        if self.scenario.clock() >= pending['deadline']:
            self.discard(robot, 'AMCL 홈 위치 확인 시간 초과')
            return
        # NaN 비교는 거짓이므로 '이하'일 때만 통과시킨다.
        if not math.dist((x, y), pending['home']) <= self.radius_m:
            return
        status = self.scenario.health.get(robot, {}).get('status', {})
        if status.get('boot_id') != pending['boot_id']:
            self.discard(robot, '확인 중 로봇이 다시 켜짐')
            return
        del self.pending[robot]
        for zone in pending['zones']:
            reason = self.refusal(robot, zone)
            if reason:
                self._skipped(robot, [zone], reason, pending['source'])
                continue
            self.scenario.store.event({
                'type': 'zone_release', 'zone': zone, 'robot_id': robot, 'robot_online': True,
                'note': '홈 초기위치·현장 확인 후 잊힌 구역 해제', 'source': pending['source']})
            self.gateway.release_zone(zone, robot)

    def tick(self):
        """시간 안에 홈 위치가 확인되지 않은 대기를 버린다. 점유는 그대로 둔다."""
        for robot, pending in list(self.pending.items()):
            if self.scenario.clock() >= pending['deadline']:
                self.discard(robot, 'AMCL 홈 위치 확인 시간 초과')

    def discard(self, robot, reason):
        """대기를 버리고 이유를 남긴다."""
        pending = self.pending.pop(robot, None)
        if pending is not None:
            self._skipped(robot, pending['zones'], reason, pending['source'])

    def _skipped(self, robot, zones, reason, source):
        self.scenario.store.event({
            'type': 'zone_reclaim_skipped', 'robot_id': robot, 'zones': list(zones),
            'detail': reason, 'source': source})
