"""control-center의 공개 요청 형식과 fleet의 작업 수명 계약을 검증한다."""

from pathlib import Path

from cobot_fleet_control.control_center_web import build_plan, main, run_web
from cobot_fleet_control.web_profiles import export_profiles, load_profiles
import pytest
from test_scenario import Environment


NAV = Path(__file__).resolve().parents[2]
CONFIG = NAV / 'cobot_pinky_patrol/config'


@pytest.fixture
def env(tmp_path):
    instance = Environment(tmp_path / 'fleet.sqlite3')
    instance.scenario.store.set_stock('SHOE42', 10)
    yield instance
    instance.repo.close()


def create(**changes):
    request = dict(type='create', request_id='web1', client_request_id='click1',
                   robot_id='pinky1', operation='goto', points=['P1'])
    request.update(changes)
    return request


def test_http_statuses_and_request_id_match_upstream_web(env):
    env.scenario.armed = False
    assert env.api.handle(create())['status'] == 423
    env.scenario.armed = True
    assert env.api.handle(create(robot_id='missing'))['status'] == 404
    first = env.api.handle(create(points=[' p1 ']))
    assert first['request_id'] == 'web1' and first['status'] == 202
    assert first['body']['command'] == 'goto:P1'
    assert env.api.handle(create())['status'] == 200
    assert env.api.handle(create(points=['P2']))['status'] == 409
    assert env.api.handle(create(client_request_id='click2'))['status'] == 409
    assert env.api.handle(dict(type='raw', command='home'))['status'] == 403
    env.fleet.tick()
    assert len(env.gateway.sent) == 1


def test_stale_robot_is_service_unavailable_not_bad_input(env):
    env.now = 4
    reply = env.api.handle(create())
    assert reply['status'] == 503
    assert env.repo.get('click1') is None


def test_battery_five_second_period_is_not_treated_as_link_loss(env):
    env.order()
    env.tick()
    for now in (1, 2, 3, 4, 5, 6):
        env.now = now
        env.scenario.telemetry('pinky1', dict(state='MOVING', central_controlled=True))
        if now == 5:
            env.scenario.telemetry('pinky1', battery=80.0)
        env.scenario.tick()
        assert env.current()['state'] == 'RUNNING'
    env.now = 16
    env.scenario.telemetry('pinky1', dict(state='MOVING', central_controlled=True))
    env.scenario.tick()
    assert env.current()['state'] == 'UNKNOWN'


def test_existing_web_resolve_payload_requires_real_idle_status(env):
    env.api.handle(create())
    env.fleet.tick()
    stop = env.api.handle(dict(type='estop', robot_id='pinky1'))
    assert stop['status'] == 202
    assert stop['body']['task_id'] == 'click1'
    assert stop['body']['operation'] == 'emergency_stop'
    env.fleet.on_status('pinky1', dict(command_id='click1', state='STOPPED', task_finished=True))
    assert env.repo.get('click1')['state'] == 'UNKNOWN'
    request = dict(type='resolve', task_id='click1', result='FAILED',
                   client_request_id='resolve1', note='현장에서 정지 확인')
    assert env.api.handle(request)['status'] == 409
    env.scenario.telemetry('pinky1', dict(
        state='STOPPED', busy=False, held_zone=None, central_controlled=True, central_latched=True))
    reply = env.api.handle(request)
    assert reply['status'] == 200 and reply['body']['state'] == 'FAILED'
    assert not env.scenario.store.holds()
    assert env.api.handle(request)['status'] == 409
    assert env.api.handle(dict(request, task_id='unknown'))['status'] == 404


