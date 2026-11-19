"""YOLO 판정 세 가지(핑키 상태, 팔 빠짐, 추락 아님)를 묶어 적재 완료를 정한다.

ROS·MQTT 를 모른다. 시각은 Unix 초다. 모르는 것은 참으로 치지 않는다.
"""

from collections import deque
import math

from .load_evidence import finite

RULE_VERSION = 'lc-1'
JUDGED_DECISION = 'vision_judged'
DROP_NAMES = ('box_on_floor', 'box_run_over')
PERCHED = 'box_perched_on_rim'
SOURCE_KINDS = ('sim_fixture', 'model_output')
CLOCK_ERROR_MAX = 0.25
TRAY_MARKERS = {'ZA': 31, 'ZB': 30, 'ZC': 32}
# 단계별 조건표. 하차는 표만 바꿔 쓴다. 하차의 placed 는 근거가 정해지지 않아 싣지 않는다.
TABLE = {
    'VERIFY_LOAD': {'side': 'pickup', 'arm_key': 'pickup_arm', 'zone_state': 'LOADED',
                    'key': 'load_present', 'grip': 'PICK', 'release': 'LOAD'},
    'VERIFY_UNLOAD': {'side': 'dropoff', 'arm_key': 'dropoff_arm', 'zone_state': 'EMPTY',
                      'key': 'load_absent', 'grip': 'PICK_DROPOFF', 'release': 'UNLOAD'},
}


def center(bbox):
    """사각형 중심 좌표를 돌려준다."""
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def valid_bbox(bbox):
    """유효한 [x1, y1, x2, y2] 사각형인지 검사한다."""
    return (isinstance(bbox, list) and len(bbox) == 4 and all(finite(v) for v in bbox)
            and bbox[2] > bbox[0] and bbox[3] > bbox[1])


def inside(bbox, anchor):
    """사각형 중심이 anchor 사각형 안에 있는가."""
    x, y = center(bbox)
    return anchor[0] <= x <= anchor[2] and anchor[1] <= y <= anchor[3]


def iou(first, second):
    """두 사각형의 IoU 를 계산한다."""
    overlap = (max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
               * max(0.0, min(first[3], second[3]) - max(first[1], second[1])))
    if overlap <= 0.0:
        return 0.0
    area = ((first[2] - first[0]) * (first[3] - first[1])
            + (second[2] - second[0]) * (second[3] - second[1]) - overlap)
    return overlap / area if area > 0.0 else 0.0


def near(bbox, anchor, reach):
    """사각형 중심이 anchor 를 가로·세로 reach 배만큼 넓힌 범위 안에 있는가."""
    x, y = center(bbox)
    w, h = anchor[2] - anchor[0], anchor[3] - anchor[1]
    return (anchor[0] - reach * w <= x <= anchor[2] + reach * w
            and anchor[1] - reach * h <= y <= anchor[3] + reach * h)


