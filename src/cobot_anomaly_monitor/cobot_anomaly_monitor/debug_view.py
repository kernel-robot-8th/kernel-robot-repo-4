"""메뉴 6.5 디버그 표시용 순수 계산. 관제나 로봇 상태를 바꾸지 않는다."""

import math

PASS_RADIUS_M = 0.15
TRACE_LIMIT = 40
STATUS_FIELDS = ('state', 'detail', 'waypoint', 'total', 'held_zone', 'busy', 'central_controlled',
                 'central_latched', 'command_id')


def parse_zone_status(text):
    """`/zone_manager/status`의 `A:free`, `A:occupied_by:pinky1`을 (구역, 점유자)로 읽는다."""
    zone, _, state = text.partition(':')
    if not zone or not state:
        return None
    if state == 'free':
        return zone, None
    return (zone, state.split(':', 1)[1]) if state.startswith('occupied_by:') else None


def zone_table(reported, statuses):
    """구역 관리자와 로봇이 말하는 점유자를 나란히 놓는다. 다르면 토큰이 샌 것이다."""
    held = {status['held_zone']: robot for robot, status in statuses.items()
            if status.get('held_zone')}
    rows = []
    for zone in sorted(set(reported) | set(held)):
        known = zone in reported
        manager, robot = reported.get(zone), held.get(zone)
        rows.append({'zone': zone, 'manager_known': known, 'manager': manager, 'robot': robot,
                     'match': manager == robot if known else None})
    return rows


def ready_problems(robot, graph):
    """fleet_control의 ready()가 이동을 거절할 이유를 미리 보여 준다."""
    if not graph:
        return ['연결 정보 없음']
    command = graph['robots'].get(robot, {}).get('patrol_cmd', {})
    checks = (('patrol_cmd 발행자', command.get('publishers')),
              ('patrol_cmd 구독자', command.get('subscribers')),
              ('task_request 구독자', graph['request'].get('subscribers')),
              ('tasks 발행자', graph['tasks'].get('publishers')))
    return [f'{name} {count}개 (1개여야 함)' for name, count in checks if count != 1]


class RouteTrace:
    """로봇이 지난 지점을 순서대로 남긴다. 게이트 경유처럼 경로를 확인하는 용도다."""

    def __init__(self, points, radius_m=PASS_RADIUS_M, limit=TRACE_LIMIT):
        self.points, self.radius_m, self.limit = points, radius_m, limit
        self.routes = {}

    def update(self, robot, x, y):
        """반경 안에서 가장 가까운 지점을 기록한다. 같은 지점은 이어서 쓰지 않는다."""
        near = [(math.dist((x, y), point[:2]), name) for name, point in self.points.items()]
        near = [item for item in near if item[0] <= self.radius_m]
        if not near:
            return
        name = min(near)[1]
        route = self.routes.setdefault(robot, [])
        if not route or route[-1] != name:
            route.append(name)
            del route[:-self.limit]
