"""Tests for recorder filtering helpers."""

from __future__ import annotations

import pytest

from franka_feedback_teleop.filter import ExponentialMovingAverage, WRENCH_EMA_ALPHA


def test_wrench_alpha_constant() -> None:
    assert WRENCH_EMA_ALPHA == 0.1


def test_ema_first_sample_is_unchanged() -> None:
    ema = ExponentialMovingAverage(0.1, 3)

    assert ema.update([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]


def test_ema_updates_and_resets() -> None:
    ema = ExponentialMovingAverage(0.1, 2)

    assert ema.update([0.0, 10.0]) == [0.0, 10.0]
    assert ema.update([10.0, 20.0]) == [1.0, 11.0]

    ema.reset()

    assert ema.update([5.0, 6.0]) == [5.0, 6.0]


def test_ema_validates_vector_size() -> None:
    ema = ExponentialMovingAverage(0.1, 6)

    with pytest.raises(ValueError, match='Expected EMA sample of length 6'):
        ema.update([1.0, 2.0])
