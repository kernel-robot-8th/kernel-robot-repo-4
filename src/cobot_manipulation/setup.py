"""로봇팔 패키지 등록."""
from glob import glob

from setuptools import find_packages, setup

package_name = 'cobot_manipulation'

setup(
    name=package_name, version='0.1.0', packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.xml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='cobot manipulation team', maintainer_email='cobot@example.com',
    description='관제 장치 작업 요청으로 OMX 추론 스크립트를 실행하는 worker',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={'console_scripts': [
        'omx_infer_worker_node = cobot_manipulation.omx_infer_worker_node:main']},
)
