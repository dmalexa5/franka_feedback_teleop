"""ROS 2 recorder node for Franka leader-follower teleoperation episodes."""

from __future__ import annotations

import importlib
import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from .adapters import ImagePayload, get_adapter, source_timestamp_ns
from .command_listener import CommandListener
from .config import RecorderConfig, TopicSpec, load_recorder_config, topic_names_by_key
from .topic_cache import TopicCache
from .writer import EpisodeWriter


def import_message_type(type_str: str) -> type:
    """Import a ROS message class from a package/msg/Class string."""
    package_name, separator, message_name = type_str.partition('/msg/')
    if not separator:
        raise ValueError(f'Unsupported message type format: {type_str}')
    module = importlib.import_module(f'{package_name}.msg')
    return getattr(module, message_name)


def missing_required_topic_keys(config: RecorderConfig, caches: Mapping[str, TopicCache]) -> List[str]:
    """Return enabled required topics that have not produced a first sample."""
    missing: List[str] = []
    for spec in config.required_topics():
        cache = caches[spec.key]
        if not cache.has_message:
            missing.append(spec.key)
    return missing


def metadata_updates_from_caches(caches: Mapping[str, TopicCache]) -> Dict[str, Any]:
    """Extract episode metadata that becomes available only after messages arrive."""
    updates: Dict[str, Any] = {}

    follower_joint_state = caches['follower_joint_state'].latest_payload
    gripper_joint_state = caches['gripper_joint_state'].latest_payload
    wrist_info = (
        caches['wrist_camera_info'].latest_payload
        if 'wrist_camera_info' in caches
        else None
    )
    base_info = caches['base_camera_info'].latest_payload if 'base_camera_info' in caches else None

    if follower_joint_state is not None:
        updates['follower_joint_ordering'] = follower_joint_state['joint_names']
    if gripper_joint_state is not None:
        updates['gripper_joint_ordering'] = gripper_joint_state['joint_names']

    camera_updates: Dict[str, Any] = {}
    if wrist_info is not None:
        camera_updates['wrist'] = wrist_info
    if base_info is not None:
        camera_updates['base'] = base_info
    if camera_updates:
        updates['camera_intrinsics'] = camera_updates

    return updates


def quaternion_to_rpy(orientation_xyzw: List[float]) -> List[float]:
    """Convert a quaternion in XYZW order into roll, pitch, yaw."""
    x, y, z, w = orientation_xyzw

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return [roll, pitch, yaw]


def gripper_width_from_joint_state(joint_state: Mapping[str, Any]) -> float:
    """Extract the gripper opening width in meters from a JointState payload."""
    positions = list(joint_state['joint_position'])
    if len(positions) >= 2:
        return float(positions[0] + positions[1])
    if positions:
        return float(2.0 * positions[0])
    raise ValueError('Gripper JointState payload is missing position values.')


def frame_from_caches(
    timestamp_sec: float,
    frame_index: int,
    episode_index: int,
    caches: Mapping[str, TopicCache],
) -> Tuple[Dict[str, Any], Dict[str, Optional[ImagePayload]]]:
    """Build one recorder frame from the current topic caches."""
    follower_joint_state = caches['follower_joint_state'].latest_payload
    follower_pose = caches['follower_pose'].latest_payload
    follower_wrench = caches['follower_wrench'].latest_payload
    gripper_joint_state = caches['gripper_joint_state'].latest_payload

    images = {
        'wrist': caches['wrist_image'].latest_payload if 'wrist_image' in caches else None,
        'base': caches['base_image'].latest_payload if 'base_image' in caches else None,
    }

    gripper_width = gripper_width_from_joint_state(gripper_joint_state)
    action = (
        list(follower_pose['position'])
        + quaternion_to_rpy(follower_pose['orientation_xyzw'])
        + [gripper_width]
    )
    observation_state = (
        list(follower_joint_state['joint_position'])
        + list(follower_wrench['wrench'])
    )

    row = {
        'action': action,
        'observation': {
            'state': observation_state,
            'image': None,
            'wrist_image': None,
        },
        'timestamp': float(timestamp_sec),
        'frame_index': int(frame_index),
        'episode_index': int(episode_index),
        'index': int(frame_index),
        'task_index': 0,
    }

    return row, images


