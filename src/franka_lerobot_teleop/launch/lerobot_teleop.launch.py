from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource, XmlLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    robot_config_file = LaunchConfiguration('robot_config_file')
    gripper_robot_ip = LaunchConfiguration('gripper_robot_ip')
    gripper_use_fake_hardware = LaunchConfiguration('gripper_use_fake_hardware')
    gripper_robot_type = LaunchConfiguration('gripper_robot_type')
    gripper_namespace = LaunchConfiguration('gripper_namespace')
    gripper_teleop_parameters_file = LaunchConfiguration('gripper_teleop_parameters_file')
    gripper_teleop_namespace = LaunchConfiguration('gripper_teleop_namespace')
    lerobot_export_namespace = LaunchConfiguration('lerobot_export_namespace')

    return LaunchDescription([
        DeclareLaunchArgument(
            'robot_config_file',
            default_value=PathJoinSubstitution([
                FindPackageShare('franka_ros2_teleop'),
                'config',
                'fr3_teleop_config.yaml',
            ]),
            description='Path to the leader-follower teleoperation robot config file.',
        ),
        DeclareLaunchArgument(
            'gripper_robot_ip',
            default_value='192.168.1.11',
            description='Hostname or IP address of the gripper robot.',
        ),
        DeclareLaunchArgument(
            'gripper_use_fake_hardware',
            default_value='false',
            description='Use fake hardware for the Franka gripper.',
        ),
        DeclareLaunchArgument(
            'gripper_robot_type',
            default_value='fr3',
            description='Robot type used to derive Franka gripper joint names.',
        ),
        DeclareLaunchArgument(
            'gripper_namespace',
            default_value='',
            description='Namespace for the Franka gripper controller launch.',
        ),
        DeclareLaunchArgument(
            'gripper_teleop_parameters_file',
            default_value=PathJoinSubstitution([
                FindPackageShare('franka_gripper_teleop'),
                'config',
                'gripper_teleop.yaml',
            ]),
            description='Path to the parameter YAML for the gripper teleop node.',
        ),
        DeclareLaunchArgument(
            'gripper_teleop_namespace',
            default_value='',
            description='Namespace for the custom gripper teleop node.',
        ),
        DeclareLaunchArgument(
            'lerobot_export_namespace',
            default_value='',
            description='Namespace for the LeRobot export node.',
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('franka_ros2_teleop'),
                'launch',
                'teleop.launch.py',
            ])),
            launch_arguments={
                'robot_config_file': robot_config_file,
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('franka_gripper'),
                'launch',
                'gripper.launch.py',
            ])),
            launch_arguments={
                'robot_ip': gripper_robot_ip,
                'use_fake_hardware': gripper_use_fake_hardware,
                'robot_type': gripper_robot_type,
                'namespace': gripper_namespace,
            }.items(),
        ),
        IncludeLaunchDescription(
            XmlLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('foxglove_bridge'),
                'launch',
                'foxglove_bridge_launch.xml',
            ]))
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('franka_gripper_teleop'),
                'launch',
                'gripper_teleop.launch.py',
            ])),
            launch_arguments={
                'parameters_file': gripper_teleop_parameters_file,
                'namespace': gripper_teleop_namespace,
            }.items(),
        ),
        Node(
            package='franka_lerobot_teleop',
            executable='lerobot_export',
            name='lerobot_export',
            namespace=lerobot_export_namespace,
            output='screen',
        ),
    ])
