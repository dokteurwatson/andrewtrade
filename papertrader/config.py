from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _parse_coin_list(raw_value: str | None) -> List[str]:
    if not raw_value:
        return ["BTC", "ETH", "XRP"]
    value = raw_value.strip()
    if value.startswith("["):
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("COIN_LIST JSON value must be an array")
        coins = [str(item).upper().strip() for item in parsed if str(item).strip()]
    else:
        coins = [part.upper().strip() for part in value.split(",") if part.strip()]
    if not coins:
        raise ValueError("COIN_LIST cannot be empty")
    return coins


@dataclass(frozen=True)
class Settings:
    mode: str
    exchange_id: str
    timeframe: str
    poll_seconds: int
    candle_limit: int
    start_capital_usd: float
    coin_list: List[str]
    min_order_usd: float
    slippage_rate: float
    taker_fee_rate: float
    rsi_period: int
    rsi_entry_threshold: float
    rsi_exit_threshold: float
    sma_period: int
    risk_threshold_balance: float
    position_sizing_below_threshold: str
    risk_per_trade_above_threshold: float
    stop_loss_pct_above_threshold: float
    max_daily_loss_above_threshold: float
    max_open_positions_above_threshold: int
    max_consecutive_losses_above_threshold: int
    cooldown_candles_after_limit: int
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    state_dir: str
    log_level: str
    bugatti_target_usd: float
    cash_reserve_pct: float

    @property
    def symbols(self) -> List[str]:
        return [f"{coin}/USD" for coin in self.coin_list]


def load_settings() -> Settings:
    return Settings(
        mode=os.getenv("MODE", "paper").lower(),
        exchange_id=os.getenv("EXCHANGE_ID", "kraken").lower(),
        timeframe=os.getenv("TIMEFRAME", "4h"),
        poll_seconds=_parse_int(os.getenv("POLL_SECONDS"), 60),
        candle_limit=_parse_int(os.getenv("CANDLE_LIMIT"), 300),
        start_capital_usd=_parse_float(os.getenv("PAPER_START_CAPITAL_USD"), 50.0),
        coin_list=_parse_coin_list(os.getenv("COIN_LIST")),
        min_order_usd=_parse_float(os.getenv("MIN_ORDER_USD"), 10.0),
        slippage_rate=_parse_float(os.getenv("SLIPPAGE_RATE"), 0.0005),
        taker_fee_rate=_parse_float(os.getenv("TAKER_FEE_RATE"), 0.0026),
        rsi_period=_parse_int(os.getenv("RSI_PERIOD"), 2),
        rsi_entry_threshold=_parse_float(os.getenv("RSI_ENTRY_THRESHOLD"), 20.0),
        rsi_exit_threshold=_parse_float(os.getenv("RSI_EXIT_THRESHOLD"), 70.0),
        sma_period=_parse_int(os.getenv("SMA_PERIOD"), 100),
        risk_threshold_balance=_parse_float(os.getenv("RISK_THRESHOLD_BALANCE"), 100.0),
        position_sizing_below_threshold=os.getenv("POSITION_SIZING_BELOW_THRESHOLD", "all_in").lower(),
        risk_per_trade_above_threshold=_parse_float(os.getenv("RISK_PER_TRADE_ABOVE_THRESHOLD"), 0.01),
        stop_loss_pct_above_threshold=_parse_float(os.getenv("STOP_LOSS_PCT_ABOVE_THRESHOLD"), 0.02),
        max_daily_loss_above_threshold=_parse_float(os.getenv("MAX_DAILY_LOSS_ABOVE_THRESHOLD"), 0.03),
        max_open_positions_above_threshold=_parse_int(os.getenv("MAX_OPEN_POSITIONS_ABOVE_THRESHOLD"), 1),
        max_consecutive_losses_above_threshold=_parse_int(os.getenv("MAX_CONSECUTIVE_LOSSES_ABOVE_THRESHOLD"), 3),
        cooldown_candles_after_limit=_parse_int(os.getenv("COOLDOWN_CANDLES_AFTER_LIMIT"), 3),
        telegram_enabled=_parse_bool(os.getenv("TELEGRAM_ENABLED"), True),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        state_dir=os.getenv("STATE_DIR", "./state"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        bugatti_target_usd=_parse_float(os.getenv("BUGATTI_TARGET_USD"), 2000000.0),
        cash_reserve_pct=_parse_float(os.getenv("CASH_RESERVE_PCT"), 0.02),
    )
