"""데몬 없이 배포 설정과 실행 스크립트의 데이터 보존·인자 전달 계약을 검증한다."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import yaml

CONFIG = Path(__file__).resolve().parents[1] / 'config/docker'


def test_compose_uses_one_image_and_persistent_db():
    """웹과 세 관제 서비스는 같은 코드 이미지와 기존 ROS 도메인을 사용한다."""
    config = yaml.safe_load((CONFIG / 'compose.yaml').read_text())
    services = config['services']
    for name in ('fleet', 'bridge', 'zone-manager', 'web'):
        assert services[name]['image'] == config['x-runtime']['image']
        assert services[name]['network_mode'] == 'host'
        assert services[name]['environment']['ROS_DOMAIN_ID'] == '100'
        assert services[name]['environment']['CYCLONEDDS_URI'] == (
            '${COBOT_CYCLONEDDS_URI:-file:///opt/cobot/cyclonedds.xml}')
    # 로봇별 브릿지는 환경변수로 끌 수 있고, 값을 주지 않으면 셋 다 연결한다.
    for robot in ('pinky1', 'pinky2', 'pinky3'):
        assert (f'{robot}:=${{COBOT_{robot.upper()}:-true}}'
                in services['bridge']['command'])
    assert services['fleet']['volumes'] == ['fleet-data:/var/lib/cobot']
    assert 'db_path:=/var/lib/cobot/fleet_control.sqlite3' in services['fleet']['command']
    assert 'broker' not in services
    assert services['web']['depends_on'] == {'fleet': {'condition': 'service_started'}}
    assert 'fleet:=existing' in services['web']['command']
    assert 'mode:=execute' in services['web']['command']
    assert ('patrol_config_dir:=/opt/cobot_ws/src/cobot_pinky_patrol/config'
            in services['fleet']['command'])
    # 웹 기동기가 중앙 실행기·구역 매니저·브릿지를 추가로 띄우지 않는다.
    assert 'fleet:=start' not in services['web']['command']
    assert services['web']['healthcheck']['test'][0] == 'CMD'
    assert '/api/health' in services['web']['healthcheck']['test'][-1]


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
                        'pydot': '2.0.0', 'pyparsing': '3.1.4'}
    lines = (CONFIG / 'versions.env').read_text().splitlines()
    versions = dict(line.split('=', 1) for line in lines
                    if line and not line.startswith('#'))
    for name in ('ROS_BASE_IMAGE',):
        assert re.search(r'@sha256:[a-f0-9]{64}$', versions[name])
    dockerfile = (CONFIG / 'Dockerfile').read_text()
    assert 'ARG ROS_BASE_IMAGE=' + versions['ROS_BASE_IMAGE'] in dockerfile
    assert '--require-hashes' in dockerfile
    assert '--symlink-install' not in dockerfile
    assert 'USER cobot' in dockerfile
    # 웹 패키지도 체크아웃 하나에서 빌드한다. 별도 고정 커밋을 두지 않는다.
    assert 'CONTROL_CENTER_REVISION' not in dockerfile
    assert 'python3-fastapi python3-uvicorn' in dockerfile
    assert 'src/cobot_patrol_interfaces' in dockerfile


@pytest.fixture
def runner(tmp_path):
    """Docker 실행을 기록만 하는 대체 CLI. 컨테이너·네트워크는 켜지 않는다."""
    repo = tmp_path / 'repo'
    config = repo / 'src/cobot_navigation/cobot_fleet_control/config/docker'
    shutil.copytree(CONFIG, config)
    for name in ('cobot_control_center', 'cobot_patrol_interfaces'):
        package = repo / 'src' / name
        package.mkdir(parents=True)
        (package / 'original.txt').write_text('committed source\n')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(
        ['git', '-C', str(repo), '-c', 'user.name=Deployment Test',
         '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    # 커밋 뒤에 고친 웹 파일: 이미지에는 작업 트리 내용이 들어가야 한다.
    (repo / 'src/cobot_control_center/original.txt').write_text('working tree edit\n')
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
        result = subprocess.run(['/bin/bash', str(config / 'fleet_docker.sh'), *args],
                                env=environment, capture_output=True, text=True, check=False)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    run.staged_dir = repo / 'src/cobot_navigation/.docker-context/control-center'
    return run


def test_build_only_builds_and_labels_source(runner):
    """빌드는 같은 체크아웃의 웹 원본을 준비하고 버전을 기록하며 서비스를 시작하지 않는다."""
    result, calls = runner('build')
    assert result.returncode == 0
    assert calls[-1]['args'][-2:] == ['build', 'fleet']
    # 커밋 안 한 웹 수정도 이미지에 들어가므로 dirty 로 남긴다.
    assert calls[-1]['dirty'] == 'true'
    assert calls[-1]['revision']
    assert not any('up' in call['args'] for call in calls)
    assert not (runner.staged_dir / 'revision.txt').exists()
    staged = runner.staged_dir / 'src'
    assert (staged / 'cobot_control_center/original.txt').read_text() == 'working tree edit\n'
    assert (staged / 'cobot_patrol_interfaces/original.txt').read_text() == 'committed source\n'


def test_down_preserves_volumes_by_default(runner):
    """종료 시 실행 원장 볼륨을 유지한다."""
    result, calls = runner('down')
    assert result.returncode == 0
    assert calls[-1]['args'][-1] == 'down'
    assert '-v' not in calls[-1]['args'] and '--volumes' not in calls[-1]['args']


def test_up_starts_web_and_ros_execution_services(runner):
    """통합 기동에 웹과 세 ROS 서비스를 함께 포함한다."""
    result, calls = runner('up')
    assert result.returncode == 0
    assert calls[-1]['args'][-5:] == ['-d', 'bridge', 'zone-manager', 'fleet', 'web']
    assert 'broker' not in calls[-1]['args']


def test_image_check_does_not_start_dependencies_or_ros_nodes(runner):
    """이미지 검사는 의존 서비스를 띄우지 않고 미리보기만 실행한다."""
    result, calls = runner('check')
    assert result.returncode == 0
    args = calls[-1]['args']
    assert args[args.index('run'):args.index('run') + 5] == [
        'run', '--rm', '--no-deps', 'web', '/opt/cobot/entrypoint.sh']
    assert '--mode preview --fleet existing' in args[-1]
    assert not any('up' in call['args'] for call in calls)


def test_smoke_isolates_network_and_does_not_mount_operational_data(runner):
    """실제 기동 검사는 외부 통신과 운영 원장을 연결하지 않는 임시 컨테이너를 쓴다."""
    result, calls = runner('smoke')
    assert result.returncode == 0
    args = calls[-1]['args']
    assert args[:3] == ['run', '--rm', '--init']
    assert args[args.index('--network') + 1] == 'none'
    assert args[args.index('--cap-drop') + 1] == 'ALL'
    assert 'ROS_DOMAIN_ID=77' in args
    assert 'ROS_LOCALHOST_ONLY=1' in args
    assert 'ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST' in args
    assert not any(arg.startswith('CYCLONEDDS_URI=') for arg in args)
    assert args[-2:] == ['python', '/opt/cobot/smoke_check.py']
    assert not any(arg in args for arg in ('--volume', '-v', '--mount', '--publish', '-p'))
    assert not any('up' in call['args'] for call in calls)


def test_host_installer_help_does_not_install_packages():
    """설치기 도움말은 시스템 변경 없이 읽을 수 있다."""
    result = subprocess.run(['bash', str(CONFIG / 'install_host.sh'), '--help'],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert '--check' in result.stdout


def test_trace_export_sources_ros_environment_and_quotes_id(runner):
    """조회 명령은 ROS 환경을 읽고 ID를 쉘 코드와 분리한다."""
    result, calls = runner('export-bt', 'job-001')
    assert result.returncode == 0
    args = calls[-1]['args']
    assert '/opt/cobot/entrypoint.sh' in args
    assert args[-2:] == ['bash', 'job-001']
    assert '--command-id "$1"' in args[-3]


def test_trace_export_rejects_shell_input(runner):
    """명령 ID에 쉘 구문이 들어오면 실행 전에 거절한다."""
    result, calls = runner('export-bt', 'job;invalid')
    assert result.returncode == 2
    assert not any('exec' in call['args'] for call in calls)


def test_live_viewer_reads_running_container_journal(runner):
    """뷰어는 새 실행기를 띄우지 않고 현재 원장을 조회한다."""
    result, calls = runner('view-bt')
    assert result.returncode == 0
    assert calls[-1]['args'][-6:] == [
        'ros2', 'run', 'cobot_fleet_control', 'fleet_bt_viewer',
        '--db', '/var/lib/cobot/fleet_control.sqlite3']
    assert not any('up' in call['args'] or 'run' == call['args'][0] for call in calls)


def test_direct_database_recovery_command_is_removed(runner):
    """DB 직접 수정으로 작업 보류를 해제하는 명령을 허용하지 않는다."""
    result, calls = runner('resolve-unknown', 'job-001')
    assert result.returncode == 2
    assert not any('exec' in call['args'] for call in calls)
