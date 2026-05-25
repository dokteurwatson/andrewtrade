from __future__ import annotations

from pathlib import Path

from papertrader.config import Settings
from papertrader.exchange import Candle
from papertrader.runner import PaperTrader, Signal
from papertrader.state import Position


def make_settings(tmp_path: Path, *, start_capital: float = 50.0, threshold: float = 100.0) -> Settings:
    return Settings(
        mode="paper",
        exchange_id="kraken",
        timeframe="4h",
        poll_seconds=60,
        candle_limit=300,
        start_capital_usd=start_capital,
        coin_list=["BTC", "ETH", "XRP"],
        min_order_usd=10.0,
        slippage_rate=0.0,
        taker_fee_rate=0.0,
        rsi_period=2,
        rsi_entry_threshold=20.0,
        rsi_exit_threshold=70.0,
        sma_period=200,
        risk_threshold_balance=threshold,
        position_sizing_below_threshold="all_in",
        risk_per_trade_above_threshold=0.01,
        stop_loss_pct_above_threshold=0.02,
        max_daily_loss_above_threshold=0.03,
        max_open_positions_above_threshold=1,
        max_consecutive_losses_above_threshold=1,
        cooldown_candles_after_limit=3,
        telegram_enabled=False,
        telegram_bot_token="",
        telegram_chat_id="",
        state_dir=str(tmp_path),
        log_level="INFO",
        bugatti_target_usd=2000000.0,
    )


def make_signal(symbol: str, close: float, low: float, *, enter: bool, exit_: bool) -> Signal:
    candle = Candle(timestamp=1, open=close, high=close, low=low, close=close, volume=100)
    return Signal(
        symbol=symbol,
        candle=candle,
        sma_value=close - 1,
        rsi_value=10.0 if enter else 80.0,
        trend_ok=True,
        enter_long=enter,
        exit_long=exit_,
    )


def test_entry_below_threshold_uses_all_cash(tmp_path: Path) -> None:
    trader = PaperTrader(make_settings(tmp_path, start_capital=50.0, threshold=100.0))
    signal = make_signal("BTC/USD", close=100.0, low=99.0, enter=True, exit_=False)

    trader._evaluate_entries(signal, {"BTC/USD": 100.0})

    position = trader.state.positions["BTC/USD"]
    assert position.stop_price == 0.0
    assert 0.0 <= trader.state.cash_usd < 1e-6


def test_entry_above_threshold_uses_risk_sizing_and_stop(tmp_path: Path) -> None:
    trader = PaperTrader(make_settings(tmp_path, start_capital=200.0, threshold=100.0))
    signal = make_signal("BTC/USD", close=100.0, low=99.0, enter=True, exit_=False)

    trader._evaluate_entries(signal, {"BTC/USD": 100.0})

    position = trader.state.positions["BTC/USD"]
    assert position.quantity == 1.0
    assert position.stop_price == 98.0
    assert trader.state.cash_usd == 100.0


def test_exit_loss_triggers_cooldown_above_threshold(tmp_path: Path) -> None:
    trader = PaperTrader(make_settings(tmp_path, start_capital=200.0, threshold=100.0))
    trader.state.positions["BTC/USD"] = Position(
        symbol="BTC/USD",
        quantity=1.0,
        entry_price=100.0,
        entry_timestamp=1,
        stop_price=98.0,
    )
    trader.state.cash_usd = 100.0

    signal = make_signal("BTC/USD", close=99.0, low=97.0, enter=False, exit_=False)
    trader._evaluate_exits(signal)

    assert "BTC/USD" not in trader.state.positions
    assert trader.state.cooldown_remaining == 3
