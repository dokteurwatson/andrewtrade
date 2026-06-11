"""Tests voor PnL-berekening (USD tickers → EUR account)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from stocktrader import fx_rates
from stocktrader.pnl import compute_trade_pnl, t212_usd_to_account


def test_t212_buy_rate_matches_docs():
    # T212: buy rate = spot × (1 − 0,15%)
    rate = 1.40 * (1 - 0.0015)
    assert rate == pytest.approx(1.3979, abs=1e-4)
    eur = t212_usd_to_account(100.0, 1.40, side="buy", fee_pct=0.15)
    assert eur == pytest.approx(100.0 / rate, abs=1e-4)


def test_t212_sell_rate_matches_docs():
    rate = 1.41 * (1 + 0.0015)
    assert rate == pytest.approx(1.412115, abs=1e-4)
    eur = t212_usd_to_account(100.0, 1.41, side="sell", fee_pct=0.15)
    assert eur == pytest.approx(100.0 / rate, abs=1e-4)


def test_qh_roundtrip_from_t212_export():
    """QH 2026-06-11 — spots uit T212 export."""
    buy_eur = t212_usd_to_account(13 * 7.20, 1.15327747, side="buy", fee_pct=0.15)
    sell_eur = t212_usd_to_account(13 * 7.72, 1.15276820, side="sell", fee_pct=0.15)
    assert buy_eur == pytest.approx(81.28, abs=0.02)
    assert sell_eur == pytest.approx(86.93, abs=0.02)
    assert round(sell_eur - buy_eur, 2) == pytest.approx(5.65, abs=0.02)


@patch.object(fx_rates, "_fetch_live_rate", return_value=1.15327747)
def test_compute_trade_pnl_eur_uses_stored_entry_cost(mock_fetch):
    fx_rates._cache.clear()
    entry_cost = t212_usd_to_account(13 * 7.20, 1.15327747, side="buy", fee_pct=0.15)
    with patch.object(fx_rates, "_fetch_live_rate", return_value=1.15276820):
        fx_rates._cache.clear()
        pnl, fee = compute_trade_pnl(
            entry_price=7.20,
            exit_price=7.72,
            shares=13,
            broker="t212",
            fee_pct=0.15,
            account_currency="EUR",
            entry_eur_cost=entry_cost,
        )
    assert pnl == pytest.approx(5.65, abs=0.02)
    assert fee > 0


def test_compute_trade_pnl_paper_broker_usd():
    pnl, fee = compute_trade_pnl(
        entry_price=10.0,
        exit_price=11.0,
        shares=5,
        broker="paper",
        fee_pct=0.15,
        account_currency="USD",
    )
    assert pnl == pytest.approx(5.0)
    assert fee == pytest.approx(0.0)
