"""Launch the Franka teleop stack together with recording."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    """Create the teleop-plus-recorder launch description."""
    robot_config_file = LaunchConfiguration('robot_config_file')
    gripper_robot_ip = LaunchConfiguration('gripper_robot_ip')
    gripper_use_fake_hardware = LaunchConfiguration('gripper_use_fake_hardware')
    gripper_robot_type = LaunchConfiguration('gripper_robot_type')
    gripper_namespace = LaunchConfiguration('gripper_namespace')
    gripper_teleop_parameters_file = LaunchConfiguration('gripper_teleop_parameters_file')
    gripper_teleop_namespace = LaunchConfiguration('gripper_teleop_namespace')

    config_path = LaunchConfiguration('config_path')
    output_dir = LaunchConfiguration('output_dir')
    sample_rate_hz = LaunchConfiguration('sample_rate_hz')
    enable_wrist_camera = LaunchConfiguration('enable_wrist_camera')
    enable_base_camera = LaunchConfiguration('enable_base_camera')

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
            'config_path',
            default_value=PathJoinSubstitution([
                FindPackageShare('franka_lerobot_teleop'),
                'config',
                'recording.yaml',
            ]),
            description='Path to the recorder configuration YAML.',
        ),
        DeclareLaunchArgument(
            'output_dir',
            default_value='',
            description='Override the output directory from the YAML config.',
        ),
        DeclareLaunchArgument(
            'sample_rate_hz',
            default_value='0',
            description='Override the sample rate. Set 0 to keep the YAML value.',
        ),
        DeclareLaunchArgument(
            'enable_wrist_camera',
            default_value='',
            description='Override the wrist camera enable flag.',
        ),
        DeclareLaunchArgument(
            'enable_base_camera',
            default_value='',
            description='Override the base camera enable flag.',
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([
                FindPackageShare('franka_lerobot_teleop'),
                'launch',
                'basic_teleop.launch.py',
            ])),
            launch_arguments={
                'robot_config_file': robot_config_file,
                'gripper_robot_ip': gripper_robot_ip,
                'gripper_use_fake_hardware': gripper_use_fake_hardware,
                'gripper_robot_type': gripper_robot_type,
                'gripper_namespace': gripper_namespace,
                'gripper_teleop_parameters_file': gripper_teleop_parameters_file,
                'gripper_teleop_namespace': gripper_teleop_namespace,
            }.items(),
        ),
        Node(
            package='franka_lerobot_teleop',
            executable='teleop_recorder',
            output='screen',
            parameters=[{
                'config_path': config_path,
                'output_dir': output_dir,
                'sample_rate_hz': sample_rate_hz,
                'enable_wrist_camera': enable_wrist_camera,
                'enable_base_camera': enable_base_camera,
            }],
        ),
    ])
