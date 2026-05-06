"""Tests for recorder frame assembly."""

from __future__ import annotations

from typing import Any

from franka_feedback_teleop.filter import ExponentialMovingAverage
from franka_feedback_teleop.recorder_node import frame_from_caches
from franka_feedback_teleop.topic_cache import TopicCache


def _cache(key: str, payload: Any) -> TopicCache:
    cache = TopicCache(key)
    cache.latest_payload = payload
    return cache


def _caches(wrench: list[float]) -> dict[str, TopicCache]:
    return {
        'follower_joint_state': _cache(
            'follower_joint_state',
            {'joint_position': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]},
        ),
        'follower_pose': _cache(
            'follower_pose',
            {
                'position': [1.0, 2.0, 3.0],
                'orientation_xyzw': [0.0, 0.0, 0.0, 1.0],
            },
        ),
        'follower_wrench': _cache('follower_wrench', {'wrench': wrench}),
        'gripper_joint_state': _cache(
            'gripper_joint_state',
            {'joint_position': [0.01, 0.02]},
        ),
        'base_image': _cache('base_image', None),
        'wrist_image': _cache('wrist_image', None),
    }


def test_frame_uses_direct_parquet_columns_and_follower_action_state() -> None:
    wrench_filter = ExponentialMovingAverage(0.1, 6)

    row, images = frame_from_caches(1.5, 2, 3, _caches([0.0] * 6), wrench_filter)

    assert row['action.state'] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    assert row['action.wrench'] == [0.0] * 6
    assert row['action.gripper'] == 0.03
    assert row['phase'] == 'free'
    assert row['observation.pose'] == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0]
    assert row['observation.wrench'] == [0.0] * 6
    assert row['timestamp'] == 1.5
    assert row['frame_index'] == 2
    assert row['episode_index'] == 3
    assert row['task_index'] == 0
    assert row['observation.base_image'] == {'bytes': None, 'path': None}
    assert row['observation.wrist_image'] == {'bytes': None, 'path': None}
    assert images == {'wrist': None, 'base': None}
    assert 'leader' not in row
    assert 'observation' not in row


def test_action_wrench_is_filtered_and_observation_wrench_is_raw() -> None:
    wrench_filter = ExponentialMovingAverage(0.1, 6)

    frame_from_caches(0.0, 0, 1, _caches([0.0] * 6), wrench_filter)
    row, _ = frame_from_caches(0.1, 1, 1, _caches([10.0] * 6), wrench_filter)

    assert row['action.wrench'] == [1.0] * 6
    assert row['observation.wrench'] == [10.0] * 6
