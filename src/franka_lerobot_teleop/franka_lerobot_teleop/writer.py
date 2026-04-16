"""Episode writing helpers for the recorder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import cv2
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .adapters import ImagePayload


DEFAULT_CHUNK_INDEX = 0
DEFAULT_ROW_GROUP_SIZE = 128
CAMERA_VIDEO_KEYS = {
    'base': 'observation.images.base',
    'wrist': 'observation.images.wrist',
}
LOW_DIMENSIONAL_FEATURES = (
    'action.state',
    'action.wrench',
    'action.gripper',
    'phase',
    'observation.pose',
    'observation.wrench',
    'timestamp',
)


def recorder_schema() -> pa.Schema:
    """Return the recorder Parquet schema for low-dimensional frame data."""
    return pa.schema([
        pa.field('action.state', pa.list_(pa.float64())),
        pa.field('action.wrench', pa.list_(pa.float64())),
        pa.field('action.gripper', pa.float64()),
        pa.field('phase', pa.int64()),
        pa.field('observation.pose', pa.list_(pa.float64())),
        pa.field('observation.wrench', pa.list_(pa.float64())),
        pa.field('timestamp', pa.float64()),
        pa.field('frame_index', pa.int64()),
        pa.field('episode_index', pa.int64()),
        pa.field('index', pa.int64()),
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
    if isinstance(value, np.generic):
        return value.item()
    return value


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSON lines from a metadata file."""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def _write_jsonl(path: Path, records: List[Mapping[str, Any]]) -> None:
    """Rewrite a JSON lines metadata file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for record in records:
            json.dump(_json_ready(dict(record)), handle, sort_keys=True)
            handle.write('\n')


class EpisodeWriter:
    """Write LeRobot-style episode Parquet files and synchronized MP4 videos."""

    def __init__(self, output_dir: Path, row_group_size: int = DEFAULT_ROW_GROUP_SIZE) -> None:
        self._output_dir = Path(output_dir)
        self._data_dir = self._output_dir / 'data' / f'chunk-{DEFAULT_CHUNK_INDEX:03d}'
        self._videos_dir = self._output_dir / 'videos' / f'chunk-{DEFAULT_CHUNK_INDEX:03d}'
        self._meta_dir = self._output_dir / 'meta'
        self._info_path = self._meta_dir / 'info.json'
        self._tasks_path = self._meta_dir / 'tasks.jsonl'
        self._episodes_path = self._meta_dir / 'episodes.jsonl'
        self._episode_stats_path = self._meta_dir / 'episodes_stats.jsonl'

        self._episode_path: Optional[Path] = None
        self._last_finalized_episode_id: Optional[int] = None
        self._parquet_writer: Optional[pq.ParquetWriter] = None
        self._video_writers: Dict[str, cv2.VideoWriter] = {}
        self._video_sizes: Dict[str, Tuple[int, int]] = {}
        self._video_paths: Dict[str, Path] = {}
        self._frame_buffer: List[Dict[str, Any]] = []
        self._stats_rows: List[Dict[str, Any]] = []
        self._row_group_size = int(row_group_size)
        self._frame_index = 0
        self._global_frame_start = 0
        self._meta: Dict[str, Any] = {}
        self._episode_id: Optional[int] = None
        self._task_index = 0
        self._fps = 30.0
        if self._row_group_size <= 0:
            raise ValueError('row_group_size must be positive.')

    @property
    def is_active(self) -> bool:
        """Return true when an episode is open for writing."""
        return self._parquet_writer is not None

    @property
    def episode_dir(self) -> Optional[Path]:
        """Return the dataset root while an episode is active."""
        return self._output_dir if self.is_active else None

    @property
    def episode_path(self) -> Optional[Path]:
        """Return the active episode Parquet path."""
        return self._episode_path

    @property
    def frame_index(self) -> int:
        """Return the number of written frames in the active episode."""
        return self._frame_index

    @property
    def episode_id(self) -> Optional[int]:
        """Return the active episode id when available."""
        return self._episode_id

    def start_episode(self, metadata: Mapping[str, Any]) -> Path:
        """Create the next episode Parquet file and prepare video output."""
        self._ensure_dataset_dirs()
        episode_id = self._next_episode_id()
        self._episode_path = self._data_dir / f'episode_{episode_id:06d}.parquet'
        self._frame_index = 0
        self._global_frame_start = self._next_global_frame_index()
        self._meta = dict(metadata)
        self._meta['task'] = str(self._meta.get('task') or 'default_task')
        self._episode_id = episode_id
        self._task_index = self._task_index_for(self._meta['task'])
        self._fps = float(self._meta.get('frequency') or 30.0)
        self._frame_buffer = []
        self._stats_rows = []
        self._video_writers = {}
        self._video_sizes = {}
        self._video_paths = {}
        self._parquet_writer = pq.ParquetWriter(
            str(self._episode_path),
            recorder_schema(),
        )
        return self._episode_path

    def update_metadata(self, updates: Mapping[str, Any]) -> None:
        """Merge metadata updates for the active episode."""
        if not self.is_active:
            return
        _deep_update(self._meta, dict(updates))

    def write_frame(
        self,
        frame: Mapping[str, Any],
        images: Mapping[str, Optional[ImagePayload]],
    ) -> None:
        """Append one Parquet frame and one synchronized video frame per camera."""
        if not self.is_active or self._episode_path is None or self._episode_id is None:
            raise RuntimeError('Cannot write a frame without an active episode.')

        frame_record = _json_ready(dict(frame))
        frame_record.pop('observation.base_image', None)
        frame_record.pop('observation.wrist_image', None)
        frame_record['episode_index'] = int(self._episode_id)
        frame_record['frame_index'] = int(self._frame_index)
        frame_record['index'] = int(self._global_frame_start + self._frame_index)
        frame_record['task_index'] = int(self._task_index)

        for camera_name in ('base', 'wrist'):
            payload = images.get(camera_name)
            if payload is not None:
                self._write_video_frame(camera_name, payload)

        self._frame_buffer.append(frame_record)
        self._stats_rows.append(frame_record)
        if len(self._frame_buffer) >= self._row_group_size:
            self._flush_frames()
        self._frame_index += 1

    def finalize(self) -> None:
        """Finalize the active episode."""
        if not self.is_active or self._parquet_writer is None:
            return
        try:
            self._flush_frames()
            self._parquet_writer.close()
            self._append_episode_metadata_record()
            self._append_episode_stats_record()
            self._write_info()
            self._last_finalized_episode_id = self._episode_id
        finally:
            self._parquet_writer = None
            self._release_video_writers()
            self._episode_path = None

    def update_last_episode_metadata(self, updates: Mapping[str, Any]) -> bool:
        """Rewrite the most recently finalized episode metadata record."""
        if self._last_finalized_episode_id is None or not self._episodes_path.exists():
            return False

        records = _load_jsonl(self._episodes_path)
        updated = False
        for record in records:
            if record.get('episode_index') == self._last_finalized_episode_id:
                _deep_update(record, dict(updates))
                updated = True

        if not updated:
            return False

        _write_jsonl(self._episodes_path, records)
        if self.is_active:
            _deep_update(self._meta, dict(updates))
        return True

    def _ensure_dataset_dirs(self) -> None:
        """Create the standard episode-based LeRobot dataset directories."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        for video_key in CAMERA_VIDEO_KEYS.values():
            (self._videos_dir / video_key).mkdir(parents=True, exist_ok=True)

    def _task_index_for(self, task: str) -> int:
        """Return a stable task index, appending to tasks.jsonl if needed."""
        records = _load_jsonl(self._tasks_path)
        for record in records:
            if record.get('task') == task:
                return int(record['task_index'])

        task_index = 0
        if records:
            task_index = max(int(record['task_index']) for record in records) + 1
        records.append({'task_index': task_index, 'task': task})
        _write_jsonl(self._tasks_path, records)
        return task_index

    def _write_video_frame(self, camera_name: str, payload: ImagePayload) -> None:
        """Write one RGB camera payload into its episode MP4 stream."""
        video_key = CAMERA_VIDEO_KEYS[camera_name]
        if video_key not in self._video_writers:
            self._open_video_writer(video_key, payload)

        width, height = self._video_sizes[video_key]
        rgb_frame = np.asarray(payload.image.convert('RGB'))
        if rgb_frame.shape[1] != width or rgb_frame.shape[0] != height:
            rgb_frame = cv2.resize(rgb_frame, (width, height), interpolation=cv2.INTER_AREA)
        bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
        self._video_writers[video_key].write(bgr_frame)

    def _open_video_writer(self, video_key: str, payload: ImagePayload) -> None:
        """Open a new MP4 writer for one camera stream."""
        if self._episode_id is None:
            raise RuntimeError('Cannot open a video writer without an active episode id.')
        video_path = self._videos_dir / video_key / f'episode_{self._episode_id:06d}.mp4'
        video_path.parent.mkdir(parents=True, exist_ok=True)
        width = int(payload.width)
        height = int(payload.height)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(video_path), fourcc, self._fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError(f'Failed to open MP4 writer for {video_path}.')
        self._video_writers[video_key] = writer
        self._video_sizes[video_key] = (width, height)
        self._video_paths[video_key] = video_path

    def _release_video_writers(self) -> None:
        """Release every open OpenCV video writer."""
        for writer in self._video_writers.values():
            writer.release()
        self._video_writers = {}

    def _append_episode_metadata_record(self) -> None:
        """Append one finalized episode record to episodes.jsonl."""
        if self._episode_id is None:
            return
        record = {
            'episode_index': self._episode_id,
            'length': self._frame_index,
            'tasks': [self._meta.get('task', 'default_task')],
            'success': self._meta.get('success'),
            'duration': self._meta.get('duration', 0.0),
            'episode_chunk': DEFAULT_CHUNK_INDEX,
            'dataset_from_index': self._global_frame_start,
            'dataset_to_index': self._global_frame_start + self._frame_index,
            'data_path': self._episode_path.relative_to(self._output_dir).as_posix()
            if self._episode_path is not None
            else None,
            'video_paths': {
                key: path.relative_to(self._output_dir).as_posix()
                for key, path in sorted(self._video_paths.items())
            },
        }
        records = _load_jsonl(self._episodes_path)
        records.append(record)
        _write_jsonl(self._episodes_path, records)

    def _append_episode_stats_record(self) -> None:
        """Append low-dimensional per-episode statistics to episodes_stats.jsonl."""
        if self._episode_id is None:
            return
        record = {
            'episode_index': self._episode_id,
            'stats': self._episode_stats(),
        }
        records = _load_jsonl(self._episode_stats_path)
        records.append(record)
        _write_jsonl(self._episode_stats_path, records)

    def _episode_stats(self) -> Dict[str, Dict[str, List[float]]]:
        """Return per-feature mean/std/min/max summaries for the active episode."""
        stats: Dict[str, Dict[str, List[float]]] = {}
        if not self._stats_rows:
            return stats

        for feature in LOW_DIMENSIONAL_FEATURES:
            values = []
            for row in self._stats_rows:
                value = row.get(feature)
                if value is None:
                    continue
                if isinstance(value, list):
                    values.append([float(item) for item in value])
                else:
                    values.append([float(value)])
            if not values:
                continue
            array = np.asarray(values, dtype=np.float64)
            stats[feature] = {
                'mean': array.mean(axis=0).tolist(),
                'std': array.std(axis=0).tolist(),
                'min': array.min(axis=0).tolist(),
                'max': array.max(axis=0).tolist(),
            }
        return stats

    def _write_info(self) -> None:
        """Write LeRobot dataset-level metadata."""
        episodes = _load_jsonl(self._episodes_path)
        tasks = _load_jsonl(self._tasks_path)
        info = {
            'codebase_version': 'v2.1',
            'robot_type': 'franka',
            'total_episodes': len(episodes),
            'total_frames': sum(int(record.get('length', 0)) for record in episodes),
            'total_tasks': len(tasks),
            'total_videos': sum(len(record.get('video_paths', {})) for record in episodes),
            'total_chunks': 1,
            'chunks_size': 1000,
            'fps': self._fps,
            'splits': {'train': f'0:{len(episodes)}'},
            'data_path': 'data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet',
            'video_path': (
                'videos/chunk-{episode_chunk:03d}/{video_key}/'
                'episode_{episode_index:06d}.mp4'
            ),
            'features': self._feature_metadata(),
        }
        with self._info_path.open('w', encoding='utf-8') as handle:
            json.dump(_json_ready(info), handle, indent=2, sort_keys=True)
            handle.write('\n')

    def _feature_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Return dataset feature metadata for info.json."""
        features: Dict[str, Dict[str, Any]] = {
            'action.state': {
                'dtype': 'float64',
                'shape': [7],
                'names': [
                    'joint_0',
                    'joint_1',
                    'joint_2',
                    'joint_3',
                    'joint_4',
                    'joint_5',
                    'joint_6',
                ],
            },
            'action.wrench': {
                'dtype': 'float64',
                'shape': [6],
                'names': ['fx', 'fy', 'fz', 'tx', 'ty', 'tz'],
            },
            'action.gripper': {'dtype': 'float64', 'shape': [1], 'names': ['width']},
            'phase': {'dtype': 'int64', 'shape': [1], 'names': None},
            'observation.pose': {
                'dtype': 'float64',
                'shape': [7],
                'names': ['x', 'y', 'z', 'qx', 'qy', 'qz', 'qw'],
            },
            'observation.wrench': {
                'dtype': 'float64',
                'shape': [6],
                'names': ['fx', 'fy', 'fz', 'tx', 'ty', 'tz'],
            },
            'timestamp': {'dtype': 'float64', 'shape': [1], 'names': None},
            'frame_index': {'dtype': 'int64', 'shape': [1], 'names': None},
            'episode_index': {'dtype': 'int64', 'shape': [1], 'names': None},
            'index': {'dtype': 'int64', 'shape': [1], 'names': None},
            'task_index': {'dtype': 'int64', 'shape': [1], 'names': None},
        }

        features.update(self._existing_video_features())
        for video_key, size in self._video_sizes.items():
            width, height = size
            features[video_key] = {
                'dtype': 'video',
                'shape': [height, width, 3],
                'names': ['height', 'width', 'channel'],
                'info': {
                    'video.fps': self._fps,
                    'video.codec': 'mp4v',
                },
            }
        return features

    def _existing_video_features(self) -> Dict[str, Dict[str, Any]]:
        """Load existing video feature metadata so info.json keeps prior cameras."""
        if not self._info_path.exists():
            return {}
        with self._info_path.open('r', encoding='utf-8') as handle:
            info = json.load(handle)
        features = info.get('features', {})
        if not isinstance(features, dict):
            return {}
        return {
            key: value
            for key, value in features.items()
            if isinstance(value, dict) and value.get('dtype') == 'video'
        }

    def _next_episode_id(self) -> int:
        """Return the next available zero-based episode id."""
        highest = -1
        for episode_path in self._data_dir.glob('episode_*.parquet'):
            try:
                highest = max(highest, int(episode_path.stem.split('_')[-1]))
            except ValueError:
                continue
        return highest + 1

    def _next_global_frame_index(self) -> int:
        """Return the next global frame index from episode metadata or data files."""
        highest = 0
        for record in _load_jsonl(self._episodes_path):
            if 'dataset_to_index' in record:
                highest = max(highest, int(record['dataset_to_index']))
            elif 'dataset_from_index' in record and 'length' in record:
                highest = max(highest, int(record['dataset_from_index']) + int(record['length']))

        if highest:
            return highest

        for episode_path in self._data_dir.glob('episode_*.parquet'):
            try:
                table = pq.read_table(episode_path, columns=['index'])
            except Exception:
                continue
            if table.num_rows:
                highest = max(highest, int(table.column('index').to_pylist()[-1]) + 1)
        return highest

    def _flush_frames(self) -> None:
        """Write the buffered frames as one Parquet row group."""
        if not self._frame_buffer:
            return
        if self._parquet_writer is None:
            raise RuntimeError('Cannot flush frames without an active Parquet writer.')
        table = pa.Table.from_pylist(self._frame_buffer, schema=recorder_schema())
        self._parquet_writer.write_table(table)
        self._frame_buffer = []
