"""Small filtering helpers for recorder signal conditioning."""

from __future__ import annotations

from typing import Iterable, List, Optional


WRENCH_EMA_ALPHA = 0.1


class ExponentialMovingAverage:
    """Apply an exponential moving average to fixed-size vectors."""

    def __init__(self, alpha: float, vector_size: int) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError('EMA alpha must be in the range (0.0, 1.0].')
        if vector_size <= 0:
            raise ValueError('EMA vector_size must be positive.')
        self._alpha = float(alpha)
        self._vector_size = int(vector_size)
        self._previous: Optional[List[float]] = None

    def reset(self) -> None:
        """Forget the previous filtered value."""
        self._previous = None

    def update(self, sample: Iterable[float]) -> List[float]:
        """Return the next filtered vector."""
        values = [float(value) for value in sample]
        if len(values) != self._vector_size:
            raise ValueError(
                f'Expected EMA sample of length {self._vector_size}, got {len(values)}.'
            )

        if self._previous is None:
            self._previous = values
            return list(values)

        filtered = [
            self._alpha * value + (1.0 - self._alpha) * previous
            for value, previous in zip(values, self._previous)
        ]
        self._previous = filtered
        return list(filtered)
