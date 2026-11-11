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

명령(/api/tasks, 정지, 해제, 개발용 수동 명령)은 직접 로봇에 보내지 않는다. 작업 노드에 요청 토픽으로 넘기고
그 응답을 HTTP 로 바꾸기만 한다. 검증·기록·발행은 작업 노드가 한다.
작업 노드는 cobot_fleet_control 의 fleet_control_node 하나다 (하트비트로 로봇 명령 허용).
비상정지는 estop 으로 넘기고, 정지 잠금 복구(release_control)와
수동 상차 확인(confirm_loaded)도 같은 요청 토픽으로 넘긴다.
"""

import asyncio

from cobot_control_center.fleet_api_utils import initial_pose_error, MJPEG_BOUNDARY, mjpeg_part
from fastapi import (Body, FastAPI, HTTPException, Query, Request, Response, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# WebSocket 이 새 스냅샷을 기다리는 한 번의 최대 시간 [s]. 끊긴 연결을 이 주기로 알아챈다.
WS_WAIT_SEC = 1.0


READ_ONLY_DETAIL = '읽기 전용 백엔드: 명령은 실물 관제 화면(bringup, 8080)에서'


class NoCacheStaticFiles(StaticFiles):
    """화면 파일을 고치면 새로 고침만으로 반영되게, 브라우저가 매번 바뀌었는지 묻게 한다."""

    async def get_response(self, path, scope):
        # 캐시 지시가 없으면 브라우저가 예전 index.html·js 를 그대로 써서 새 버튼이 안 보인다.
        # 안 바뀌었으면 ETag 로 304 만 오가므로 부담이 없다.
        response = await super().get_response(path, scope)
        response.headers['Cache-Control'] = 'no-cache'
        return response


def create_app(store, map_data=None, web_dir=None, domain_id=None, layers=None,
               tasks=None, publish_request=None, cameras=None):
    """
    웹 앱을 만든다. 데이터는 인자로 받은 SnapshotStore 에서만 읽는다.

    map_data 는 load_map() 결과 (info, pgm 바이트) 또는 None, web_dir 은 화면 정적 파일 폴더다.
    domain_id 는 이 백엔드가 붙은 ROS_DOMAIN_ID 다. fleet_status 를 받기 전에도 화면이
    실물·시험 중 어디를 보는지 알 수 있게 health 에 싣는다.
    layers 는 load_map_layers() 결과(구역 지점·출구·대기 슬롯·홈) 또는 None 이다.
    tasks 는 TaskStore, publish_request 는 요청 JSON 문자열을 task_request 토픽에 내는 함수다.
    둘 중 하나라도 None 이면 명령 경로는 503 이다 (읽기 전용).
    cameras 는 CameraStore 또는 None 이다. None 이면 카메라 경로는 모든 로봇에 404 다.
    """
    app = FastAPI(title='cobot control center API', version='0.1.0')

    def source(request):
        # 누가 눌렀는지: 로그인이 없으므로 접속 IP 를 운영자 조치 기록(source)에 남긴다.
        return request.client.host if request.client else ''

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
        task_health = tasks.health() if tasks is not None else {'controller_online': False}
        camera_health = cameras.health() if cameras is not None else {}
        # read_only: 명령을 넘길 곳이 없는 백엔드 (개발용 fleet_api_dev). 화면은 명령 버튼을 모두 끈다.
        return {'ok': True, 'domain_id': domain_id, 'read_only': publish_request is None,
                **store.health(), **task_health,
                'cameras': camera_health}

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

    # ---------- 카메라 (로봇이 낸 JPEG 를 풀지 않고 그대로 넘긴다) ----------

    def camera_or_404(robot_id):
        if cameras is None or robot_id not in cameras.robots():
            raise HTTPException(status_code=404, detail=f'카메라를 구독하지 않는 로봇: {robot_id}')
        return cameras

    @app.get('/api/robots/{robot_id}/camera.jpg')
    def camera_frame(robot_id: str):
        frame = camera_or_404(robot_id).latest(robot_id)
        if frame is None:
            raise HTTPException(status_code=404, detail=f'아직 받은 영상이 없음: {robot_id}')
        return Response(content=frame[1], media_type='image/jpeg',
                        headers={'Cache-Control': 'no-store'})

    @app.get('/api/robots/{robot_id}/camera')
    def camera_stream(robot_id: str):
        store_ = camera_or_404(robot_id)

        async def frames():
            # 보는 사람이 창을 닫으면 Starlette 가 이 생성기를 취소한다.
            # 프레임이 없으면 아무것도 보내지 않고 기다린다 (화면은 /api/health 의 cameras 로 '영상 없음'을 띄운다).
            frame = store_.latest(robot_id)
            seq = 0
            if frame is not None:
                seq = frame[0]
                yield mjpeg_part(frame[1])
            while True:
                if not await asyncio.to_thread(store_.wait_newer, robot_id, seq, WS_WAIT_SEC):
                    continue
                seq, jpeg = store_.latest(robot_id)
                yield mjpeg_part(jpeg)

        return StreamingResponse(
            frames(), media_type=f'multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}',
            headers={'Cache-Control': 'no-store'})

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

    # ---------- 명령 (작업 노드 fleet_control_node 경유) ----------

    def call_controller(payload):
        if tasks is None or publish_request is None:
            raise HTTPException(status_code=503, detail=READ_ONLY_DETAIL)
        if not tasks.online():
            raise HTTPException(status_code=503,
                                detail='작업 노드 응답 없음 (fleet_control_node 를 켜 주세요)')
        result = tasks.request(payload, publish_request)
        if result is None:
            raise HTTPException(status_code=503, detail='작업 노드가 제때 답하지 않음')
        status, body = result
        body = body if isinstance(body, dict) else {}
        if status >= 400 and 'task_id' in body:
            # 기록된 거절(REJECTED): 이유와 작업을 함께 돌려준다.
            return JSONResponse(status_code=status,
                                content={'detail': body.get('detail'), 'task': body})
        return JSONResponse(status_code=status, content=body)

    @app.post('/api/tasks')
    def create_task(body: dict = Body(...)):
        return call_controller({
            'type': 'create', 'client_request_id': body.get('client_request_id'),
            'robot_id': body.get('robot_id'), 'operation': body.get('operation'),
            'points': body.get('points') or []})

    @app.post('/api/robots/{robot_id}/stop')
    def stop_robot(robot_id: str, body: dict = Body(default={})):
        emergency = bool(body.get('emergency', False))
        if emergency:
            # fleet_control 은 stop 의 emergency 를 보지 않는다. 비상정지는 estop 요청이다.
            return call_controller({
                'type': 'estop', 'robot_id': robot_id,
                'client_request_id': body.get('client_request_id')})
        return call_controller({
            'type': 'stop', 'robot_id': robot_id,
            'client_request_id': body.get('client_request_id')})

    @app.post('/api/commands/estop')
    def estop_all(body: dict = Body(default={})):
        # 전체 비상정지: 로봇 지정 없이 한 번 내면 fleet 이 전 로봇·팔을 세운다.
        return call_controller({
            'type': 'estop', 'client_request_id': body.get('client_request_id')})

    @app.post('/api/robots/{robot_id}/release_control')
    def release_control(robot_id: str, request: Request, body: dict = Body(default={})):
        # 정지 잠금·보류 복구. 검사는 fleet_control 이 한다. 운영자·메모·확인 항목은 선택이고,
        # 누가 눌렀는지는 접속 IP(source)로 남긴다 (화면 확인 창 한 번, 2026-11-09 임시 일반형).
        return call_controller({
            'type': 'release_control', 'robot_id': robot_id,
            'client_request_id': body.get('client_request_id'),
            'operator': body.get('operator'), 'note': body.get('note'),
            'evidence': body.get('evidence'),
            'source': source(request)})

    @app.post('/api/robots/{robot_id}/initial_pose')
    def initial_pose(robot_id: str, request: Request, body: dict = Body(default={})):
        # AMCL 위치를 다시 잡는다. pose 가 없으면 홈 (좌표는 fleet_control 이 순찰 설정에서 읽음),
        # 있으면 화면 지도에서 찍은 {x, y, yaw}. 검사·발행은 fleet_control 이 한다 (이 서버는 로봇
        # 토픽을 발행하지 않는다). 지도 범위만 지도를 가진 여기서 먼저 본다.
        # 누가 눌렀는지는 접속 IP(source)로 남긴다.
        payload = {'type': 'initial_pose', 'robot_id': robot_id,
                   'client_request_id': body.get('client_request_id'),
                   'source': source(request)}
        pose = body.get('pose')
        if pose is not None:
            error = initial_pose_error(pose, map_data[0] if map_data else None)
            if error:
                raise HTTPException(status_code=400, detail=error)
            payload['pose'] = {key: float(pose[key]) for key in ('x', 'y', 'yaw')}
        return call_controller(payload)

    @app.post('/api/orders/{order_id}/recover')
    def recover_order(order_id: str, request: Request, body: dict = Body(default={})):
        # 멈춘 주문 복구: decision 'resume'(이어서 가기) 또는 'fail'(주문 취소).
        # 화면은 확인 창 한 번 뒤 보낸다 (2026-11-09 임시 일반형). 운영자·메모는 선택이고,
        # 이어서 가기 단계 제한·확인 항목 검사는 fleet_control(scenario_safety.recover)이 한다.
        return call_controller({
            'type': 'resolve', 'order_id': order_id, 'decision': body.get('decision'),
            'client_request_id': body.get('client_request_id'),
            'operator': body.get('operator'), 'note': body.get('note'),
            'evidence': body.get('evidence'),
            'source': source(request)})

    @app.post('/api/orders/{order_id}/confirm_loaded')
    def confirm_loaded(order_id: str, body: dict = Body(default={})):
        # 수동 상차 확인. 운영자가 실물 상차를 끝냈을 때 기존 주문에 확인값을 넣는다.
        # SKU·적재·팔 퇴피·통로·상차장 상태 검사는 fleet_control 이 하고, 통과하면 구역 이탈부터 재개한다.
        return call_controller({
            'type': 'confirm_loaded', 'order_id': order_id,
            'client_request_id': body.get('client_request_id'),
            'operator': body.get('operator'), 'note': body.get('note'),
            'evidence': body.get('evidence')})

    @app.post('/api/robots/{robot_id}/raw_cmd')
    def raw_command(robot_id: str, body: dict = Body(default={})):
        # 개발용 수동 명령. 검사·전달은 fleet_control_node 가 정한다 (allow_raw_cmd 꺼지면 403).
        return call_controller({
            'type': 'raw', 'robot_id': robot_id,
            'client_request_id': body.get('client_request_id'),
            'command': body.get('command')})

    @app.post('/api/commands/arm')
    def arm_commands(request: Request, body: dict = Body(default={})):
        # 작업 명령 켜기/끄기. 꺼져 있으면 작업 노드가 작업·수동 명령을 423 으로 거절한다.
        return call_controller({
            'type': 'arm', 'armed': body.get('armed'),
            'client_request_id': body.get('client_request_id'),
            'source': source(request)})

    @app.post('/api/tasks/{task_id}/resolve')
    def resolve_task(task_id: str, body: dict = Body(default={})):
        return call_controller({
            'type': 'resolve', 'task_id': task_id,
            'client_request_id': body.get('client_request_id'),
            'result': body.get('result', 'FAILED'), 'note': body.get('note', '')})

    def task_store():
        if tasks is None:
            raise HTTPException(status_code=503, detail=READ_ONLY_DETAIL)
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
        app.mount('/', NoCacheStaticFiles(directory=web_dir, html=True, follow_symlink=True),
                  name='web')

    return app
