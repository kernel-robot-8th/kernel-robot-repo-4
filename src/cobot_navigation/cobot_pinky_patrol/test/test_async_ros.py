"""단일 executor의 실제 Nav2 액션·라이프사이클·토픽 콜백을 격리 검증한다."""

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
import yaml

ISOLATED = (os.environ.get('ROS_DOMAIN_ID') == '77'
            and os.environ.get('ROS_LOCALHOST_ONLY') == '1')
pytestmark = pytest.mark.skipif(not ISOLATED, reason='격리 도메인 77·localhost에서만 실행')


@pytest.fixture
def ros_env(tmp_path, monkeypatch):
    """가짜 Nav2 서버도 작업 스레드 없이 같은 executor에서 실행한다."""
    from lifecycle_msgs.srv import GetState
    from nav2_msgs.action import NavigateToPose
    import rclpy
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.task import Future
    from std_msgs.msg import String

    from cobot_pinky_patrol.pinky_patrol_node import PinkyPatrolNode

    config_file = Path(__file__).resolve().parents[1] / 'config/pinky1.yaml'
    config = yaml.safe_load(config_file.read_text())
    params = config['pinky_patrol_node']['ros__parameters']
    params.update(restore_pose=False, idle_return_sec=0.0, tick_sec=0.01,
                  pose_file=str(tmp_path / 'pose.json'))
    param_file = tmp_path / 'params.yaml'
    param_file.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(PinkyPatrolNode, '_create_led_client',
                        lambda self: SimpleNamespace(service_is_ready=lambda: False))
    rclpy.init(args=['--ros-args', '--params-file', str(param_file)])
    hardware = Node('fake_nav2')
    jobs, goals, events = [], [], []
    options = {'travel': 0.03, 'allow_cancel': True, 'reject': False, 'fail': False}

    async def execute(handle):
        future = Future()
        jobs.append((handle, future, time.monotonic() + options['travel']))
        return await future

    def advance():
        for handle, future, deadline in list(jobs):
            if future.done():
                continue
            if handle.is_cancel_requested:
                handle.canceled()
                future.set_result(NavigateToPose.Result())
            elif time.monotonic() >= deadline:
                if options['fail']:
                    handle.abort()
                else:
                    handle.succeed()
                future.set_result(NavigateToPose.Result())

    def goal_callback(goal):
        goals.append(goal)
        return GoalResponse.REJECT if options['reject'] else GoalResponse.ACCEPT

    action = ActionServer(
        hardware, NavigateToPose, 'navigate_to_pose', execute_callback=execute,
        goal_callback=goal_callback,
        cancel_callback=lambda handle: (CancelResponse.ACCEPT if options['allow_cancel']
                                        else CancelResponse.REJECT))
    timer = hardware.create_timer(0.01, advance)

    def active(request, response):
        response.current_state.id = 3
        return response

    services = [hardware.create_service(GetState, name + '/get_state', active)
                for name in ('amcl', 'bt_navigator')]
    robot = PinkyPatrolNode()
    command_pub = hardware.create_publisher(String, 'patrol_cmd', 10)
    subscription = hardware.create_subscription(
        String, 'patrol_status', lambda msg: events.append(json.loads(msg.data)), 10)
    executor = SingleThreadedExecutor()
    executor.add_node(hardware)
    executor.add_node(robot)

    def pump(condition, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)
            if condition():
                return True
        return False

    def send(command_id, command):
        command_pub.publish(String(data=json.dumps(
            {'command_id': command_id, 'command': command})))

    try:
        assert pump(lambda: command_pub.get_subscription_count() > 0)
        yield SimpleNamespace(robot=robot, hardware=hardware, executor=executor, goals=goals,
                              events=events, send=send, pump=pump, options=options,
                              String=String, timer=timer, services=services,
                              subscription=subscription)
    finally:
        robot.close()
        executor.shutdown()
        action.destroy()
        robot.destroy_node()
        hardware.destroy_node()
        rclpy.shutdown()


def terminal(env, command_id):
    return [e for e in env.events if e.get('command_id') == command_id
            and e.get('task_finished')]


def test_real_action_callbacks_complete_without_workers(ros_env):
    """목표 접수·결과 콜백이 같은 executor에서 실행되고 ID가 유지된다."""
    env = ros_env
    env.send('ros-job', 'goto:P1,P2')
    assert env.pump(lambda: terminal(env, 'ros-job'))
    assert terminal(env, 'ros-job')[-1]['state'] == 'DONE'
    assert len(env.goals) == 2
    assert not env.robot.controller.busy


def test_stop_is_processed_during_action_and_no_next_waypoint(ros_env):
    """이동 중에도 명령 콜백이 실행되고 취소 후 다음 지점으로 가지 않는다."""
    env = ros_env
    env.options['travel'] = 5
    env.send('ros-stop', 'goto:P1,P2')
    assert env.pump(lambda: env.robot.navigation._handle is not None)
    env.send('stop-request', 'stop')
    assert env.pump(lambda: terminal(env, 'ros-stop'))
    assert terminal(env, 'ros-stop')[-1]['state'] == 'STOPPED'
    assert len(env.goals) == 1


