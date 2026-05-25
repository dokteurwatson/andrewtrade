from __future__ import annotations

from papertrader.indicators import rsi, sma


def test_sma_returns_average_of_last_window() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == 4


def test_sma_returns_none_for_invalid_period() -> None:
    assert sma([1, 2], 3) is None
    assert sma([1, 2, 3], 0) is None


def test_rsi_returns_100_when_no_losses() -> None:
    assert rsi([1, 2, 3, 4, 5], 2) == 100.0


def test_rsi_returns_none_when_not_enough_data() -> None:
    assert rsi([1, 2], 2) is None
