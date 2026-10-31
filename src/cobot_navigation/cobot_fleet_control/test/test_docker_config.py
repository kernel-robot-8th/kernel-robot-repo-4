"""데몬 없이 배포 설정과 실행 스크립트의 데이터 보존·인자 전달 계약을 검증한다."""

import json
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[1] / 'config/docker'


def test_compose_uses_one_image_and_persistent_db():
    """세 관제 서비스는 같은 코드 이미지와 기존 ROS 도메인을 사용한다."""
    config = yaml.safe_load((CONFIG / 'compose.yaml').read_text())
    services = config['services']
    for name in ('fleet', 'bridge', 'zone-manager'):
        assert services[name]['image'] == config['x-runtime']['image']
        assert services[name]['network_mode'] == 'host'
        assert services[name]['environment']['ROS_DOMAIN_ID'] == '100'
    assert services['fleet']['volumes'] == ['fleet-data:/var/lib/cobot']
    assert 'db_path:=/var/lib/cobot/fleet_control.sqlite3' in services['fleet']['command']
    assert services['broker']['profiles'] == ['local-broker']
    assert 'ports' not in services['broker']


def test_python_and_base_versions_are_pinned():
    """직접·하위 Python 의존성과 두 베이스 이미지의 digest가 비어 있지 않다."""
    lock = (CONFIG / 'requirements.lock').read_text()
    packages = {}
    for line in lock.splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-z_-]+)==([0-9.]+) --hash=sha256:([a-f0-9]{64})', line)
        assert match, line
        packages[match[1]] = match[2]
    assert packages == {'pip': '25.0.1', 'setuptools': '75.8.0', 'py-trees': '2.2.3',
                        'paho-mqtt': '2.1.0', 'pydot': '2.0.0', 'pyparsing': '3.1.4'}
    lines = (CONFIG / 'versions.env').read_text().splitlines()
    versions = dict(line.split('=', 1) for line in lines
                    if line and not line.startswith('#'))
    for name in ('ROS_BASE_IMAGE', 'MOSQUITTO_IMAGE'):
        assert re.search(r'@sha256:[a-f0-9]{64}$', versions[name])
    dockerfile = (CONFIG / 'Dockerfile').read_text()
    assert 'ARG ROS_BASE_IMAGE=' + versions['ROS_BASE_IMAGE'] in dockerfile
    assert '--require-hashes' in dockerfile
    assert '--symlink-install' not in dockerfile
    assert 'USER cobot' in dockerfile


@pytest.fixture
def runner(tmp_path):
    """Docker 실행을 기록만 하는 대체 CLI. 컨테이너·네트워크는 켜지 않는다."""
    binary = tmp_path / 'docker'
    log = tmp_path / 'calls.jsonl'
    binary.write_text("""#!/usr/bin/python3
import json
import os
import sys
with open(os.environ['FAKE_DOCKER_LOG'], 'a') as stream:
    stream.write(json.dumps({'args': sys.argv[1:],
                             'revision': os.environ.get('COBOT_SOURCE_REVISION'),
                             'dirty': os.environ.get('COBOT_SOURCE_DIRTY')}) + '\\n')
""")
    binary.chmod(0o755)
    environment = {'PATH': str(tmp_path) + os.pathsep + os.defpath,
                   'FAKE_DOCKER_LOG': str(log)}

    def run(*args):
        result = subprocess.run(['/bin/bash', str(CONFIG / 'fleet_docker.sh'), *args],
                                env=environment, capture_output=True, text=True, check=False)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return run


def test_build_only_builds_and_labels_source(runner):
    result, calls = runner('build')
    assert result.returncode == 0
    assert calls[-1]['args'][-2:] == ['build', 'fleet']
    assert calls[-1]['dirty'] in ('true', 'false')
    assert calls[-1]['revision']
    assert not any('up' in call['args'] for call in calls)


def test_down_preserves_volumes_by_default(runner):
    result, calls = runner('down')
    assert result.returncode == 0
    assert calls[-1]['args'][-1] == 'down'
    assert '-v' not in calls[-1]['args'] and '--volumes' not in calls[-1]['args']


def test_optional_broker_is_explicit(runner):
    result, calls = runner('up-local')
    assert result.returncode == 0
    assert calls[-1]['args'][-5:] == ['-d', 'broker', 'bridge', 'zone-manager', 'fleet']
    assert '--profile' in calls[-1]['args']


def test_trace_export_sources_ros_environment_and_quotes_id(runner):
    result, calls = runner('export-bt', 'job-001')
    assert result.returncode == 0
    args = calls[-1]['args']
    assert '/opt/cobot/entrypoint.sh' in args
    assert args[-2:] == ['bash', 'job-001']
    assert '--command-id "$1"' in args[-3]


def test_trace_export_rejects_shell_input(runner):
    result, calls = runner('export-bt', 'job;invalid')
    assert result.returncode == 2
    assert not any('exec' in call['args'] for call in calls)
