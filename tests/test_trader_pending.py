"""Pending-entry guard — geen dubbele ENTRY tijdens lopende buy."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from stocktrader.config import Settings
from stocktrader.parser import Setup
from stocktrader.state import DayState
from stocktrader.trader import Trader


def _settings(**kwargs) -> Settings:
    base = dict(
        paper_capital=1000.0,
        data_source="finazon",
        polygon_api_key="",
        bar_poll_seconds=60,
        alpaca_api_key="",
        alpaca_api_secret="",
        alpaca_data_feed="iex",
        finazon_api_key="k",
        broker="paper",
        t212_api_key="",
        t212_api_secret="",
        t212_demo=True,
        t212_extended_hours=True,
        fx_eur_usd=1.08,
        fx_gbp_usd=1.27,
        fx_buffer_pct=0.03,
        max_order_usd=500.0,
        max_shares_per_order=0,
        volume_mult=2.0,
        orb_minutes=0,
        cash_reserve_pct=0.02,
        risk_threshold_usd=200.0,
        risk_per_trade_pct=0.02,
        max_position_pct=0.25,
        max_position_pct_large=0.10,
        large_cap_threshold=10000.0,
        max_positions=1,
        telegram_enabled=False,
        telegram_token="",
        telegram_chat_id="",
        dashboard_port=5001,
        state_dir="./state",
        log_level="INFO",
    )
    base.update(kwargs)
    return Settings(**base)


def _sti_setup() -> Setup:
    return Setup("STI", hold=28.0, break_=28.0, t1=35.0, t2=40.0)


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_enter_without_pending_skips_buy(mock_broker, mock_stream) -> None:
    client = MagicMock()
    mock_broker.return_value = client
    mock_stream.return_value = MagicMock()
    trader = Trader(_settings())
    state = DayState.empty(date(2026, 6, 5), start_capital=100.0)

    trader._enter(state, _sti_setup())

    client.buy_market.assert_not_called()
    assert "STI" not in trader._pending_entries


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_pending_cleared_after_enter(mock_broker, mock_stream) -> None:
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = Trader(_settings())
    state = DayState.empty(date(2026, 6, 5), start_capital=100.0)
    trader._pending_entries.add("STI")

    with patch.object(trader, "_enter_inner") as inner:
        trader._enter(state, _sti_setup())
        inner.assert_called_once()

    assert "STI" not in trader._pending_entries
