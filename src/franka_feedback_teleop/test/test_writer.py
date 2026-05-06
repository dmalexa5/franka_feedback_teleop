"""Tests for direct Parquet episode writing."""

from __future__ import annotations

import json

from PIL import Image
import pyarrow as pa
import pyarrow.parquet as pq

from franka_feedback_teleop.adapters import ImagePayload
from franka_feedback_teleop.writer import EpisodeWriter, recorder_schema


def _row() -> dict[str, object]:
    return {
        'action.state': [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        'action.wrench': [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        'action.gripper': 0.03,
        'phase': 'free',
        'observation.pose': [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0],
        'observation.wrench': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        'observation.base_image': {'bytes': None, 'path': None},
        'observation.wrist_image': {'bytes': None, 'path': None},
        'timestamp': 0.0,
        'frame_index': 0,
        'episode_index': 1,
        'task_index': 0,
    }


def _image_payload() -> ImagePayload:
    return ImagePayload(
        image=Image.new('RGB', (2, 2), color=(255, 0, 0)),
        width=2,
        height=2,
        encoding='rgb8',
        frame_id='camera',
    )


def test_writer_creates_parquet_episode_with_expected_schema(tmp_path) -> None:
    writer = EpisodeWriter(tmp_path, row_group_size=1)
    episode_dir = writer.start_episode({'task': 'pick', 'success': None, 'duration': 0.0})

    writer.write_frame(_row(), {'base': _image_payload(), 'wrist': _image_payload()})
    writer.update_metadata({'duration': 1.25})
    writer.finalize()

    table = pq.read_table(episode_dir / 'frames.parquet')
    rows = table.to_pylist()

    assert table.schema.names == recorder_schema().names
    assert 'index' not in table.schema.names
    assert table.schema.field('action.state').type == pa.list_(pa.float64())
    assert table.schema.field('action.wrench').type == pa.list_(pa.float64())
    assert table.schema.field('action.gripper').type == pa.float64()
    assert table.schema.field('phase').type == pa.string()
    assert table.schema.field('observation.base_image').type == recorder_schema().field(
        'observation.base_image'
    ).type
    assert rows[0]['observation.base_image'] == {
        'bytes': None,
        'path': 'images/base/000000.jpg',
    }
    assert rows[0]['observation.wrist_image'] == {
        'bytes': None,
        'path': 'images/wrist/000000.jpg',
    }
    assert (episode_dir / 'images' / 'base' / '000000.jpg').exists()
    assert (episode_dir / 'images' / 'wrist' / '000000.jpg').exists()

    with (episode_dir / 'meta.json').open('r', encoding='utf-8') as handle:
        meta = json.load(handle)

    assert meta == {'duration': 1.25, 'success': None, 'task': 'pick'}