class LoadComplete:
    """구역·상자 프레임과 팔 단계 결과를 모아 두고, 요청마다 세 조건을 다시 센다."""

    def __init__(self, stream_id, model_id, calibration_id, hold_sec=1.0, still_ratio=0.15,
                 drop_frames=3, fresh_sec=2.0, gap_sec=1.0, min_frames=3, drop_reach=1.0,
                 gripper_closed_max=None, gripper_open_min=None,
                 drop_tray_iou_max=None, require_tray_marker_absent=False,
                 min_tray_box_frames=0, latch_drop=False):
        for name, value in {'hold_sec': hold_sec, 'still_ratio': still_ratio,
                            'fresh_sec': fresh_sec, 'gap_sec': gap_sec,
                            'drop_reach': drop_reach}.items():
            if not finite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        for name, value in {'drop_frames': drop_frames, 'min_frames': min_frames}.items():
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        for name, value in {'require_tray_marker_absent': require_tray_marker_absent,
                            'latch_drop': latch_drop}.items():
            if type(value) is not bool:
                raise ValueError(f'{name} must be a bool')
        if type(min_tray_box_frames) is not int or min_tray_box_frames < 0:
            raise ValueError('min_tray_box_frames must be a non-negative integer')
        if drop_tray_iou_max is not None and (
                not finite(drop_tray_iou_max) or not 0.0 < drop_tray_iou_max <= 1.0):
            raise ValueError('drop_tray_iou_max must be within (0, 1]')
        self.ids = {'stream_id': stream_id, 'model_id': model_id, 'calibration_id': calibration_id}
        self.hold_sec, self.still_ratio, self.drop_frames = hold_sec, still_ratio, drop_frames
        self.fresh_sec, self.gap_sec, self.min_frames = fresh_sec, gap_sec, min_frames
        self.drop_reach = drop_reach
        self.drop_tray_iou_max = drop_tray_iou_max
        self.require_tray_marker_absent = require_tray_marker_absent
        self.min_tray_box_frames = min_tray_box_frames
        self.latch_drop = latch_drop
        # 그리퍼 기준값. 둘 다 정해졌을 때만 닫힘→열림을 본다(실물 값을 본 뒤 정한다).
        self.gripper = ((gripper_closed_max, gripper_open_min)
                        if gripper_closed_max is not None and gripper_open_min is not None
                        else None)
        self.zones = deque(maxlen=120)
        self.boxes = deque(maxlen=120)
        self.arm = {}
        self.problem = {'zones': '구역 프레임 없음', 'boxes': '상자 프레임 없음'}

    def _accept(self, kind, history, frame, now):
        """프레임 한 장의 출처·시각·순번을 본다. 어긋나면 쌓아 둔 것을 버린다."""
        ts, seq = frame.get('capture_time'), frame.get('frame_seq')
        error, epoch = frame.get('clock_error_sec'), frame.get('stream_epoch')
        if (frame.get('source_kind') not in SOURCE_KINDS
                or any(frame.get(key) != value for key, value in self.ids.items())
                or not finite(error) or not 0 <= error <= CLOCK_ERROR_MAX or not finite(ts)
                or ts - error > now or now - ts + error > 3
                or type(seq) is not int or seq < 0 or not isinstance(epoch, str) or not epoch):
            history.clear()
            self.problem[kind] = '시각·스트림·모델·보정 불일치'
            return False
        if history:
            last = history[-1]
            if ts <= last['capture_time'] or (epoch == last['stream_epoch']
                                              and seq <= last['frame_seq']):
                return False
            if epoch != last['stream_epoch']:
                history.clear()
        self.problem[kind] = ''
        return True

    def on_zones(self, frame, now):
        """구역 근거 프레임을 받는다."""
        if not self._accept('zones', self.zones, frame, now):
            return
        zones = frame.get('zones')
        marker = frame.get('marker_state')
        ok = marker == 'OK' and isinstance(zones, dict)
        zone_map = zones if isinstance(zones, dict) else {}
        self.zones.append({
            'capture_time': frame['capture_time'], 'clock_error_sec': frame['clock_error_sec'],
            'stream_epoch': frame['stream_epoch'], 'frame_seq': frame['frame_seq'],
            'marker_state': marker, 'ok': ok, 'zones': zone_map})

    def on_boxes(self, frame, now):
        """상자·핑키 검출 프레임을 받는다."""
        if not self._accept('boxes', self.boxes, frame, now):
            return
        pinky, boxes = frame.get('pinky'), frame.get('boxes')
        marker = frame.get('marker_state')
        usable = (marker == 'OK' and isinstance(pinky, list)
                  and isinstance(boxes, list) and not frame.get('truncated'))
        clean_pinky = ([p for p in pinky if isinstance(p, dict) and valid_bbox(p.get('bbox'))
                        and isinstance(p.get('zones'), list)] if usable else [])
        clean_boxes = ([b for b in boxes if isinstance(b, dict) and valid_bbox(b.get('bbox'))
                        and isinstance(b.get('name'), str)] if usable else [])
        markers = frame.get('tray_markers')
        self.boxes.append({
            'capture_time': frame['capture_time'], 'clock_error_sec': frame['clock_error_sec'],
            'stream_epoch': frame['stream_epoch'], 'frame_seq': frame['frame_seq'],
            'marker_state': marker, 'ok': usable, 'pinky': clean_pinky, 'boxes': clean_boxes,
            'tray_markers': ([m for m in markers if type(m) is int]
                             if isinstance(markers, list) else None)})

    def on_arm_result(self, result, now):
        """팔 단계 결과를 주문·로봇·단계별로 기억한다. 팔 단계가 아니면 버린다."""
        stage = result.get('stage')
        if (stage not in {s[k] for s in TABLE.values() for k in ('grip', 'release')}
                or result.get('measured') is not True or result.get('finished') is not True
                or not result.get('order_id') or not result.get('robot_id')):
            return
        data = result.get('data') if isinstance(result.get('data'), dict) else {}
        joints = data.get('joints') if isinstance(data.get('joints'), dict) else {}
        grip = joints.get('gripper.pos')
        self.arm[(result['order_id'], result['robot_id'], stage)] = {
            'at': now, 'success': result.get('success') is True,
            'arm_safe': data.get('arm_safe') if type(data.get('arm_safe')) is bool else None,
            'gripper': grip if finite(grip) else None, 'source': result.get('source'),
            'session_id': (result.get('session_id')
                           if isinstance(result.get('session_id'), str) else None),
            'attempt': result.get('attempt') if type(result.get('attempt')) is int else None,
            'request_id': (result.get('request_id')
                           if isinstance(result.get('request_id'), str) else None),
            'fake': data.get('fake') is True, 'manual': data.get('manual') is True}
        for key in sorted(self.arm, key=lambda k: self.arm[k]['at'])[:-60]:
            del self.arm[key]

    def _arm(self, request, spec):
        """잡았다가(grip) 놓고 물러났다(release + arm_safe)를 단계 결과 두 개로 본다."""
        key = (request['order_id'], request['robot_id'])
        grip, release = self.arm.get(key + (spec['grip'],)), self.arm.get(key + (spec['release'],))
        info = {'source': 'arm_result', 'grip': grip, 'release': release,
                'gripper_checked': self.gripper is not None}
        if not grip or not release or release['at'] < grip['at']:
            return None, '팔 단계 결과 없음', info
        if not grip['success'] or not release['success']:
            return None, '팔 단계 실패', info
        if grip['manual'] or release['manual']:
            return None, '팔 단계가 사람 승인 결과', info
        if grip['fake'] or release['fake']:
            return None, '팔 단계가 가짜 실행 결과', info
        route = request.get('route') if isinstance(request.get('route'), dict) else {}
        expected_arm = route.get(spec.get('arm_key', ''))
        if (not isinstance(grip.get('source'), str) or not grip['source']
                or grip.get('source') != release.get('source')
                or (isinstance(expected_arm, str) and expected_arm
                    and grip['source'] != expected_arm)):
            return None, '팔 결과 출처 불일치', info
        req_session = request.get('session_id')
        g_sess, r_sess = grip.get('session_id'), release.get('session_id')
        if ((g_sess and r_sess and g_sess != r_sess)
                or (isinstance(req_session, str) and req_session
                    and ((g_sess and g_sess != req_session)
                         or (r_sess and r_sess != req_session)))):
            return None, '팔 결과 세션 불일치', info
        req_attempt = request.get('attempt')
        if (type(req_attempt) is int and (
                (grip.get('attempt') is not None and grip['attempt'] != req_attempt)
                or (release.get('attempt') is not None and release['attempt'] != req_attempt))):
            return None, '팔 결과 시도 불일치', info
        if release['arm_safe'] is None:
            return None, '팔 상태 모름', info
        if release['arm_safe'] is False:
            return False, '팔 퇴피 미확인', info
        if self.gripper:
            closed_max, open_min = self.gripper
            if grip['gripper'] is None or release['gripper'] is None:
                return None, '그리퍼 값 없음', info
            if grip['gripper'] > closed_max:
                return None, '잡기 뒤 그리퍼 닫힘 미확인', info
            if release['gripper'] < open_min:
                return False, '놓기 뒤 그리퍼 열림 미확인', info
        return True, '', info

    def _anchor(self, frame, zone):
        """그 구역 핑키의 상자. 둘 이상이면 어느 것인지 모른다."""
        found = [p['bbox'] for p in frame['pinky'] if zone in p['zones']]
        return found[0] if len(found) == 1 else None

    def _filter_drop_boxes(self, boxes, anchor):
        """D2 설정 시 그 구역 핑키 안 tray 와 겹치는 box_on_floor 만 추락에서 제외한다."""
        if self.drop_tray_iou_max is None or anchor is None:
            return boxes
        trays = [b['bbox'] for b in boxes
                 if b['name'] == 'box_on_tray' and inside(b['bbox'], anchor)]
        if not trays:
            return boxes
        return [b for b in boxes if not (
            b['name'] == 'box_on_floor'
            and any(iou(b['bbox'], tray) >= self.drop_tray_iou_max for tray in trays))]

    def _drop(self, zone, received):
        """그 구역 핑키 주변의 바닥 상자가 최근 몇 장 이어졌는지 센다."""
        frames = [f for f in self.boxes if f['capture_time'] - f['clock_error_sec'] >= received]
        anchor, marked = None, []
        for frame in frames:
            current = self._anchor(frame, zone) if frame['ok'] else None
            anchor = current or anchor
            candidates = self._filter_drop_boxes(frame['boxes'], current)
            names = sorted({b['name'] for b in candidates
                            if anchor and b['name'] in DROP_NAMES
                            and near(b['bbox'], anchor, self.drop_reach)})
            marked.append((frame, names))
        streak = []
        for frame, names in reversed(marked):
            if not names:
                break
            streak.append((frame, names))
        streak.reverse()
        if self.latch_drop and len(streak) < self.drop_frames:
            current_run, latched = [], []
            for frame, names in marked:
                if names:
                    current_run.append((frame, names))
                    if len(current_run) >= self.drop_frames:
                        latched = list(current_run)
                else:
                    current_run = []
            if latched:
                return latched
        return streak

    def _still(self, zone, start, end):
        """유지 구간 동안 그 구역 핑키 상자가 제자리인가. 표본이 모자라면 모른다."""
        track = []
        for frame in self.boxes:
            if not start <= frame['capture_time'] <= end:
                continue
            anchor = self._anchor(frame, zone) if frame['ok'] else None
            if anchor is None:
                return None, '상자 위치 표본 끊김'
            track.append(anchor)
        if len(track) < 2:
            return None, '상자 위치 표본 부족'
        first = track[0]
        size = max(first[2] - first[0], first[3] - first[1])
        moved = max(math.dist(center(first), center(b)) for b in track[1:])
        if moved > self.still_ratio * size:
            return False, '상자 위치가 움직임'
        return True, ''

    def _run(self, zone, state, received, now):
        """지금까지 끊기지 않고 이어진 '원하는 구역 상태' 프레임 묶음."""
        run = []
        for frame in reversed(self.zones):
            if (frame['capture_time'] - frame['clock_error_sec'] < received or not frame['ok']
                    or frame['zones'].get(zone) != state
                    or (run and run[-1]['capture_time'] - frame['capture_time'] > self.gap_sec)):
                break
            run.append(frame)
        run.reverse()
        if run and now - run[-1]['capture_time'] + run[-1]['clock_error_sec'] > self.fresh_sec:
            return []
        return run

    def _tray_checks(self, zone, start, end):
        """유지 구간 꼬리에서 빈 트레이 마커(Track A)와 트레이 상자 최소 프레임 조건을 확인한다."""
        marker_id = TRAY_MARKERS.get(zone)
        window = [f for f in self.boxes if start <= f['capture_time'] <= end]
        clean = []
        for frame in reversed(window):
            if self.require_tray_marker_absent:
                robots = [p for p in frame['pinky'] if zone in p['zones']]
                robot = robots[0] if len(robots) == 1 else {}
                seen_flag = robot.get('tray_marker_seen')
                robot_markers = (robot.get('tray_markers')
                                 if isinstance(robot.get('tray_markers'), list) else None)
                markers = (robot_markers if robot_markers is not None
                           else frame.get('tray_markers'))
                if type(seen_flag) is not bool and markers is None:
                    return '트레이 마커 근거 없음'
                if seen_flag is True or (markers is not None and marker_id in markers):
                    break
            clean.append(frame)
        clean.reverse()
        if self.require_tray_marker_absent and (
                len(clean) < self.min_frames
                or clean[-1]['capture_time'] - clean[0]['capture_time'] < self.hold_sec):
            return '트레이 마커 검출(빈 차 의심)'
        if self.min_tray_box_frames > 0:
            tray_box_frames = 0
            for frame in clean:
                anchor = self._anchor(frame, zone) if frame['ok'] else None
                if anchor and any(b['name'] == 'box_on_tray' and inside(b['bbox'], anchor)
                                  for b in frame['boxes']):
                    tray_box_frames += 1
            if tray_box_frames < self.min_tray_box_frames:
                return '트레이 위 상자 미확인'
        return ''

    def judge(self, request, received, now):
        """요청 하나의 판정. verdict 는 pass(성공 답)·drop(추락 결과)·wait(답 보류)다."""
        spec = TABLE.get(request.get('stage'))
        route = request.get('route') if isinstance(request.get('route'), dict) else {}
        zone = route.get(spec['side']) if spec else None
        if not spec or not isinstance(zone, str):
            return self._out('wait', 'UNKNOWN', '판정 대상 단계·구역 아님', {}, None)
        arm, arm_reason, arm_info = self._arm(request, spec)
        run = self._run(zone, spec['zone_state'], received, now)
        latest = self.zones[-1] if self.zones else None
        seen = (latest['zones'].get(zone) if latest and latest['ok']
                and now - latest['capture_time'] + latest['clock_error_sec'] <= self.fresh_sec
                else None)
        conditions = {'zone': bool(run) if seen is not None else None, 'arm': arm,
                      'no_drop': None if self.problem['boxes'] else True, 'zone_state': seen}
        streak = self._drop(zone, received)
        if len(streak) >= self.drop_frames:
            conditions['no_drop'] = False
            data = {'box_dropped': True, spec['key']: bool(run), 'arm_safe': arm is True,
                    'decision': JUDGED_DECISION, 'unjudged': False, 'rule_version': RULE_VERSION,
                    'evidence': {'frame_seq': [f['frame_seq'] for f, _ in streak],
                                 'stream_epoch': streak[-1][0]['stream_epoch'],
                                 'names': sorted({n for _, names in streak for n in names})}}
            return self._out('drop', 'BOX_DROPPED', '상자 추락 감지', conditions, data)
        if arm is not True:
            state = 'ARM_UNKNOWN' if arm is None else 'ARM_PRESENT'
            return self._out('wait', state, arm_reason, conditions, None)
        if not run:
            reason = self.problem['zones'] or (
                '구역 상태 모름(마커·영상)' if seen is None else f'구역 상태 {seen}')
            state = seen if seen in ('NO_ROBOT', 'EMPTY') else 'UNKNOWN'
            return self._out('wait', state, reason, conditions, None)
        if streak:
            conditions['no_drop'] = None
            return self._out('wait', 'LOADING', '바닥 상자 확인 중', conditions, None)
        if self.problem['boxes']:
            return self._out('wait', 'UNKNOWN', self.problem['boxes'], conditions, None)
        last_box = self.boxes[-1] if self.boxes else None
        if (last_box is None or now - last_box['capture_time']
                + last_box['clock_error_sec'] > self.fresh_sec):
            conditions['no_drop'] = None  # 상자 프레임이 끊기면 추락 여부를 모른다
            return self._out('wait', 'UNKNOWN', '상자 프레임 끊김', conditions, None)
        span = run[-1]['capture_time'] - run[0]['capture_time']
        if span < self.hold_sec or len(run) < self.min_frames:
            return self._out('wait', 'LOADING', '적재 표본 수집 중', conditions, None)
        for frame in self.boxes:
            if not run[0]['capture_time'] <= frame['capture_time'] <= run[-1]['capture_time']:
                continue
            anchor = self._anchor(frame, zone) if frame['ok'] else None
            if anchor and any(b['name'] == PERCHED and near(b['bbox'], anchor, 0.0)
                              for b in frame['boxes']):
                return self._out('wait', 'LOADING', '상자 턱 걸림(기준 미정)', conditions, None)
        if request.get('stage') == 'VERIFY_LOAD':
            tray_reason = self._tray_checks(zone, run[0]['capture_time'], run[-1]['capture_time'])
            if tray_reason:
                return self._out('wait', 'LOADING', tray_reason, conditions, None)
        still, still_reason = self._still(zone, run[0]['capture_time'], run[-1]['capture_time'])
        if still is not True:
            return self._out('wait', 'LOADING', still_reason, conditions, None)
        data = {spec['key']: True, 'arm_safe': True, 'box_dropped': False,
                'decision': JUDGED_DECISION, 'unjudged': False,
                'arm_source': arm_info['source'], 'rule_version': RULE_VERSION,
                'evidence': dict(self.ids, stream_epoch=run[-1]['stream_epoch'],
                                 frame_seq=[f['frame_seq'] for f in run],
                                 hold_sec=round(span, 3), arm=arm_info)}
        return self._out('pass', 'LOAD_COMPLETE', '', conditions, data)

    @staticmethod
    def _out(verdict, state, reason, conditions, data):
        return {'verdict': verdict, 'state': state, 'reason': reason, 'conditions': conditions,
                'data': data}
