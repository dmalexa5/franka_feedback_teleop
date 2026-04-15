# `franka_lerobot_teleop`

`franka_lerobot_teleop` is a minimal ROS 2 Humble data recorder for leader-follower Franka teleoperation episodes stored directly as per-episode Parquet files.

## Architecture

The ROS 2 recorder node caches the latest message for each configured topic and writes one timestep at a fixed 30 Hz directly into the active episode's Parquet file.

The recorder never writes while idle. Recording starts, stops, and post-stop success annotation happen through `/franka_lerobot_teleop/command` with JSON payloads in `std_msgs/String`. Legacy plain-text `start` and `stop` commands are still accepted for compatibility.

## Configuration

The default configuration lives in [`config/recording.yaml`](/ros2_ws/src/franka_lerobot_teleop/config/recording.yaml). It defines:

- output directory
- sample rate
- required and optional topics
- camera enable flags
- topic names
- ROS message types
- adapter identifiers

Launch arguments override the YAML values for:

- `config_path`
- `output_dir`
- `sample_rate_hz`
- `enable_wrist_camera`
- `enable_base_camera`

## Launch Usage

Launch a basic teleop (no recording) setup with:

```bash
ros2 launch franka_lerobot_teleop basic_teleop.launch.py
```

Run the recorder node with:

```bash
ros2 launch franka_lerobot_teleop recording_teleop.launch.py
```

Override defaults when needed:

```bash
ros2 launch franka_lerobot_teleop recording_teleop.launch.py \
  output_dir:=/tmp/franka_dataset \
  sample_rate_hz:=30 \
  enable_wrist_camera:=true \
  enable_base_camera:=true
```



## Start And Stop Workflow

Use the standalone UI helper after sourcing ROS:

```bash
python3 scripts/recorder_ui.py start --task "peel the cucumber"
python3 scripts/recorder_ui.py stop
```

The recorder creates the next episode folder immediately on `start`, but it does not write frames until every required enabled topic has produced at least one message. This makes the latest-sample synchronization rule explicit and keeps partial frames out of the dataset. On `stop`, the UI publishes the stop command first, then prompts for success or failure and publishes a follow-up annotation for the just-finished episode.

## Internal Data Format

Each episode is written under:

```text
episodes/episode_000001/
  meta.json
  frames.parquet
  images/wrist/000000.jpg
  images/base/000000.jpg
```

`meta.json` stores only:

- `task`
- `success`
- `duration`
- `frequency`

Each `frames.parquet` row stores:

- `action.state`: follower joint positions as seven joint angles
- `action.wrench`: filtered follower wrench as `[fx, fy, fz, tx, ty, tz]`
- `action.gripper`: measured gripper width
- `phase`: currently always `free`
- `observation.pose`: follower pose as `[x, y, z, qx, qy, qz, qw]`
- `observation.wrench`: raw follower wrench as `[fx, fy, fz, tx, ty, tz]`
- `observation.base_image`: image cell with `bytes` and `path`
- `observation.wrist_image`: image cell with `bytes` and `path`
- `timestamp`: seconds from the first written frame in the episode
- `frame_index`: zero-based frame index
- `episode_index`: numeric id of the current episode
- `task_index`: currently always `0`

`action.state` comes from `/franka_teleop/follower/franka_robot_state_broadcaster/desired_joint_states`. `action.gripper` is derived from `/franka_gripper/joint_states`.

`action.wrench` and `observation.wrench` both come from `/franka_teleop/follower/franka_robot_state_broadcaster/external_wrench_in_stiffness_frame`. `action.wrench` applies an exponential moving average with alpha `0.1`; `observation.wrench` stores the raw topic value.

Image columns store LeRobot-style path cells such as `{"bytes": null, "path": "images/base/000000.jpg"}` while JPEG files stay in the episode image directories.

## Verification

Recommended checks after changes:

```bash
python3 -m pytest src/franka_lerobot_teleop/test
colcon build --packages-select franka_lerobot_teleop
```
