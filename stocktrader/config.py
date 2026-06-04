from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Paper mode (geen IBKR nodig)
    paper_mode:       bool   # True = PaperClient, False = IBKRClient
    paper_capital:    float  # startkapitaal (paper mode + tracked capital bij IBKR)
    tracked_capital:  bool   # IBKR-orders wel, sizing/cash uit state (niet IB $1M)
    max_order_usd:    float  # harde max orderwaarde voor sizing (0 = uit)
    max_shares_per_order: int  # harde max stuks bij sizing (0 = uit)
    max_order_shares: int  # max stuks per IBKR order (chunking; 0 env → default 500)
    data_source:      str    # "yfinance" of "polygon"
    polygon_api_key:  str    # verplicht bij data_source=polygon

    # IBKR Gateway verbinding (alleen gebruikt als paper_mode=False)
    ibkr_host:      str
    ibkr_port:      int
    ibkr_client_id: int
    otc_filter_enabled: bool  # False = alleen check of symbool op IBKR bestaat
    ibkr_market_data_type: int   # 1=live 2=frozen 3=delayed 4=delayed_frozen
    ibkr_bar_stream: str         # historical (default) | realtime

    # Strategie
    volume_mult:       float  # breakout candle moet X keer het ORB gemiddelde zijn
    orb_minutes:       int    # opening range duur (0 = geen ORB filter)

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

    def effective_max_order_shares(self) -> int:
        """Harde limiet per IBKR order (Gateway/TWS). 0 in .env = 500."""
        return self.max_order_shares if self.max_order_shares > 0 else 500

    @staticmethod
    def _parse_market_data_type(raw: str) -> int:
        key = raw.strip().lower()
        mapping = {"live": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4}
        if key in mapping:
            return mapping[key]
        try:
            return int(key)
        except ValueError:
            return 3

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            paper_mode=os.getenv("PAPER_MODE", "true").lower() == "true",
            paper_capital=float(os.getenv("PAPER_CAPITAL", "1000.0")),
            tracked_capital=os.getenv("TRACKED_CAPITAL", "false").lower() == "true",
            max_order_usd=float(os.getenv("MAX_ORDER_USD", "500.0")),
            max_shares_per_order=int(os.getenv("MAX_SHARES_PER_ORDER", "0")),
            max_order_shares=int(os.getenv("MAX_ORDER_SHARES", "500")),
            data_source=os.getenv("DATA_SOURCE", "yfinance"),
            polygon_api_key=os.getenv("POLYGON_API_KEY", ""),
            ibkr_host=os.getenv("IBKR_HOST", "ib-gateway"),
            ibkr_port=int(os.getenv("IBKR_PORT", "4002")),
            ibkr_client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
            otc_filter_enabled=os.getenv("OTC_FILTER_ENABLED", "true").lower() == "true",
            ibkr_market_data_type=Settings._parse_market_data_type(
                os.getenv("IBKR_MARKET_DATA_TYPE", "delayed")
            ),
            ibkr_bar_stream=os.getenv("IBKR_BAR_STREAM", "historical").lower(),
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
