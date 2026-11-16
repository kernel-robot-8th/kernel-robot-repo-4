# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('cobot_simulation')
    default_config = os.path.join(pkg_dir, 'config', 'sim_params.yaml')
    default_rviz = os.path.join(pkg_dir, 'rviz', 'cobot_fleet.rviz')

    try:
        bringup_dir = get_package_share_directory('cobot_bringup')
        default_map = os.path.join(bringup_dir, 'config', 'maps', 'map_shoe_store_1021_gate67.yaml')
    except Exception:
        default_map = os.path.expanduser(
            '~/kernel-robot-repo-4/src/cobot_bringup/config/maps/map_shoe_store_1021_gate67.yaml'
        )

    rate_arg = DeclareLaunchArgument(
        'rate_hz', default_value='50.0', description='Loop frequency (Hz)'
    )
    tf_arg = DeclareLaunchArgument(
        'publish_tf', default_value='true', description='Publish TF tree'
    )
    lidar_arg = DeclareLaunchArgument(
        'enable_lidar', default_value='true', description='Enable 2D planar LiDAR'
    )
    pinky_arg = DeclareLaunchArgument(
        'num_pinky', default_value='3', description='Number of Pinky robots'
    )
    config_arg = DeclareLaunchArgument(
        'config_file', default_value=default_config, description='Path to parameter YAML'
    )
    map_arg = DeclareLaunchArgument(
        'map', default_value=default_map, description='Path to official project map YAML'
    )
    use_map_server_arg = DeclareLaunchArgument(
        'use_map_server',
        default_value='true',
        description='Launch nav2_map_server for project official map',
    )
    rviz_arg = DeclareLaunchArgument(
        'rviz', default_value='false', description='Launch RViz2 visualizer'
    )
    rviz_config_arg = DeclareLaunchArgument(
        'rviz_config', default_value=default_rviz, description='Path to RViz configuration file'
    )

    map_server_node = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[{
            'yaml_filename': LaunchConfiguration('map'),
            'topic_name': 'map',
            'frame_id': 'map',
        }],
        condition=IfCondition(LaunchConfiguration('use_map_server')),
    )

    lifecycle_manager_node = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_map',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'autostart': True,
            'node_names': ['map_server'],
        }],
        condition=IfCondition(LaunchConfiguration('use_map_server')),
    )

    sim_node = Node(
        package='cobot_simulation',
        executable='arena_sim_node',
        name='arena_sim_node',
        output='screen',
        parameters=[
            LaunchConfiguration('config_file'),
            {
                'rate_hz': LaunchConfiguration('rate_hz'),
                'publish_tf': LaunchConfiguration('publish_tf'),
                'enable_lidar': LaunchConfiguration('enable_lidar'),
                'num_pinky': LaunchConfiguration('num_pinky'),
            },
        ],
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rviz_config')],
        condition=IfCondition(LaunchConfiguration('rviz')),
    )

    return LaunchDescription([
        rate_arg,
        tf_arg,
        lidar_arg,
        pinky_arg,
        config_arg,
        map_arg,
        use_map_server_arg,
        rviz_arg,
        rviz_config_arg,
        map_server_node,
        lifecycle_manager_node,
        sim_node,
        rviz_node,
    ])
