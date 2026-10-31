"""관제 BT 패키지 등록."""
from glob import glob

from setuptools import find_packages, setup

setup(
    name='cobot_fleet_control', version='0.1.0', packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/cobot_fleet_control']),
        ('share/cobot_fleet_control', ['package.xml']),
        ('share/cobot_fleet_control/config', glob('config/*.yaml')),
        ('share/cobot_fleet_control/launch', glob('launch/*.launch.xml')),
    ],
    install_requires=['setuptools', 'py_trees==2.2.3', 'paho-mqtt==2.1.0'],
    maintainer='cobot navigation team', maintainer_email='cobot@example.com',
    description='MQTT commands, persistent job events and Python behaviour trees for Pinky',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'fleet_control_node = cobot_fleet_control.fleet_control_node:main',
        'fleet_startup = cobot_fleet_control.fleet_startup:main',
        'fleet_bt_trace = cobot_fleet_control.bt_visualization:main',
        'fleet_resolve_unknown = cobot_fleet_control.resolve_unknown:main']},
)