def test_plain_stop_does_not_hold_and_robot_takes_next_manual_command(env):
    # 일반 정지는 보류·결과 모름을 만들지 않고 로봇에 stop 만 보낸다 (진호 님 원래 기준)
    reply = env.api.handle(dict(type='stop', robot_id='pinky1', client_request_id='stop1'))
    assert reply['status'] == 202 and reply['body']['operation'] == 'stop'
    assert reply['body']['task_id'] is None
    assert env.gateway.stops == ['pinky1'] and env.gateway.halts == []
    assert not env.scenario.store.holds() and env.api.snapshot()['tasks'] == []
    assert env.scenario.armed
    # 멈춘(STOPPED) 로봇도 잠금이 없으면 다음 수동 명령을 받는다
    env.scenario.telemetry('pinky1', dict(
        state='STOPPED', busy=False, held_zone=None, central_controlled=True,
        central_latched=False))
    assert env.api.handle(create())['status'] == 202


def test_plain_stop_cancels_unsent_task_and_running_task_ends_by_robot_result(env):
    env.api.handle(create())
    env.api.handle(dict(type='stop', robot_id='pinky1'))
    assert env.repo.get('click1')['state'] == 'FAILED'
    env.fleet.tick()
    assert env.gateway.sent == []
    env.scenario.telemetry('pinky1', dict(
        state='IDLE', busy=False, held_zone=None, central_controlled=True))
    env.api.handle(create(client_request_id='click2'))
    env.fleet.tick()
    assert env.repo.get('click2')['state'] == 'RUNNING'
    env.api.handle(dict(type='stop', robot_id='pinky1'))
    assert env.repo.get('click2')['state'] == 'RUNNING' and not env.scenario.store.holds()
    env.fleet.on_status('pinky1', dict(command_id='click2', state='STOPPED', task_finished=True))
    env.fleet.tick()
    assert env.repo.get('click2')['state'] not in {'RUNNING', 'UNKNOWN'}


def test_auto_dispatch_does_not_pick_a_stopped_robot(env):
    for robot in env.fleet.robots:
        env.scenario.telemetry(robot, dict(
            state='STOPPED', busy=False, held_zone=None, central_controlled=True))
    assert not any(env.scenario._available(robot) for robot in env.fleet.robots)
    assert all(env.scenario._available(robot, allow_stopped=True) for robot in env.fleet.robots)


def test_legacy_resolve_cannot_unlock_scenario_cargo_reservations(env):
    env.order()
    env.tick()
    task_id = env.current()['request_id']
    env.api.handle(dict(type='stop', robot_id='pinky1'))
    env.scenario.telemetry('pinky1', dict(
        state='STOPPED', busy=False, held_zone=None, central_controlled=True, central_latched=True))
    reply = env.api.handle(dict(type='resolve', task_id=task_id, result='FAILED', note='정지 확인'))
    assert reply['status'] == 409
    assert env.scenario.store.resources('order1')


def test_active_tasks_survive_recent_list_limit(env):
    env.api.handle(create())
    from cobot_fleet_control.contracts import Command
    for number in range(60):
        command = Command('done' + str(number), 'pinky2', 'home')
        env.repo.create(command)
        env.repo.transition(command.command_id, 'SUCCEEDED')
    tasks = env.api.snapshot(limit=3)['tasks']
    assert len(tasks) == 3
    assert tasks[0]['task_id'] == 'click1'


def test_arm_reply_includes_upstream_request_metadata(env):
    reply = env.api.handle(dict(
        type='arm', armed=True, source='127.0.0.1', client_request_id='arm-click'))
    assert reply['body']['source'] == '127.0.0.1'
    assert reply['body']['client_request_id'] == 'arm-click'


def test_current_split_profiles_export_without_copying_source(tmp_path):
    rules = export_profiles(CONFIG, 'lab', ['pinky1', 'pinky2', 'pinky3'], tmp_path)
    import yaml
    for robot in rules.configs:
        exported = yaml.safe_load((tmp_path / (robot + '.yaml')).read_text(encoding='utf-8'))
        assert exported['pinky_patrol_node']['ros__parameters'] == rules.configs[robot]
    assert rules.configs['pinky1']['home_name'] == 'I1'
    assert rules.configs['pinky2']['points']['ZA'] == rules.configs['pinky1']['points']['ZA']
    rules.validate('pinky1', 'goto', ['P1', 'I1'])
    rules.validate('pinky1', 'zone', ['ZA'])
    for operation, points in [
            ('goto', ['ZA']), ('zone', ['P1']), ('goto', ['P50']), ('goto', ['I2'])]:
        with pytest.raises(ValueError):
            rules.validate('pinky1', operation, points)


