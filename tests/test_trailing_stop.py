"""Tests voor trailing stop-loss logica."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from unittest.mock import MagicMock, patch

from stocktrader.config import Settings
from stocktrader.parser import Setup
from stocktrader.state import DayState, Position
from stocktrader.trader import Trader
from stocktrader.trailing_stop import (
    compute_trailing_stop,
    parse_trail_steps,
    trailing_allowed,
)


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


def test_parse_trail_steps() -> None:
    assert parse_trail_steps("5:0,10:5,15:10") == [(5.0, 0.0), (10.0, 5.0), (15.0, 10.0)]


def test_trailing_raises_stop_after_activation() -> None:
    s = _settings()
    entry = 10.0
    hw = 11.0  # +10%
    _, new_stop, changed = compute_trailing_stop(
        entry=entry,
        high_water=hw,
        current_stop=8.0,
        target=15.0,
        settings=s,
    )
    assert changed
    assert new_stop == round(11.0 * 0.97, 4)


def test_trailing_never_lowers_stop() -> None:
    s = _settings()
    _, new_stop, changed = compute_trailing_stop(
        entry=10.0,
        high_water=11.0,
        current_stop=10.8,
        target=15.0,
        settings=s,
    )
    assert not changed
    assert new_stop == 10.8


def test_trailing_capped_below_target() -> None:
    s = _settings()
    _, new_stop, changed = compute_trailing_stop(
        entry=10.0,
        high_water=14.5,
        current_stop=8.0,
        target=14.0,
        settings=s,
    )
    assert not changed
    assert new_stop == 8.0


def test_steps_mode_breakeven_at_5pct() -> None:
    s = _settings(trail_mode="steps")
    _, new_stop, changed = compute_trailing_stop(
        entry=10.0,
        high_water=10.6,
        current_stop=8.0,
        target=15.0,
        settings=s,
    )
    assert changed
    assert new_stop == 10.0


def test_trailing_allowed_before_runner() -> None:
    pos = {"target_price": 4.5, "t2_price": 5.0, "stop_price": 3.5, "entry_price": 3.9}
    assert trailing_allowed(pos)


def test_trailing_allowed_t2_equals_t1() -> None:
    # T2 == T1: geen runner mogelijk, trailing altijd ok
    pos = {"target_price": 4.5, "t2_price": 4.5, "stop_price": 3.5, "entry_price": 3.9}
    assert trailing_allowed(pos)


def test_trailing_allowed_t2_equals_t1_stop_above_entry() -> None:
    # T2 == T1, trailing heeft stop boven entry getrokken — mag nog steeds
    pos = {"target_price": 4.5, "t2_price": 4.5, "stop_price": 4.1, "entry_price": 3.9,
           "runner_active": False}
    assert trailing_allowed(pos)


def test_trailing_blocked_in_runner() -> None:
    pos = {"target_price": 5.0, "t2_price": 5.0, "stop_price": 4.5, "entry_price": 3.9,
           "runner_active": True}
    assert not trailing_allowed(pos)


def _trader_with_position(**pos_kw) -> Trader:
    mock_broker = MagicMock()
    mock_stream = MagicMock()
    with patch("stocktrader.trader.build_bar_stream", return_value=mock_stream), patch(
        "stocktrader.trader._build_broker_client", return_value=mock_broker
    ):
        trader = Trader(_settings())
    trader._running = True
    state = DayState.empty(date(2026, 6, 9), start_capital=100.0)
    state.setups = [asdict(Setup("STAK", 3.5, 3.9, 4.5, 5.0))]
    pos = Position(
        ticker="STAK",
        shares=2,
        entry_price=3.90,
        stop_price=3.50,
        target_price=4.50,
        entry_time="10:00",
        order_id="x",
        t2_price=5.00,
        high_water=3.90,
        **pos_kw,
    )
    state.positions["STAK"] = asdict(pos)
    trader._state = state
    trader.store = MagicMock()
    return trader


@patch("stocktrader.trader.build_bar_stream")
@patch("stocktrader.trader._build_broker_client")
def test_trailing_exit_on_pullback(mock_broker, mock_stream) -> None:
    mock_broker.return_value = MagicMock()
    mock_stream.return_value = MagicMock()
    trader = _trader_with_position()
    # +7.7% high → trail stop omhoog; low blijft boven nieuwe stop
    trader._on_bar("STAK", 3.9, 4.20, 4.08, 4.15, 1000, is_new_bar=True)
    pos = trader._state.positions["STAK"]
    assert pos["stop_price"] > 3.50
    trail_stop = pos["stop_price"]
    # Pullback onder trail stop
    trader._on_bar("STAK", 4.15, 4.18, trail_stop - 0.05, 4.0, 1000, is_new_bar=True)
    action = trader._order_queue.get_nowait()
    assert action[0] == "EXIT"
    assert action[3] == "TRAIL"  # trailing stop boven entry, maar geen runner
