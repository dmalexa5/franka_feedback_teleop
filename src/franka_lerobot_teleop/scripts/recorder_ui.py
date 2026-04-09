#!/usr/bin/env python3
"""Publish start and stop recorder commands from the command line."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Mapping, Optional, Sequence

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
        '--task',
        help='Task description to store in meta.json. Required for start.',
    )
    parser.add_argument(
        '--topic',
        default='/franka_lerobot_teleop/command',
        help='Recorder command topic. Defaults to /franka_lerobot_teleop/command.',
    )
    args = parser.parse_args(argv)
    if args.command == 'start' and not args.task:
        parser.error('--task is required when command is start.')
    return args


def publish_command(publisher: Any, node: Node, payload: Mapping[str, Any]) -> None:
    """Publish one structured recorder command."""
    deadline = time.monotonic() + 2.0
    while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.05)

    message = String()
    message.data = json.dumps(payload, separators=(',', ':'))
    publisher.publish(message)
    rclpy.spin_once(node, timeout_sec=0.2)
    time.sleep(0.1)


def prompt_success() -> bool:
    """Prompt the operator for an episode success label."""
    while True:
        answer = input('Was the episode successful? [y/n]: ').strip().lower()
        if answer in {'y', 'yes'}:
            return True
        if answer in {'n', 'no'}:
            return False
        print("Please answer 'y' or 'n'.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Publish one command and exit."""
    args = parse_args(argv)
    rclpy.init(args=None)
    node = Node('franka_lerobot_recorder_ui')
    publisher = node.create_publisher(String, args.topic, 10)

    if args.command == 'start':
        publish_command(publisher, node, {'command': 'start', 'task': args.task})
    else:
        publish_command(publisher, node, {'command': 'stop'})
        success = prompt_success()
        publish_command(
            publisher,
            node,
            {'command': 'annotate_last_episode', 'success': success},
        )

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
