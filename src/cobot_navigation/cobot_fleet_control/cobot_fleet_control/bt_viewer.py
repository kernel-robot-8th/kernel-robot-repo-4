"""중앙 실행 원장을 읽는 실시간 BT 조회 서버. 로봇 명령이나 DB 변경 기능은 없다."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit


TRACE_TYPES = ('bt_snapshot', 'scenario_bt_snapshot')


def read_snapshots(db_path, after=0, limit=200):
    """읽기 전용 연결로 최신 트리와 이후 변경을 읽는다. 없는 DB를 생성하지 않는다."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        return dict(status='waiting', detail='실행 원장이 생성되기를 기다리고 있습니다.',
                    cursor=0, snapshots=[], orders=[])
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.2) as db:
        kind = "json_extract(payload, '$.type')"
        identity = ("coalesce(json_extract(payload, '$.order_id'), "
                    "json_extract(payload, '$.command_id'))")
        if after == 0:
            rows = db.execute(
                f'SELECT event_id,payload FROM outbox WHERE event_id IN ('
                f'SELECT max(event_id) FROM outbox WHERE {kind} IN (?,?) '
                f'GROUP BY {kind}, {identity}) ORDER BY event_id DESC LIMIT ?',
                (*TRACE_TYPES, limit)).fetchall()
            rows.reverse()
        else:
            rows = db.execute(
                f'SELECT event_id,payload FROM outbox WHERE event_id>? AND {kind} IN (?,?) '
                'ORDER BY event_id LIMIT ?', (after, *TRACE_TYPES, limit)).fetchall()
        snapshots = [dict(json.loads(payload), event_id=event_id) for event_id, payload in rows]
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scenario_orders'").fetchone()
        orders = ([json.loads(row[0]) for row in db.execute(
            'SELECT snapshot FROM scenario_orders ORDER BY rowid DESC LIMIT 200')]
            if exists else [])
        # 재시작이나 과거 DB 교체를 감지해 브라우저가 커서를 다시 맞추게 한다.
        head = db.execute('SELECT coalesce(max(event_id),0) FROM outbox').fetchone()[0]
    return dict(status='ready', detail='실행 원장 조회 중',
                cursor=max((row[0] for row in rows), default=after), reset=after > head,
                snapshots=snapshots, orders=orders)


def viewer_page():
    """소스 실행과 ROS 패키지 설치 양쪽에서 같은 화면 파일을 사용한다."""
    source = Path(__file__).resolve().parents[1] / 'docs/bt_viewer.html'
    if source.is_file():
        return source.read_bytes()
    from ament_index_python.packages import get_package_share_directory
    return (Path(get_package_share_directory('cobot_fleet_control'))
            / 'docs/bt_viewer.html').read_bytes()


def make_server(db_path, host='127.0.0.1', port=8091):
    """기존 웹 관제와 별개인 조회 전용 도구를 생성한다."""
    page = viewer_page()

    class Handler(BaseHTTPRequestHandler):
        """정해진 화면과 스냅샷 API만 제공하며 파일 경로를 외부 입력으로 받지 않는다."""

        def reply(self, status, content, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            route = urlsplit(self.path)
            if route.path == '/':
                self.reply(200, page, 'text/html; charset=utf-8')
            elif route.path == '/api/snapshots':
                try:
                    after = int(parse_qs(route.query).get('after', ['0'])[0])
                    if after < 0:
                        raise ValueError('커서는 0 이상이어야 합니다')
                    payload = read_snapshots(db_path, after)
                    status = 200
                except ValueError:
                    payload, status = dict(status='error', detail='조회 커서 형식 오류'), 400
                except sqlite3.Error:
                    payload, status = dict(status='error', detail='실행 원장을 읽을 수 없습니다.'), 503
                self.reply(status, json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                           'application/json; charset=utf-8')
            else:
                self.reply(404, b'', 'text/plain')

        def do_POST(self):
            self.reply(405, b'', 'text/plain')

        def log_message(self, format, *args):
            """주기적 조회 로그로 관제 터미널이 채워지지 않도록 한다."""

    return ThreadingHTTPServer((host, port), Handler)


def main(args=None):
    """기본 127.0.0.1:8091에서 실제 BT 상태를 0.5초 간격으로 조회한다."""
    parser = argparse.ArgumentParser(description='중앙 관제 실시간 BT 조회 도구')
    parser.add_argument('--db', default='~/.cobot/fleet_control.sqlite3', help='관제 실행 원장 경로')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8091)
    options = parser.parse_args(args)
    try:
        with make_server(options.db, options.host, options.port) as server:
            print(f'BT 뷰어: http://{options.host}:{server.server_port} (조회 전용, 종료: Ctrl+C)')
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ImportError) as error:
        parser.exit(1, f'BT 뷰어 기동 실패: {error}\n')


if __name__ == '__main__':
    main()
