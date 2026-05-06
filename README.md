# `franka_feedback_teleop`

`franka_feedback_teleop` is a compact ROS 2 Humble demo for Franka
leader-follower feedback teleoperation with a custom gripper teleop command
path.

This repository no longer documents or launches data collection. It is focused
on running the teleop stack and the gripper command path together.

## What It Launches

The main launch file is:

```bash
ros2 launch franka_feedback_teleop basic_teleop.launch.py
```

It includes:

- `franka_ros2_teleop` leader-follower teleoperation
- `franka_gripper` gripper control
- `franka_gripper_teleop` custom gripper teleop commands

Useful launch arguments include:

- `robot_config_file`: leader-follower teleop robot config file
- `gripper_robot_ip`: gripper robot hostname or IP address
- `gripper_use_fake_hardware`: whether to use fake gripper hardware
- `gripper_robot_type`: Franka robot type used for gripper joint names
- `gripper_namespace`: namespace for the gripper controller launch
- `gripper_teleop_parameters_file`: parameter file for the gripper teleop node
- `gripper_teleop_namespace`: namespace for the gripper teleop node

## Docker (Reccomended)

A Docker Compose development environment is available:

```bash
docker compose up --build
```

For serial device access inside the container, see
[`docs/SERIAL.md`](docs/SERIAL.md).

## Setup

From the workspace root:

```bash
git submodule update --init --recursive
rosdep update
rosdep install --from-paths src --ignore-src --rosdistro humble -y
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DBUILD_TESTS=OFF
source install/setup.bash
```

For the first build, it is recommended to use this build command to prevent out-of-memory issues (particularly on a NUC device):

```bash
MAKEFLAGS="-j1 -l1" CMAKE_BUILD_PARALLEL_LEVEL=1 colcon build \
  --symlink-install \
  --executor sequential \
  --parallel-workers 1 \
  --cmake-args \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTING=OFF \
    -DBUILD_TESTS=OFF
```

There will likely be warnings! Don't worry, the packages this project is based on are under rapid development.

## Manual Checks

After changing this package, rebuild with:

```bash
colcon build --symlink-install --packages-select franka_feedback_teleop
ros2 launch franka_feedback_teleop basic_teleop.launch.py
```

The build checks package and install metadata. The launch command checks that
the demo wiring resolves in your hardware or fake-hardware environment.