def test_web_rejects_invalid_points_before_creating_or_dispatching(env):
    env.api.point_rules = load_profiles(CONFIG, 'lab', env.fleet.robots)
    for operation, points in [('goto', ['ZA']), ('goto', ['P50']), ('zone', ['P1'])]:
        assert env.api.handle(create(operation=operation, points=points))['status'] == 400
    assert env.repo.get('click1') is None
    assert env.gateway.sent == []


@pytest.fixture
def share(tmp_path):
    root = tmp_path / 'control-center-share'
    (root / 'launch').mkdir(parents=True)
    for name in ('fleet_api.launch.xml', 'fleet_status.launch.xml'):
        (root / 'launch' / name).write_text('<launch/>')
    return root


def test_web_plan_has_one_execution_owner_and_uses_upstream_http_ws(share, tmp_path):
    plan, _, _ = build_plan(NAV, share, tmp_path)
    assert [name for name, _ in plan] == ['fleet', 'web-status', 'web-api']
    commands = [arg for _, argv in plan for arg in argv]
    assert 'fleet_api.launch.xml' in commands
    assert 'fleet_status.launch.xml' in commands
    assert not any('task_manager' in arg or 'mqtt' in arg.lower() for arg in commands)
    assert f'points_dir:={tmp_path.resolve()}' in commands
    external, _, _ = build_plan(NAV, share, tmp_path, start_fleet=False)
    assert [name for name, _ in external] == ['web-status', 'web-api']


def test_missing_feature_control_center_fails_before_start(tmp_path):
    with pytest.raises(ValueError, match='feature/control-center'):
        build_plan(NAV, tmp_path, tmp_path / 'output')


def test_preview_does_not_export_or_start_services(share, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr('cobot_fleet_control.control_center_web.run_web',
                        lambda *args: pytest.fail('preview started services'))
    output = tmp_path / 'not-created'
    main(['--navigation-root', str(NAV), '--control-center-share', str(share),
          '--output-dir', str(output)])
    assert not output.exists()
    assert 'fleet_api.launch.xml' in capsys.readouterr().out


def test_web_export_happens_before_start_and_owned_services_are_cleaned(share, tmp_path):
    output = tmp_path / 'profiles'
    plan, config, robots = build_plan(NAV, share, output)
    events = []

    class Runner:
        def start(self, name, argv):
            assert (output / 'pinky1.yaml').is_file()
            events.append(name)

        def pump(self):
            raise RuntimeError('web server exited')

        def close(self):
            events.append('closed')

    with pytest.raises(RuntimeError, match='web server exited'):
        run_web(plan, config, robots, 'lab', output, Runner())
    assert events == ['fleet', 'web-status', 'web-api', 'closed']


def test_web_launcher_is_a_plain_process_and_package_installs_it(monkeypatch):
    import runpy
    import xml.etree.ElementTree as ET
    import setuptools
    package = NAV / 'cobot_fleet_control'
    launch = ET.parse(package / 'launch/control_center_web.launch.xml').getroot()
    assert launch.findall('node') == []  # argparse를 쓰는 프로세스 감독기에 ROS 노드 이름 재매핑 인자를 전달하지 않는다.
    assert 'ros2 run cobot_fleet_control control_center_web' in launch.find('executable').get('cmd')
    registered = {}
    monkeypatch.chdir(package)
    monkeypatch.setattr(setuptools, 'setup', lambda **kwargs: registered.update(kwargs))
    runpy.run_path(str(package / 'setup.py'))
    assert any('control_center_web = ' in value
               for value in registered['entry_points']['console_scripts'])
    assert any('launch/control_center_web.launch.xml' in files
               for _, files in registered['data_files'])
