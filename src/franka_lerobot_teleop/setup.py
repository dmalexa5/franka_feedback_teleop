from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'franka_lerobot_teleop'

setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (
            os.path.join('share', package_name, 'launch'),
            [f for f in glob('launch/*') if os.path.isfile(f)],
        ),
        (
            os.path.join('share', package_name, 'config'),
            [f for f in glob('config/*') if os.path.isfile(f)],
        ),
    ],
    install_requires=['setuptools', 'numpy', 'Pillow', 'pyarrow', 'PyYAML'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='dmalexa5@ncsu.edu',
    description='Minimal Parquet recorder for Franka leader-follower teleoperation data.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    scripts=[
        'scripts/recorder_ui.py',
    ],
    entry_points={
        'console_scripts': [
            'teleop_recorder = franka_lerobot_teleop.recorder_node:main',
        ]
    },
)
