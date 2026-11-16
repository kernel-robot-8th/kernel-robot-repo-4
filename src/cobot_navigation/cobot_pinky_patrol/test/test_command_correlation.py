"""명령 ID가 콜백 사이에 유지되고 다른 명령의 거절과 섞이지 않는지 검증한다."""

from test_patrol_controller import advance, completed, make_environment


def test_final_id_after_cancel_and_cleanup():
    """취소 요청 때가 아니라 종료 확인 후 원래 작업 ID로 응답한다."""
    env = make_environment()
    env.c.submit('goto:P1', 'job1')
    advance(env, 'NAVIGATING')
    env.c.submit('goto:P2', 'job2')
    env.c.submit('stop')
    env.c.tick()
    assert [e['command_id'] for e in completed(env)] == ['job2']
    env.nav.finish('CANCELED')
    advance(env, 'IDLE')
    assert [e['command_id'] for e in completed(env)] == ['job2', 'job1']
    assert completed(env)[-1]['state'] == 'STOPPED'
