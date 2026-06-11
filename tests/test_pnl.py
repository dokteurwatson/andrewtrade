"""Tests voor PnL-berekening (USD tickers → EUR account)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from stocktrader import fx_rates
from stocktrader.pnl import compute_trade_pnl


def test_compute_trade_pnl_usd_account():
    pnl, fee = compute_trade_pnl(
        entry_price=7.20,
        exit_price=7.72,
        shares=11,
        broker="t212",
        fee_pct=0.11,
        account_currency="USD",
    )
    gross = (7.72 - 7.20) * 11
    expected_fee = (7.20 + 7.72) * 11 * 0.0011
    assert pnl == pytest.approx(round(gross - expected_fee, 2))
    assert fee == pytest.approx(round(expected_fee, 2))


@patch.object(fx_rates, "_fetch_live_rate", return_value=1.08)
def test_compute_trade_pnl_eur_includes_buy_and_sell_fx(mock_fetch):
    fx_rates._cache.clear()
    pnl, fee = compute_trade_pnl(
        entry_price=7.20,
        exit_price=7.72,
        shares=11,
        broker="t212",
        fee_pct=0.11,
        account_currency="EUR",
        fx_eur_usd=1.08,
        fx_fee_fixed=0.12,
        entry_fx_fee=0.12,
    )
    gross_eur = (7.72 - 7.20) * 11 / 1.08
    assert fee == pytest.approx(0.24)
    assert pnl == pytest.approx(round(gross_eur - 0.24, 2))


def test_compute_trade_pnl_paper_broker_usd():
    pnl, fee = compute_trade_pnl(
        entry_price=10.0,
        exit_price=11.0,
        shares=5,
        broker="paper",
        fee_pct=0.11,
        account_currency="USD",
    )
    assert pnl == pytest.approx(5.0)
    assert fee == pytest.approx(0.0)
