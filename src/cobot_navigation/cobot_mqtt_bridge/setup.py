from glob import glob

from setuptools import find_packages, setup

package_name = 'cobot_mqtt_bridge'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml') + glob('config/*.service')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.xml')),
    ],
    install_requires=['setuptools', 'pyyaml'],
    zip_safe=True,
    maintainer='김진호',
    maintainer_email='cdwlsgh1@gmail.com',
    description='cobot_domain_bridge 와 병행해서 쓰는 MQTT 토픽 중계',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'mqtt_bridge_node = cobot_mqtt_bridge.mqtt_bridge_node:main',
        ],
    },
)
