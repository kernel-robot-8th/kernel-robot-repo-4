import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'cobot_amcl_corrector'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.xml')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='your_name',
    maintainer_email='you@example.com',
    description='항공뷰(Overhead Camera) 및 태블릿 PoseFix 기반 다중 로봇 AMCL 위치 보정 패키지',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'amcl_corrector_node = cobot_amcl_corrector.amcl_corrector_node:main',
        ],
    },
)
