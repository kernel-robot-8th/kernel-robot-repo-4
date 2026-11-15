"""홈랩에서 재현할 P5·P7 디버깅 사례."""

from cobot_anomaly_monitor.sim_link_probe import link_state
from harness import Stack


def test_bridge_counts_need_both_sides():
    assert link_state(25, 0, True) == '전달 미관측'
    assert link_state(140, 140, True) == '양쪽 수신'
    assert link_state(0, 0, True) == '원천 미관측'
    assert link_state(2, 0, False) == '관측 중'


def test_waiting_reason_uses_current_robot_and_snapshot(tmp_path):
    s = Stack(tmp_path)
    try:
        s.core.on_status('pinky1', dict(state='IDLE', central_controlled=True, central_latched=True))
        s.core.on_battery('pinky1', 80)
        s.core.on_tasks(dict(armed=True, tasks=[], orders=[], holds={}))
        assert s.core.live()['allocation']['pinky1'] == ['central_latched']
        s.now += 11
        reasons = s.core.live()['allocation']['pinky1']
        assert '상태 만료' in reasons and '배터리 만료' in reasons
    finally:
        s.close()
