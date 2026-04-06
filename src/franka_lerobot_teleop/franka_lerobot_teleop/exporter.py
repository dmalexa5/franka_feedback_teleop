"""Standalone exporter from internal episodes into a LeRobot-friendly layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - optional runtime dependency
    pa = None
    pq = None


REQUIRED_FRAME_FIELDS = (
    'timestamp',
    'observation',
    'action',
    'source_timestamps',
    'receipt_timestamps',
)


def flatten_record(record: Mapping[str, Any], prefix: str = '') -> Dict[str, Any]:
    """Flatten a nested mapping using dot-separated keys."""
    flattened: Dict[str, Any] = {}
    for key, value in record.items():
        new_key = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            flattened.update(flatten_record(value, new_key))
        else:
            flattened[new_key] = value
    return flattened


def load_episode(episode_dir: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Load one internal episode directory."""
    meta_path = episode_dir / 'meta.json'
    frames_path = episode_dir / 'frames.jsonl'
    with meta_path.open('r', encoding='utf-8') as handle:
        meta = json.load(handle)
    with frames_path.open('r', encoding='utf-8') as handle:
        frames = [json.loads(line) for line in handle if line.strip()]
    return meta, frames


def validate_episode(
    episode_dir: Path,
    meta: Mapping[str, Any],
    frames: Sequence[Mapping[str, Any]],
) -> None:
    """Validate an internal episode before export."""
    if 'episode_name' not in meta:
        raise ValueError(f'{episode_dir} is missing episode_name in meta.json.')
    for field in REQUIRED_FRAME_FIELDS:
        if not frames:
            break
        if field not in frames[0]:
            raise ValueError(f'{episode_dir} is missing required frame field {field!r}.')

    for frame in frames:
        for camera_name in ('wrist', 'base'):
            path = (
                frame.get('observation', {})
                .get('images', {})
                .get(camera_name, {})
                .get('path')
            )
            if path and not (episode_dir / path).exists():
                raise ValueError(f'Missing referenced image file: {episode_dir / path}')


def ensure_parquet_support() -> None:
    """Raise a clear error when pyarrow is unavailable."""
    if pa is None or pq is None:
        raise RuntimeError(
            'Parquet export requires pyarrow. Install python3-pyarrow or pip install pyarrow.'
        )


def export_dataset(input_root: Path, output_dir: Path) -> List[Dict[str, Any]]:
    """Export all internal episodes found under the input root."""
    ensure_parquet_support()
    episodes_dir = input_root / 'episodes'
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'meta').mkdir(exist_ok=True)
    (output_dir / 'data').mkdir(exist_ok=True)
    (output_dir / 'images').mkdir(exist_ok=True)

    exported: List[Dict[str, Any]] = []
    for episode_dir in sorted(path for path in episodes_dir.glob('episode_*') if path.is_dir()):
        exported.append(export_episode(episode_dir, output_dir))

    info = {
        'format': 'lerobot_friendly',
        'source_root': str(input_root),
        'episode_count': len(exported),
        'episodes': [item['episode_name'] for item in exported],
    }
    with (output_dir / 'meta' / 'info.json').open('w', encoding='utf-8') as handle:
        json.dump(info, handle, indent=2, sort_keys=True)
        handle.write('\n')

    with (output_dir / 'meta' / 'episodes.jsonl').open('w', encoding='utf-8') as handle:
        for item in exported:
            handle.write(json.dumps(item, separators=(',', ':')) + '\n')

    return exported


def export_episode(episode_dir: Path, output_dir: Path) -> Dict[str, Any]:
    """Export one internal episode into the dataset layout."""
    meta, frames = load_episode(episode_dir)
    validate_episode(episode_dir, meta, frames)

    episode_name = meta['episode_name']
    exported_images_dir = output_dir / 'images' / episode_name
    _copy_images(episode_dir / 'images', exported_images_dir)

    rows: List[Dict[str, Any]] = []
    for frame in frames:
        updated = json.loads(json.dumps(frame))
        for camera_name in ('wrist', 'base'):
            image_path = (
                updated.get('observation', {})
                .get('images', {})
                .get(camera_name, {})
                .get('path')
            )
            if image_path:
                updated['observation']['images'][camera_name]['path'] = (
                    Path('images') / episode_name / image_path
                ).as_posix()
        rows.append(flatten_record(updated))

    table = pa.Table.from_pylist(rows)
    parquet_path = output_dir / 'data' / f'{episode_name}.parquet'
    pq.write_table(table, parquet_path)

    return {
        'episode_id': meta.get('episode_id'),
        'episode_name': episode_name,
        'frame_count': len(rows),
        'start_timestamp': meta.get('start_timestamp'),
        'end_timestamp': meta.get('end_timestamp'),
        'parquet_path': Path('data') / parquet_path.name,
    }


def _copy_images(source_dir: Path, target_dir: Path) -> None:
    """Copy an episode image tree into the exported dataset."""
    if not source_dir.exists():
        return
    for file_path in source_dir.rglob('*'):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(source_dir)
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse exporter CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Export internal episodes into a LeRobot-friendly layout.'
    )
    parser.add_argument(
        '--input-root',
        required=True,
        help='Root directory containing the internal episodes/ tree.',
    )
    parser.add_argument('--output-dir', required=True, help='Output directory for the exported dataset.')
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the standalone exporter."""
    args = parse_args(argv)
    export_dataset(Path(args.input_root).expanduser(), Path(args.output_dir).expanduser())
    return 0
