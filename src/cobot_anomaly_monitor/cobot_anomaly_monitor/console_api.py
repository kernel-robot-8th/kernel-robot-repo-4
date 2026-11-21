"""메뉴 6.5 개발 콘솔용 HTTP. 로봇에는 직접 명령하지 않고 관제 요청만 전달한다."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from .manual_adapter import arm_missing_text
from .scenario_view import is_customer_order

BODY_LIMIT = 16384
# declined: 자리 주문 CUSTOMER 에서 고객이 사지 않음(회수). 관제 control_api 가 받는 type 이다.
CONTROL_TYPES = ('arm', 'inventory', 'order', 'received', 'declined', 'resolve', 'pause',
                 'estop', 'release_control', 'create')
CONSOLE_OPERATIONS = ('goto', 'zone', 'leave', 'home')
WRITE_ROUTES = ('control', 'mode', 'work')
ARM_ON_DETAIL = '가동 허용 켜기는 관제 웹에서만 합니다. 이 창구는 끄기만 전달합니다.'
MOCK_CLASSES = ('box_on_floor', 'box_perched_on_rim', 'box_run_over', 'lid_detached')
TERMINAL = ('COMPLETED', 'FAILED')
# 관제 confirm_loaded 가 받는 주문(origin/sakim scenario_safety.py:59-63): 상태 RUNNING·UNKNOWN,
# 단계 PICKUP_EXIT~VERIFY_LOAD 와 CORRECT_PICKUP, MOVE_PICKUP 완료, 실패 없음. 멈춘 주문 중에는 UNKNOWN 만 된다.
CONFIRM_LOADED_STAGES = frozenset({'PICKUP_EXIT', 'DOCK_PICKUP', 'MARKER', 'PICK', 'LOAD',
                                   'VERIFY_LOAD', 'CORRECT_PICKUP'})
# 자리 주문은 상차장만 예약해 관제가 늘 거절한다(scenario_safety.py:77-80, scenario_runtime.py:61-65).
SEAT_CONFIRM_NOTE = '자리 주문은 수동 상차 확인(confirm_loaded)을 관제가 거절함 · fail 로 종결 후 재주문'
# 주문 수신 원문(trace_work_wire)에 감시가 남기는 경고 종류.
WARNING_KINDS = ('arm_node_missing', 'adapter_warning')
WIRE_PAGE_LIMIT = 40  # 경고를 찾을 때 읽는 수신 원문 쪽수 상한(쪽당 50건)


class ConsoleApi:
    """요청 해석만 맡는다. 저장소와 ROS 접근은 run으로 실행기 스레드에 넘긴다."""

    def __init__(self, core, adapter, run, wait_reply, allow_mock=True, clock=time.time,
                 commands=False, observation_only=False, dock_tolerance=None):
        self.core, self.adapter, self.run, self.wait_reply = core, adapter, run, wait_reply
        self.allow_mock, self.clock, self.commands = allow_mock, clock, commands
        self.observation_only = observation_only
        # 추적표 정차 행 공차 비교용 scenario_config 값 {'dock_xy_m', 'dock_yaw_deg'}. 없으면 관제 행동으로만 본다.
        self.dock_tolerance = dock_tolerance
        self.cached = {}

    def refresh(self):
        """실행기 스레드에서 호출한다. GET은 이 사본만 읽는다."""
        work = self.adapter.pending() if self.adapter else []
        live = self.core.live()
        # 아래 두 값은 화면용 덧붙임이다. 노드 타이머에서 돌므로 이상한 주문 값 하나로 예외가 나면
        # 노드 전체가 멈춘다. 실패하면 그 값만 비우고 갱신은 계속한다.
        for row in live.get('missions', []):
            try:
                self._recovery_options(row)
            except Exception:  # noqa: BLE001 - 표시용 값 계산 실패가 감시를 멈추면 안 된다
                row['recovery_options'], row['recovery_note'] = [], ''
        try:
            arm_waits = self._arm_waits()
        except Exception:  # noqa: BLE001
            arm_waits = []
        self.cached = dict(live, work=work, allow_mock=self.allow_mock,
                           commands_enabled=self.commands, arm_waits=arm_waits,
                           adapter={'enabled': self.adapter is not None,
                                    'blocked': self.adapter.blocked if self.adapter else ''})

    def _recovery_options(self, row):
        """
        멈춘 주문에 관제가 받는 복구 길을 붙인다. recovery(옛 칸)는 그대로 둔다.

        resume 은 이동·수령 단계만, fail 은 멈춘 주문 모두, confirm_loaded 는 경로 주문의 상차 검증 중에만이다.
        로봇 정지·구역 보유 같은 실시간 조건은 관제가 요청 때 다시 확인한다.
        """
        options, note = [], ''
        if row.get('recovery'):
            options = (['resume'] if row['recovery'] == 'resume' else []) + ['fail']
        order = self.core.orders.get(row.get('mission_id')) or {}
        stage = order.get('stage')
        if (order.get('state') == 'UNKNOWN' and isinstance(stage, str)
                and stage in CONFIRM_LOADED_STAGES
                and isinstance(order.get('completed'), (list, tuple))
                and 'MOVE_PICKUP' in order['completed'] and order.get('robot_id')
                and not order.get('failure') and not order.get('operator_load_confirmation')):
            route = self.core._route(order) if order.get('route') else {}
            if is_customer_order(order, route) or (not route and order.get('destination')):
                note = SEAT_CONFIRM_NOTE
            else:
                options.append('confirm_loaded')
        row['recovery_options'] = options
        row['recovery_note'] = note

    def _arm_waits(self):
        """지금 단계가 팔 작업인데 그 팔의 팀 노드가 안 보이는 주문. 아무도 답하지 않는다."""
        missing = {t for t, present in (self.core.arm_nodes or {}).items() if present is False}
        if not missing:
            return []
        waits = []
        for order in self.core.orders.values():
            rid = order.get('request_id')
            if order.get('state') in TERMINAL or not isinstance(rid, str) or not rid:
                continue
            try:
                request = self._request_of(order['order_id'], rid)
            except Exception:  # noqa: BLE001 - 주문 하나의 이상한 기록이 다른 주문 표시를 막지 않게 한다
                continue
            target = request.get('target') if request else None
            if not isinstance(target, str) or target not in missing or request.get('answered'):
                continue
            waits.append({'order_id': order['order_id'], 'robot_id': order.get('robot_id'),
                          'stage': order.get('stage'), 'request_id': rid,
                          'target': request['target'], 'since': request.get('at'),
                          'detail': arm_missing_text(request['target'])})
        return waits

    def _request_of(self, order_id, request_id):
        """관측한 작업 요청 원문(없으면 어댑터 접수본)과 결과 관측 여부."""
        requests, _ = self.core.store.observed_work(order_id)
        seen = next((r for r in requests if r.get('request_id') == request_id), None)
        if seen and seen.get('target'):
            return {'target': seen['target'], 'at': seen.get('wire_observed_at'),
                    'answered': bool(seen.get('wire_results'))}
        row = self.adapter.store.work(request_id) if self.adapter else None
        if row:
            request = json.loads(row['request_json'])
            return {'target': request.get('target'), 'at': row['created_at'],
                    'answered': row['state'] != 'PENDING'}
        return None

    def handle(self, method, path, body):
        """(HTTP 상태, 본문)을 돌려준다. 쓰기 뒤에는 사본을 바로 맞춰 이중 승인을 막는다."""
        if self.observation_only and method == 'POST':
            return 403, {'detail': '중계 관측 전용: 상태 변경 불가'}
        status, reply = self._route(method, path, body)
        if method == 'POST':
            try:
                self.run(self.refresh)
            except Exception:  # 처리한 요청의 응답은 사본 갱신 실패와 무관하게 돌려준다.
                logging.exception('콘솔 사본 갱신 실패')
        return status, reply

    def _route(self, method, path, body):
        parts = path.split('?')[0].strip('/').split('/')
        if parts[:2] != ['api', 'fms'] or len(parts) < 3:
            return 404, {'detail': '없는 경로'}
        name, rest = parts[2], parts[3:]
        if (method == 'POST' and not self.commands
                and (name in WRITE_ROUTES or (name == 'anomalies' and not rest))):
            return 403, {'detail': '읽기 전용: 시뮬에서 console_commands를 켜야 합니다'}
        try:
            if method == 'GET' and name == 'live_state' and not rest:
                return 200, self.cached
            if method == 'GET' and name == 'orders' and len(rest) == 2 and rest[1] == 'history':
                cursor = parse_qs(urlsplit(path).query).get('after', ['0'])
                if len(cursor) != 1 or not cursor[0].isascii() or not cursor[0].isdigit():
                    raise ValueError('after는 0 이상의 정수')
                after = int(cursor[0])
                if after > 2**63 - 1:
                    raise ValueError('after 범위 초과')
                return 200, self.run(lambda: self.core.store.wire_page(rest[0], after))
            if method == 'GET' and name == 'orders' and len(rest) == 2 and rest[1] == 'trace':
                order_id = rest[0]
                return 200, self.run(lambda: self._order_trace(order_id))
            if method == 'POST' and name == 'control' and not rest:
                return self._control(body)
            if method == 'POST' and name == 'mode' and not rest:
                mode = self.run(lambda: self.core.set_mode(body.get('mode')))
                return 200, {'mode': mode}
            if method == 'POST' and name == 'anomalies' and not rest:
                return self._mock(body)
            if method == 'POST' and name == 'anomalies' and len(rest) == 1:
                return 200, self.run(lambda: self.core.acknowledge(
                    rest[0], body.get('ack_state'), body.get('operator'), body.get('note', '')))
            if method == 'POST' and name == 'work' and len(rest) == 1:
                return self._work(rest[0], body)
        except KeyError:
            return 404, {'detail': '없는 대상'}
        except ValueError as error:
            return 400, {'detail': str(error)}
        except TimeoutError:
            return 504, {'detail': '모니터 실행기 응답 없음'}
        except Exception as error:  # 응답 없이 연결이 끊기지 않게 한다.
            logging.exception('콘솔 요청 처리 실패: %s %s', method, path.split('?')[0])
            # 오류 문구에는 경로·SQL이 섞일 수 있다. 시뮬 콘솔에서만 그대로 보여 준다.
            text = f'{type(error).__name__}: {error}' if self.commands else type(error).__name__
            return 500, {'detail': '내부 오류: ' + text}
        return 404, {'detail': '없는 경로'}

    def _control(self, body):
        kind = body.get('type')
        if kind not in CONTROL_TYPES:
            raise ValueError('허용하지 않는 요청 type')
        request = dict(body)
        if kind == 'arm' and request.get('armed') is not False:
            return 403, {'detail': ARM_ON_DETAIL}
        if kind == 'resolve':
            # 관제는 이름 없는 복구도 받는다. 이 창구는 누가 확인했는지를 계속 요구한다.
            operator = request.get('operator')
            if not isinstance(operator, str) or not operator.strip():
                raise ValueError('operator 필요')
        if kind == 'create':
            if request.get('operation') not in CONSOLE_OPERATIONS:
                raise ValueError('콘솔의 create는 ' + ', '.join(CONSOLE_OPERATIONS) + '만 허용')
            request.setdefault('client_request_id', 'console_' + uuid.uuid4().hex)
        if kind == 'order' and isinstance(request.get('order'), dict):
            request['order'] = dict(request['order'])
            request['order'].setdefault('order_id', 'scn_' + uuid.uuid4().hex[:12])
        request_id = self.run(lambda: self.core.request(request))
        reply = self.wait_reply(request_id)
        if reply is None:
            return 504, {'detail': '관제 응답 없음: fleet_control 실행과 도메인을 확인하세요'}
        if kind == 'resolve' and reply.get('status') == 200 and request.get('order_id'):
            try:
                self.run(lambda: self.core.close_events(
                    request.get('order_id'), request.get('operator'), request.get('note', '')))
            except Exception:  # 복구는 이미 받아들여졌다. 사건 닫기 실패로 응답을 바꾸지 않는다.
                logging.exception('복구 뒤 사건 닫기 실패')
        status = reply.get('status')
        if type(status) is not int or not 100 <= status <= 599:
            return 502, {'detail': '관제 응답에 status 없음'}
        return status, reply.get('body') or {}

    def _mock(self, body):
        if not self.allow_mock:
            return 403, {'detail': '모의 이벤트 꺼짐'}
        if body.get('vision_class') not in MOCK_CLASSES:
            raise ValueError('vision_class: ' + ', '.join(MOCK_CLASSES))
        event = {'event_id': 'mock_' + uuid.uuid4().hex, 'camera_id': 'console_mock',
                 'vision_class': body['vision_class'], 'confidence': 1.0,
                 'detected_at': self.clock(), 'map_x': body.get('map_x'),
                 'map_y': body.get('map_y')}
        return 200, self.run(lambda: self.core.on_vision_event(event))

    def _work(self, request_id, body):
        if not self.adapter:
            return 409, {'detail': '수동 어댑터 꺼짐'}
        decision = body.get('decision')
        if decision == 'confirm_arm':
            return 200, self.run(lambda: self.adapter.confirm_arm(request_id, body.get('operator')))
        if decision == 'manual_load':
            return 200, self.run(lambda: self.adapter.manual_load(
                request_id, body.get('operator'), body.get('note'),
                body.get('load_present'), body.get('arm_safe')))
        if decision == 'approve':
            return 200, self.run(lambda: self.adapter.approve(
                request_id, body.get('operator'), body.get('note', ''), body.get('sku')))
        if decision == 'reject':
            return 200, self.run(lambda: self.adapter.reject(
                request_id, body.get('operator'), body.get('note', ''), body.get('retry_safe')))
        raise ValueError('decision: approve 또는 reject')

    def _order_trace(self, order_id):
        from .stage_trace import build_stage_trace, order_notes
        store = self.core.store
        reader = self.adapter or store
        attempts = store.trace_attempts(order_id)
        known = {r['request_id']: r for r in attempts}
        known.update({r['request_id']: r for r in reader.order_work_history(order_id)})
        history, unmatched = store.observed_work(order_id, known.values())
        order = self.core.orders.get(order_id) or store.trace_order(order_id)
        if order is None:
            old = store.scenario(order_id)
            if old:
                order = dict(order_id=order_id, robot_id=old['robot_id'], state=old['mission_state'],
                             stage=old['current_stage'], route=old['route'], detail=old['detail'])
            elif history or unmatched:
                order = dict(order_id=order_id, state='UNOBSERVED')
            else:
                raise KeyError(order_id)
        trace = build_stage_trace(order, history, tasks=self.core.tasks,
                                  attempts=attempts,
                                  route=self.core._route(order) if order.get('route') else {},
                                  unmatched=unmatched, terminal=store.terminal_resources(order_id),
                                  dock_tolerance=self.dock_tolerance)
        warnings = self._warnings(order_id)
        self._mark_arm_missing(order, trace, warnings)
        notes = order_notes(order, history, attempts=attempts,
                            control_events=store.control_events(order_id=order_id))
        return {'order_id': order_id, 'order': order, 'trace': trace, 'unmatched_results': unmatched,
                'warnings': warnings, 'alarms': self.core.alarms(order_id), 'notes': notes}

    def _warnings(self, order_id):
        """감시가 남긴 주문 경고(팔 노드 없음·모르는 단계)를 수신 원문에서 모은다."""
        found, after = [], 0
        for _ in range(WIRE_PAGE_LIMIT):
            page = self.core.store.wire_page(order_id, after)
            found += [dict(row['payload'], kind=row['kind'], request_id=row['request_id'],
                           at=row['at'])
                      for row in page['events']
                      if row['kind'] in WARNING_KINDS and isinstance(row['payload'], dict)]
            after = page['next_cursor']
            if after is None:
                break
        return found

    def _mark_arm_missing(self, order, trace, warnings):
        """
        결과가 안 온 팔 단계 행에 '팔 노드 없음'을 붙인다.

        요청 때 남긴 경고가 있거나, 지금 단계 행인데 그 팔 노드가 지금 안 보이면 붙인다.
        """
        recorded = {w['request_id']: w.get('detail') or arm_missing_text(w.get('target'))
                    for w in warnings if w['kind'] == 'arm_node_missing'}
        nodes = self.core.arm_nodes or {}
        for row in trace:
            rid = row.get('request_id')
            if not rid or row['checkpoints'].get('result') != 'NONE':
                continue
            detail = recorded.get(rid)
            if (not detail and rid == order.get('request_id')
                    and order.get('state') not in TERMINAL
                    and nodes.get(row.get('target')) is False):
                detail = arm_missing_text(row['target'])
            if detail:
                row['evidence_summary'] += ' · ' + detail
                row['evidence_detail'] = dict(row['evidence_detail'] or {},
                                              arm_node_missing=detail)


def serve(api, host, port):
    """표준 라이브러리 서버를 데몬 스레드로 띄운다."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _guarded(self, work):
            try:
                work()
            except OSError:
                raise  # 끊긴 연결에는 답할 수 없다.
            except Exception as error:
                logging.exception('콘솔 HTTP 처리 실패: %s', self.path.split('?')[0])
                self._reply(500, {'detail': '내부 오류: ' + type(error).__name__})

        def do_GET(self):
            self._guarded(lambda: self._reply(*api.handle('GET', self.path, None)))

        def do_POST(self):
            self._guarded(self._post)

        def _post(self):
            # JSON 강제로 다른 사이트의 단순 폼 전송(CSRF)을 막는다.
            if 'application/json' not in self.headers.get('Content-Type', ''):
                self._reply(415, {'detail': 'application/json 필요'})
                return
            size = (self.headers.get('Content-Length') or '0').strip()
            if not (size.isascii() and size.isdigit()):
                self._reply(400, {'detail': 'Content-Length 오류'})
                return
            length = int(size)
            if length > BODY_LIMIT:
                self._reply(413, {'detail': '요청은 16 KiB 이하'})
                return
            try:
                body = json.loads(self.rfile.read(length) or b'{}')
            except ValueError:
                self._reply(400, {'detail': 'JSON 오류'})
                return
            if not isinstance(body, dict):
                self._reply(400, {'detail': 'JSON 객체 필요'})
                return
            self._reply(*api.handle('POST', self.path, body))

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05},
                     daemon=True).start()
    return server
