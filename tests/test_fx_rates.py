"""Tests voor live FX sizing (T212 EUR account → USD tickers)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stocktrader import fx_rates


def test_get_rate_to_usd_usd_is_one():
    assert fx_rates.get_rate_to_usd(
        "USD", fallback_eur_usd=1.08, fallback_gbp_usd=1.27, buffer_pct=0.03,
    ) == pytest.approx(1.0)


@patch.object(fx_rates, "_fetch_live_rate", return_value=1.10)
def test_get_rate_to_usd_eur_live_with_buffer(mock_fetch):
    fx_rates._cache.clear()
    rate = fx_rates.get_rate_to_usd(
        "EUR", fallback_eur_usd=1.08, fallback_gbp_usd=1.27, buffer_pct=0.03,
    )
    assert rate == pytest.approx(1.10 * 0.97)
    mock_fetch.assert_called_once_with("EURUSD")


@patch.object(fx_rates, "_fetch_live_rate", return_value=None)
def test_get_rate_to_usd_eur_fallback(mock_fetch):
    fx_rates._cache.clear()
    rate = fx_rates.get_rate_to_usd(
        "EUR", fallback_eur_usd=1.08, fallback_gbp_usd=1.27, buffer_pct=0.0,
    )
    assert rate == pytest.approx(1.08)
