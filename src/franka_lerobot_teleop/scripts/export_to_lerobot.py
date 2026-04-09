#!/usr/bin/env python3
"""Standalone entry point for the ForceVLA-shaped exporter."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from franka_lerobot_teleop.exporter import main


if __name__ == '__main__':
    raise SystemExit(main())
