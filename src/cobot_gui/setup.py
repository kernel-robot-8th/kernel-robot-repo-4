from setuptools import find_packages, setup

package_name = 'cobot_gui'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/menu_tree.yaml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rkd1rjs2',
    maintainer_email='rkd1rjs2@gmail.com',
    description='FMS 관제 대시보드(GUI): 메뉴 레지스트리와 검사·문서 생성 도구',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'gen_menu_doc = cobot_gui.gen_menu_doc:main',
            'check_menu_tree = cobot_gui.menu_registry:main',
        ],
    },
)
