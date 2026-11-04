import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_pinky_description = get_package_share_directory('pinky_description')

    # 1. RViz2 설정 파일 경로
    rviz_config_path = os.path.join(pkg_pinky_description, 'rviz', 'view_robot.rviz')

    # 2. upload_robot.launch.py 포함 (robot_state_publisher + joint_state_publisher 자동 구동)
    upload_robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_pinky_description, 'launch', 'upload_robot.launch.py')
        ),
        launch_arguments={'is_sim': 'true'}.items()
    )

    # 3. RViz2 노드 (미리 저장된 .rviz 로드)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config_path]
    )

    # 4. 26번 Pinky FSM 제어기 노드
    fsm_controller_node = Node(
        package='pinky_description',
        executable='26_pinky_fsm_controller.py',
        name='pinky_fsm_controller',
        output='screen'
    )

    # 5. 26번 Pinky FSM 실시간 Plot 모니터 노드
    fsm_monitor_node = Node(
        package='pinky_description',
        executable='26_pinky_fsm_monitor.py',
        name='pinky_fsm_monitor',
        output='screen'
    )

    return LaunchDescription([
        upload_robot_launch,
        rviz_node,
        fsm_controller_node,
        fsm_monitor_node
    ])
