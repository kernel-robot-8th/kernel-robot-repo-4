"""수동 어댑터 계약 시험. 관제가 조용히 버리는 답을 내면 실패해야 한다."""

import json

from cobot_anomaly_monitor.manual_adapter import ManualAdapter, yaw_error_deg
from cobot_anomaly_monitor.monitor_store import MonitorStore
import pytest

ROUTE = {'pickup': 'ZA', 'dropoff': 'ZC', 'pickup_arm': 'omx1', 'dropoff_arm': 'omx3',
         'lane': 'main'}
POINTS = {'ZA': [0.6, 0.5, -1.5], 'ZC': [-0.5, 0.3, 1.5]}


class Fixture:
    def __init__(self, path):
        self.store = MonitorStore(path / 'm.sqlite3')
        self.results = []
        self.state = {'pose_x': 0.63, 'pose_y': 0.54, 'pose_yaw': -1.5, 'speed_mps': 0.0}
        self.now = 100.0
        self.adapter = ManualAdapter(self.store, self.results.append, ['vision', 'omx1'], POINTS,
                                     lambda robot: self.state, clock=lambda: self.now)
        self.adapter.on_heartbeat({'session_id': 's1'})
        self.seq = 0

    def request(self, stage='PICK', **changes):
        self.seq += 1
        data = {'request_id': f'r{self.seq}', 'order_id': 'o1', 'robot_id': 'pinky1',
                'stage': stage, 'target': 'vision', 'action': 'x', 'sku': 'SHOE42', 'quantity': 1,
                'attempt': 1, 'route': ROUTE, 'timeout_sec': 300.0, 'session_id': 's1',
                'seq': self.seq, 'issued_at': self.now, 'ttl_sec': 5.0}
        data.update(changes)
        return data


@pytest.fixture
def fx(tmp_path):
    item = Fixture(tmp_path)
    yield item
    item.store.close()


def state_of(fx, request):
    return fx.store.work(request['request_id'])['state']


def test_result_matches_the_request_and_marks_the_operator(fx):
    request = fx.request('PICK', target='omx1')
    assert fx.adapter.on_request(request)
    result = fx.adapter.approve(request['request_id'], 'kgh', '현장 확인')
    assert result['source'] == 'omx1' and result['stage'] == 'PICK'
    assert result['measured'] is True and result['finished'] is True
    assert result['success'] is True and result['detail'] == '현장 확인'
    assert result['data'] == {'manual': True, 'operator': 'kgh'}
    assert fx.results == [result]


@pytest.mark.parametrize('stage,required', [
    ('VERIFY_LOAD', ('load_present', 'arm_safe')),
    ('VERIFY_UNLOAD', ('placed', 'load_absent', 'arm_safe')),
    ('PICKUP_EXIT', ('clear',)), ('PATH_EXIT', ('clear',)), ('RETURN_EXIT', ('clear',)),
    ('CORRECT_PICKUP', ('no_motion',)),
])
def test_stage_evidence_is_complete(fx, stage, required):
    request = fx.request(stage)
    fx.adapter.on_request(request)
    data = fx.adapter.approve(request['request_id'], 'kgh')['data']
    assert all(data[key] is True for key in required)


def test_sku_defaults_to_the_order_and_can_report_a_mismatch(fx):
    first, second = fx.request('MARKER'), None
    fx.adapter.on_request(first)
    assert fx.adapter.approve(first['request_id'], 'kgh')['data']['sku'] == 'SHOE42'
    second = fx.request('QR')
    fx.adapter.on_request(second)
    assert fx.adapter.approve(second['request_id'], 'kgh', sku='OTHER')['data']['sku'] == 'OTHER'


def test_dock_error_comes_from_the_pose_not_the_operator(fx):
    request = fx.request('DOCK_PICKUP')
    fx.adapter.on_request(request)
    data = fx.adapter.approve(request['request_id'], 'kgh')['data']
    assert data['xy_m'] == pytest.approx(0.05)
    assert data['yaw_deg'] == pytest.approx(0.0)
    assert data['stopped'] is True and data['base_hold'] is True


def test_dock_uses_the_dropoff_point_and_wraps_yaw(fx):
    fx.state.update(pose_x=-0.5, pose_y=0.3, pose_yaw=1.5 + 0.1)
    request = fx.request('DOCK_DROPOFF')
    fx.adapter.on_request(request)
    data = fx.adapter.approve(request['request_id'], 'kgh')['data']
    assert data['xy_m'] == pytest.approx(0.0)
    assert data['yaw_deg'] == pytest.approx(5.7296, abs=0.001)
    assert yaw_error_deg(3.1, -3.1) == pytest.approx(-4.7662, abs=0.001)


