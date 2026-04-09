# `franka_lerobot_teleop`

`franka_lerobot_teleop` is a minimal ROS 2 Humble data recorder for leader-follower Franka teleoperation plus a standalone exporter for LeRobot-friendly datasets.

## Architecture

The package is intentionally split into two stages:

1. Stage 1: a ROS 2 recorder node caches the latest message for each configured topic and writes one synchronized timestep at a fixed 30 Hz.
2. Stage 2: a standalone exporter converts the internal episode folders into a Parquet-based dataset layout with copied image assets.

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

- recorder sample timestamp
- follower observations
- leader actions
- optional leader twist
- gripper command intent
- image paths
- source timestamps per topic
- receipt timestamps per topic

## Gripper Command Mirror

The MVP does not sniff ROS action goal traffic directly. Instead, it supports an optional lightweight mirror topic:

- topic: `/franka_lerobot_teleop/gripper_command`
- type: `std_msgs/msg/String`
- payload: JSON object with
  - `command_type`
  - `width_cmd`
  - `speed_cmd`
  - `force_cmd`
  - `epsilon_inner`
  - `epsilon_outer`
  - `source_action`
  - `sent_at_ns`

When the mirror topic is disabled or absent, the recorder still writes gripper observation from `/franka_gripper/joint_states` and fills the command intent with `command_type="none"` plus null numeric command fields.

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

The exporter keeps observation and action columns separate with dot-named fields that match the internal schema.