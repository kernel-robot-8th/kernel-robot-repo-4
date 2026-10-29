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
        # 좌표 파라미터 YAML 과 로봇별 launch (없으면 install 에 복사되지 않아 노드가 시작을 거부함)
        ('share/' + package_name + '/config', glob('config/*.yaml')),
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
            'pinky_patrol_node_pinky1 = cobot_pinky_patrol.pinky_patrol_node_pinky1:main',
            'pinky_patrol_node_pinky2 = cobot_pinky_patrol.pinky_patrol_node_pinky2:main',
            'pinky_patrol_node_pinky3 = cobot_pinky_patrol.pinky_patrol_node_pinky3:main',
        ],
    },
)
