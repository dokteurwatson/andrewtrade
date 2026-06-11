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


def test_compute_trade_pnl_eur_account_converts():
    fx_rates._cache.clear()
    with patch.object(fx_rates, "_fetch_live_rate", return_value=1.08):
        pnl, fee = compute_trade_pnl(
            entry_price=7.20,
            exit_price=7.72,
            shares=11,
            broker="t212",
            fee_pct=0.11,
            account_currency="EUR",
            fx_eur_usd=1.08,
        )
    usd_pnl, usd_fee = compute_trade_pnl(
        entry_price=7.20,
        exit_price=7.72,
        shares=11,
        broker="t212",
        fee_pct=0.11,
        account_currency="USD",
    )
    assert pnl == pytest.approx(round(usd_pnl / 1.08, 2))
    assert fee == pytest.approx(round(usd_fee / 1.08, 2))


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
