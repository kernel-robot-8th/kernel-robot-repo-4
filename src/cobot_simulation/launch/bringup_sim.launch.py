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
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory('cobot_simulation')
    default_config = os.path.join(pkg_dir, 'config', 'sim_params.yaml')

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

    return LaunchDescription([
        rate_arg,
        tf_arg,
        lidar_arg,
        pinky_arg,
        config_arg,
        sim_node,
    ])
