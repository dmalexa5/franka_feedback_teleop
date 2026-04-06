#!/usr/bin/env python3
"""Publish start and stop recorder commands from the command line."""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for the recorder UI helper."""
    parser = argparse.ArgumentParser(
        description='Publish a start or stop command to the recorder.'
    )
    parser.add_argument('command', choices=('start', 'stop'), help='Recorder command to publish.')
    parser.add_argument(
        '--topic',
        default='/franka_lerobot_teleop/command',
        help='Recorder command topic. Defaults to /franka_lerobot_teleop/command.',
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Publish one command and exit."""
    args = parse_args(argv)
    rclpy.init(args=None)
    node = Node('franka_lerobot_recorder_ui')
    publisher = node.create_publisher(String, args.topic, 10)
    message = String()
    message.data = args.command
    publisher.publish(message)
    rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
