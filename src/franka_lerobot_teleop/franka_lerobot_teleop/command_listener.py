"""Structured recorder command subscription wrapper."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from rclpy.node import Node
from std_msgs.msg import String


class CommandListener:
    """Listen for recorder lifecycle commands on a String topic."""

    def __init__(
        self,
        node: Node,
        topic_name: str,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        self._node = node
        self._callback = callback
        self._subscription = node.create_subscription(String, topic_name, self._on_message, 10)

    def _on_message(self, message: String) -> None:
        """Normalize the incoming command and forward valid values."""
        payload = self._parse_payload(message.data)
        if payload is None:
            self._node.get_logger().warn(
                f"Ignoring unsupported recorder command '{message.data}'."
            )
            return
        self._callback(payload)

    def _parse_payload(self, data: str) -> Optional[Dict[str, Any]]:
        """Accept either legacy plain-text commands or JSON command objects."""
        normalized = data.strip()
        if not normalized:
            return None

        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError:
            return self._parse_legacy_command(normalized)

        if not isinstance(payload, dict):
            return None

        command = str(payload.get('command', '')).strip().lower()
        if command == 'start':
            task = payload.get('task', '')
            if task is None:
                task = ''
            return {'command': 'start', 'task': str(task)}
        if command == 'stop':
            return {'command': 'stop'}
        if command == 'annotate_last_episode':
            success = payload.get('success')
            if not isinstance(success, bool):
                return None
            return {'command': 'annotate_last_episode', 'success': success}
        return None

    def _parse_legacy_command(self, command: str) -> Optional[Dict[str, Any]]:
        """Translate old plain-text commands into the structured contract."""
        normalized = command.strip().lower()
        if normalized == 'start':
            return {'command': 'start', 'task': ''}
        if normalized == 'stop':
            return {'command': 'stop'}
        return None
