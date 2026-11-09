"""별도 control-center 패키지의 HTTP·WebSocket 서버를 fleet과 함께 기동한다."""

import argparse
import os
from pathlib import Path
import shlex
import signal

from .fleet_startup import FleetStartup
from .web_profiles import export_profiles, load_profiles, read_parameters


def build_plan(navigation_root, control_center_share, output_dir, site='lab',
               host='127.0.0.1', port=8080, start_fleet=True):
    """웹 코드를 복제하지 않고 기존 관제 패키지의 실행 설정을 재사용한다."""
    root, share = Path(navigation_root).resolve(), Path(control_center_share).resolve()
    for name in ('fleet_api.launch.xml', 'fleet_status.launch.xml'):
        if not (share / 'launch' / name).is_file():
            raise ValueError('feature/control-center의 cobot_control_center를 먼저 빌드·source하세요')
    if not isinstance(host, str) or not host or any(c.isspace() for c in host):
        raise ValueError('웹 host 형식 오류')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('웹 port 범위는 1~65535')
    config_dir = root / 'cobot_pinky_patrol/config'
    robots = read_parameters(root / 'cobot_fleet_control/config/fleet_control.yaml')['robot_ids']
    zone_params = root / 'cobot_zone_traffic_control/config/zone_params.yaml'
    if set(read_parameters(zone_params)['robot_ids']) != set(robots):
        raise ValueError('fleet과 zone_manager의 로봇 목록을 일치시키세요')
    load_profiles(config_dir, site, robots)
    map_yaml = root / 'map_view_pc/maps/cobot_map_v9.yaml'
    if not map_yaml.is_file():
        raise ValueError('현재 지도 YAML이 없습니다')
    commands = []
    if start_fleet:
        commands.append(('fleet', [
            'ros2', 'launch', 'cobot_fleet_control', 'fleet_control.launch.xml',
            f'patrol_config_dir:={config_dir}', f'site:={site}']))
    commands.extend([
        ('web-status', ['ros2', 'launch', 'cobot_control_center', 'fleet_status.launch.xml']),
        ('web-api', ['ros2', 'launch', 'cobot_control_center', 'fleet_api.launch.xml',
                     f'host:={host}', f'port:={port}', f'map_yaml:={map_yaml}',
                     f'points_dir:={Path(output_dir).resolve()}', f'zone_params:={zone_params}']),
    ])
    return commands, config_dir, robots


def run_web(plan, config_dir, robots, site, output_dir, runner=None):
    """지점 내보내기가 끝난 뒤 실행하며 자신이 시작한 프로세스만 정리한다."""
    export_profiles(config_dir, site, robots, output_dir)
    runner = runner or FleetStartup()
    try:
        for name, command in plan:
            runner.start(name, command)
        while True:
            runner.pump()
    finally:
        runner.close()


def main(args=None):
    """기본은 읽기 전용 미리보기; 실제 기동은 웹·상태 노드와 선택적 fleet_control_node를 띄운다."""
    parser = argparse.ArgumentParser(description='control-center 웹 + fleet 실행 경로')
    parser.add_argument('--navigation-root', required=True,
                        help='src/cobot_navigation 절대 경로')
    parser.add_argument('--control-center-share', help='미리보기·검증용 upstream share 경로')
    parser.add_argument('--output-dir', default='~/.cache/cobot/control_center_profiles')
    parser.add_argument('--site', default='lab')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--mode', choices=('preview', 'execute'), default='preview')
    parser.add_argument('--fleet', choices=('start', 'existing'), default='start')
    options = parser.parse_args(args)
    output = Path(options.output_dir).expanduser().resolve()
    try:
        share = options.control_center_share
        if not share:
            from ament_index_python.packages import get_package_share_directory
            share = get_package_share_directory('cobot_control_center')
        plan, config_dir, robots = build_plan(
            options.navigation_root, share, output, options.site, options.host,
            options.port, options.fleet == 'start')
        if options.mode == 'preview':
            print(f'웹용 지점 프로필: {output} (실행 시 생성)')
            for name, command in plan:
                print(f'{name}: {shlex.join(command)}')
            print('미리보기 완료: 서버·로봇·파일 생성을 실행하지 않았습니다.')
            return
        if os.name != 'posix' or os.environ.get('ROS_DOMAIN_ID') != '100':
            raise ValueError('Linux 관제 PC에서 기존 ROS_DOMAIN_ID=100 환경을 source하세요')

        def stop(signum, frame):
            raise KeyboardInterrupt

        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, stop)
        run_web(plan, config_dir, robots, options.site, output)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, ImportError, LookupError) as error:
        parser.exit(1, f'웹 관제 기동 실패: {error}\n')


if __name__ == '__main__':
    main()
