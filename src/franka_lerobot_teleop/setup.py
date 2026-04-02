from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'franka_lerobot_teleop'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (
            os.path.join('share', package_name, 'launch'),
            [f for f in glob('launch/*') if os.path.isfile(f)],
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='dmalexa5@ncsu.edu',
    description='TODO: Package description',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'lerobot_export = franka_lerobot_teleop.lerobot_export:main'
        ],
    },
)
