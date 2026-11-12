"""메뉴 6.5 개발 콘솔용 HTTP. 로봇에는 직접 명령하지 않고 관제 요청만 전달한다."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import uuid

BODY_LIMIT = 16384
CONTROL_TYPES = ('arm', 'inventory', 'order', 'received', 'resolve', 'pause', 'estop',
                 'release_control', 'create')
CONSOLE_OPERATIONS = ('goto', 'zone', 'leave', 'home')
WRITE_ROUTES = ('control', 'mode', 'work')
MOCK_CLASSES = ('box_on_floor', 'box_perched_on_rim', 'box_run_over', 'lid_detached')


class ConsoleApi:
    """요청 해석만 맡는다. 저장소와 ROS 접근은 run으로 실행기 스레드에 넘긴다."""

    def __init__(self, core, adapter, run, wait_reply, allow_mock=True, clock=time.time,
                 commands=False):
        self.core, self.adapter, self.run, self.wait_reply = core, adapter, run, wait_reply
        self.allow_mock, self.clock, self.commands = allow_mock, clock, commands
        self.cached = {}

    def refresh(self):
        """실행기 스레드에서 호출한다. GET은 이 사본만 읽는다."""
        work = self.adapter.pending() if self.adapter else []
        self.cached = dict(self.core.live(), work=work, allow_mock=self.allow_mock,
                           commands_enabled=self.commands,
                           adapter={'enabled': self.adapter is not None,
                                    'blocked': self.adapter.blocked if self.adapter else ''})

    def handle(self, method, path, body):
        """(HTTP 상태, 본문)을 돌려준다. 쓰기 뒤에는 사본을 바로 맞춰 이중 승인을 막는다."""
        status, reply = self._route(method, path, body)
        if method == 'POST':
            try:
                self.run(self.refresh)
            except TimeoutError:
                pass
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
        return 404, {'detail': '없는 경로'}

    def _control(self, body):
        kind = body.get('type')
        if kind not in CONTROL_TYPES:
            raise ValueError('허용하지 않는 요청 type')
        request = dict(body)
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
        if kind == 'resolve' and reply.get('status') == 200:
            self.run(lambda: self.core.close_events(
                request.get('order_id'), request.get('operator'), request.get('note', '')))
        return reply.get('status', 502), reply.get('body') or {}

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
        if decision == 'approve':
            return 200, self.run(lambda: self.adapter.approve(
                request_id, body.get('operator'), body.get('note', ''), body.get('sku')))
        if decision == 'reject':
            return 200, self.run(lambda: self.adapter.reject(
                request_id, body.get('operator'), body.get('note', ''), body.get('retry_safe')))
        raise ValueError('decision: approve 또는 reject')


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

        def do_GET(self):
            self._reply(*api.handle('GET', self.path, None))

        def do_POST(self):
            # JSON 강제로 다른 사이트의 단순 폼 전송(CSRF)을 막는다.
            if 'application/json' not in self.headers.get('Content-Type', ''):
                self._reply(415, {'detail': 'application/json 필요'})
                return
            length = int(self.headers.get('Content-Length') or 0)
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
