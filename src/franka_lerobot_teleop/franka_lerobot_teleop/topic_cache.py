"""Caches the latest message for each configured recorder input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TopicCache:
    """Mutable latest-sample cache for one topic."""

    key: str
    latest_message: Optional[Any] = None
    latest_payload: Optional[Any] = None
    source_timestamp_ns: Optional[int] = None
    receipt_timestamp_ns: Optional[int] = None

    def update(
        self,
        message: Any,
        payload: Any,
        source_timestamp_ns: Optional[int],
        receipt_timestamp_ns: int,
    ) -> None:
        """Store the newest message and its normalized payload."""
        self.latest_message = message
        self.latest_payload = payload
        self.source_timestamp_ns = source_timestamp_ns
        self.receipt_timestamp_ns = receipt_timestamp_ns

    @property
    def has_message(self) -> bool:
        """Return true once the cache has seen at least one message."""
        return self.latest_message is not None

    def is_stale(self, now_ns: int, threshold_ns: int) -> bool:
        """Return true when the cached sample is older than the threshold."""
        if self.receipt_timestamp_ns is None:
            return True
        return (now_ns - self.receipt_timestamp_ns) > threshold_ns
