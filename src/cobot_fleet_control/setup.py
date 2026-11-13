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
        ('share/cobot_fleet_control/docs', glob('docs/*.html')),
    ],
    install_requires=['setuptools', 'py_trees==2.2.3'],
    maintainer='김지혜 (로봇 수행 관제)', maintainer_email='cobot@example.com',
    description='Pinky 주문별 전체 시나리오 BT·주행 BT와 실시간 관측 도구',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'fleet_control_node = cobot_fleet_control.fleet_control_node:main',
        'fleet_startup = cobot_fleet_control.fleet_startup:main',
        'control_center_web = cobot_fleet_control.control_center_web:main',
        'fleet_bt_viewer = cobot_fleet_control.bt_viewer:main',
        'fleet_bt_trace = cobot_fleet_control.bt_visualization:main']},
)
