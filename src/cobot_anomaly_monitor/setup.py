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
        'audit_site_map = cobot_anomaly_monitor.site_audit:main',
        'monitor_node = cobot_anomaly_monitor.monitor_node:main',
        'replay_zone_evidence = cobot_anomaly_monitor.replay_evidence:main',
        'sim_link_probe = cobot_anomaly_monitor.sim_link_probe:main',
        'mqtt_zone_evidence = cobot_anomaly_monitor.mqtt_evidence:main',
        'pixel_event_node = cobot_anomaly_monitor.pixel_event_node:main',
        'build_camera_calibration = cobot_anomaly_monitor.pixel_map:main']},
)
