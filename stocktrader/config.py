from __future__ import annotations
import os
from dataclasses import dataclass


def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _float(key: str, default: float) -> float:
    val = os.getenv(key, str(default))
    try:
        return float(val)
    except ValueError:
        raise ValueError(f"Ongeldige waarde voor {key}: {val!r} (verwacht getal)") from None


def _int(key: str, default: int) -> int:
    val = os.getenv(key, str(default))
    try:
        return int(val)
    except ValueError:
        raise ValueError(f"Ongeldige waarde voor {key}: {val!r} (verwacht geheel getal)") from None


def _bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "true" if default else "false")
    return val.lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class Settings:
    paper_capital:    float
    data_source:      str    # yfinance | polygon | alpaca | finazon
    polygon_api_key:  str
    bar_poll_seconds: int

    alpaca_api_key:    str
    alpaca_api_secret: str
    alpaca_data_feed:  str   # iex (gratis) | sip (betaald)

    finazon_api_key:       str   # us_stocks_essential dataset (~$19/mnd non-pro)
    finazon_frequency:     str   # 1s | 10s | 1m — hoe vaak snapshots worden gestuurd

    broker:          str     # paper | t212
    t212_api_key:    str
    t212_api_secret: str     # Basic auth (key:secret); leeg = legacy header-only
    t212_demo:       bool    # True → demo.trading212.com
    t212_extended_hours: bool  # pre-/after-market orders via T212 API
    fx_eur_usd: float          # fallback EUR→USD als live FX faalt
    fx_gbp_usd: float          # fallback GBP→USD als live FX faalt
    fx_buffer_pct: float       # marge op FX-schatting (T212 spread/fees)
    t212_fx_fee_pct: float     # fallback FX-schatting als T212_FX_FEE_FIXED_EUR=0
    t212_fx_fee_fixed_eur: float  # vaste FX-fee per order-leg (koop + verkoop) in EUR

    max_order_usd:    float
    max_shares_per_order: int

    volume_mult:       float
    orb_minutes:       int

    trailing_stop_enabled: bool
    trail_mode:            str    # trail | steps
    trail_activation_pct:  float
    trail_distance_pct:    float
    trail_steps:           str    # bijv. "5:0,10:5,15:10"

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

    def validate(self) -> None:
        """Controleer verplichte keys voor de gekozen broker/datasource."""
        ds = self.effective_data_source()
        if ds == "finazon" and not self.finazon_api_key:
            raise RuntimeError("FINAZON_API_KEY is verplicht voor DATA_SOURCE=finazon")
        if ds == "alpaca" and (not self.alpaca_api_key or not self.alpaca_api_secret):
            raise RuntimeError(
                "ALPACA_API_KEY en ALPACA_API_SECRET zijn verplicht voor DATA_SOURCE=alpaca"
            )
        if ds == "polygon" and not self.polygon_api_key:
            raise RuntimeError("POLYGON_API_KEY is verplicht voor DATA_SOURCE=polygon")

        broker = self.effective_broker()
        if broker == "t212" and not self.t212_api_key:
            raise RuntimeError("T212_API_KEY is verplicht voor BROKER=t212")

    @staticmethod
    def from_env() -> "Settings":
        log_level = _str("LOG_LEVEL", "INFO").upper()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level not in valid_levels:
            raise ValueError(
                f"Ongeldige LOG_LEVEL: {log_level!r} "
                f"(verwacht een van {sorted(valid_levels)})"
            )

        settings = Settings(
            paper_capital=_float("PAPER_CAPITAL", 1000.0),
            data_source=_str("DATA_SOURCE", "yfinance").lower(),
            polygon_api_key=_str("POLYGON_API_KEY", ""),
            bar_poll_seconds=_int("BAR_POLL_SECONDS", 60),
            alpaca_api_key=_str("ALPACA_API_KEY", ""),
            alpaca_api_secret=_str("ALPACA_API_SECRET", ""),
            alpaca_data_feed=_str("ALPACA_DATA_FEED", "iex").lower(),
            finazon_api_key=_str("FINAZON_API_KEY", ""),
            finazon_frequency=_str("FINAZON_FREQUENCY", "10s").lower(),
            broker=_str("BROKER", "paper").lower(),
            t212_api_key=_str("T212_API_KEY", ""),
            t212_api_secret=_str("T212_API_SECRET", ""),
            t212_demo=_bool("T212_DEMO", True),
            t212_extended_hours=_bool("T212_EXTENDED_HOURS", False),
            fx_eur_usd=_float("FX_EUR_USD", 1.08),
            fx_gbp_usd=_float("FX_GBP_USD", 1.27),
            fx_buffer_pct=_float("FX_BUFFER_PCT", 0.03),
            t212_fx_fee_pct=_float("T212_FX_FEE_PCT", 0.11),
            t212_fx_fee_fixed_eur=_float("T212_FX_FEE_FIXED_EUR", 0.12),
            max_order_usd=_float("MAX_ORDER_USD", 500.0),
            max_shares_per_order=_int("MAX_SHARES_PER_ORDER", 0),
            volume_mult=_float("VOLUME_MULT", 2.0),
            orb_minutes=_int("ORB_MINUTES", 0),
            trailing_stop_enabled=_bool("TRAILING_STOP_ENABLED", True),
            trail_mode=_str("TRAIL_MODE", "trail").lower(),
            trail_activation_pct=_float("TRAIL_ACTIVATION_PCT", 5.0),
            trail_distance_pct=_float("TRAIL_DISTANCE_PCT", 3.0),
            trail_steps=_str("TRAIL_STEPS", "5:0,10:5,15:10"),
            cash_reserve_pct=_float("CASH_RESERVE_PCT", 0.02),
            risk_threshold_usd=_float("RISK_THRESHOLD_USD", 200.0),
            risk_per_trade_pct=_float("RISK_PER_TRADE_PCT", 0.02),
            max_position_pct=_float("MAX_POSITION_PCT", 0.25),
            max_position_pct_large=_float("MAX_POSITION_PCT_LARGE", 0.10),
            large_cap_threshold=_float("LARGE_CAP_THRESHOLD", 10000.0),
            max_positions=_int("MAX_POSITIONS", 3),
            telegram_enabled=_bool("TELEGRAM_ENABLED", False),
            telegram_token=_str("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=_str("TELEGRAM_CHAT_ID", ""),
            dashboard_port=_int("DASHBOARD_PORT", 5001),
            state_dir=_str("STATE_DIR", "./stocktrader_state"),
            log_level=log_level,
        )
        settings.validate()
        return settings
