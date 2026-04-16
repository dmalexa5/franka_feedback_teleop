#!/usr/bin/env python3
"""
Rewrite LeRobot-style episode parquet files to be more HF Dataset Viewer friendly.

What it does:
- Recursively finds .parquet files under <dataset_root>/data
- Rewrites them with:
    - write_page_index=True
    - configurable row_group_size
    - configurable compression
- Writes to a new output dataset directory by default
- Optionally replaces files in-place

Example: --outp
    python rewrite_parquet_for_hf.py \
        --input ~/franka_contact_data \
        --output ~/franka_contact_data_hf_fixed \
        --row-group-size 256 \
        --compression zstd
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input dataset root, e.g. ~/franka_contact_data",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output dataset root. If omitted with --in-place, files are rewritten in-place.",
    )
    parser.add_argument(
        "--row-group-size",
        type=int,
        default=256,
        help="Target rows per row group. Smaller is more viewer-friendly. Default: 256",
    )
    parser.add_argument(
        "--compression",
        type=str,
        default="zstd",
        choices=["zstd", "snappy", "gzip", "brotli", "lz4", "none"],
        help="Parquet compression codec. Default: zstd",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite parquet files in-place. Use carefully.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting output directory if it already exists.",
    )
    return parser.parse_args()


def expand_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path.expanduser().resolve()


def validate_args(args: argparse.Namespace) -> tuple[Path, Path | None]:
    input_root = expand_path(args.input)
    output_root = expand_path(args.output)

    if not input_root.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_root}")

    data_dir = input_root / "data"
    if not data_dir.exists():
        raise FileNotFoundError(f"Expected data directory not found: {data_dir}")

    if args.in_place:
        if output_root is not None:
            raise ValueError("Do not pass --output together with --in-place.")
    else:
        if output_root is None:
            raise ValueError("Pass --output unless using --in-place.")
        if output_root.exists():
            if args.overwrite:
                shutil.rmtree(output_root)
            else:
                raise FileExistsError(
                    f"Output path already exists: {output_root}\n"
                    f"Use --overwrite to replace it."
                )

    return input_root, output_root


def copy_non_data_dirs(input_root: Path, output_root: Path) -> None:
    """
    Copy everything except the data directory as-is.
    Then create the output data directory structure for rewritten parquet files.
    """
    for item in input_root.iterdir():
        dst = output_root / item.name
        if item.name == "data":
            continue
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)


def find_parquet_files(data_root: Path) -> list[Path]:
    return sorted(data_root.rglob("*.parquet"))


def rewrite_one_file(
    src: Path,
    dst: Path,
    row_group_size: int,
    compression: str,
) -> None:
    compression_arg = None if compression == "none" else compression

    table = pq.read_table(src)

    dst.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        dst,
        compression=compression_arg,
        row_group_size=row_group_size,
        write_page_index=True,
    )


def rewrite_dataset_out_of_place(
    input_root: Path,
    output_root: Path,
    row_group_size: int,
    compression: str,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    copy_non_data_dirs(input_root, output_root)

    input_data_root = input_root / "data"
    parquet_files = find_parquet_files(input_data_root)

    if not parquet_files:
        print(f"No parquet files found under {input_data_root}")
        return

    print(f"Found {len(parquet_files)} parquet file(s).")
    for i, src in enumerate(parquet_files, start=1):
        rel = src.relative_to(input_root)
        dst = output_root / rel
        print(f"[{i}/{len(parquet_files)}] Rewriting {rel}")
        rewrite_one_file(src, dst, row_group_size, compression)

    print(f"\nDone. Rewritten dataset saved to:\n{output_root}")


def rewrite_dataset_in_place(
    input_root: Path,
    row_group_size: int,
    compression: str,
) -> None:
    input_data_root = input_root / "data"
    parquet_files = find_parquet_files(input_data_root)

    if not parquet_files:
        print(f"No parquet files found under {input_data_root}")
        return

    print(f"Found {len(parquet_files)} parquet file(s).")
    for i, src in enumerate(parquet_files, start=1):
        tmp = src.with_suffix(".parquet.tmp")
        print(f"[{i}/{len(parquet_files)}] Rewriting {src.relative_to(input_root)}")
        rewrite_one_file(src, tmp, row_group_size, compression)
        tmp.replace(src)

    print(f"\nDone. Files rewritten in-place under:\n{input_root}")


def main() -> int:
    args = parse_args()

    try:
        input_root, output_root = validate_args(args)
    except Exception as exc:
        print(f"Argument error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.in_place:
            rewrite_dataset_in_place(
                input_root=input_root,
                row_group_size=args.row_group_size,
                compression=args.compression,
            )
        else:
            assert output_root is not None
            rewrite_dataset_out_of_place(
                input_root=input_root,
                output_root=output_root,
                row_group_size=args.row_group_size,
                compression=args.compression,
            )
    except Exception as exc:
        print(f"Rewrite failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())