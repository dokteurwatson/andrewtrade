from __future__ import annotations

from stocktrader.market_data import orb_avg_volume


def test_orb_avg_volume_empty() -> None:
    assert orb_avg_volume([]) is None


def test_orb_avg_volume_single_bar() -> None:
    assert orb_avg_volume([1000.0]) == 1000.0


def test_orb_avg_volume_multiple_bars() -> None:
    assert orb_avg_volume([100.0, 200.0, 300.0]) == 200.0