def test_dock_is_refused_without_a_pose_and_stays_pending(fx):
    fx.state.update(pose_x=None, pose_y=None, pose_yaw=None)
    request = fx.request('DOCK_PICKUP')
    fx.adapter.on_request(request)
    with pytest.raises(ValueError, match='자세'):
        fx.adapter.approve(request['request_id'], 'kgh')
    assert fx.results == [] and state_of(fx, request) == 'PENDING'


def test_dock_is_refused_while_moving(fx):
    fx.state['speed_mps'] = 0.2
    request = fx.request('DOCK_PICKUP')
    fx.adapter.on_request(request)
    with pytest.raises(ValueError, match='움직이고'):
        fx.adapter.approve(request['request_id'], 'kgh')


def test_failure_is_retry_safe_only_when_the_operator_says_so(fx):
    first = fx.request('LOAD', target='omx1')
    fx.adapter.on_request(first)
    assert fx.adapter.reject(first['request_id'], 'kgh', '낙하')['data'].get('retry_safe') is None
    second = fx.request('LOAD', target='omx1')
    fx.adapter.on_request(second)
    result = fx.adapter.reject(second['request_id'], 'kgh', '재시도', retry_safe=True)
    assert result['success'] is False and result['data']['retry_safe'] is True


def test_other_targets_are_left_alone(fx):
    request = fx.request(target='omx3')
    assert not fx.adapter.on_request(request)
    assert fx.store.work(request['request_id']) is None


def test_duplicate_request_is_answered_once(fx):
    request = fx.request()
    assert fx.adapter.on_request(request)
    assert not fx.adapter.on_request(request)
    fx.adapter.approve(request['request_id'], 'kgh')
    with pytest.raises(KeyError):
        fx.adapter.approve(request['request_id'], 'kgh')
    assert len(fx.results) == 1


def test_duplicates_survive_a_restart(fx, tmp_path):
    request = fx.request()
    fx.adapter.on_request(request)
    other = ManualAdapter(MonitorStore(tmp_path / 'm.sqlite3'), fx.results.append, ['vision'],
                          POINTS, lambda robot: fx.state, clock=lambda: fx.now)
    other.on_heartbeat({'session_id': 's1'})
    assert not other.on_request(request)
    other.store.close()


def test_old_session_stale_sequence_and_expired_requests_are_not_offered(fx):
    wrong = fx.request(session_id='old')
    assert not fx.adapter.on_request(wrong)
    assert state_of(fx, wrong) == 'REJECTED_SESSION'
    good = fx.request()
    assert fx.adapter.on_request(good)
    stale = fx.request(seq=1)
    assert not fx.adapter.on_request(stale)
    assert state_of(fx, stale) == 'REJECTED_SEQ'
    late = fx.request(issued_at=fx.now - 6.0)
    assert not fx.adapter.on_request(late)
    assert state_of(fx, late) == 'EXPIRED'
    assert [r['request_id'] for r in fx.adapter.pending()] == [good['request_id']]


def test_new_session_restarts_sequences(fx):
    fx.adapter.on_request(fx.request())
    fx.adapter.on_heartbeat({'session_id': 's2'})
    assert fx.adapter.on_request(fx.request(session_id='s2', seq=1))


def test_safety_requests_are_recorded_without_an_answer(fx):
    request = fx.request('SAFETY', target='omx1', action='hold')
    assert not fx.adapter.on_request(request)
    assert state_of(fx, request) == 'SAFETY_NOTED' and fx.results == []


def test_blocked_adapter_takes_nothing(fx):
    fx.adapter.blocked = 'work_result 발행자 2개'
    request = fx.request()
    assert not fx.adapter.on_request(request)
    assert fx.store.work(request['request_id']) is None


def test_operator_is_required(fx):
    request = fx.request()
    fx.adapter.on_request(request)
    with pytest.raises(ValueError, match='operator'):
        fx.adapter.approve(request['request_id'], ' ')


def test_answer_text_is_kept(fx):
    request = fx.request('VERIFY_LOAD')
    fx.adapter.on_request(request)
    result = fx.adapter.approve(request['request_id'], 'kgh')
    row = fx.store.work(request['request_id'])
    assert row['state'] == 'APPROVED' and json.loads(row['result_json']) == result
