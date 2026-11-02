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
관제 백엔드 웹 API (FastAPI, ROS 없음).

브라우저는 ROS 토픽 이름을 모르고 이 API 만 본다. 안쪽(ROS 토픽, 나중의 MQTT·DB)이 바뀌어도
여기 경로와 응답 모양을 유지한다.

명령(/api/tasks, 정지, 해제)은 직접 로봇에 보내지 않는다. task_manager_node 에 요청 토픽으로 넘기고
그 응답을 HTTP 로 바꾸기만 한다. 검증·기록·발행은 task_manager_node 가 한다.
"""

import asyncio

from fastapi import (Body, FastAPI, HTTPException, Query, Response, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# WebSocket 이 새 스냅샷을 기다리는 한 번의 최대 시간 [s]. 끊긴 연결을 이 주기로 알아챈다.
WS_WAIT_SEC = 1.0


def create_app(store, map_data=None, web_dir=None, domain_id=None, layers=None,
               tasks=None, publish_request=None):
    """
    웹 앱을 만든다. 데이터는 인자로 받은 SnapshotStore 에서만 읽는다.

    map_data 는 load_map() 결과 (info, pgm 바이트) 또는 None, web_dir 은 화면 정적 파일 폴더다.
    domain_id 는 이 백엔드가 붙은 ROS_DOMAIN_ID 다. fleet_status 를 받기 전에도 화면이
    실물·시험 중 어디를 보는지 알 수 있게 health 에 싣는다.
    layers 는 load_map_layers() 결과(구역 지점·출구·대기 슬롯·홈) 또는 None 이다.
    tasks 는 TaskStore, publish_request 는 요청 JSON 문자열을 task_request 토픽에 내는 함수다.
    둘 중 하나라도 None 이면 명령 경로는 503 이다 (읽기 전용).
    """
    app = FastAPI(title='cobot control center API', version='0.1.0')

    def map_or_404():
        if map_data is None:
            raise HTTPException(status_code=404, detail='지도가 설정되지 않음 (map_yaml)')
        return map_data

    @app.get('/api/map/info')
    def map_info():
        return map_or_404()[0]

    @app.get('/api/map/image')
    def map_image():
        return Response(content=map_or_404()[1], media_type='image/x-portable-graymap')

    @app.get('/api/map/layers')
    def map_layers():
        if layers is None:
            raise HTTPException(status_code=404,
                                detail='구역·지점 설정이 없음 (points_dir, zone_params)')
        return layers

    def latest():
        _, snapshot = store.get()
        if snapshot is None:
            raise HTTPException(status_code=503, detail='fleet_status 를 아직 받지 못함')
        return snapshot

    @app.get('/api/health')
    def health():
        task_health = tasks.health() if tasks is not None else {'task_manager_online': False}
        return {'ok': True, 'domain_id': domain_id, **store.health(), **task_health}

    @app.get('/api/fleet')
    def fleet():
        return latest()

    @app.get('/api/robots')
    def robots():
        snapshot = latest()
        return [{'robot_id': name, **robot}
                for name, robot in snapshot.get('robots', {}).items()]

    @app.get('/api/robots/{robot_id}')
    def robot(robot_id: str):
        robots = latest().get('robots', {})
        if robot_id not in robots:
            raise HTTPException(status_code=404, detail=f'등록되지 않은 로봇: {robot_id}')
        return {'robot_id': robot_id, **robots[robot_id]}

    @app.get('/api/events')
    def events(after: int = Query(0, ge=0), robot: str | None = None,
               limit: int = Query(200, ge=1, le=1000)):
        # 이벤트 로그 (메모리, 백엔드를 다시 켜면 지워짐). 화면은 처음에 이걸 읽고 이후엔 WS 로 받는다.
        return store.events(after, robot, limit)

    @app.websocket('/ws/fleet')
    async def ws_fleet(websocket: WebSocket):
        await websocket.accept()
        closed = asyncio.Event()

        async def watch_close():
            # 원천이 멈춰 보낼 것이 없을 때도 끊긴 연결을 알아채려고 수신을 따로 지켜본다.
            try:
                while (await websocket.receive())['type'] != 'websocket.disconnect':
                    pass
            finally:
                closed.set()

        watcher = asyncio.create_task(watch_close())
        seq, snapshot = store.get()
        try:
            if snapshot is not None:
                await websocket.send_json(snapshot)
            while not closed.is_set():
                # store 는 스레드 lock 을 쓰므로 이벤트 루프를 막지 않게 스레드에서 기다린다.
                if await asyncio.to_thread(store.wait_newer, seq, WS_WAIT_SEC):
                    if closed.is_set():
                        break
                    seq, snapshot = store.get()
                    await websocket.send_json(snapshot)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            watcher.cancel()

    # ---------- 명령 (task_manager_node 경유) ----------

    def call_task_manager(payload):
        if tasks is None or publish_request is None:
            raise HTTPException(status_code=503, detail='명령 기능이 꺼져 있음 (읽기 전용 백엔드)')
        if not tasks.online():
            raise HTTPException(status_code=503,
                                detail='task_manager_node 응답 없음 (작업 노드를 켜 주세요)')
        result = tasks.request(payload, publish_request)
        if result is None:
            raise HTTPException(status_code=503, detail='task_manager_node 가 제때 답하지 않음')
        status, body = result
        body = body if isinstance(body, dict) else {}
        if status >= 400 and 'task_id' in body:
            # 기록된 거절(REJECTED): 이유와 작업을 함께 돌려준다.
            return JSONResponse(status_code=status,
                                content={'detail': body.get('detail'), 'task': body})
        return JSONResponse(status_code=status, content=body)

    @app.post('/api/tasks')
    def create_task(body: dict = Body(...)):
        return call_task_manager({
            'type': 'create', 'client_request_id': body.get('client_request_id'),
            'robot_id': body.get('robot_id'), 'operation': body.get('operation'),
            'points': body.get('points') or []})

    @app.post('/api/robots/{robot_id}/stop')
    def stop_robot(robot_id: str, body: dict = Body(default={})):
        return call_task_manager({
            'type': 'stop', 'robot_id': robot_id,
            'client_request_id': body.get('client_request_id'),
            'emergency': bool(body.get('emergency', False))})

    @app.post('/api/tasks/{task_id}/resolve')
    def resolve_task(task_id: str, body: dict = Body(default={})):
        return call_task_manager({
            'type': 'resolve', 'task_id': task_id,
            'client_request_id': body.get('client_request_id'),
            'result': body.get('result', 'FAILED'), 'note': body.get('note', '')})

    def task_store():
        if tasks is None:
            raise HTTPException(status_code=503, detail='명령 기능이 꺼져 있음 (읽기 전용 백엔드)')
        return tasks

    @app.get('/api/tasks')
    def list_tasks(robot_id: str = None, state: str = None, limit: int = 50):
        return task_store().tasks(robot_id, state, limit)

    @app.get('/api/tasks/{task_id}')
    def get_task(task_id: str):
        task = task_store().task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f'없는 작업 (최근 목록 밖일 수 있음): {task_id}')
        return task

    @app.websocket('/ws/tasks')
    async def ws_tasks(websocket: WebSocket):
        """처음에 최근 작업 목록을, 그 뒤 바뀐 작업을 하나씩 보낸다. 밀리면 목록을 다시 보낸다."""
        await websocket.accept()
        if tasks is None:
            await websocket.close(code=1013)
            return
        closed = asyncio.Event()

        async def watch_close():
            try:
                while (await websocket.receive())['type'] != 'websocket.disconnect':
                    pass
            finally:
                closed.set()

        watcher = asyncio.create_task(watch_close())
        seq = tasks.seq()
        try:
            await websocket.send_json({'type': 'tasks', 'tasks': tasks.tasks()})
            while not closed.is_set():
                if not await asyncio.to_thread(tasks.wait_newer, seq, WS_WAIT_SEC):
                    continue
                if closed.is_set():
                    break
                seq, changed = tasks.changes_since(seq)
                if changed is None:
                    await websocket.send_json({'type': 'tasks', 'tasks': tasks.tasks()})
                    continue
                for task in changed:
                    await websocket.send_json({'type': 'task', 'task': task})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            watcher.cancel()

    # API 경로를 먼저 등록하고 마지막에 '/' 를 마운트해야 /api·/ws 가 정적 파일에 가려지지 않는다.
    # colcon --symlink-install 은 설치된 web/ 파일을 build/ 로 가는 링크로 만든다. 그래서 링크를 따라간다.
    if web_dir is not None:
        app.mount('/', StaticFiles(directory=web_dir, html=True, follow_symlink=True),
                  name='web')

    return app
