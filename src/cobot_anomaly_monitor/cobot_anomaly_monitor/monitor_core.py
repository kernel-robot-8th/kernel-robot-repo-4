"""관제 스냅샷을 7단계 기록으로 바꾸고 CCTV 이벤트를 판정한다. ROS에 의존하지 않는다."""

from collections import deque, OrderedDict
import json
import math
import time
import uuid

from .debug_view import (
    parse_zone_status, ready_problems, RouteTrace, STATUS_FIELDS, zone_table)
from .judgment import is_duplicate, judge
from .scenario_view import (
    cargo_of, driving_of, op_state_of, queue_wait_of, RESUMABLE_STAGES, STAGE_STEP,
    STEP_CARGO_AFTER, STEP_CODES, step_of, zone_of)

MODES = ('OBSERVE_ONLY', 'AUTO_HOLD')
TERMINAL = ('COMPLETED', 'FAILED')
BLOCKED = ('UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL')
ACK_STATES = ('ACKNOWLEDGED', 'RESOLVED', 'FALSE_ALARM')
STOP_REQUEST = {'PAUSE': 'pause', 'ESTOP': 'estop'}
REPLY_LIMIT = 200
LOG_LIMIT = 30
TASK_LIMIT = 10
CAMERA_POLICIES = ('field', 'sim')


def step_code(step):
    """7단계 번호를 이름으로 바꾼다."""
    return STEP_CODES[step - 1] if step else 'NONE'


def camera_allowed(camera_id, policy):
    """현장에서 시뮬 이벤트가 정지를 부르지 않게 한다. sim이면 시뮬 카메라만 받는다."""
    if policy not in CAMERA_POLICIES:
        raise ValueError('camera_policy: field 또는 sim')
    return str(camera_id).startswith('sim_') == (policy == 'sim')


