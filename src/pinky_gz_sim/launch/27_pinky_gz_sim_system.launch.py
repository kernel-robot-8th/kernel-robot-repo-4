import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():
    pinky_gz_sim_dir = get_package_share_directory('pinky_gz_sim')

    namespace_arg = DeclareLaunchArgument('namespace', default_value='', description='Namespace for robot')
    world_name_arg = DeclareLaunchArgument('world_name', default_value='pinky_factory.world', description='Gazebo World Name')
    cam_tilt_arg = DeclareLaunchArgument('cam_tilt_deg', default_value='0', description='Camera tilt angle in degrees')

    # 1. Main XML launch inclusion (Gazebo Sim 3D Server, Client, Robot Spawn, ROS-GZ Bridge, Image Bridge)
    launch_sim_xml = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(pinky_gz_sim_dir, 'launch', 'launch_sim.launch.xml')
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('namespace'),
            'world_name': LaunchConfiguration('world_name'),
            'cam_tilt_deg': LaunchConfiguration('cam_tilt_deg')
        }.items()
    )

    # 2. RViz2 Node with Pre-configured Layout (Fixed Frame: base_footprint, RobotModel, LaserScan, Image)
    rviz_config_path = os.path.join(pinky_gz_sim_dir, 'rviz', '27_pinky_gz.rviz')
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config_path],
        parameters=[{'use_sim_time': True}]
    )

    # 3. Teleop Keyboard Controller (Runs in dedicated Gnome-Terminal window)
    teleop_node = Node(
        package='pinky_gz_sim',
        executable='27_pinky_gz_teleop_keyboard.py',
        name='pinky_gz_teleop_keyboard',
        output='screen',
        prefix=['gnome-terminal --'],
        parameters=[{'use_sim_time': True}]
    )

    # 4. Telemetry Monitor Node
    telemetry_monitor_node = Node(
        package='pinky_gz_sim',
        executable='27_pinky_gz_sim_telemetry_monitor.py',
        name='gz_telemetry_monitor',
        output='screen',
        parameters=[{'use_sim_time': True}]
    )

    return LaunchDescription([
        namespace_arg,
        world_name_arg,
        cam_tilt_arg,
        launch_sim_xml,
        rviz_node,
        teleop_node,
        telemetry_monitor_node
    ])
