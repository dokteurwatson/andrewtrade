from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    paper_capital:    float
    data_source:      str    # yfinance | polygon | alpaca | finazon
    polygon_api_key:  str
    bar_poll_seconds: int

    alpaca_api_key:    str
    alpaca_api_secret: str
    alpaca_data_feed:  str   # iex (gratis) | sip (betaald)

    finazon_api_key: str     # us_stocks_essential dataset (~$19/mnd non-pro)

    broker:          str     # paper | t212
    t212_api_key:    str
    t212_api_secret: str     # Basic auth (key:secret); leeg = legacy header-only
    t212_demo:       bool    # True → demo.trading212.com

    max_order_usd:    float
    max_shares_per_order: int

    volume_mult:       float
    orb_minutes:       int

    cash_reserve_pct:        float
    risk_threshold_usd:      float
    risk_per_trade_pct:      float
    max_position_pct:        float
    max_position_pct_large:  float
    large_cap_threshold:     float
    max_positions:           int

    telegram_enabled:  bool
    telegram_token:    str
    telegram_chat_id:  str

    dashboard_port:    int
    state_dir:         str
    log_level:         str

    def effective_data_source(self) -> str:
        return self.data_source.lower()

    def effective_broker(self) -> str:
        return self.broker.lower()

    def stale_bar_seconds(self) -> int:
        defaults = {"yfinance": 180, "polygon": 120, "alpaca": 90, "finazon": 90}
        return defaults.get(self.effective_data_source(), 180)

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            paper_capital=float(os.getenv("PAPER_CAPITAL", "1000.0")),
            data_source=os.getenv("DATA_SOURCE", "yfinance").lower(),
            polygon_api_key=os.getenv("POLYGON_API_KEY", ""),
            bar_poll_seconds=int(os.getenv("BAR_POLL_SECONDS", "60")),
            alpaca_api_key=os.getenv("ALPACA_API_KEY", ""),
            alpaca_api_secret=os.getenv("ALPACA_API_SECRET", ""),
            alpaca_data_feed=os.getenv("ALPACA_DATA_FEED", "iex").lower(),
            finazon_api_key=os.getenv("FINAZON_API_KEY", ""),
            broker=os.getenv("BROKER", "paper").lower(),
            t212_api_key=os.getenv("T212_API_KEY", ""),
            t212_api_secret=os.getenv("T212_API_SECRET", ""),
            t212_demo=os.getenv("T212_DEMO", "true").lower() == "true",
            max_order_usd=float(os.getenv("MAX_ORDER_USD", "500.0")),
            max_shares_per_order=int(os.getenv("MAX_SHARES_PER_ORDER", "0")),
            volume_mult=float(os.getenv("VOLUME_MULT", "2.0")),
            orb_minutes=int(os.getenv("ORB_MINUTES", "0")),
            cash_reserve_pct=float(os.getenv("CASH_RESERVE_PCT", "0.02")),
            risk_threshold_usd=float(os.getenv("RISK_THRESHOLD_USD", "200.0")),
            risk_per_trade_pct=float(os.getenv("RISK_PER_TRADE_PCT", "0.02")),
            max_position_pct=float(os.getenv("MAX_POSITION_PCT", "0.25")),
            max_position_pct_large=float(os.getenv("MAX_POSITION_PCT_LARGE", "0.10")),
            large_cap_threshold=float(os.getenv("LARGE_CAP_THRESHOLD", "10000.0")),
            max_positions=int(os.getenv("MAX_POSITIONS", "3")),
            telegram_enabled=os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            dashboard_port=int(os.getenv("DASHBOARD_PORT", "5001")),
            state_dir=os.getenv("STATE_DIR", "./stocktrader_state"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
