# `franka_lerobot_teleop`

`franka_lerobot_teleop` is a minimal ROS 2 Humble data recorder for leader-follower Franka teleoperation plus a standalone exporter for nested Parquet datasets.

## Architecture

The package is intentionally split into two stages:

1. Stage 1: a ROS 2 recorder node caches the latest message for each configured topic and writes one synchronized timestep at a fixed 30 Hz.
2. Stage 2: a standalone exporter converts the internal episode folders into a nested Parquet dataset layout with copied image assets.

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
  frames.jsonl
  images/wrist/000000.jpg
  images/base/000000.jpg
```

`meta.json` stores only:

- `task`
- `success`
- `duration`
- `frequency`

Each `frames.jsonl` row stores:

- `action.ee_pose`: follower pose as `[x, y, z, qx, qy, qz, qw]`
- `action.gripper`: measured gripper width
- `observation.images.base`: base image path
- `observation.images.wrist`: wrist image path
- `observation.state.q`: follower joint positions
- `observation.state.ee_pose`: follower pose as `[x, y, z, qx, qy, qz, qw]`
- `observation.state.wrench`: follower wrench as `[fx, fy, fz, tx, ty, tz]`
- `leader.q`: optional leader joint positions
- `leader.ee_pose`: optional leader pose as `[x, y, z, qx, qy, qz, qw]`
- `timestamp`: seconds from the first written frame in the episode
- `frame_index`: zero-based frame index
- `episode_index`: numeric id of the current episode

`action.ee_pose` intentionally duplicates the follower end-effector pose on `/franka_teleop/follower/franka_robot_state_broadcaster/current_pose`. `action.gripper` is derived from `/franka_gripper/joint_states`.

`observation.state` is built from follower joint state, pose, and wrench topics. `leader` is present only when optional leader topics have produced samples.

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

The exporter writes nested Parquet columns:

- `action.ee_pose`
- `action.gripper`
- `observation.images.base`
- `observation.images.wrist`
- `observation.state.q`
- `observation.state.ee_pose`
- `observation.state.wrench`
- `leader.q`
- `leader.ee_pose`
- `timestamp`
- `frame_index`
- `episode_index`