def clean_event(raw, now):
    """합의한 이벤트 형식만 받는다. 좌표는 둘 다 있어야 위치로 본다."""
    if not isinstance(raw, dict):
        raise ValueError('이벤트는 JSON 객체')
    for name in ('event_id', 'camera_id', 'vision_class'):
        if not isinstance(raw.get(name), str) or not raw[name]:
            raise ValueError(f'{name} 필요')
    event = dict(raw, confidence=raw.get('confidence', 0.0), zone_id=raw.get('zone_id') or '',
                 detected_at=raw.get('detected_at', now), bbox=raw.get('bbox') or [])
    for name in ('confidence', 'detected_at'):
        if not _number(event[name]):
            raise ValueError(f'{name}은 숫자')
    if not (_number(raw.get('map_x')) and _number(raw.get('map_y'))):
        event.update(map_x=None, map_y=None)
    return event


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class MonitorCore:
    """주문 실행은 관제가 맡고 여기서는 기록·판정과 정지 요청만 한다."""

    def __init__(self, store, routes, robots, send, mode='OBSERVE_ONLY', clock=time.time,
                 points=None):
        if mode not in MODES:
            raise ValueError('mode: OBSERVE_ONLY 또는 AUTO_HOLD')
        self.store, self.routes, self.robots = store, routes, list(robots)
        self.send, self.mode, self.clock = send, mode, clock
        self.status, self.pose, self.speed = {}, {}, {}
        self.orders, self.holds = {}, {}
        self.armed, self.tasks_at = None, None
        self.steps = {row['mission_id']: row['current_step_seq'] for row in store.scenarios(500)}
        self.replies = OrderedDict()
        self.control_requests = {}
        self.trace = RouteTrace(points or {})
        self.zones, self.tasks, self.seen = {}, [], {}
        self.graph, self.ros = None, {}
        self.log = deque(maxlen=LOG_LIMIT)
        self.log_rows = {}

    def _seen(self, robot, topic):
        self.seen.setdefault(robot, {})[topic] = self.clock()

    def on_status(self, robot, status):
        """순찰 상태를 받는다."""
        self.status[robot] = status
        self._seen(robot, 'patrol_status')

    def on_pose(self, robot, x, y, yaw):
        """amcl_pose를 받는다. 정지 중에는 발행이 멈추므로 시간으로 버리지 않는다."""
        self.pose[robot] = (x, y, yaw)
        self.trace.update(robot, x, y)
        self._seen(robot, 'amcl_pose')

    def on_speed(self, robot, speed):
        """오도메트리 속도를 받는다."""
        self.speed[robot] = speed
        self._seen(robot, 'odom')

    def on_zone_status(self, text):
        """구역 관리자의 점유 상태를 받는다. 바뀔 때만 오므로 켜기 전 값은 모른다."""
        parsed = parse_zone_status(text)
        if parsed:
            self.zones[parsed[0]] = parsed[1]

    def on_tasks(self, snapshot):
        """관제 스냅샷을 기록에 맞춘다."""
        self.armed, self.tasks_at = snapshot.get('armed'), self.clock()
        self.holds = snapshot.get('holds') or {}
        self.tasks = (snapshot.get('tasks') or [])[:TASK_LIMIT]
        self.orders = {order['order_id']: order for order in snapshot.get('orders', [])}
        for order in self.orders.values():
            self._sync_order(order)
        self.flush()

    def flush(self):
        """로봇 상태 표를 현재 값으로 맞춘다."""
        for robot, view in self.robots_view().items():
            pose = self.pose.get(robot, (None, None, None))
            self.store.save_live({
                'robot_id': robot, 'op_state': view['op_state'],
                'cargo_state': view['cargo_state'], 'current_zone': view['zone'],
                'last_waypoint': view['waypoint'], 'pose_x': pose[0], 'pose_y': pose[1],
                'pose_yaw': pose[2], 'speed_mps': view['speed_mps'],
                'active_mission_id': view['order_id'], 'active_step_seq': view['step_seq'],
                'active_step_code': step_code(view['step_seq']), 'updated_at': view['updated_at']})

    def _route(self, order):
        route = dict(self.routes.get(order['route'], {}))
        if order.get('kind') == 'return' and route:
            route.update(pickup=route['dropoff'], dropoff=route['pickup'],
                         pickup_arm=route['dropoff_arm'], dropoff_arm=route['pickup_arm'])
        return route

    def _step(self, order):
        """단계는 앞으로만 간다. 재개 뒤 상태값이 잠시 뒤처져도 되돌리지 않는다."""
        if not order.get('robot_id'):
            return 0
        step = step_of(order, self.status.get(order['robot_id']), self._route(order))
        return max(step, self.steps.get(order['order_id'], 0))

    def _sync_order(self, order):
        mission = order['order_id']
        stored = self.store.scenario(mission)
        if stored and stored['mission_state'] in TERMINAL:
            return
        previous = self.steps.get(mission, 0)
        step, route, now = self._step(order), self._route(order), self.clock()
        reason = stored['hold_reason'] if stored else ''
        if stored and stored['mission_state'] in BLOCKED and order['state'] == 'RUNNING':
            reason = ''
        self.store.save_scenario({
            'mission_id': mission, 'route': order['route'], 'kind': order.get('kind', 'delivery'),
            'sku': order['sku'], 'quantity': order['quantity'], 'robot_id': order.get('robot_id'),
            'load_arm_id': route.get('pickup_arm', ''),
            'unload_arm_id': route.get('dropoff_arm', ''),
            'current_step_seq': step, 'current_step_code': step_code(step),
            'current_stage': order['stage'], 'cargo_state': cargo_of(order),
            'mission_state': order['state'], 'hold_reason': reason,
            'detail': order.get('detail') or '',
            'created_at': stored['created_at'] if stored else order.get('created_at', now),
            'updated_at': now})
        if step > previous:
            self._advance(order, route, previous, step, now)
        self.steps[mission] = step
        if step:
            self._mark_task(order, step, reason, now)

    def _advance(self, order, route, previous, step, now):
        mission = order['order_id']
        if previous:
            state = 'FAILED' if order.get('failure') else 'SUCCEEDED'
            self.store.update_task(f'{mission}-S{previous}', state, now)
        completed = set(order.get('completed', ()))
        for seq in range(previous + 1, step + 1):
            # 스냅샷은 1초 주기라 짧은 단계는 사이에 끝날 수 있다.
            passed = {s for s, n in STAGE_STEP.items() if n == seq} & completed
            state = 'RUNNING' if seq == step else 'SUCCEEDED' if passed else 'SKIPPED'
            self.store.save_task({
                'task_id': f'{mission}-S{seq}', 'mission_id': mission, 'step_seq': seq,
                'step_code': step_code(seq), 'actor_id': self._actor(order, route, seq),
                'expected_cargo_after': STEP_CARGO_AFTER[seq - 1], 'task_state': state,
                'started_at': now, 'finished_at': None if seq == step else now})

    @staticmethod
    def _actor(order, route, step):
        return {3: route.get('pickup_arm'), 6: route.get('dropoff_arm')}.get(
            step) or order['robot_id']

    def _mark_task(self, order, step, reason, now):
        task_id, state = f"{order['order_id']}-S{step}", order['state']
        if state == 'COMPLETED':
            self.store.update_task(task_id, 'SUCCEEDED', now)
        elif state == 'FAILED':
            self.store.update_task(task_id, 'FAILED', now)
        elif state in BLOCKED:
            self.store.update_task(task_id, 'HOLD_ANOMALY' if reason else 'BLOCKED')
        else:
            self.store.update_task(task_id, 'RUNNING')

    def _active_order(self, robot):
        return next((order for order in self.orders.values()
                     if order.get('robot_id') == robot and order['state'] not in TERMINAL), None)

    def robots_view(self):
        """판정 입력인 로봇 스냅샷을 만든다."""
        return {robot: self._robot_view(robot) for robot in self.robots}

    def _robot_view(self, robot):
        status, order = self.status.get(robot), self._active_order(robot)
        pose = self.pose.get(robot, (None, None, None))
        speed = self.speed.get(robot)
        op_state = op_state_of(status, order is not None)
        if robot in self.holds or (order and order['state'] in BLOCKED):
            stored = self.store.scenario(order['order_id']) if order else None
            op_state = 'HOLD_ANOMALY' if stored and stored['hold_reason'] else 'PAUSED'
        return {
            'order_id': order['order_id'] if order else None,
            'stage': order['stage'] if order else None,
            'step_seq': self._step(order) if order else 0,
            'cargo_state': cargo_of(order) if order else 'EMPTY',
            'zone': zone_of(status, order is not None), 'pose_x': pose[0], 'pose_y': pose[1],
            'pose_yaw': pose[2], 'speed_mps': speed, 'driving': driving_of(status),
            'queue_wait': queue_wait_of(status, speed),
            'updated_at': self.clock(), 'op_state': op_state,
            'waypoint': str((status or {}).get('detail') or '')}

    def request(self, payload, control=None):
        """관제 요청을 보내고 request_id를 돌려준다. 응답은 task_events로 온다."""
        request_id = uuid.uuid4().hex
        if control:
            self.control_requests[request_id] = control
        row = {'at': self.clock(), 'type': payload.get('type'),
               'robot_id': payload.get('robot_id'), 'operation': payload.get('operation'),
               'points': payload.get('points'), 'status': None, 'rtt_ms': None, 'detail': ''}
        self.log.append(row)
        self.log_rows[request_id] = row
        self.send(dict(payload, request_id=request_id))
        return request_id

    def on_task_event(self, event):
        """요청 응답을 보관하고 CCTV 조치 결과를 기록에 반영한다."""
        if event.get('type') != 'reply' or not event.get('request_id'):
            return
        request_id = event['request_id']
        self.replies[request_id] = event
        self._log_reply(request_id, event)
        while len(self.replies) > REPLY_LIMIT:
            self.replies.popitem(last=False)
        control = self.control_requests.pop(request_id, None)
        if control:
            self._record_reply(control, event)

    def _log_reply(self, request_id, event):
        row = self.log_rows.pop(request_id, None)
        if row:
            body = event.get('body') or {}
            row.update(status=event.get('status'), detail=body.get('detail', ''),
                       rtt_ms=round((self.clock() - row['at']) * 1000.0, 1))
        while len(self.log_rows) > REPLY_LIMIT:
            self.log_rows.pop(next(iter(self.log_rows)))

    def _record_reply(self, control, event):
        event_id, robot = control
        row = self.store.event(event_id)
        detail = json.loads(row['control_detail'] or '{}')
        detail[robot] = {'status': event.get('status'), 'body': event.get('body')}
        failed = any(not 200 <= (d.get('status') or 0) < 300 for d in detail.values()
                     if isinstance(d, dict))
        action = row['control_action'].rsplit('_', 1)[0]
        self.store.set_control(event_id, action + ('_FAILED' if failed else '_ACCEPTED'), detail)

    def on_vision_event(self, raw):
        """이벤트를 판정해 기록하고 모드에 맞게 조치한다."""
        event = clean_event(raw, self.clock())
        known = self.store.event(event['event_id'])
        if known:
            return known
        same = is_duplicate(event, self.store.open_events(), event['detected_at'])
        if same:
            self.store.touch_event(same['event_id'], event['detected_at'])
            return self.store.event(same['event_id'])
        robots = self.robots_view()
        result = judge(event, robots)
        linked = robots.get(result['linked_robot_id'], {})
        self.store.add_event({
            'event_id': event['event_id'], 'detected_at': event['detected_at'],
            'last_seen': event['detected_at'], 'repeat_count': 1, 'camera_id': event['camera_id'],
            'vision_class': event['vision_class'], 'confidence': event['confidence'],
            'bbox_json': json.dumps(event['bbox']), 'map_x': event.get('map_x'),
            'map_y': event.get('map_y'), 'zone_id': event['zone_id'],
            'linked_robot_id': result['linked_robot_id'],
            'linked_mission_id': result['linked_order_id'],
            'robot_step_at_event': step_code(linked.get('step_seq', 0)),
            'robot_cargo_at_event': linked.get('cargo_state', 'UNKNOWN'),
            'judgment': result['judgment'], 'recommended_action': result['recommended_action'],
            'stop_targets_json': json.dumps(result['stop_targets']),
            'alarm_text': result['alarm_text'], 'control_action': 'NONE'})
        self._control(event['event_id'], result, robots)
        return self.store.event(event['event_id'])

    def _control(self, event_id, result, robots):
        action, targets = result['recommended_action'], result['stop_targets']
        if action == 'NONE' or not targets:
            return
        if self.mode != 'AUTO_HOLD':
            self.store.set_control(event_id, 'OBSERVE_ONLY', {})
            return
        self.store.set_control(event_id, action + '_SENT', {})
        for robot in targets:
            order_id = robots[robot].get('order_id')
            if order_id:
                self.store.set_hold_reason(order_id, f"CCTV {result['judgment']} {event_id}")
            self.request({'type': STOP_REQUEST[action], 'robot_id': robot,
                          'client_request_id': 'cctv_' + event_id[:60]}, (event_id, robot))

    def set_mode(self, mode):
        """판정 뒤 조치 범위를 바꾼다."""
        if mode not in MODES:
            raise ValueError('mode: OBSERVE_ONLY 또는 AUTO_HOLD')
        self.mode = mode
        return mode

    def acknowledge(self, event_id, state, operator, note=''):
        """운영자 확인을 기록한다. 로봇 복구는 관제 resolve로 따로 요청한다."""
        if state not in ACK_STATES:
            raise ValueError('ack_state: ' + ', '.join(ACK_STATES))
        if not isinstance(operator, str) or not operator.strip():
            raise ValueError('operator 필요')
        if not self.store.event(event_id):
            raise KeyError(event_id)
        self.store.set_ack(event_id, state, operator, note, self.clock())
        return self.store.event(event_id)

    def close_events(self, mission_id, operator, note=''):
        """관제가 복구를 받은 주문의 열린 이벤트를 닫는다."""
        for row in self.store.open_events():
            if row['linked_mission_id'] == mission_id:
                self.store.set_ack(row['event_id'], 'RESOLVED', operator, note, self.clock())

    def _link(self, robot, now):
        status = self.status.get(robot) or {}
        ages = {topic: now - at for topic, at in self.seen.get(robot, {}).items()}
        graph = (self.graph or {}).get('robots', {}).get(robot, {})
        return {'robot_id': robot, 'status': {key: status.get(key) for key in STATUS_FIELDS},
                'ages': ages, 'graph': graph, 'problems': ready_problems(robot, self.graph)}

    def live(self):
        """웹 표시용 현재 상태를 만든다."""
        now = self.clock()
        views = self.robots_view()
        missions = []
        for row in self.store.scenarios(20):
            row['recovery'] = None
            if row['mission_state'] in BLOCKED:
                row['recovery'] = 'resume' if row['current_stage'] in RESUMABLE_STAGES else 'fail'
            missions.append(row)
        return {'time': now, 'mode': self.mode, 'armed': self.armed, 'ros': self.ros,
                'zones': zone_table(self.zones, self.status), 'tasks': self.tasks,
                'log': list(reversed(self.log)), 'routes': self.trace.routes,
                'links': [self._link(robot, now) for robot in self.robots],
                'fleet_age_sec': None if self.tasks_at is None else now - self.tasks_at,
                'robots': [dict(views[r], robot_id=r) for r in self.robots],
                'holds': self.holds, 'missions': missions, 'anomalies': self.store.events(30)}
