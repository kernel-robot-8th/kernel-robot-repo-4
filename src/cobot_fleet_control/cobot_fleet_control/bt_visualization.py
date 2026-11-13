"""실제 py_trees 방문 상태를 기록하고 HTML 재생용 JSON으로 내보낸다."""

import argparse
import json
from pathlib import Path
import sqlite3
import time

import py_trees

from .repository import encode


def tree_nodes(tree, visitor):
    """완료 상태와 이번 갱신에서 실제 방문한 노드를 구분해 직렬화한다."""
    return [dict(id=str(node.id), name=node.name, kind=type(node).__name__,
                 status=node.status.value, children=[str(child.id) for child in node.children],
                 visited=node.id in visitor.visited, feedback=node.feedback_message,
                 stage=getattr(node, 'stage', None))
            for node in tree.root.iterate()]


class TreeTrace:
    """실행 트리를 바꾸지 않고 노드 상태·방문 경로를 관찰한다."""

    def __init__(self, command, tree, repository):
        self.command = command
        self.tree = tree
        self.repository = repository
        self.visitor = py_trees.visitors.SnapshotVisitor()
        tree.visitors.append(self.visitor)
        self.tick_index = 0
        self.previous = None

    def capture(self, phase='tick'):
        """상태나 방문 경로가 바뀔 때만 저장해 대기 중 이벤트 폭증을 막는다."""
        nodes = tree_nodes(self.tree, self.visitor)
        job = self.repository.get(self.command.command_id)
        snapshot = {
            'type': 'bt_snapshot', 'command_id': self.command.command_id,
            'robot_id': self.command.robot_id, 'root_id': str(self.tree.root.id),
            'job_state': job['state'], 'phase': phase, 'nodes': nodes,
        }
        signature = encode(snapshot)
        if signature != self.previous:
            snapshot.update(tick=self.tick_index, recorded_at=time.time())
            self.repository.record_bt_snapshot(snapshot)
            self.previous = signature
        self.tick_index += 1


class ScenarioTreeTrace:
    """전체 주문 BT의 실제 노드 상태를 실행 원장에 기록해 실시간 뷰어로 전달한다."""

    def __init__(self, tree, repository, order_id):
        self.tree, self.repository, self.order_id = tree, repository, order_id
        self.visitor = py_trees.visitors.SnapshotVisitor()
        tree.visitors.append(self.visitor)
        self.tick_index = 0
        self.previous = None

    def capture(self, order, phase='tick'):
        """상태·방문·설명이 달라질 때만 저장해 반복 대기 중 기록 폭증을 막는다."""
        snapshot = dict(type='scenario_bt_snapshot', order_id=self.order_id,
                        robot_id=order['robot_id'], root_id=str(self.tree.root.id),
                        job_state=order['state'], stage=order['stage'], phase=phase,
                        resources=self.repository.db.execute(
                            'SELECT name FROM scenario_resources WHERE order_id=? ORDER BY name',
                            (self.order_id,)).fetchall(),
                        nodes=tree_nodes(self.tree, self.visitor))
        snapshot['resources'] = [row[0] for row in snapshot['resources']]
        signature = encode(snapshot)
        if signature != self.previous:
            snapshot.update(tick=self.tick_index, recorded_at=time.time())
            self.repository.record_bt_snapshot(snapshot)
            self.previous = signature
        self.tick_index += 1


def export_traces(db_path, command_id=None, order_id=None):
    """ACK 여부와 무관하게 저장된 BT 이벤트를 읽기 전용 연결로 추출한다."""
    path = Path(db_path).expanduser().resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
        rows = connection.execute('SELECT payload FROM outbox ORDER BY event_id')
        snapshots = [event for row in rows
                     if (event := json.loads(row[0])).get('type') in {
                         'bt_snapshot', 'scenario_bt_snapshot'}
                     and (command_id is None or event.get('command_id') == command_id)
                     and (order_id is None or event.get('order_id') == order_id)]
    return {'format': 'cobot-bt-trace-v1', 'source': 'recorded', 'snapshots': snapshots}


def main(args=None):
    """현장 DB에서 수집한 실행 이력을 리포트로 가져올 수 있게 내보낸다."""
    parser = argparse.ArgumentParser(description='관제 BT 실행 스냅샷 JSON 내보내기')
    parser.add_argument('--db', required=True, help='관제 SQLite 파일 경로')
    parser.add_argument('--output', required=True, help='실행 기록을 저장할 JSON 파일 경로')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--command-id', help='특정 주행 명령만 추출할 때 지정')
    selection.add_argument('--order-id', help='특정 주문의 전체 BT만 추출할 때 지정')
    options = parser.parse_args(args)
    result = export_traces(options.db, options.command_id, options.order_id)
    Path(options.output).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                    encoding='utf-8')


if __name__ == '__main__':
    main()
