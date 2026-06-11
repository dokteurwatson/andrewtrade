"""
Tests voor _on_bar timestamp-dedup in de Trader.
Verifieer dat dubbele bars (zelfde ts) genegeerd worden en nieuwere geaccepteerd.
"""
from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock, patch

from stocktrader.config import Settings
from stocktrader.finazon_stream import FinazonBarStream
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
        finazon_frequency="10s",
        broker="paper",
        t212_api_key="",
        t212_api_secret="",
        t212_demo=True,
        t212_extended_hours=True,
        fx_eur_usd=1.08,
        fx_gbp_usd=1.27,
        fx_buffer_pct=0.03,
        t212_fx_fee_pct=0.15,
        max_order_usd=500.0,
        max_shares_per_order=0,
        volume_mult=2.0,
        orb_minutes=0,
        trailing_stop_enabled=True,
        trail_mode="trail",
        trail_activation_pct=5.0,
        trail_distance_pct=3.0,
        trail_steps="5:0,10:5,15:10",
        cash_reserve_pct=0.02,
        risk_threshold_usd=200.0,
        risk_per_trade_pct=0.02,
        max_position_pct=0.25,
        max_position_pct_large=0.10,
        large_cap_threshold=10000.0,
        max_positions=3,
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


def _init_trader(trader: Trader) -> None:
    from datetime import date

    trader._running = True
    state = DayState.empty(date(2026, 6, 5), start_capital=100.0)
    state.setups = [asdict(_sti_setup())]
    trader._state = state


def _ws_msg(ts: int, close: float = 29.0) -> dict:
    return {"s": "STI", "t": ts, "o": 28.5, "h": 30.0, "l": 28.0, "c": close, "v": 5000}


def _bind_ws_stream(trader: Trader) -> FinazonBarStream:
    stream = FinazonBarStream(api_key="k")
    stream.subscribe_bars(["STI"], trader._on_bar)
    return stream


def _inject_bar(trader: Trader, ts: int, close: float = 29.0) -> None:
    """Injecteer een bar direct in _on_bar (simuleert WS of een andere bron)."""
    trader._on_bar("STI", 28.5, 30.0, 28.0, close, 5000, is_new_bar=True, bar_ts=ts)


# ---------------------------------------------------------------------------
# Dedup: zelfde ts → overgeslagen
# ---------------------------------------------------------------------------

@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_on_bar_dedup_same_ts(mock_broker, mock_stream):
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = Trader(_settings())
    _init_trader(trader)
    trader._last_bar_ts["STI"] = 1000

    trader._on_bar("STI", 1, 2, 0.5, 1.5, 100, is_new_bar=True, bar_ts=1000)

    assert trader._bar_count.get("STI", 0) == 0


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_on_bar_accepts_newer_ts(mock_broker, mock_stream):
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = Trader(_settings())
    _init_trader(trader)
    trader._last_bar_ts["STI"] = 1000

    trader._on_bar("STI", 1, 2, 0.5, 1.5, 100, is_new_bar=True, bar_ts=1001)

    assert trader._bar_count["STI"] == 1
    assert trader._last_bar_ts["STI"] == 1001


# ---------------------------------------------------------------------------
# WS-dedup: dubbele bar via twee paden
# ---------------------------------------------------------------------------

@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_duplicate_bar_same_ts_skipped(mock_broker, mock_stream):
    """Eerste bar geaccepteerd, tweede met zelfde ts overgeslagen."""
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = Trader(_settings())
    _init_trader(trader)
    stream = _bind_ws_stream(trader)

    stream._emit_bar(_ws_msg(1699540020))
    assert trader._bar_count["STI"] == 1
    bars_after_first = trader._bars_received

    stream._emit_bar(_ws_msg(1699540020, close=29.1))
    assert trader._bar_count["STI"] == 1
    assert trader._bars_received == bars_after_first


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_newer_bar_accepted_after_duplicate(mock_broker, mock_stream):
    """Na dubbele bar wordt de volgende minuut-bar correct geaccepteerd."""
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = Trader(_settings())
    _init_trader(trader)
    stream = _bind_ws_stream(trader)

    _inject_bar(trader, ts=1699540020)
    assert trader._bar_count["STI"] == 1
    bars_after = trader._bars_received

    _inject_bar(trader, ts=1699540020, close=29.5)
    assert trader._bar_count["STI"] == 1
    assert trader._bars_received == bars_after

    _inject_bar(trader, ts=1699540080, close=30.0)
    assert trader._bar_count["STI"] == 2
    assert trader._last_bar_ts["STI"] == 1699540080
