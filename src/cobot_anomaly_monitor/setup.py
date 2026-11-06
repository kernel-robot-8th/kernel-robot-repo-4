"""이상 감지 관제 패키지 등록."""
from glob import glob

from setuptools import find_packages, setup

setup(
    name='cobot_anomaly_monitor', version='0.1.0', packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/cobot_anomaly_monitor']),
        ('share/cobot_anomaly_monitor', ['package.xml']),
        ('share/cobot_anomaly_monitor/config', glob('config/*.yaml')),
        ('share/cobot_anomaly_monitor/launch', glob('launch/*.launch.xml')),
    ],
    install_requires=['setuptools'],
    maintainer='강건한', maintainer_email='rkd1rjs2@gmail.com',
    description='Scenario records, CCTV judgment and manual work adapter for the relay laptop',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'monitor_node = cobot_anomaly_monitor.monitor_node:main']},
)
