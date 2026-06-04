from __future__ import annotations

from pathlib import Path

from papertrader.config import Settings


def make_settings(tmp_path: Path, **overrides) -> Settings:
    defaults = {
        "mode": "paper",
        "exchange_id": "kraken",
        "timeframe": "4h",
        "poll_seconds": 60,
        "candle_limit": 300,
        "start_capital_usd": 50.0,
        "coin_list": ["BTC", "ETH", "XRP"],
        "min_order_usd": 10.0,
        "slippage_rate": 0.0,
        "taker_fee_rate": 0.0,
        "rsi_period": 2,
        "rsi_entry_threshold": 20.0,
        "rsi_exit_threshold": 70.0,
        "sma_period": 200,
        "risk_threshold_balance": 100.0,
        "position_sizing_below_threshold": "all_in",
        "risk_per_trade_above_threshold": 0.01,
        "stop_loss_pct_above_threshold": 0.02,
        "stop_loss_pct_below_threshold": 0.05,
        "max_daily_loss_above_threshold": 0.03,
        "max_open_positions_above_threshold": 1,
        "max_consecutive_losses_above_threshold": 1,
        "cooldown_candles_after_limit": 3,
        "telegram_enabled": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "state_dir": str(tmp_path),
        "log_level": "INFO",
        "bugatti_target_usd": 2000000.0,
        "cash_reserve_pct": 0.0,
        "kraken_api_key": "",
        "kraken_api_secret": "",
        "live_trading_enabled": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)
