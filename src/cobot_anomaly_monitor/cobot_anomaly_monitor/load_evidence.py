"""검출기는 호기를 식별하지 않는다. 요청 시각·정차 위치·구역으로 적재 근거를 귀속한다."""

import math

SETTLE_SEC = 1.0


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class LoadEvidence:
    """한 모니터 실행기에서 사용하는 요청별 증거 창. 시각은 Unix 초이다."""

    def __init__(self, core, points, stream_id, calibration_id, model_id):
        self.core, self.points = core, points
        self.stream_id, self.calibration_id, self.model_id = stream_id, calibration_id, model_id
        self.frames = {}
        self.arm = {}
        self.watermarks = {}
        self.reasons = {}

    def attribution(self, request, now):
        core = self.core
        order = core.orders.get(request['order_id'], {})
        robot = request['robot_id']
        zone = request['route']['pickup']
        if (core.tasks_at is None or not 0 <= now - core.tasks_at <= 3
                or order.get('state') != 'RUNNING' or order.get('stage') != 'VERIFY_LOAD'
                or order.get('request_id') != request['request_id']
                or order.get('robot_id') != robot):
            return '현재 주문·단계 스냅샷 대기'
        if robot not in core.robots:
            return '대상 호기 미등록'
        if zone not in ('ZA', 'ZB') or zone not in self.points:
            return '상차 구역 좌표 없음'
        target = zone[1:]
        for name in core.robots:
            state = core.status.get(name, {})
            seen = core.seen.get(name, {})
            pose = core.pose.get(name)
            active = 0 <= now - seen.get('patrol_status', -math.inf) <= 3
            distance = math.dist(pose[:2], self.points[zone][:2]) if pose else None
            if distance is not None and not math.isfinite(distance):
                return f'{name} 위치 오류'
            stationary = state.get('busy') is False and bool(core.stationary_pose.get(name))
            if name == robot:
                if distance is None or not active:
                    return f'{name} 위치·상태 미확인'
                # AMCL 은 움직일 때만 위치를 낸다(update_min_d). 정지 뒤 위치가 안 오면
                # busy False + 오도메트리 정지 1초 이상(속도 표본 1초 안)일 때 마지막 위치를 정지 위치로 본다.
                still = getattr(core, 'still_since', {}).get(name)
                if (not stationary and state.get('busy') is False and still is not None
                        and now - still >= SETTLE_SEC
                        and 0 <= now - seen.get('odom', -math.inf) <= 1):
                    stationary = True
                # 이동 후 오래된 위치는 도착 근거로 사용할 수 없다.
                if not stationary:
                    return f'{name} 정지 후 위치 확인 필요'
                if (state.get('held_zone') != target or state.get('arrived_zone') != target
                        or state.get('central_latched') is not False or distance > .15):
                    return f'{name} 상차 도착·정지 미확인'
                continue
            # 다른 호기: 같은 구역 토큰이면 막는다. 정지를 요구하지 않는다(다른 구역 주행은 정상).
            if state.get('held_zone') == target:
                return f'{name} 같은 구역 가능'
            if not active:
                # 기동하지 않은 호기(위치 없음)는 배제한다. 상태가 끊긴 호기의 마지막 위치가 가까우면 막는다.
                if distance is not None and distance <= .50:
                    return f'{name} 상태 끊김·구역 근처 마지막 위치'
                continue
            if distance is None:
                return f'{name} 위치 미확인'
            if stationary:
                if distance <= .35:
                    return f'{name} 같은 구역 가능'
                continue
            # 주행 중(또는 정지 미확인): 최신 위치가 0.50 m 밖이어야 배제한다.
            if not 0 <= now - seen.get('amcl_pose', -math.inf) <= 3:
                return f'{name} 주행 중 위치 만료'
            if distance <= .50:
                return f'{name} 주행 중 구역 근처'
        return ''

    def observe(self, request, received, frame, now):
        rid = request['request_id']
        problem = self.attribution(request, now)
        ts, seq = frame.get('capture_time'), frame.get('frame_seq')
        error = frame.get('clock_error_sec')
        history = self.frames.setdefault(rid, [])
        if (problem or frame.get('stream_id') != self.stream_id
                or frame.get('source_kind') not in ('sim_fixture', 'model_output')
                or frame.get('model_id') != self.model_id
                or frame.get('calibration_id') != self.calibration_id
                or not finite(error) or not 0 <= error <= .25 or not finite(ts)
                # 미래 프레임은 오차를 빼고도 지금보다 늦을 때만 버린다(이전 `ts + error > now` 는
                # 오차보다 빨리 도착한 정상 프레임을 버렸다, 11-09 시뮬 vl_2·3).
                or ts - error < received or ts - error > now or now - ts + error > 3
                or type(seq) is not int or seq < 0):
            history.clear()
            self.reasons[rid] = problem or '시각·스트림·모델·보정 불일치'
            return
        previous = self.watermarks.get(rid)
        epoch = frame.get('stream_epoch')
        if not isinstance(epoch, str) or not epoch:
            history.clear()
            self.reasons[rid] = '스트림 시작 식별자 없음'
            return
        if previous:
            old_epoch, old_seq, old_ts = previous
            if ts <= old_ts or (epoch == old_epoch and seq <= old_seq):
                return
            if epoch != old_epoch:
                history.clear()
        self.watermarks[rid] = (epoch, seq, ts)
        zones = frame.get('zones')
        if (frame.get('marker_state') != 'OK' or not isinstance(zones, dict)
                or zones.get(request['route']['pickup']) != 'LOADED'):
            history.clear()
            self.reasons[rid] = '마커 또는 단일 적재 핑키 미확인'
            return
        fields = ('source_kind', 'stream_id', 'model_id', 'calibration_id', 'capture_time', 'stream_epoch',
                  'frame_seq', 'clock_error_sec')
        provenance = {key: frame[key] for key in ('recorded_epoch', 'replay_rec', 'replay_frame')
                      if isinstance(frame.get(key), str)}
        history.append(dict({key: frame[key] for key in fields}, **provenance, received_at=now,
                            frame_age_ms=round((now - ts) * 1000), box_present=True))
        history[:] = [f for f in history[-3:] if now - f['capture_time'] + f['clock_error_sec'] <= 3]
        self.reasons[rid] = '팔 퇴피 확인 대기' if len(history) == 3 else '적재 표본 수집 중'

    def clear(self, rid):
        for table in (self.frames, self.arm, self.reasons, self.watermarks):
            table.pop(rid, None)
