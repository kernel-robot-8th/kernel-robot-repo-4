"""설정 분리 이후 로봇 식별·좌표·설치·launch 연결을 검증한다."""

from copy import deepcopy
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET

from cobot_pinky_patrol.patrol_controller import PatrolController
from cobot_pinky_patrol.patrol_points_utils import parse_points, parse_zone_points
import pytest
import setuptools
from test_patrol_controller import Gate, Navigation
import yaml


PKG = Path(__file__).resolve().parents[1]


def load_parameters(robot_id='pinky1', site='lab'):
    """launch와 같은 순서로 공통·현장·로봇 설정을 읽는다."""
    parameters = {}
    for name in ('common.yaml', f'sites/{site}.yaml', f'robots/{robot_id}.yaml'):
        document = yaml.safe_load((PKG / 'config' / name).read_text(encoding='utf-8'))
        parameters.update(deepcopy(document['pinky_patrol_node']['ros__parameters']))
    return parameters


@pytest.mark.parametrize('robot_id', ['pinky1', 'pinky2', 'pinky3'])
def test_robot_profile_only_contains_identity(robot_id):
    """현장 좌표와 실행 기본값을 로봇별 파일에 다시 복사하지 않는다."""
    profile = yaml.safe_load(
        (PKG / f'config/robots/{robot_id}.yaml').read_text(encoding='utf-8'))
    assert profile['pinky_patrol_node']['ros__parameters'] == {
        'robot_id': robot_id, 'home_name': f'I{robot_id[-1]}'}


@pytest.mark.parametrize('robot_id', ['pinky1', 'pinky2', 'pinky3'])
@pytest.mark.parametrize('point', ['P36', 'P50'])
def test_unused_points_are_rejected_before_navigation(robot_id, point):
    """예비 원점 지점을 명령해도 실제 이동 목표를 만들지 않는다."""
    config = load_parameters(robot_id)
    navigation, events = Navigation(), []
    controller = PatrolController(
        parse_points(config['points']), config['home_name'],
        parse_zone_points(config['zone_points']), navigation, Gate(), events.append,
        lambda: None, lambda: True, lambda: None)
    controller.submit(f'goto:{point}', 'unused-point')
    assert navigation.goals == []
    assert events[-1]['state'] == 'FAILED'
    assert events[-1]['task_finished'] is True
    assert 'unknown point' in events[-1]['detail']


def test_common_launch_loads_profiles_in_order():
    """ROS에 전달하는 세 설정 경로와 노드 이름이 설치 구성과 맞는다."""
    launch = ET.parse(PKG / 'launch/patrol.launch.xml').getroot()
    robot_arg = launch.find("arg[@name='robot_id']")
    assert robot_arg is not None and 'default' not in robot_arg.attrib
    node = launch.find("node[@exec='pinky_patrol_node']")
    assert node.attrib['name'] == 'pinky_patrol_node'
    files = [p.attrib['from'] for p in node.findall('param') if 'from' in p.attrib]
    for robot_id in ('pinky1', 'pinky2', 'pinky3'):
        resolved = [Path(name.replace('$(find-pkg-share cobot_pinky_patrol)', str(PKG))
                         .replace('$(var site)', 'lab').replace('$(var robot_id)', robot_id))
                    for name in files]
        assert resolved == [PKG / 'config/common.yaml', PKG / 'config/sites/lab.yaml',
                            PKG / f'config/robots/{robot_id}.yaml']
        assert all(path.is_file() for path in resolved)


@pytest.mark.parametrize('robot_id', ['pinky1', 'pinky2', 'pinky3'])
def test_legacy_launch_forwards_identity_and_options(robot_id):
    """기존 launch 이름에서도 로봇 ID·현장·LED 선택이 공통 launch로 전달된다."""
    launch = ET.parse(PKG / f'launch/{robot_id}_patrol.launch.xml').getroot()
    assert launch.findall('node') == []
    include = launch.find('include')
    assert include.attrib['file'].endswith('/launch/patrol.launch.xml')
    assert {a.attrib['name']: a.attrib['value'] for a in include.findall('arg')} == {
        'robot_id': robot_id, 'site': '$(var site)', 'start_led': '$(var start_led)'}


def test_package_installs_nested_profiles_and_shared_entrypoint(monkeypatch):
    """설치본에서도 공통 launch가 모든 설정과 단일 실행기를 찾을 수 있다."""
    registered = {}
    monkeypatch.chdir(PKG)
    monkeypatch.setattr(setuptools, 'setup', lambda **kwargs: registered.update(kwargs))
    runpy.run_path(str(PKG / 'setup.py'))
    installed = {str(Path(destination) / Path(source).name)
                 for destination, sources in registered['data_files'] for source in sources}
    for relative in ('common.yaml', 'sites/lab.yaml', 'robots/pinky1.yaml',
                     'robots/pinky2.yaml', 'robots/pinky3.yaml'):
        assert f'share/cobot_pinky_patrol/config/{relative}' in installed
    assert 'share/cobot_pinky_patrol/launch/patrol.launch.xml' in installed
    entries = dict(entry.split(' = ') for entry in registered['entry_points']['console_scripts'])
    assert entries['robot_startup'] == 'cobot_pinky_patrol.robot_startup:main'
    for name in ('pinky_patrol_node', 'pinky_patrol_node_pinky1',
                 'pinky_patrol_node_pinky2', 'pinky_patrol_node_pinky3'):
        assert entries[name] == 'cobot_pinky_patrol.pinky_patrol_node:main'
