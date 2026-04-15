"""Episode writing helpers for the recorder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pyarrow as pa
import pyarrow.parquet as pq

from .adapters import ImagePayload


DEFAULT_ROW_GROUP_SIZE = 128


def recorder_schema() -> pa.Schema:
    """Return the direct recorder Parquet schema."""
    image_struct = pa.struct([
        pa.field('bytes', pa.binary()),
        pa.field('path', pa.string()),
    ])
    return pa.schema([
        pa.field('action.state', pa.list_(pa.float64())),
        pa.field('action.wrench', pa.list_(pa.float64())),
        pa.field('action.gripper', pa.float64()),
        pa.field('phase', pa.string()),
        pa.field('observation.pose', pa.list_(pa.float64())),
        pa.field('observation.wrench', pa.list_(pa.float64())),
        pa.field('observation.base_image', image_struct),
        pa.field('observation.wrist_image', image_struct),
        pa.field('timestamp', pa.float64()),
        pa.field('frame_index', pa.int64()),
        pa.field('episode_index', pa.int64()),
        pa.field('task_index', pa.int64()),
    ])


def _deep_update(target: Dict[str, Any], updates: Mapping[str, Any]) -> None:
    """Recursively merge mappings into the target dictionary."""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
            continue
        target[key] = value


def _json_ready(value: Any) -> Any:
    """Convert a nested structure into JSON-serializable Python values."""
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


class EpisodeWriter:
    """Write per-episode metadata, frames, and image assets."""

    def __init__(self, output_dir: Path, row_group_size: int = DEFAULT_ROW_GROUP_SIZE) -> None:
        self._output_dir = Path(output_dir)
        self._episodes_dir = self._output_dir / 'episodes'
        self._episode_dir: Optional[Path] = None
        self._last_finalized_episode_dir: Optional[Path] = None
        self._parquet_writer: Optional[pq.ParquetWriter] = None
        self._frame_buffer: List[Dict[str, Any]] = []
        self._row_group_size = int(row_group_size)
        self._frame_index = 0
        self._meta: Dict[str, Any] = {}
        self._episode_id: Optional[int] = None
        self._episode_name: Optional[str] = None
        if self._row_group_size <= 0:
            raise ValueError('row_group_size must be positive.')

    @property
    def is_active(self) -> bool:
        """Return true when an episode is open for writing."""
        return self._parquet_writer is not None

    @property
    def episode_dir(self) -> Optional[Path]:
        """Return the active episode directory."""
        return self._episode_dir

    @property
    def frame_index(self) -> int:
        """Return the number of written frames."""
        return self._frame_index

    @property
    def episode_id(self) -> Optional[int]:
        """Return the active episode id when available."""
        return self._episode_id

    def start_episode(self, metadata: Mapping[str, Any]) -> Path:
        """Create the next episode directory and write its initial metadata."""
        self._episodes_dir.mkdir(parents=True, exist_ok=True)
        episode_id = self._next_episode_id()
        self._episode_dir = self._episodes_dir / f'episode_{episode_id:06d}'
        (self._episode_dir / 'images' / 'wrist').mkdir(parents=True, exist_ok=True)
        (self._episode_dir / 'images' / 'base').mkdir(parents=True, exist_ok=True)
        self._frame_index = 0
        self._meta = dict(metadata)
        self._episode_id = episode_id
        self._episode_name = self._episode_dir.name
        self._write_meta()
        self._frame_buffer = []
        self._parquet_writer = pq.ParquetWriter(
            str(self._episode_dir / 'frames.parquet'),
            recorder_schema(),
        )
        return self._episode_dir

    def update_metadata(self, updates: Mapping[str, Any]) -> None:
        """Merge metadata updates and rewrite meta.json."""
        if not self.is_active:
            return
        _deep_update(self._meta, dict(updates))
        self._write_meta()

    def write_frame(
        self,
        frame: Mapping[str, Any],
        images: Mapping[str, Optional[ImagePayload]],
    ) -> None:
        """Append one Parquet frame and save any matching image assets."""
        if not self.is_active or self._episode_dir is None:
            raise RuntimeError('Cannot write a frame without an active episode.')

        frame_record = _json_ready(dict(frame))

        for camera_name in ('base', 'wrist'):
            payload = images.get(camera_name)
            image_path = None
            if payload is not None:
                image_path = self._write_image(camera_name, payload, self._frame_index)
            frame_record[f'observation.{camera_name}_image'] = {
                'bytes': None,
                'path': image_path,
            }

        self._frame_buffer.append(frame_record)
        if len(self._frame_buffer) >= self._row_group_size:
            self._flush_frames()
        self._frame_index += 1

    def finalize(self) -> None:
        """Finalize the active episode."""
        if not self.is_active or self._parquet_writer is None:
            return
        self._flush_frames()
        self._write_meta()
        self._parquet_writer.close()
        self._parquet_writer = None
        self._last_finalized_episode_dir = self._episode_dir
        self._episode_dir = None

    def update_last_episode_metadata(self, updates: Mapping[str, Any]) -> bool:
        """Rewrite the most recently opened episode metadata."""
        if self._last_finalized_episode_dir is None:
            return False

        meta_path = self._last_finalized_episode_dir / 'meta.json'
        if not meta_path.exists():
            return False

        with meta_path.open('r', encoding='utf-8') as handle:
            current_meta = json.load(handle)

        _deep_update(current_meta, dict(updates))

        with meta_path.open('w', encoding='utf-8') as handle:
            json.dump(_json_ready(current_meta), handle, indent=2, sort_keys=True)
            handle.write('\n')

        if self.is_active:
            self._meta = current_meta
        return True

    def _write_image(self, camera_name: str, payload: ImagePayload, index: int) -> str:
        """Write one camera frame and return its path relative to the episode root."""
        assert self._episode_dir is not None
        relative_path = Path('images') / camera_name / f'{index:06d}.jpg'
        absolute_path = self._episode_dir / relative_path
        payload.image.convert('RGB').save(absolute_path, format='JPEG', quality=95)
        return relative_path.as_posix()

    def _write_meta(self) -> None:
        """Write meta.json into the active episode directory."""
        if self._episode_dir is None:
            return
        meta_path = self._episode_dir / 'meta.json'
        with meta_path.open('w', encoding='utf-8') as handle:
            json.dump(_json_ready(self._meta), handle, indent=2, sort_keys=True)
            handle.write('\n')

    def _next_episode_id(self) -> int:
        """Return the next available numeric episode id."""
        highest = 0
        for directory in self._episodes_dir.glob('episode_*'):
            try:
                highest = max(highest, int(directory.name.split('_')[-1]))
            except ValueError:
                continue
        return highest + 1

    def _flush_frames(self) -> None:
        """Write the buffered frames as one Parquet row group."""
        if not self._frame_buffer:
            return
        if self._parquet_writer is None:
            raise RuntimeError('Cannot flush frames without an active Parquet writer.')
        table = pa.Table.from_pylist(self._frame_buffer, schema=recorder_schema())
        self._parquet_writer.write_table(table)
        self._frame_buffer = []