def test_cancel_rejection_keeps_busy_until_original_action_ends(ros_env):
    """취소 거절 후에도 콜백이 동작하며 원래 액션 종료 전 새 목표를 막는다."""
    env = ros_env
    env.options.update(travel=0.8, allow_cancel=False)
    env.send('ros-reject-cancel', 'goto:P1,P2')
    assert env.pump(lambda: env.robot.navigation._handle is not None)
    env.send('stop-request', 'stop')
    assert env.pump(lambda: bool(env.robot.navigation.fault))
    assert env.robot.controller.busy and not terminal(env, 'ros-reject-cancel')
    env.send('ros-other', 'home')
    assert env.pump(lambda: terminal(env, 'ros-other'))
    assert terminal(env, 'ros-other')[-1]['detail'] == 'robot busy'
    assert env.pump(lambda: terminal(env, 'ros-reject-cancel'))
    assert terminal(env, 'ros-reject-cancel')[-1]['state'] == 'STOPPED'
    assert len(env.goals) == 1


def test_real_goal_rejection_retries_and_finishes(ros_env):
    env = ros_env
    env.options['reject'] = True
    env.send('ros-rejected', 'goto:P1')
    assert env.pump(lambda: terminal(env, 'ros-rejected'))
    assert terminal(env, 'ros-rejected')[-1]['state'] == 'FAILED'
    assert len(env.goals) == 3


def test_zone_grant_and_exit_with_real_topics(ros_env):
    """구역 허가도 같은 executor에서 수신하고 출구 도착 뒤에만 반납한다."""
    env = ros_env
    from cobot_zone_traffic_control.zone_manager_node import ZoneManagerNode

    manager = ZoneManagerNode()
    env.executor.add_node(manager)
    try:
        env.send('ros-zone', 'zone:ZA')
        assert env.pump(lambda: terminal(env, 'ros-zone'))
        assert terminal(env, 'ros-zone')[-1]['state'] == 'DONE'
        assert env.robot.controller.held_zone == 'A'
        assert len(env.goals) == 1
        env.send('ros-leave', 'leave')
        assert env.pump(lambda: terminal(env, 'ros-leave'))
        assert env.robot.controller.held_zone is None
        assert len(env.goals) == 2
    finally:
        env.executor.remove_node(manager)
        manager.destroy_node()


def test_initial_rotation_is_timer_driven_and_stop_interrupts_it(ros_env):
    """초기 회전 중에도 정지 콜백이 실행되고 Nav2 목표가 생기지 않는다."""
    from geometry_msgs.msg import PoseWithCovarianceStamped, Twist

    env = ros_env
    poses, velocities = [], []
    pose_sub = env.hardware.create_subscription(
        PoseWithCovarianceStamped, 'initialpose', poses.append, 10)
    velocity_sub = env.hardware.create_subscription(
        Twist, 'cmd_vel', lambda msg: velocities.append(msg.angular.z), 10)
    env.robot._saved_pose = (1, 2, 0)
    env.robot._pose_initialized = False
    env.robot.config['initialpose_settle_sec'] = 0.01
    env.robot.config['initial_rotation_sec'] = 3.0
    try:
        assert env.pump(lambda: env.robot.initial_pub.get_subscription_count() > 0)
        env.send('ros-initialization', 'goto:P1')
        assert env.pump(lambda: any(v != 0 for v in velocities))
        env.send('stop-request', 'emergency_stop')
        assert env.pump(lambda: terminal(env, 'ros-initialization'))
        assert terminal(env, 'ros-initialization')[-1]['state'] == 'STOPPED'
        assert env.pump(lambda: velocities[-1] == 0)
        assert poses and not env.goals
        assert not env.robot._pose_initialized
    finally:
        env.hardware.destroy_subscription(pose_sub)
        env.hardware.destroy_subscription(velocity_sub)


def test_led_response_never_blocks_navigation(ros_env, monkeypatch):
    """LED 응답이 영구 지연되어도 주행과 정지 콜백은 계속 실행된다."""
    from rclpy.task import Future

    import cobot_pinky_patrol.pinky_patrol_node as module

    env = ros_env
    calls = []
    monkeypatch.setattr(module, 'SetLed', SimpleNamespace(Request=SimpleNamespace))
    env.robot.led_cli = SimpleNamespace(
        service_is_ready=lambda: True,
        call_async=lambda request: calls.append(request) or Future())
    env.send('ros-led', 'goto:P1')
    assert env.pump(lambda: terminal(env, 'ros-led'))
    assert terminal(env, 'ros-led')[-1]['state'] == 'DONE'
    assert len(calls) == 1
    assert env.robot._led_future is not None
