import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    pkg_pinky_description = get_package_share_directory('pinky_description')
    rviz_config_path = os.path.join(pkg_pinky_description, 'rviz', 'pinky_16fleet.rviz')

    # 1. upload_robot.launch.py (Pinky Robot State Publisher)
    upload_robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_pinky_description, 'launch', 'upload_robot.launch.py')
        ),
        launch_arguments={'is_sim': 'true'}.items()
    )

    # 2. RViz2 3D 관제
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config_path]
    )

    # 3. Domain 1 회전 8마리 노드
    domain1_node = Node(
        package='pinky_description',
        executable='26_pinky_domain1_turtles.py',
        name='pinky_domain1_manager',
        output='screen'
    )

    # 4. Domain 7 십자 수렴 2마리 노드
    domain7_node = Node(
        package='pinky_description',
        executable='26_pinky_domain7_turtles.py',
        name='pinky_domain7_manager',
        output='screen'
    )

    # 5. Domain 8 대각 수렴 2마리 노드
    domain8_node = Node(
        package='pinky_description',
        executable='26_pinky_domain8_turtles.py',
        name='pinky_domain8_manager',
        output='screen'
    )

    # 6. Domain 9 원점 수렴 2마리 노드
    domain9_node = Node(
        package='pinky_description',
        executable='26_pinky_domain9_turtles.py',
        name='pinky_domain9_manager',
        output='screen'
    )

    # 7. Domain 0 중앙 관제 오라클 & 7대 3D RViz 마커 노드
    oracle_node = Node(
        package='pinky_description',
        executable='26_pinky_central_oracle_monitor.py',
        name='central_26_pinky_oracle_monitor',
        output='screen'
    )

    # 8. 목표 지정 인터랙티브 GUI 클릭 창 노드
    gui_dispatcher_node = Node(
        package='pinky_description',
        executable='26_pinky_ui_goal_dispatcher_gui.py',
        name='pinky_ui_goal_dispatcher',
        output='screen'
    )

    return LaunchDescription([
        upload_robot_launch,
        rviz_node,
        domain1_node,
        domain7_node,
        domain8_node,
        domain9_node,
        oracle_node,
        gui_dispatcher_node
    ])
