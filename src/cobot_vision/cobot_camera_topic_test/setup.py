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

"""Install camera communication nodes, launch configuration and documentation."""

from glob import glob

from setuptools import find_packages, setup


setup(
    name='cobot_camera_topic_test',
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/cobot_camera_topic_test']),
        ('share/cobot_camera_topic_test', ['package.xml', 'README.md']),
        ('share/cobot_camera_topic_test/launch', glob('launch/*.launch.xml')),
        ('share/cobot_camera_topic_test/config', glob('config/*.yaml')),
        ('share/cobot_camera_topic_test/rviz', glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    extras_require={'test': ['pytest']},
    zip_safe=True,
    maintainer='Pinky Team4 vision',
    maintainer_email='vision@example.com',
    description='Pinky Pro Best Effort JPEG and raw camera topic test',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'camera_publisher = cobot_camera_topic_test.camera_publisher_node:main',
        'camera_subscriber = cobot_camera_topic_test.camera_subscriber_node:main',
    ]},
)