class RecorderNode(Node):
    """Record Franka teleoperation data into per-episode folders."""

    def __init__(self) -> None:
        super().__init__('franka_lerobot_recorder')
        self.declare_parameter('config_path', '')
        self.declare_parameter('output_dir', '')
        self.declare_parameter('sample_rate_hz', 0)
        self.declare_parameter('enable_wrist_camera', '')
        self.declare_parameter('enable_base_camera', '')

        overrides = {
            'output_dir': self.get_parameter('output_dir').value,
            'sample_rate_hz': self.get_parameter('sample_rate_hz').value,
            'enable_wrist_camera': self.get_parameter('enable_wrist_camera').value,
            'enable_base_camera': self.get_parameter('enable_base_camera').value,
        }
        config_path = self.get_parameter('config_path').value or None
        self._config = load_recorder_config(config_path=config_path, overrides=overrides)
        self._writer = EpisodeWriter(self._config.output_dir)
        self._caches: Dict[str, TopicCache] = {
            spec.key: TopicCache(spec.key) for spec in self._config.enabled_topics()
        }
        self._subscriptions = []
        self._recording = False
        self._episode_first_frame_timestamp_ns: Optional[int] = None

        self._create_subscriptions()
        self._command_listener = CommandListener(self, self._config.command_topic, self._handle_command)
        self._timer = self.create_timer(1.0 / self._config.sample_rate_hz, self._on_timer)

        self.get_logger().info(
            f'Recorder ready. Output directory: {self._config.output_dir}. '
            f'Listening for commands on {self._config.command_topic}.'
        )

    def _create_subscriptions(self) -> None:
        """Create one subscription per enabled configured topic."""
        for spec in self._config.enabled_topics():
            message_type = import_message_type(spec.type_str)
            adapter = get_adapter(spec.adapter)
            qos = qos_profile_sensor_data if spec.qos_profile == 'sensor_data' else 10
            subscription = self.create_subscription(
                message_type,
                spec.topic,
                self._make_topic_callback(spec, adapter),
                qos,
            )
            self._subscriptions.append(subscription)

    def _make_topic_callback(self, spec: TopicSpec, adapter: Callable[[Any], Any]) -> Callable[[Any], None]:
        """Build a cache update callback for one topic."""
        def callback(message: Any) -> None:
            try:
                payload = adapter(message)
            except Exception as exc:  # pragma: no cover - depends on runtime data
                self.get_logger().error(
                    f"Failed to adapt message for topic '{spec.topic}': {exc}"
                )
                return
            source_ns = source_timestamp_ns(message)
            if source_ns is None and spec.adapter == 'json_string':
                source_ns = payload.get('sent_at_ns')
            self._caches[spec.key].update(
                message=message,
                payload=payload,
                source_timestamp_ns=source_ns,
                receipt_timestamp_ns=self.get_clock().now().nanoseconds,
            )

        return callback

    def _handle_command(self, command: str) -> None:
        """Start or stop recording."""
        if command == 'start':
            self._start_recording()
        elif command == 'stop':
            self._stop_recording()

    def _start_recording(self) -> None:
        """Start a new episode if the recorder is idle."""
        if self._recording:
            self.get_logger().warn('Recorder is already active. Ignoring duplicate start command.')
            return

        metadata = {
            'start_timestamp': self.get_clock().now().nanoseconds,
            'end_timestamp': None,
            'sample_rate_hz': self._config.sample_rate_hz,
            'enabled_topics': topic_names_by_key(self._config),
            'required_topics': {
                spec.key: spec.topic for spec in self._config.required_topics()
            },
            'pose_frame_description': self._config.pose_frame_description,
            'wrench_frame_description': self._config.wrench_frame_description,
            'teleop_mode': self._config.teleop_mode,
            'robot_name': self._config.robot_name,
            'latest_sample_note': self._config.latest_sample_note,
            'follower_joint_ordering': None,
            'gripper_joint_ordering': None,
            'camera_topics': {
                'wrist': (
                    self._config.topics['wrist_image'].topic
                    if 'wrist_image' in self._caches
                    else None
                ),
                'base': (
                    self._config.topics['base_image'].topic
                    if 'base_image' in self._caches
                    else None
                ),
            },
            'camera_intrinsics': {'wrist': None, 'base': None},
            'action_semantics': 'cartesian_xyz_rpy_plus_width',
            'state_semantics': 'desired_joint_positions_plus_wrench',
            'pose_representation': 'xyz_rpy',
            'config_path': str(self._config.config_path),
        }
        episode_dir = self._writer.start_episode(metadata)
        self._recording = True
        self._episode_first_frame_timestamp_ns = None
        self.get_logger().info(f'Started recording to {episode_dir}.')

    def _stop_recording(self) -> None:
        """Finalize the active episode."""
        if not self._recording:
            self.get_logger().warn('Recorder is idle. Ignoring stop command.')
            return
        self._writer.finalize(self.get_clock().now().nanoseconds)
        self._recording = False
        self.get_logger().info('Stopped recording and finalized the current episode.')

    def _on_timer(self) -> None:
        """Write one latest-sample frame at the configured fixed rate."""
        if not self._recording:
            return

        missing_topics = missing_required_topic_keys(self._config, self._caches)
        if missing_topics:
            self.get_logger().warn(
                f'Waiting for required topics before writing frames: {missing_topics}',
                throttle_duration_sec=5.0,
            )
            return

        now_ns = self.get_clock().now().nanoseconds
        stale_threshold_ns = int(self._config.camera_stale_threshold_sec * 1_000_000_000)
        for key in ('wrist_image', 'base_image'):
            cache = self._caches.get(key)
            if cache is not None and cache.is_stale(now_ns, stale_threshold_ns):
                self.get_logger().warn(
                    f"Camera topic '{self._config.topics[key].topic}' is stale.",
                    throttle_duration_sec=5.0,
                )

        self._writer.update_metadata(metadata_updates_from_caches(self._caches))
        if self._episode_first_frame_timestamp_ns is None:
            self._episode_first_frame_timestamp_ns = now_ns
        timestamp_sec = (now_ns - self._episode_first_frame_timestamp_ns) / 1_000_000_000.0
        episode_index = self._writer.episode_id
        if episode_index is None:
            raise RuntimeError('Recorder attempted to write a frame without an active episode id.')
        frame, images = frame_from_caches(
            timestamp_sec,
            self._writer.frame_index,
            episode_index,
            self._caches,
        )
        self._writer.write_frame(frame, images)

    def destroy_node(self) -> bool:
        """Finalize any active episode before node destruction."""
        if self._recording:
            self._writer.finalize(self.get_clock().now().nanoseconds)
            self._recording = False
        return super().destroy_node()


def main(args: Optional[List[str]] = None) -> None:
    """Run the recorder node."""
    rclpy.init(args=args)
    node = RecorderNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
