"""Minimal start and stop command subscription wrapper."""

from __future__ import annotations

from typing import Callable

from rclpy.node import Node
from std_msgs.msg import String


class CommandListener:
    """Listen for recorder lifecycle commands on a String topic."""

    def __init__(self, node: Node, topic_name: str, callback: Callable[[str], None]) -> None:
        self._node = node
        self._callback = callback
        self._subscription = node.create_subscription(String, topic_name, self._on_message, 10)

    def _on_message(self, message: String) -> None:
        """Normalize the incoming command and forward valid values."""
        command = message.data.strip().lower()
        if command not in {'start', 'stop'}:
            self._node.get_logger().warn(
                f"Ignoring unsupported recorder command '{message.data}'. "
                "Expected 'start' or 'stop'."
            )
            return
        self._callback(command)
