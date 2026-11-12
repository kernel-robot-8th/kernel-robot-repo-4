"""관제 스냅샷을 7단계 기록으로 바꾸고 CCTV 이벤트를 판정한다. ROS에 의존하지 않는다."""

from collections import deque, OrderedDict
import json
import math
import time
import uuid

from .debug_view import (
    parse_zone_status, ready_problems, RouteTrace, STATUS_FIELDS, zone_table)
from .judgment import closed_before, INHERIT_SEC, is_duplicate, judge
from .scenario_view import (
    cargo_of, driving_of, op_state_of, queue_wait_of, RESUMABLE_STAGES, STAGE_STEP,
    STEP_CARGO_AFTER, STEP_CODES, step_of, zone_of)

MODES = ('OBSERVE_ONLY', 'AUTO_HOLD')
TERMINAL = ('COMPLETED', 'FAILED')
BLOCKED = ('UNKNOWN', 'PAUSED', 'ESTOP', 'MANUAL')
ACK_STATES = ('ACKNOWLEDGED', 'RESOLVED', 'FALSE_ALARM')
STOP_REQUEST = {'PAUSE': 'pause', 'ESTOP': 'estop'}
# 정지 요청이 나간 사건만 스냅샷으로 닫는다. 거절된 정지(_FAILED)는 운영자 확인으로 남긴다.
STOP_OPEN = tuple(action + suffix for action in STOP_REQUEST for suffix in ('_SENT', '_ACCEPTED'))
FLEET_RESOLVER = 'fleet'
FLEET_RESOLVED_NOTE = '관제에서 재개됨(스냅샷으로 확인)'
STOP_SKIPPED_NOTE = '이미 전체 정지 중'
# 걸리지 않은 정지는 같은 물체가 다시 감지될 때 다시 요청한다. 간격은 두 배씩 늘려 상한에서 멈춘다.
RESEND_FIRST_SEC = 5.0
RESEND_MAX_SEC = 60.0
REPLY_LIMIT = 200
LOG_LIMIT = 30
TASK_LIMIT = 10
CAMERA_POLICIES = ('field', 'sim')
STILL_SPEED_MPS = 0.03  # manual_adapter.MOVING_SPEED_MPS 와 같은 정지 기준


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
        self.stationary_pose = {}
        self.still_since = {}  # 오도메트리 속도가 STILL_SPEED_MPS 이하로 이어진 시작 시각
        self.battery = {}
        self.busy_robots = set()
        self.armed, self.tasks_at = None, None
        self.steps = {row['mission_id']: row['current_step_seq'] for row in store.scenarios(500)}
        self.replies = OrderedDict()
        self.control_requests = {}
        self.stop_sent = OrderedDict()  # event_id -> (마지막 정지 요청 시각, 보낸 횟수)
        self.trace = RouteTrace(points or {})
        self.zones, self.tasks, self.seen = {}, [], {}
        self.graph, self.ros = None, {}
        self.diagnostics = None
        self.log = deque(maxlen=LOG_LIMIT)
        self.log_rows = {}

    def _seen(self, robot, topic):
        self.seen.setdefault(robot, {})[topic] = self.clock()

    def on_status(self, robot, status):
        """순찰 상태를 받는다."""
        previous = self.status.get(robot, {})
        if (status.get('busy') is not False or status.get('boot_id') != previous.get('boot_id')
                or self.clock() - self.seen.get(robot, {}).get('patrol_status', 0) > 3):
            self.stationary_pose[robot] = False
        self.store.record_robot_report(robot, status)
        self.status[robot] = status
        self._seen(robot, 'patrol_status')

    def on_battery(self, robot, percent):
        if 0 <= percent <= 100:
            self.battery[robot] = percent
            self._seen(robot, 'battery')

    def on_pose(self, robot, x, y, yaw):
        """amcl_pose를 받는다. 정지 중에는 발행이 멈추므로 시간으로 버리지 않는다."""
        self.stationary_pose[robot] = self.status.get(robot, {}).get('busy') is False
        self.pose[robot] = (x, y, yaw)
        self.trace.update(robot, x, y)
        self._seen(robot, 'amcl_pose')

    def on_speed(self, robot, speed):
        """오도메트리 속도를 받는다. 멈춘 시간도 잰다(AMCL 은 정지 중 위치를 내지 않는다)."""
        self.speed[robot] = speed
        if isinstance(speed, (int, float)) and math.isfinite(speed) and abs(speed) <= STILL_SPEED_MPS:
            self.still_since.setdefault(robot, self.clock())
        else:
            self.still_since.pop(robot, None)
        self._seen(robot, 'odom')

    def on_zone_status(self, text):
        """구역 관리자의 점유 상태를 받는다."""
        parsed = parse_zone_status(text)
        if parsed:
            self.zones[parsed[0]] = parsed[1]

    def on_tasks(self, snapshot):
        """관제 스냅샷을 기록에 맞춘다."""
        self.armed, self.tasks_at = snapshot.get('armed'), self.clock()
        self.holds = snapshot.get('holds') or {}
        tasks = snapshot.get('tasks') or []
        self.busy_robots = {t.get('robot_id') for t in tasks if t.get('state') not in ('SUCCEEDED', 'FAILED')}
        self.tasks = tasks[:TASK_LIMIT]
        self.orders = {order['order_id']: order for order in snapshot.get('orders', [])}
        self.store.record_trace_snapshot(self.orders.values(), tasks, self.tasks_at, self.status, self.seen)
        for order in self.orders.values():
            self._sync_order(order)
        self._close_recovered()
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
            'battery_percent': self.battery.get(robot),
            'central_latched': (status or {}).get('central_latched'),
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
        order_id = payload.get('order_id') or (payload['order'].get('order_id') if isinstance(payload.get('order'), dict) else None)
        if isinstance(order_id, str) and order_id:
            row['order_id'] = order_id
            self.store.record_control('control_request', order_id, request_id,
                                      dict(payload, request_id=request_id), row['at'])
        self.log.append(row)
        self.log_rows[request_id] = row
        self.send(dict(payload, request_id=request_id))
        return request_id

    def on_task_event(self, event):
        """요청 응답을 보관하고 CCTV 조치 결과를 기록에 반영한다."""
        if event.get('type') == 'scenario_bt_snapshot':
            self.store.record_terminal_resources(event)
            return
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
            received = self.clock()
            row.update(status=event.get('status'), detail=body.get('detail', ''),
                       rtt_ms=round((received - row['at']) * 1000.0, 1))
            if row.get('order_id'):
                self.store.record_control('control_reply', row['order_id'], request_id,
                                          dict(event, rtt_ms=row['rtt_ms']), received)
        while len(self.log_rows) > REPLY_LIMIT:
            self.log_rows.pop(next(iter(self.log_rows)))

    def _record_reply(self, control, event):
        event_id, robot = control
        row = self.store.event(event_id)
        detail = json.loads(row['control_detail'] or '{}')
        detail[robot] = {'status': event.get('status'), 'body': event.get('body')}
        failed = any(not self._stop_accepted(key, d) for key, d in detail.items()
                     if isinstance(d, dict))
        action = row['control_action'].rsplit('_', 1)[0]
        self.store.set_control(event_id, action + ('_FAILED' if failed else '_ACCEPTED'), detail)

    @staticmethod
    def _stop_accepted(key, reply):
        """전체 정지는 2xx만으로 믿지 않는다. 관제가 armed를 껐는지도 본다."""
        if not 200 <= (reply.get('status') or 0) < 300:
            return False
        return key != 'ALL' or (reply.get('body') or {}).get('armed') is False

    def on_vision_event(self, raw):
        """이벤트를 판정해 기록하고 모드에 맞게 조치한다."""
        event = clean_event(raw, self.clock())
        known = self.store.event(event['event_id'])
        if known:
            return known
        same = is_duplicate(event, self.store.open_events(), event['detected_at'])
        if same:
            self.store.touch_event(same['event_id'], event['detected_at'])
            self._retry(same)
            return self.store.event(same['event_id'])
        robots = self.robots_view()
        result = self._inherit(event, judge(event, robots), robots)
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
            'stop_scope': result['stop_scope'],
            'stop_targets_json': json.dumps(result['stop_targets']),
            'alarm_text': result['alarm_text'], 'control_action': 'NONE'})
        self._control(event['event_id'], result, robots)
        return self.store.event(event['event_id'])

    def _inherit(self, event, result, robots):
        """닫힌 로봇 지정 사건 자리의 재감지가 전체 정지로 번지지 않게 그 사건의 범위를 잇는다."""
        if result['judgment'] != 'LANE_OBSTACLE':
            return result
        at = event['detected_at']
        closed = closed_before(event, self.store.resolved_since(at - INHERIT_SEC), at)
        if not closed:
            return result
        robot = closed['linked_robot_id']
        return {'judgment': closed['judgment'], 'linked_robot_id': robot,
                'linked_order_id': robots.get(robot, {}).get('order_id'),
                'recommended_action': closed['recommended_action'], 'stop_scope': 'ROBOT',
                'stop_targets': json.loads(closed['stop_targets_json']),
                'alarm_text': f"[재감지 {closed['event_id']}] {closed['alarm_text']}"}

    def _retry(self, row):
        """
        묶인 재감지에서 걸리지 않은 정지를 다시 요청한다.

        관찰 모드에서 기록만 한 사건도 AUTO_HOLD로 바뀐 뒤 다시 감지되면 여기서 세운다.
        판정은 다시 하지 않고 기록된 조치·범위·대상을 그대로 쓴다.
        """
        action = row['control_action']
        if self.mode != 'AUTO_HOLD' or row['hold_seen'] or not (
                action == 'OBSERVE_ONLY' or action.endswith(('_SENT', '_ACCEPTED', '_FAILED'))):
            return
        targets = json.loads(row['stop_targets_json'])
        everyone = row['stop_scope'] == 'ALL'
        if self._all_stopped() if everyone else (
                targets and all(robot in self.holds for robot in targets)):
            return
        sent_at, count = self.stop_sent.get(row['event_id'], (None, 0))
        if sent_at is not None and self.clock() - sent_at < min(
                RESEND_FIRST_SEC * 2 ** (count - 1), RESEND_MAX_SEC):
            return
        self._control(row['event_id'], {
            'judgment': row['judgment'], 'recommended_action': row['recommended_action'],
            'stop_scope': row['stop_scope'], 'stop_targets': targets}, self.robots_view())

    def _all_stopped(self):
        return self.armed is False and all(robot in self.holds for robot in self.robots)

    def _control(self, event_id, result, robots):
        action, targets = result['recommended_action'], result['stop_targets']
        everyone = result['stop_scope'] == 'ALL'
        if action == 'NONE' or not (targets or everyone):
            return
        if self.mode != 'AUTO_HOLD':
            self.store.set_control(event_id, 'OBSERVE_ONLY', {})
            return
        reason = f"CCTV {result['judgment']} {event_id}"
        if everyone:
            # 전체 정지는 사고와 무관한 주문도 세운다. 먼저 적힌 사유는 덮지 않는다.
            for robot in self.robots:
                if robots[robot].get('order_id'):
                    self.store.set_hold_reason(robots[robot]['order_id'], reason, keep=True)
            if action == 'PAUSE' and self._all_stopped():
                # 이미 전체 정지 중이면 pause를 겹쳐 보내지 않는다. estop은 언제나 보낸다.
                self.store.set_control(event_id, 'PAUSE_ACCEPTED',
                                       {'ALL': {'skipped': STOP_SKIPPED_NOTE}})
                return
        self.store.set_control(event_id, action + '_SENT', {})
        self.stop_sent[event_id] = (self.clock(), self.stop_sent.get(event_id, (None, 0))[1] + 1)
        self.stop_sent.move_to_end(event_id)
        while len(self.stop_sent) > REPLY_LIMIT:
            self.stop_sent.popitem(last=False)
        if everyone:
            # 로봇 지정 없는 요청 한 건이 전 로봇 보류와 armed 끄기를 함께 부른다.
            # 응답 키는 'ALL' 고정이다. None을 쓰면 기록 키가 "null"이 된다.
            self.request({'type': STOP_REQUEST[action],
                          'client_request_id': 'cctv_' + event_id[:60]}, (event_id, 'ALL'))
            return
        for robot in targets:
            order_id = robots[robot].get('order_id')
            if order_id:
                self.store.set_hold_reason(order_id, reason)
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
            if row['linked_mission_id'] != mission_id:
                continue
            # 전체 정지는 주문 하나의 복구로 풀리지 않는다. 확인만 남기고 스냅샷이 풀릴 때 닫는다.
            waiting = row['stop_scope'] == 'ALL' and row['control_action'] in STOP_OPEN
            self.store.set_ack(row['event_id'], 'ACKNOWLEDGED' if waiting else 'RESOLVED',
                               operator, note, self.clock())

    def _close_recovered(self):
        """
        관제에서 풀린 정지 사건을 닫는다.

        메모리가 아니라 DB의 열린 사건과 방금 받은 스냅샷만 본다(재시작 뒤에도 같다).
        정지가 스냅샷에 한 번 보인 뒤에만 닫는다. 요청 직후의 옛 스냅샷으로 닫지 않는다.
        """
        for row in self.store.open_stop_events(STOP_OPEN):
            seen, held = self._hold_of(row)
            if seen and not row['hold_seen']:
                self.store.mark_hold_seen(row['event_id'])
            elif not held and row['hold_seen']:
                self.store.close_recovered(row['event_id'], FLEET_RESOLVER,
                                           FLEET_RESOLVED_NOTE, self.clock())

    def _hold_of(self, row):
        """(정지가 반영된 것이 보이는가, 아직 풀리지 않았는가)를 돌려준다."""
        if row['stop_scope'] == 'ALL':
            # 전체 정지는 armed가 켜지고, 보류가 비고, 보류 주문이 없어야 풀린 것이다.
            held = (self.armed is not True or bool(self.holds)
                    or any(order['state'] in BLOCKED for order in self.orders.values()))
            # armed만 꺼진 스냅샷은 다른 사유일 수 있다. 관제 응답이나 전 로봇 보류까지 본다.
            seen = self.armed is False and (
                row['control_action'].endswith('_ACCEPTED') or self._all_stopped())
            return seen, held
        order = self.orders.get(row['linked_mission_id'])
        if order:
            held = order['state'] in BLOCKED
            return held, held
        held = any(robot in self.holds for robot in json.loads(row['stop_targets_json']))
        # 연결 주문이 스냅샷에서 사라졌으면 남은 보류가 이 사건의 것인지 알 수 없다.
        # 정지를 새로 확인한 것으로 치지 않는다. 이미 확인한 사건은 보류가 풀릴 때 닫는다.
        return held and not row['linked_mission_id'], held

    def _link(self, robot, now):
        status = self.status.get(robot) or {}
        ages = {topic: now - at for topic, at in self.seen.get(robot, {}).items()}
        graph = (self.graph or {}).get('robots', {}).get(robot, {})
        return {'robot_id': robot, 'status': {key: status.get(key) for key in STATUS_FIELDS},
                'ages': ages, 'graph': graph, 'problems': ready_problems(robot, self.graph)}

    def allocation_reasons(self, robot, now):
        status = self.status.get(robot, {})
        seen = self.seen.get(robot, {})
        checks = [
            (self.armed is True, '관제 비무장'),
            (self.tasks_at is not None and now - self.tasks_at <= 3, '관제 스냅샷 만료'),
            (robot not in self.holds, '보류'),
            (not self._active_order(robot), '주문 예약'),
            (robot not in self.busy_robots, '미종료 작업'),
            (now - seen.get('patrol_status', float('-inf')) <= 3, '상태 만료'),
            (now - seen.get('battery', float('-inf')) <= 10, '배터리 만료'),
            (self.battery.get(robot, -1) >= 20, '배터리 20% 미만 또는 미수신'),
            (status.get('state') in ('IDLE', 'DONE'), '대기 상태 아님'),
            (status.get('central_controlled') is True, '중앙 제어 미확인'),
            (status.get('central_latched') is not True, 'central_latched'),
            (not status.get('held_zone'), '구역 점유'),
        ]
        return [reason for ok, reason in checks if not ok]

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
                'diagnostics': self.diagnostics, 'ready_graph': self.graph,
                'allocation': {r: self.allocation_reasons(r, now) for r in self.robots},
                'zones': zone_table(self.zones, self.status), 'tasks': self.tasks,
                'log': list(reversed(self.log)), 'routes': self.trace.routes,
                'links': [self._link(robot, now) for robot in self.robots],
                'fleet_age_sec': None if self.tasks_at is None else now - self.tasks_at,
                'robots': [dict(views[r], robot_id=r) for r in self.robots],
                'holds': self.holds, 'missions': missions, 'anomalies': self.store.events(30)}
