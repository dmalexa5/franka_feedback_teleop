"""Configuration helpers for the Franka teleoperation recorder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ament_index_python.packages import get_package_share_directory
import yaml


def default_config_path() -> Path:
    """Return the installed default recording configuration path."""
    return Path(get_package_share_directory('franka_lerobot_teleop')) / 'config' / 'recording.yaml'


def _as_bool(value: Any) -> bool:
    """Convert a YAML value into a strict boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'true', '1', 'yes', 'on'}:
            return True
        if lowered in {'false', '0', 'no', 'off'}:
            return False
    raise ValueError(f'Cannot interpret {value!r} as a boolean.')


def optional_bool(value: Any) -> Optional[bool]:
    """Parse a launch or parameter value into an optional boolean."""
    if value in (None, '', 'auto', 'default'):
        return None
    return _as_bool(value)


def optional_positive_int(value: Any) -> Optional[int]:
    """Parse a launch or parameter integer override where 0 means default."""
    if value in (None, '', 'auto', 'default'):
        return None
    parsed = int(value)
    if parsed == 0:
        return None
    return parsed


@dataclass(frozen=True)
class TopicSpec:
    """Normalized description of one recorder input."""

    key: str
    topic: str
    type_str: str
    adapter: str
    enabled: bool
    required: bool
    role: str
    description: str
    qos_profile: str = 'sensor_data'


@dataclass(frozen=True)
class RecorderConfig:
    """Fully resolved recorder configuration."""

    config_path: Path
    output_dir: Path
    sample_rate_hz: int
    camera_stale_threshold_sec: float
    command_topic: str
    teleop_mode: str
    robot_name: str
    pose_frame_description: str
    wrench_frame_description: str
    latest_sample_note: str
    topics: Dict[str, TopicSpec]

    def enabled_topics(self) -> Iterable[TopicSpec]:
        """Iterate over enabled topics."""
        return (spec for spec in self.topics.values() if spec.enabled)

    def required_topics(self) -> Iterable[TopicSpec]:
        """Iterate over enabled required topics."""
        return (spec for spec in self.enabled_topics() if spec.required)


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load and validate a YAML document."""
    with path.open('r', encoding='utf-8') as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f'Expected a mapping in {path}.')
    return data


def _normalize_topic_specs(raw_topics: Mapping[str, Mapping[str, Any]]) -> Dict[str, TopicSpec]:
    """Convert raw YAML topic entries into immutable specs."""
    topics: Dict[str, TopicSpec] = {}
    for key, value in raw_topics.items():
        topics[key] = TopicSpec(
            key=key,
            topic=str(value['topic']),
            type_str=str(value['type']),
            adapter=str(value['adapter']),
            enabled=_as_bool(value.get('enabled', True)),
            required=_as_bool(value.get('required', False)),
            role=str(value.get('role', 'data')),
            description=str(value.get('description', key)),
            qos_profile=str(value.get('qos_profile', 'sensor_data')),
        )
    return topics


def load_recorder_config(
    config_path: Optional[str] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> RecorderConfig:
    """Load recorder configuration and apply launch or parameter overrides."""
    resolved_config_path = Path(config_path).expanduser() if config_path else default_config_path()
    raw = _load_yaml(resolved_config_path)
    overrides = dict(overrides or {})

    output_dir = Path(overrides.get('output_dir') or raw['output_dir']).expanduser()
    sample_rate_override = optional_positive_int(overrides.get('sample_rate_hz'))
    sample_rate_hz = sample_rate_override or int(raw['sample_rate_hz'])
    if sample_rate_hz <= 0:
        raise ValueError('sample_rate_hz must be > 0.')

    topics = _normalize_topic_specs(raw['topics'])
    wrist_override = optional_bool(overrides.get('enable_wrist_camera'))
    base_override = optional_bool(overrides.get('enable_base_camera'))

    if wrist_override is not None:
        topics['wrist_image'] = TopicSpec(
            **{**topics['wrist_image'].__dict__, 'enabled': wrist_override}
        )
        topics['wrist_camera_info'] = TopicSpec(
            **{
                **topics['wrist_camera_info'].__dict__,
                'enabled': wrist_override,
                'required': wrist_override,
            }
        )
    if base_override is not None:
        topics['base_image'] = TopicSpec(
            **{**topics['base_image'].__dict__, 'enabled': base_override}
        )
        topics['base_camera_info'] = TopicSpec(
            **{
                **topics['base_camera_info'].__dict__,
                'enabled': base_override,
                'required': base_override,
            }
        )

    return RecorderConfig(
        config_path=resolved_config_path,
        output_dir=output_dir,
        sample_rate_hz=sample_rate_hz,
        camera_stale_threshold_sec=float(raw.get('camera_stale_threshold_sec', 0.5)),
        command_topic=str(raw.get('command_topic', '/franka_lerobot_teleop/command')),
        teleop_mode=str(raw.get('teleop_mode', 'leader_follower')),
        robot_name=str(raw.get('robot_name', 'franka')),
        pose_frame_description=str(
            raw.get(
                'pose_frame_description',
                'End-effector poses are stored from PoseStamped messages '
                'using the source frame_id.',
            )
        ),
        wrench_frame_description=str(raw.get('wrench_frame_description', 'base frame')),
        latest_sample_note=str(
            raw.get(
                'latest_sample_note',
                'Each 30 Hz sample stores the latest cached message per enabled topic. '
                'This intentionally permits temporal skew across mixed-rate streams.',
            )
        ),
        topics=topics,
    )


def topic_names_by_key(config: RecorderConfig) -> Dict[str, str]:
    """Return the configured topic names keyed by logical topic id."""
    return {key: spec.topic for key, spec in config.topics.items() if spec.enabled}
