from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Paper mode (geen IBKR nodig)
    paper_mode:       bool   # True = PaperClient, False = IBKRClient
    paper_capital:    float  # startkapitaal voor paper trading
    data_source:      str    # "yfinance" of "polygon"
    polygon_api_key:  str    # verplicht bij data_source=polygon

    # IBKR Gateway verbinding (alleen gebruikt als paper_mode=False)
    ibkr_host:      str
    ibkr_port:      int
    ibkr_client_id: int

    # Strategie
    volume_mult:       float  # breakout candle moet X keer het ORB gemiddelde zijn
    orb_minutes:       int    # opening range duur (0 = geen ORB filter)
    stop_loss_field:   str    # "hold" — uit de watchlist
    target_field:      str    # "t1"   — uit de watchlist

    # Kapitaal & risicobeheer
    cash_reserve_pct:        float  # % cash buffer (fees)
    risk_threshold_usd:      float  # onder dit bedrag → all-in, erboven → risico-based
    risk_per_trade_pct:      float  # % van portfolio dat geriskeerd wordt per trade
    max_position_pct:        float  # max % van portfolio in één positie (onder drempel)
    max_position_pct_large:  float  # max % van portfolio in één positie (boven large_cap_threshold)
    large_cap_threshold:     float  # boven dit bedrag → max_position_pct_large gebruiken
    max_positions:           int    # max aantal gelijktijdige open posities

    # Telegram
    telegram_enabled:  bool
    telegram_token:    str
    telegram_chat_id:  str

    # Server
    dashboard_port:    int
    state_dir:         str
    log_level:         str

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            paper_mode=os.getenv("PAPER_MODE", "true").lower() == "true",
            paper_capital=float(os.getenv("PAPER_CAPITAL", "1000.0")),
            data_source=os.getenv("DATA_SOURCE", "yfinance"),
            polygon_api_key=os.getenv("POLYGON_API_KEY", ""),
            ibkr_host=os.getenv("IBKR_HOST", "ib-gateway"),
            ibkr_port=int(os.getenv("IBKR_PORT", "4002")),
            ibkr_client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
            volume_mult=float(os.getenv("VOLUME_MULT", "2.0")),
            orb_minutes=int(os.getenv("ORB_MINUTES", "0")),
            stop_loss_field=os.getenv("STOP_LOSS_FIELD", "hold"),
            target_field=os.getenv("TARGET_FIELD", "t1"),
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
