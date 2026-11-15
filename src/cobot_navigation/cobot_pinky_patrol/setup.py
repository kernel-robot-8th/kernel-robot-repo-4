from glob import glob

from setuptools import find_packages, setup

package_name = 'cobot_pinky_patrol'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # 설정의 하위 디렉터리도 같은 경로로 설치한다.
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/config/sites', glob('config/sites/*.yaml')),
        ('share/' + package_name + '/config/robots', glob('config/robots/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.xml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pinky',
    maintainer_email='pinky@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'robot_startup = cobot_pinky_patrol.robot_startup:main',
            'pinky_patrol_node = cobot_pinky_patrol.pinky_patrol_node:main',
            # 기존 실행 이름도 같은 구현을 호출한다. 로봇 ID는 파라미터로 지정한다.
            'pinky_patrol_node_pinky1 = cobot_pinky_patrol.pinky_patrol_node:main',
            'pinky_patrol_node_pinky2 = cobot_pinky_patrol.pinky_patrol_node:main',
            'pinky_patrol_node_pinky3 = cobot_pinky_patrol.pinky_patrol_node:main',
        ],
    },
)
