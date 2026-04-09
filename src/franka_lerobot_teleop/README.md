# `franka_lerobot_teleop`

`franka_lerobot_teleop` is a minimal ROS 2 Humble data recorder for leader-follower Franka teleoperation plus a standalone exporter for ForceVLA-shaped datasets.

## Architecture

The package is intentionally split into two stages:

1. Stage 1: a ROS 2 recorder node caches the latest message for each configured topic and writes one synchronized timestep at a fixed 30 Hz.
2. Stage 2: a standalone exporter converts the internal episode folders into a ForceVLA-shaped Parquet dataset layout with copied image assets.

The recorder never writes while idle. Recording starts and stops only through `/franka_lerobot_teleop/command` with the string payloads `start` and `stop`.

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
python3 scripts/recorder_ui.py start
python3 scripts/recorder_ui.py stop
```

The recorder creates the next episode folder immediately on `start`, but it does not write frames until every required enabled topic has produced at least one message. This makes the latest-sample synchronization rule explicit and keeps partial frames out of the dataset.

## Internal Data Format

Each episode is written under:

```text
episodes/episode_000001/
  meta.json
  frames.jsonl
  images/wrist/000000.jpg
  images/base/000000.jpg
```

`meta.json` stores:

- episode id
- start and end timestamps
- sample rate
- enabled and required topics
- joint ordering
- pose and wrench frame notes
- camera topic names
- camera intrinsics
- teleop mode
- robot name
- the latest-sample synchronization note

Each `frames.jsonl` row stores:

- `action`: `[x, y, z, roll, pitch, yaw, gripper_width]`
- `observation.state`: `[q1..q7, fx, fy, fz, tx, ty, tz]`
- `observation.image`: base image path
- `observation.wrist_image`: wrist image path
- `timestamp`: seconds from the first written frame in the episode
- `frame_index`: zero-based frame index
- `episode_index`: numeric id of the current episode
- `index`: same as `frame_index`
- `task_index`: currently always `0`

`action` is built from the follower end-effector pose on `/franka_teleop/follower/franka_robot_state_broadcaster/current_pose`, converted to `XYZ + RPY`, then concatenated with the gripper width derived from `/franka_gripper/joint_states`.

`observation.state` is built from `/franka_teleop/follower/franka_robot_state_broadcaster/desired_joint_states` concatenated with `/franka_teleop/follower/franka_robot_state_broadcaster/external_wrench_in_stiffness_frame`.

## Export Workflow

The exporter is file-based and does not require ROS:

```bash
python3 scripts/export_to_lerobot.py \
  --input-root /tmp/franka_dataset \
  --output-dir /tmp/franka_dataset_export
```

Exported output:

```text
meta/info.json
meta/episodes.jsonl
data/episode_000001.parquet
images/episode_000001/...
```

The exporter writes ForceVLA-style Parquet columns:

- `action`
- `observation.state`
- `observation.image`
- `observation.wrist_image`
- `timestamp`
- `frame_index`
- `episode_index`
- `index`
- `task_index`
