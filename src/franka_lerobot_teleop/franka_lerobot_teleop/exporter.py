"""Standalone exporter from internal episodes into a nested Parquet layout."""

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
    'action',
    'timestamp',
    'observation',
    'frame_index',
    'episode_index',
)


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
    for field in REQUIRED_FRAME_FIELDS:
        if not frames:
            break
        if field not in frames[0]:
            raise ValueError(f'{episode_dir} is missing required frame field {field!r}.')

    if frames:
        _require_nested_field(episode_dir, frames[0], ('action', 'ee_pose'))
        _require_nested_field(episode_dir, frames[0], ('action', 'gripper'))
        _require_nested_field(episode_dir, frames[0], ('observation', 'images', 'base'))
        _require_nested_field(episode_dir, frames[0], ('observation', 'images', 'wrist'))
        _require_nested_field(episode_dir, frames[0], ('observation', 'state', 'q'))
        _require_nested_field(episode_dir, frames[0], ('observation', 'state', 'ee_pose'))
        _require_nested_field(episode_dir, frames[0], ('observation', 'state', 'wrench'))

    for frame in frames:
        images = frame.get('observation', {}).get('images', {})
        for image_key in ('base', 'wrist'):
            path = images.get(image_key)
            if path and not (episode_dir / path).exists():
                raise ValueError(f'Missing referenced image file: {episode_dir / path}')


def _require_nested_field(
    episode_dir: Path,
    frame: Mapping[str, Any],
    path: Tuple[str, ...],
) -> None:
    """Require that a nested field path exists in a frame."""
    current: Any = frame
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise ValueError(
                f"{episode_dir} is missing required frame field {'.'.join(path)!r}."
            )
        current = current[key]


def export_schema() -> 'pa.Schema':
    """Return the Parquet schema for nested export rows."""
    assert pa is not None
    image_struct = pa.struct([
        pa.field('bytes', pa.binary()),
        pa.field('path', pa.string()),
    ])
    return pa.schema([
        pa.field('action.ee_pose', pa.list_(pa.float64())),
        pa.field('action.gripper', pa.float64()),
        pa.field('observation.images.base', image_struct),
        pa.field('observation.images.wrist', image_struct),
        pa.field('observation.state.q', pa.list_(pa.float64())),
        pa.field('observation.state.ee_pose', pa.list_(pa.float64())),
        pa.field('observation.state.wrench', pa.list_(pa.float64())),
        pa.field('leader.q', pa.list_(pa.float64())),
        pa.field('leader.ee_pose', pa.list_(pa.float64())),
        pa.field('timestamp', pa.float64()),
        pa.field('frame_index', pa.int64()),
        pa.field('episode_index', pa.int64()),
    ])


def image_cell(episode_name: str, image_path: Optional[str]) -> Dict[str, Optional[bytes | str]]:
    """Build one Hugging Face image cell using a dataset-relative path."""
    if image_path:
        relative_image_path = Path(image_path)
        if relative_image_path.parts and relative_image_path.parts[0] == 'images':
            relative_image_path = Path(*relative_image_path.parts[1:])
        path = (Path('images') / episode_name / relative_image_path).as_posix()
    else:
        path = None
    return {'bytes': None, 'path': path}


def ensure_parquet_support() -> None:
    """Raise a clear error when pyarrow is unavailable."""
    if pa is None or pq is None:
        raise RuntimeError(
            'Parquet export requires pyarrow. Install python3-pyarrow or pip install pyarrow.'
        )


def discover_episode_dirs(input_root: Path) -> List[Path]:
    """Return episode directories from either a dataset root or a single episode path."""
    if (input_root / 'meta.json').exists() and (input_root / 'frames.jsonl').exists():
        return [input_root]

    episodes_dir = input_root / 'episodes'
    if episodes_dir.is_dir():
        return sorted(path for path in episodes_dir.glob('episode_*') if path.is_dir())

    return []


def export_dataset(input_root: Path, output_dir: Path) -> List[Dict[str, Any]]:
    """Export all internal episodes found under the input root."""
    ensure_parquet_support()
    episode_dirs = discover_episode_dirs(input_root)
    if not episode_dirs:
        raise ValueError(
            'No episodes found. Pass either a dataset root containing an episodes/ directory '
            'or a single episode directory containing meta.json and frames.jsonl.'
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'meta').mkdir(exist_ok=True)
    (output_dir / 'data').mkdir(exist_ok=True)
    (output_dir / 'images').mkdir(exist_ok=True)

    exported: List[Dict[str, Any]] = []
    for episode_dir in episode_dirs:
        exported.append(export_episode(episode_dir, output_dir))

    info = {
        'format': 'franka_lerobot_nested',
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

    episode_name = episode_dir.name
    try:
        episode_index = int(episode_name.split('_')[-1])
    except ValueError:
        episode_index = 0
    exported_images_dir = output_dir / 'images' / episode_name
    _copy_images(episode_dir / 'images', exported_images_dir)

    rows: List[Dict[str, Any]] = []
    for frame in frames:
        observation = frame.get('observation', {})
        images = observation.get('images', {})
        state = observation.get('state', {})
        action = frame.get('action', {})
        leader = frame.get('leader', {})
        rows.append({
            'action.ee_pose': list(action.get('ee_pose', [])),
            'action.gripper': float(action.get('gripper', 0.0)),
            'observation.images.base': image_cell(episode_name, images.get('base')),
            'observation.images.wrist': image_cell(episode_name, images.get('wrist')),
            'observation.state.q': list(state.get('q', [])),
            'observation.state.ee_pose': list(state.get('ee_pose', [])),
            'observation.state.wrench': list(state.get('wrench', [])),
            'leader.q': list(leader['q']) if 'q' in leader else None,
            'leader.ee_pose': list(leader['ee_pose']) if 'ee_pose' in leader else None,
            'timestamp': float(frame.get('timestamp', 0.0)),
            'frame_index': int(frame.get('frame_index', 0)),
            'episode_index': episode_index,
        })

    table = pa.Table.from_pylist(rows, schema=export_schema())
    parquet_path = output_dir / 'data' / f'{episode_name}.parquet'
    pq.write_table(table, parquet_path)

    return {
        'episode_id': episode_index,
        'episode_name': episode_name,
        'frame_count': len(rows),
        'task': meta.get('task'),
        'success': meta.get('success'),
        'duration': meta.get('duration'),
        'frequency': meta.get('frequency'),
        'parquet_path': (Path('data') / parquet_path.name).as_posix(),
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
        description='Export internal episodes into a nested Parquet layout.'
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
