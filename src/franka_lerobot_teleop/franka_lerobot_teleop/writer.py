"""Episode writing helpers for the recorder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .adapters import ImagePayload


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

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = Path(output_dir)
        self._episodes_dir = self._output_dir / 'episodes'
        self._episode_dir: Optional[Path] = None
        self._frames_handle = None
        self._frame_index = 0
        self._meta: Dict[str, Any] = {}

    @property
    def is_active(self) -> bool:
        """Return true when an episode is open for writing."""
        return self._frames_handle is not None

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
        episode_id = self._meta.get('episode_id')
        if episode_id is None:
            return None
        return int(episode_id)

    def start_episode(self, metadata: Mapping[str, Any]) -> Path:
        """Create the next episode directory and write its initial metadata."""
        self._episodes_dir.mkdir(parents=True, exist_ok=True)
        episode_id = self._next_episode_id()
        self._episode_dir = self._episodes_dir / f'episode_{episode_id:06d}'
        (self._episode_dir / 'images' / 'wrist').mkdir(parents=True, exist_ok=True)
        (self._episode_dir / 'images' / 'base').mkdir(parents=True, exist_ok=True)
        self._frame_index = 0
        self._meta = dict(metadata)
        self._meta['episode_id'] = episode_id
        self._meta['episode_name'] = self._episode_dir.name
        self._meta['frame_count'] = 0
        self._write_meta()
        self._frames_handle = (self._episode_dir / 'frames.jsonl').open('w', encoding='utf-8')
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
        """Append one JSONL frame and save any matching image assets."""
        if not self.is_active or self._episode_dir is None or self._frames_handle is None:
            raise RuntimeError('Cannot write a frame without an active episode.')

        frame_record = json.loads(json.dumps(_json_ready(dict(frame))))

        for camera_name, payload in images.items():
            image_path = None
            if payload is not None:
                image_path = self._write_image(camera_name, payload, self._frame_index)
            if camera_name == 'base':
                frame_record['observation']['image'] = image_path
            elif camera_name == 'wrist':
                frame_record['observation']['wrist_image'] = image_path

        self._frames_handle.write(json.dumps(frame_record, separators=(',', ':')) + '\n')
        self._frames_handle.flush()
        self._frame_index += 1
        self._meta['frame_count'] = self._frame_index

    def finalize(self, end_timestamp_ns: int) -> None:
        """Finalize the active episode and persist final metadata."""
        if not self.is_active or self._frames_handle is None:
            return
        self._meta['end_timestamp'] = int(end_timestamp_ns)
        self._meta['frame_count'] = self._frame_index
        self._write_meta()
        self._frames_handle.close()
        self._frames_handle = None

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
