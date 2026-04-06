"""ROS 2 recorder node for Franka leader-follower teleoperation episodes."""

from __future__ import annotations

import importlib
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


def default_gripper_command() -> Dict[str, Any]:
    """Return the default gripper command record."""
    return {
        'command_type': 'none',
        'width_cmd': None,
        'speed_cmd': None,
        'force_cmd': None,
        'epsilon_inner': None,
        'epsilon_outer': None,
    }


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
    leader_joint_state = caches['leader_joint_state'].latest_payload
    wrist_info = (
        caches['wrist_camera_info'].latest_payload
        if 'wrist_camera_info' in caches
        else None
    )
    base_info = caches['base_camera_info'].latest_payload if 'base_camera_info' in caches else None

    if follower_joint_state is not None:
        updates['follower_joint_ordering'] = follower_joint_state['joint_names']
    if leader_joint_state is not None:
        updates['leader_joint_ordering'] = leader_joint_state['joint_names']

    camera_updates: Dict[str, Any] = {}
    if wrist_info is not None:
        camera_updates['wrist'] = wrist_info
    if base_info is not None:
        camera_updates['base'] = base_info
    if camera_updates:
        updates['camera_intrinsics'] = camera_updates

    return updates


def frame_from_caches(
    timestamp_ns: int,
    caches: Mapping[str, TopicCache],
) -> Tuple[Dict[str, Any], Dict[str, Optional[ImagePayload]]]:
    """Build one recorder frame from the current topic caches."""
    follower_joint_state = caches['follower_joint_state'].latest_payload
    follower_pose = caches['follower_pose'].latest_payload
    follower_wrench = caches['follower_wrench'].latest_payload
    gripper_joint_state = caches['gripper_joint_state'].latest_payload
    leader_joint_state = caches['leader_joint_state'].latest_payload
    leader_pose = caches['leader_pose'].latest_payload
    leader_twist = caches['leader_twist'].latest_payload if 'leader_twist' in caches else None
    gripper_command = (
        caches['gripper_command_mirror'].latest_payload
        if 'gripper_command_mirror' in caches
        else None
    )

    images = {
        'wrist': caches['wrist_image'].latest_payload if 'wrist_image' in caches else None,
        'base': caches['base_image'].latest_payload if 'base_image' in caches else None,
    }

    row = {
        'timestamp': int(timestamp_ns),
        'observation': {
            'state': {
                'follower_joint_position': follower_joint_state['joint_position'],
                'follower_joint_names': follower_joint_state['joint_names'],
                'follower_ee_position': follower_pose['position'],
                'follower_ee_orientation_xyzw': follower_pose['orientation_xyzw'],
                'follower_ee_wrench_base': follower_wrench['wrench_base'],
                'gripper_joint_position': gripper_joint_state['joint_position'],
            },
            'images': {
                'wrist': {'path': None},
                'base': {'path': None},
            },
        },
        'action': {
            'leader_joint_position': leader_joint_state['joint_position'],
            'leader_joint_names': leader_joint_state['joint_names'],
            'leader_ee_position': leader_pose['position'],
            'leader_ee_orientation_xyzw': leader_pose['orientation_xyzw'],
            'leader_ee_twist': leader_twist['twist'] if leader_twist else None,
            'gripper': default_gripper_command(),
        },
        'source_timestamps': {key: cache.source_timestamp_ns for key, cache in caches.items()},
        'receipt_timestamps': {key: cache.receipt_timestamp_ns for key, cache in caches.items()},
    }

    if gripper_command is not None:
        row['action']['gripper'] = {
            'command_type': gripper_command['command_type'],
            'width_cmd': gripper_command['width_cmd'],
            'speed_cmd': gripper_command['speed_cmd'],
            'force_cmd': gripper_command['force_cmd'],
            'epsilon_inner': gripper_command['epsilon_inner'],
            'epsilon_outer': gripper_command['epsilon_outer'],
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
            'leader_joint_ordering': None,
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
            'config_path': str(self._config.config_path),
        }
        episode_dir = self._writer.start_episode(metadata)
        self._recording = True
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
        frame, images = frame_from_caches(now_ns, self._caches)
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
